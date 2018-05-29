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
    def __init__(self,
                 host = '127.0.0.1',
                 dbname = 'humhub',
                 port = 3306,
                 dbuser = 'user',
                 dbpasswd = '',
                 trigger = '!bot'):
        """
        Initializes database connection

        :param host: database host address
        :type state: str.
        :param dbname: database name
        :type state: str.
        :param dbuser: database host port
        :type state: int.
        :param dbuser: database username
        :type name: str.
        :param dbpasswd: database userpassword
        :type state: str.
        :param trigger: trigger string for bot
        :type state: str.
        """
        super(HumhubConnector, self).__init__()

        self.cnx_in = connectToDB(host, dbname, port, dbuser, dbpasswd)
        self.cursor_in = self.cnx_in.cursor()

        self.cnx_out = connectToDB(host, dbname, port, dbuser, dbpasswd)
        self.cursor_out = self.cnx_out.cursor()

        self.cnx_processing = connectToDB(host, dbname, port, dbuser, dbpasswd)
        self.cursor_processing = self.cnx_processing.cursor()

        self.trigger = trigger
        self.current_id = getCurrentID(self.cursor_in)
        self.bot_id = getBotID(self.cursor_in)


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
            self.cursor_out.execute(query, data)
            self.cnx_out.commit()
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
        new_id = getNextID(self.cursor_in, self.current_id, self.bot_id, self.trigger)
        if (self.current_id != new_id): # new messages
            self.current_id = new_id
            inputmsg = getMessage(self.cursor_in, new_id, self.trigger)
            return inputmsg

    def process_command(self, command, payload, out_message):
        """
        Returns message object
        """
        if command == "search_appointment":
            reply = self.search_appointment(payload, self.cursor_processing)
        elif command == "book_appointment":
            reply = self.book_appointment(payload, self.cursor_processing)
        elif command == "search_competence":
            reply = self.get_competence(payload, self.cursor_processing)
        else:
            reply = RasahubMessage(
                message = "Command unknown",
                message_id = payload['message_id'],
                target = payload['message_target'],
                source = payload['message_source']
            )
        return reply

    def search_appointment(self, payload, cursor):
        """
        Search for and reply a free appointment
        """
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

        try:
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
                cursor
            )

            reply = {}

            ## send result back to source (rasa)
            #replymessage = RasahubMessage(
            #    message = "SUGGESTDATE" + json.dumps(reply),
            #    message_id = payload['message_id'],
            #    target = payload['message_source'],
            #    source = payload['message_target']
            #)
            msg = ""
            if (suggestedDate is not None and
                suggestedDate[0] is not None and
                suggestedDate[1] is not None):
                suggestedDate = searchDateFrom.replace(
                    hour=suggestedDate[0], minute=suggestedDate[1])
                # get end time
                suggestedDateTo = getEndTime(suggestedDate, payload['args']['duration'])
                msg = "Am {} gibt es zwischen {} und {} Uhr einen freien Termin."
                msg = msg.format(
                    suggestedDate.strftime("%A, den %d.%m.%Y"),
                    suggestedDate.strftime("%H:%M"),
                    suggestedDateTo.strftime("%H:%M")
                )
            else:
                msg = "Keinen freien Termin gefunden."

            replymessage = RasahubMessage(
                message = msg,
                message_id = payload['message_id'],
                target = payload['message_target'],
                source = payload['message_source']
            )
            return replymessage
        except:
            return None # auth exception, no message to process anymore

    def book_appointment(self, payload, cursor):
        """
        Books a appointment in Users Google calendars
        """
        #message_id = payload['message_id']
        raise NotImplementedError

    def get_competence(self, payload, cursor):
        """
        Returns user with searched competence
        """
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

            exceptUserIDs = getUsersInConversation(cursor, payload['message_id'], self.bot_id)
            usercompetencies = getUserCompetencies(cursor, exceptUserIDs)

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
                    resMsg += u" koennte "
                else:
                    resMsg += u" koennten "
                resMsg += u"bei dem Anliegen helfen."

        except ValueError:
            resMsg = "Keinen Ansprechpartner gefunden."
        dispatcher.utter_message(resMsg)
        return []

    def end(self):
        """
        Closed mysql connections
        """
        self.cnx_in.close()
        self.cnx_out.close()
        self.cnx_processing.close()
