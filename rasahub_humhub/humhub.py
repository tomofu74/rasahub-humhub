from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from datetime import datetime
from rasa_core.actions.action import Action
from rasa_core.events import SlotSet, AllSlotsReset
from time import gmtime, time, strftime
import json
import locale
import logging
import math
import mysql.connector
from mysql.connector import errorcode
import os
import string
import random
import re
import yaml
from nltk.stem.snowball import SnowballStemmer

stemmer = SnowballStemmer("german")
logger = logging.getLogger(__name__)
offlinemode = False
locale.setlocale(locale.LC_ALL, "de_DE.utf8")




def getUsersInConversation(cnx, senderID):
    """
    Returns a list of Humhub User IDs participating in the conversation using
    the sender ID

    :param cnx: Mysql Connection
    :type cnx: MySQLConnection
    :param senderID: Humhub conversation sender ID
    :type senderID: int
    """
    global offlinemode
    if offlinemode:
        return [9, 14]

    cursor = cnx.cursor()
    query = ("""SELECT user_id FROM user_message WHERE message_id = {}
            """).format(senderID)
    cursor.execute(query)
    users = []
    for user_id in cursor:
        users.append(user_id[0])
    return users


def getCalendar(user, date, cnx):
    """
    Gets calendar pattern of a given Humhub User ID

    :param user: Humhub user ID to get the calendar information from
    :type user: int
    :param date: Specific date to get the calendar information
    :type date: datetime
    """
    # create calendar pattern
    calendarPattern = createCalendarPattern()

    # get busy appointments
    startdate = date.strftime("%Y-%m-%d 00:00:00")
    enddate = date.strftime("%Y-%m-%d 23:59:59")
    startdate = "'" + startdate + "'"
    enddate = "'" + enddate + "'"

    cursor = cnx.cursor()
    query = ("""SELECT start_datetime, end_datetime FROM calendar_entry
                INNER JOIN calendar_entry_participant ON
                calendar_entry.id =
                calendar_entry_participant.calendar_entry_id
                WHERE calendar_entry_participant.user_id = {} AND
                calendar_entry_participant.participation_state = 3 AND
                calendar_entry.start_datetime BETWEEN {} AND {}
            """).format(user, startdate, enddate)
    cursor.execute(query)
    busydates = []
    for (start_datetime, end_datetime) in cursor:
        busydates.append([start_datetime, end_datetime])
    cnx.close()

    return setBusyDates(calendarPattern, busydates)


def setBusyDates(calendarPattern, cursor):
    """
    Sets busy dates in a given calendar pattern using calendar information

    :param calendarPattern: Blank calendar pattern
    :type calendarPattern: array
    :param cursor: Array containing start and end datetimes of busy dates
    :type cursor: array
    """
    for (start_datetime, end_datetime) in cursor:
        # convert minute to array index, round down as its starting time
        startIndex = int(float(start_datetime.minute) / 15.)
        # end minute index is round up
        endIndex = int(math.ceil(float(end_datetime.minute) / 15.))
        endAtZero = False
        if endIndex == 0:
            endAtZero = True
        else:
            endIndex -= 1  # correct index for all cases except 0
        # set all patterns to 0 between start and end indezes
        for i in range(start_datetime.hour, end_datetime.hour + 1):
            if start_datetime.hour == end_datetime.hour:
                for j in range(startIndex, endIndex + 1):
                    calendarPattern[i][j] = 1
                break
            # three cases: i = start.hour, i = end.hour or between
            if i == start_datetime.hour:
                # only set to 0 beginning from startIndex to 3
                for j in range(startIndex, 4):
                    calendarPattern[i][j] = 1
            elif i == end_datetime.hour:
                if endAtZero:
                    break
                # only set to 0 beginning from 0 to endIndex
                for j in range(endIndex + 1):
                    calendarPattern[i][j] = 1
            else:
                # set all to 0
                for j in range(0, 4):
                    calendarPattern[i][j] = 1
    return calendarPattern



def createCalendarPattern(datefrom=None, dateto=None):
    """
    Creates blank calendar pattern for one day or for timeframe between
    datefrom and dateto

    :param datefrom: Start datetime for free timeframe
    :type datefrom: datetime
    :param dateto: End datetime for free timeframe
    :type dateto: datetime
    """
    # matching against standardized calendar
    calendarPattern = []
    if datefrom and dateto:
        # set to busy = 1 except given range
        for i in range(24):
            calendarPattern.append(i)
            calendarPattern[i] = []
            for j in range(4):
                calendarPattern[i].append(j)
                calendarPattern[i][j] = 1
        # get time
        timefrom = datetime.strptime(datefrom, '%Y-%m-%dT%H:%M:%S.000Z')
        timeto = datetime.strptime(dateto, '%Y-%m-%dT%H:%M:%S.000Z')
        # round minute to next or before quarter
        startIndex = int(math.ceil(float(timefrom.minute) / 15.))
        endIndex = int(float(timeto.minute) / 15.) - 1
        # set timeframe to 0 = free
        for i in range(timefrom.hour, timeto.hour + 1):
            if i == timefrom.hour:
                for j in range(startIndex, 4):
                    calendarPattern[i][j] = 0
            elif i == timeto.hour:
                for j in range(endIndex + 1):
                    calendarPattern[i][j] = 0
            else:
                for j in range(0, 4):
                    calendarPattern[i][j] = 0
    else:
        # set to free = 0 for hole day
        for i in range(24):
            calendarPattern.append(i)
            calendarPattern[i] = []
            for j in range(4):
                calendarPattern[i].append(j)
                calendarPattern[i][j] = 0
    # pattern: [5][0] for 05:00, [5][1] for 05:15, [5][2] for 05:30,
    # [5][3] for 05:45, [6][0] for 06:00 and so on
    return calendarPattern


def matchCalendars(calendars):
    """
    Matches calendars against each other

    :param calendars: array containing all calendars to match
    :type calendars: array
    """
    calendarPattern = []
    for i in range(24):
        calendarPattern.append(i)
        calendarPattern[i] = []
        for j in range(4):
            calendarPattern[i].append(j)
            calendarPattern[i][j] = 0
    for calendar in calendars:
        if calendar is not None:
            for i in range(24):
                for j in range(4):
                    if calendar[i][j] == 1:
                        calendarPattern[i][j] = 1
    # available dates have value 1, busy dates 0
    return calendarPattern


def getDateSuggestion(calendar,
                      duration,
                      timesSearched,
                      beginHour,
                      beginMinuteIndex,
                      endHour,
                      endHourIndex):
    """
    Gets date suggestion from a filled calendar

    :param calendar: The calendar to search for a free date
    :type calendar: array (Calendarpattern)
    :param duration: Needed duration of the free date to be searched in minutes
    :type duration: int
    :param timesSearched: Number of date suggestions to skip - when we already
                          searched two times we want to skip the first two
                          occurences
    :type timesSearched: int
    :param beginHour: Index of starting hour to be searched
    :type beginHour: int
    :param beginMinuteIndex: Index of starting quarter to be searched
                             (x times 15)
    :type beginMinuteIndex: int
    :param endHour: Index of ending hour to be searched
    :type begiendHournHour: int
    :param endMinuteIndex: Index of ending quarter to be searched (x times 15)
    :type endMinuteIndex: int
    """
    if duration == 0 or duration is None:
        duration = 15
    # transfer duration to minute indezes
    durationindezes = int(math.ceil(float(duration) / 15.))
    if timesSearched is None:
        timesSearched = 0
    # take next date where all required (duration) indezes are 1
    for i in range(beginHour, endHour):
        if beginHour == i:
            rangej = beginMinuteIndex
        else:
            rangej = 0
        for j in range(rangej, 4):
            if calendar[i][j] == 0:
                founddate = True
                # look for j + durationindezes values
                for d in range(1, durationindezes):
                    n = j + d
                    if calendar[i + int(n / 4)][n % 4] == 1:
                        founddate = False
                        # set i and j to new values
                        # to skip already checked dates
                        i = i + int(n / 4)
                        j = n % 4
                        break
                    else:
                        continue
                # hour = i, minute = j
                if founddate:
                    if timesSearched == 0:
                        return [i, j * 15]
                    else:
                        # skip
                        i = i + int((durationindezes + j) / 4)
                        j = (durationindezes + j) % 4
                        timesSearched -= 1
    return [timesSearched]


def suggestDate(
    datefrom,
    dateto,
    duration,
    users,
    timesSearched,
    beginHour,
    beginMinuteIndex,
    endHour,
    endHourIndex,
    cnx
):
    """
    Gets calendars of users and calls the free date searching method
    getDateSuggestion

    :param datefrom: Starting datetime to be searched
    :type datefrom: datetime
    :param dateto: Ending datetime to be searched
    :type dateto: datetime
    :param duration: Needed duration of the free date to be searched in minutes
    :type duration: int
    :param users: List of Humhub User IDs to get claendars from
    :type users: list
    :param timesSearched: Number of date suggestions to skip - when we already
                          searched two times we want to skip the first two
                          occurences
    :type timesSearched: int
    :param beginHour: Index of starting hour to be searched
    :type beginHour: int
    :param beginMinuteIndex: Index of starting quarter to be searched
                             (x times 15)
    :type beginMinuteIndex: int
    :param endHour: Index of ending hour to be searched
    :type begiendHournHour: int
    :param endMinuteIndex: Index of ending quarter to be searched (x times 15)
    :type endMinuteIndex: int
    """
    calendarPattern = []
    dtfrom = datetime.strptime(datefrom, '%Y-%m-%dT%H:%M:%S.000Z')
    dtto = datetime.strptime(dateto, '%Y-%m-%dT%H:%M:%S.000Z')
    while dtfrom < dtto:
        calendarPattern = createCalendarPattern()
        # get users calendars
        calendars = []
        for user in users:
            calendars.append(getCalendar(user, dtfrom, cnx))
        # get free date
        calendars.append(calendarPattern)
        datesuggest = None
        datesuggest = matchCalendars(calendars)

        # gets hour and minute, needs to be combined with extracted date
        suggestion = getDateSuggestion(
            datesuggest,
            duration,
            timesSearched,
            beginHour,
            beginMinuteIndex,
            endHour,
            endHourIndex
        )
        if len(suggestion) == 1:
            timesSearched = suggestion[0]
            dtfrom = dtfrom + timedelta(days=1)
        if len(suggestion) == 2:
            return suggestion
    return []


def getEndTime(datetime, duration):
    """
    Gets end time of a free date suggestion using starting datetime and
    duration

    :param datetime: Starting datetime
    :type datetime: datetime
    :param duration: Duration in minutes
    :type duration: int
    """
    # round duration minutes to next 15
    duration = int(math.ceil(float(duration) / 15.)) * 15
    durationhour = int(duration / 60)
    durationminute = duration % 60
    newEndHour = datetime.hour + durationhour
    newEndMinute = durationminute + datetime.minute
    while newEndMinute >= 60:
        newEndHour += 1
        newEndMinute = newEndMinute % 60
    return datetime.replace(hour=newEndHour, minute=newEndMinute)


def getUserName(userID):
    """
    Gets users firstname and lastname and returns as string
    """
    firstname = ''
    lastname = ''
    global offlinemode
    if offlinemode:
        return "Christian Schmidt"
    # search in humhub db
    cnx = establishDBConnection(dbconfig)
    cursor = cnx.cursor()
    query = ("""SELECT firstname, lastname FROM profile WHERE user_id = {}
            """).format(userID)
    cursor.execute(query)
    username = ''
    for (firstname, lastname) in cursor:
        username = firstname + " " + lastname
    cnx.close()
    return username


def bookdate(cnx, datefrom, duration, users):
    # create calendar entry, duration in minutes
    cursor = cnx.cursor()
    datetimeNow = "'" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "'"
    if (datefrom.minute + duration) >= 60:
        dateto = datefrom.replace(
            hour=datefrom.hour + int((datefrom.minute + duration) / 60),
            minute=int(datefrom.minute + duration) % 60
        )
    else:
        dateto = datefrom.replace(minute=datefrom.minute + duration)

    # create one calendar entry for each user
    for user in users:
        # get user names for description except own id
        description = 'Termin mit '
        for user2 in users:
            if user is not user2:
                description += getUserName(user2) + ", "
        description = description[:-2]
        # get container id
        query = ("""SELECT `id` AS `cID` FROM `contentcontainer` WHERE
            `class` = 'humhub\\\\modules\\\\user\\\\models\\\\User' AND
            `pk` = %s AND `owner_user_id` = %s""")
        data = (user, user)
        cursor.execute(query, data)
        for cID in cursor:
            containerID = cID[0]
        # create entry
        query = (("""INSERT INTO calendar_entry(title, description,
                start_datetime, end_datetime, all_day, participation_mode,
                color, allow_decline, allow_maybe, time_zone,
                participant_info, closed) VALUES
                ('Termin', '{}', {}, {}, 0, 2, '#59d6e4', 1, 1,
                'Europe/Berlin', '', 0);""").format(
            description,
            str("'" + datefrom.strftime("%Y-%m-%d %H:%M:%S") + "'"),
            str("'" + dateto.strftime("%Y-%m-%d %H:%M:%S") + "'")))
        cursor.execute(query)
        cnx.commit()
        # get id of entry created
        calendarEntryID = cursor.lastrowid

        # insert activity
        query = ("""INSERT INTO `activity`
                (`class`, `module`, `object_model`, `object_id`)
                VALUES (%s, 'content', %s, %s);""")
        data = ('humhub\\modules\\content\\activities\\ContentCreated',
                'humhub\\modules\\calendar\\models\\CalendarEntry',
                calendarEntryID)
        cursor.execute(query, data)
        cnx.commit()

        # insert participation
        query = (("""INSERT INTO calendar_entry_participant
                (calendar_entry_id, user_id, participation_state)
                 VALUES ({}, {}, 3);""").format(calendarEntryID, user))
        cursor.execute(query)
        cnx.commit()

        query = ("""INSERT INTO `content`
            (`guid`, `object_model`, `object_id`, `visibility`, `pinned`,
             `archived`, `created_at`, `created_by`, `updated_at`,
             `updated_by`, `contentcontainer_id`, `stream_sort_date`,
             `stream_channel`) VALUES
             (%s, %s, %s, 1, 0, '0', %s, 5, %s, 5, %s, %s, 'default');""")
        data = (buildGUID(cnx),
                'humhub\\modules\\calendar\\models\\CalendarEntry',
                calendarEntryID,
                datetimeNow,
                datetimeNow,
                containerID,
                datetimeNow)
        cursor.execute(query, data)
        cnx.commit()

        query = (("""INSERT INTO user_follow
                (object_model, object_id, user_id, send_notifications)
                 VALUES (%s, %s, %s, 1);"""))
        data = ('humhub\\modules\\calendar\\models\\CalendarEntry',
                calendarEntryID,
                user)
        cursor.execute(query, data)
        cnx.commit()

        query = ("""INSERT INTO `activity`
                (`class`, `module`, `object_model`, `object_id`)
                VALUES (%s, 'calendar', %s, %s);""")
        data = ('humhub\\modules\\calendar\\activities\\ResponseAttend',
                'humhub\\modules\\calendar\\models\\CalendarEntry',
                calendarEntryID)
        cursor.execute(query, data)
        cnx.commit()
        activityID = cursor.lastrowid

        query = ("""INSERT INTO `content`
                (`guid`, `object_model`, `object_id`, `visibility`,
                `pinned`, `archived`, `created_at`, `created_by`,
                `updated_at`, `updated_by`, `contentcontainer_id`,
                `stream_sort_date`, `stream_channel`) VALUES
                (%s, %s, %s, 1, 0, '0', %s, 5, %s, 5, 5, %s,
                'activity');""")
        data = (buildGUID(cnx),
                'humhub\\modules\\activity\\models\\Activity',
                activityID,
                datetimeNow,
                datetimeNow,
                datetimeNow)
        cursor.execute(query, data)
        cnx.commit()

    return []


def buildGUID(cnx):
    """
    Builds GUID needed for content table in Humhub db
    """
    unique = 0
    while (unique == 0):
        match = None
        while (match is None):
            hexstr = str(
                os.urandom(4).encode('hex') +
                "-" + os.urandom(2).encode('hex') +
                "-" + hex(random.randint(0, 0x0fff) | 0x4000)[2:] +
                "-" + hex(random.randint(0, 0x3fff) | 0x8000)[2:] +
                "-" + os.urandom(6).encode('hex')
            )
            match = re.search(
                '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                hexstr
            )
        hexstr = "'" + hexstr + "'"
        # check if GUID is already used
        cursor = cnx.cursor(buffered=True)
        query = "SELECT id FROM `content` WHERE guid = {}".format(hexstr)
        cursor.execute(query)
        if cursor.rowcount == 0:
            unique = 1
        else:
            unique = 0
    return hexstr


def searchCompetence(search, dictionary):
    """
    Returns the path for a competence from general competence to searched
    competence.
    """
    for competence in dictionary:
        if (
            (
                'competence' in competence and
                stemmer.stem(competence['competence'])
                == stemmer.stem(search.lower())
            )
            or
            (
                'synonyms' in competence and
                stemmer.stem(search.lower()) in [
                    stemmer.stem(syn) for syn in competence['synonyms']
                ]
            )
        ):
            return [competence['competence']]
        else:
            try:
                if 'subcategories' in competence:
                    return (
                        searchCompetence(search, competence['subcategories']) +
                        [competence['competence']])
            except ValueError:
                pass
    raise ValueError("Not found")


def getUserCompetencies(cnx, exceptUserIDs):
    """
    Returns array of persons with their competences as values
    """
    competencies = {}
    cnx = establishDBConnection(dbconfig)
    cursor = cnx.cursor()
    placeholder = '%s'
    placeholders = ', '.join(placeholder for unused in exceptUserIDs)
    query = ("""SELECT firstname, lastname, competence FROM profile
             WHERE user_id NOT IN ({}) AND competence IS NOT NULL
             """).format(placeholders)
    cursor.execute(query, tuple(exceptUserIDs))
    cnx.close()
    for (firstname, lastname, competence) in cursor:
        competencies[firstname + " " + lastname] = (
            [comp.strip().lower() for comp in competence.split(',')]
        )
    return competencies


def getUsersWithCompetencies(categories, usercompetencies):
    """
    Lists competences and their corresponding user IDs and returns the user ID
    matching the needed competence

    :param categories: Needed competence category
    :type categories: list
    :param usercompetencies: User IDs and their competences
    :type usercompetencies: dict
    """
    # user -> competence ==> competence -> users
    competencies = {}
    for user in usercompetencies:
        for competence in usercompetencies[user]:
            if competence not in competencies:
                competencies[competence] = []
                competencies[competence].append(user)
            else:
                competencies[competence].append(user)
    # search for competence
    for competence in categories:  # from special to general
        if competence in competencies:
            # returns users matching requested competency
            return {
                "competence": competence,
                "users": competencies[competence]
            }
    return None


def getMatchingCompetence(dictionary, lastmessage):
    """
    Searches for a competence in a string
    """
    allCompetences = getAllCompetences(dictionary)
    searchedCompetence = []
    for word in re.split('[ .!?]', lastmessage):
        if stemmer.stem(word.strip().lower()) in [
                stemmer.stem(comp) for comp in allCompetences]:
            searchedCompetence.append(word.strip().lower())
    return searchedCompetence


def getAllCompetences(dictionary, competences=[]):
    """
    Gets all competences and synonyms in competence dictionary without
    hirarchical list
    """
    for competence in dictionary:
        competences.append(competence['competence'])
        if 'synonyms' in competence:
            for synonym in competence['synonyms']:
                competences.append(synonym)
        if 'subcategories' in competence:
            getAllCompetences(competence['subcategories'], competences)
    return competences

def getUserID(person):
    """
    Gets Humhub User ID using name information

    :param person: Name of the person to get the Humhub User ID for
    :type person: str.
    """
    # search for person string in humhub db
    # switch case for only one name (propably lastname) or
    # two separate strings (firstname + lastname)
    firstname = ''
    lastname = ''
    if len(person.split()) == 1:
        # only lastname
        lastname = person
    else:
        firstname = person.split()[0]
        lastname = person.split()[1]

    global offlinemode
    if offlinemode:
        return 8
    # search in humhub db
    cnx = establishDBConnection(dbconfig)
    cursor = cnx.cursor()
    query = ''
    if firstname == '':
        query = ("""SELECT user_id FROM profile WHERE lastname = {}
                """).format(lastname)
    else:
        query = ("""SELECT user_id FROM profile WHERE firstname = {}
                    AND lastname = {}
                """).format(firstname, lastname)
    cursor.execute(query)
    for user_id in cursor:
        userid = user_id
    cnx.close()
    return userid
