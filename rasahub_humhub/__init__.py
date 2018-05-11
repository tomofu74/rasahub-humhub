from rasahub import RasahubPlugin
from rasahub_humhub.humhub import *
from rasahub.message import RasahubMessage
import mysql.connector
from mysql.connector import errorcode
import json

class HumhubConnector(RasahubPlugin):
    """
    HumhubConnector is subclass of RasahubPlugin
    """
    def __init__(self, **kwargs):
        """
        Initializes database connection

        :param dbHost: database host address
        :type state: str.
        :param dbName: database name
        :type state: str.
        :param dbPort: database host port
        :type state: int.
        :param dbUser: database username
        :type name: str.
        :param dbPwd: database userpassword
        :type state: str.
        """
        super(HumhubConnector, self).__init__()

        dbHost = kwargs.get('host', '127.0.0.1')
        dbName = kwargs.get('dbname', 'humhub')
        dbPort = kwargs.get('port', '3306')
        dbUser = kwargs.get('dbuser', 'user')
        dbPwd = kwargs.get('dbpasswd', '')
        trigger = kwargs.get('trigger', '!bot')

        self.cnx = self.connectToDB(dbHost, dbName, dbPort, dbUser, dbPwd)
        self.cursor = self.cnx.cursor()
        self.current_id = self.getCurrentID()
        self.trigger = trigger
        self.bot_id = self.getBotID()

    def send(self, messagedata, main_queue):
        """
        Saves reply message from Rasa_Core to db

        :param messagedata: Containing the reply from Rasa as string and the conversation id
        :type state: dictionary.
        """
        query = ("INSERT INTO message_entry(message_id, user_id, content, created_at, created_by, updated_at, updated_by) "
            "VALUES (%(msg_id)s, %(bot_id)s, %(message)s, NOW(), %(bot_id)s, NOW(), %(bot_id)s)")
        data = {
          'msg_id': messagedata.message_id,
          'bot_id': self.bot_id,
          'message': messagedata.message,
        }
        try:
            self.cursor.execute(query, data)
            self.cnx.commit()
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                print("Something is wrong with your user name or password")
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                print("Database does not exist")
            else:
                print(err)

    def receive(self):
        """
        Implements receive function

        :returns: dictionary - Received message with conversation ID
        """
        new_id = self.getNextID()
        if (self.current_id != new_id): # new messages
            self.current_id = new_id
            inputmsg = self.getMessage(new_id)
            return inputmsg

    def process_command(self, command, payload):
        """
        Returns message object
        """
        if command == "search_appointment":
            reply = self.search_appointment(payload)
        elif command == "book_appointment":
            reply = self.book_appointment(payload)
        elif command == "search_competence":
            reply = self.get_competence(payload)
        else:
            reply = RasahubMessage(
                message = "Command unknown",
                message_id = payload['message_id'],
                target = payload['message_target'],
                source = payload['message_source']
            )
        return reply

    def connectToDB(self, dbHost, dbName, dbPort, dbUser, dbPwd):
        """
        Establishes connection to the database

        :param dbHost: database host address
        :type state: str.
        :param dbName: database name
        :type state: str.
        :param dbPort: database host port
        :type state: int.
        :param dbUser: database username
        :type name: str.
        :param dbPwd: database userpassword
        :type state: str.
        :returns: MySQLConnection -- Instance of class MySQLConnection
        """
        try:
            cnx = mysql.connector.connect(user=dbUser, port=int(dbPort), password=dbPwd, host=dbHost, database=dbName, autocommit=True)
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                print("Something is wrong with your user name or password")
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                print("Database does not exist")
            else:
                print(err)
        else:
            return cnx

    def getCurrentID(self):
        """
        Gets the current max message ID from Humhub

        :returns: int -- Current max message ID
        """
        query = "SELECT MAX(id) FROM message_entry;"
        self.cursor.execute(query)
        return self.cursor.fetchone()[0]

    def getBotID(self):
        """
        Gets a suitable Bot User ID from a Humhub User Group called 'Bots'

        :returns: int -- Bots Humhub User ID
        """
        query = "SELECT `user_id` FROM `group` JOIN `group_user` ON `group`.`id` = `group_user`.`group_id` WHERE `group`.`name` = 'Bots' ORDER BY user_id DESC LIMIT 1;"
        self.cursor.execute(query)
        return self.cursor.fetchone()[0]

    def getNextID(self):
        """
        Gets the next message ID from Humhub

        :returns: int -- Next message ID to process
        """
        query = ("SELECT id FROM message_entry WHERE user_id <> %(bot_id)s AND (content LIKE %(trigger)s OR message_entry.message_id IN "
            "(SELECT DISTINCT message_entry.message_id FROM message_entry JOIN user_message "
            "ON message_entry.message_id=user_message.message_id WHERE user_message.user_id = 5 ORDER BY message_entry.message_id)) "
            "AND id > %(current_id)s ORDER BY id ASC")
        data = {
            'bot_id': self.bot_id,
            'trigger': self.trigger + '%', # wildcard for SQL
            'current_id': self.current_id,
        }
        self.cursor.execute(query, data)
        results = self.cursor.fetchall()
        if len(results) > 0: # fetchall returns list of results, each as a tuple
            return results[0][0]
        else:
            return self.current_id

    def getMessage(self, msg_id):
        """
        Gets the newest message

        :returns: dictionary -- Containing the message itself as string and the conversation ID
        """
        query = "SELECT message_id, content FROM message_entry WHERE (user_id <> 5 AND id = {})".format(msg_id)
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        message_id = result[0]
        if result[1][:len(self.trigger)] == self.trigger:
            message = result[1][len(self.trigger):].strip()
        else:
            message = result[1].strip()
        messagedata = {
            'message': message,
            'message_id': message_id
        }
        return messagedata

    def search_appointment(payload):
        # if day is set:
        # search available dates for that day
        #
        # if datefrom and dateto are set:
        # search available dates between preferred
        #
        # search date after current time
        beginHour = 7
        beginMinuteIndex = 0
        endHour = 19
        endHourIndex = 3
        if payload['args']['datefrom']:
            searchDateFrom = datetime.strptime(payload['args']['datefrom'],
                                               '%Y-%m-%dT%H:%M:%S.000Z')
            if searchDateFrom.date() == datetime.now().date():
                beginHour = datetime.now().hour
                beginMinuteIndex = int(
                    math.ceil(float(datetime.now().minute) / 15.))

        suggestedDate = suggestDate(
            payload['args']['datefrom'],
            payload['args']['dateto'],
            payload['args']['duration'],
            payload['args']['users'],
            payload['args']['timesSearched'],
            beginHour,
            beginMinuteIndex,
            endHour,
            endHourIndex,
            self.cnx
        )

        reply = {}
        if (suggestedDate is not None and
            suggestedDate[0] is not None and
            suggestedDate[1] is not None):
            suggestedDate = searchDateFrom.replace(
                hour=suggestedDate[0], minute=suggestedDate[1])
            # get end time
            suggestedDateTo = getEndTime(suggestedDate, duration)
            reply = {'suggestedDate': suggestedDate, 'suggestedDateTo': suggestedDateTo}

        # send result back to source (rasa)
        replymessage = RasahubMessage(
            message = json.dumps(reply),
            message_id = payload['message_id'],
            target = payload['message_source'],
            source = payload['message_target']
        )
        return replymessage

    #def book_appointment(payload):
        #message_id = payload['message_id']

    def get_competence(payload):
        with open('competences.json') as data_file:
            data = json.load(data_file)
        try:
            s = dict((i['entity'], i['value'])
                     for i in payload['args']['entities'])
            if 'competence' not in s:
                search = getMatchingCompetence(
                    data, payload['args']['last_message'])
                if search is None:
                    resMsg = "Keinen Ansprechpartner gefunden."
            else:
                search = s['competence'].lower()

            # get possible competence values
            categories = []
            if isinstance(search, list):
                for s in search:
                    categories.append(searchCompetence(s, data))
            else:
                categories.append(searchCompetence(search, data))

            exceptUserIDs = getUsersInConversation(self.cnx, payload['message_id'])
            usercompetencies = getUserCompetencies(
                self.cnx, exceptUserIDs)

            # get users matching competences
            matchingUsers = []
            for category in categories:
                if (getUsersWithCompetencies(category, usercompetencies) is not None):
                    matchingUsers.append(
                        getUsersWithCompetencies(category, usercompetencies)
                    )
            if matchingUsers is None or len(matchingUsers) == 0:
                resMsg = "Keinen Ansprechpartner gefunden."
            else:
                # IDEA check if user is online
                resMsg = ""
                for user in matchingUsers:
                    if user["competence"] is not None:
                        i = len(user["users"])
                        for username in user["users"]:
                            resMsg += u"{}".format(username)
                            i -= 1
                            if i == 1:
                                resMsg += u" und "
                            if i > 1:
                                resMsg += u", "
                        resMsg += ", mit der Kompetenz "
                        resMsg += u"{}".format(user["competence"])
                        resMsg += u", und "
                resMsg = resMsg[:-5]
                if (len(matchingUsers) == 1 and
                   len(matchingUsers[0]["users"]) == 1):
                    resMsg += u" könnte "
                else:
                    resMsg += u" könnten "
                resMsg += u"bei dem Anliegen helfen."

        except ValueError:
            resMsg = "Keinen Ansprechpartner gefunden."
        dispatcher.utter_message(resMsg)
        if offlinemode is False:
            cnx.close()
        return []

    def end(self):
        self.cnx.close()
