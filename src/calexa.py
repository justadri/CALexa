import json
import re
from datetime import datetime, time, timedelta, date
from zoneinfo import ZoneInfo

import caldav
import recurring_ical_events
from flask import Flask
from flask_ask import Ask, statement, request
from icalendar import Calendar

app = Flask(__name__)
ask = Ask(app, '/')

# read configuration
with open('../conf/config.json') as json_data_file:
    config = json.load(json_data_file)

local_tzinfo = ZoneInfo(config['timezone'])

# open log files
# f = open('./calexa.log', 'a+')
def log(msg):
    #	global f
    #	f.write(msg)
    #	f.flush()
    print(msg)


def connect_calendar():
    global config

    client = caldav.DAVClient(config["url"], username=config["username"], password=config["password"])
    principal = client.principal()
    calendars = principal.calendars()

    return sorted(calendars, key=lambda calendar: str(calendar.url))


# split away TRIGGER and VALARM fields, since caldav library does not always parse them correctly
def filter_event_triggers(events):
    for r in events:
        # log(r.data)
        ev = ""
        ev_data = str(r.data).splitlines()
        for line in ev_data:
            if not line.lstrip().startswith("TRIGGER") and ":VALARM" not in line:
                ev += (line + '\n')
        r.data = ev

    return events


def get_caldav_events(start_date, end_date):
    calendars = connect_calendar()
    event_list = []

    if len(calendars) <= 0:
        log("ERROR: could not connect to calendar")
    else:
        log("  found calendars: " + str(len(calendars)) + "\n")
        i = 0
        for calendar in calendars:
            log("	[" + str(i + 1) + "]: " + str(calendar))
            results = calendar.search(start=start_date, end=end_date)

            log("  -> " + str(len(results)) + " events \n")

            if len(results) > 0:
                ics_calendar = Calendar()
                for caldav_event in results:
                    ics_event = Calendar.from_ical(caldav_event.data).events[0]
                    # log('--')
                    # log(ics_event.start)
                    event_start = ics_event.start
                    duration = ics_event.duration
                    if not isinstance(event_start, datetime):
                        # log(local_tzinfo)
                        ics_event.start = datetime.combine(date=event_start, time=time(), tzinfo=local_tzinfo)
                        ics_event.end = datetime.combine(date=event_start, time=time(), tzinfo=local_tzinfo) + duration
                    ics_calendar.add_component(ics_event)
                    # log(ics_event.start)
                    # log(ics_event.end)

                events_in_range = recurring_ical_events.of(ics_calendar).between(start_date, end_date)
                event_list = event_list + events_in_range

            i = i + 1

        if len(event_list) > 0:
            event_list = sorted(event_list, key=lambda d: d['DTSTART'].dt)

            # TODO: give 5 results at a time & prompt to continue

            log("  returning " + str(len(event_list)) + " event(s)\n")

        return event_list


@ask.launch
def launch():
    # return get_date_events(start_date=datetime.now(), end_date=None)
    return statement('your planner is open')


@ask.intent(intent_name='AMAZON.SearchAction<object@Calendar>',
            mapping={'start_date_str': 'object.event.startDate', 'start_time_str': 'object.startTime'})
def get_date_events(start_date_str, start_time_str):
    log(request.intent)

    log("Reading events!\n")
    log("  start date (from user): " + str(start_date_str) + "\n")
    log("  start time (from user): " + str(start_time_str) + "\n")

    start_date = get_start_date(start_date_str)

    start_time = time()
    immediate = False
    if start_time_str is not None:
        match = re.match('^(\d{2}):(\d{2})$', start_time_str)
        if match is not None:
            start_time = time(hour=int(match[1]), minute=int(match[2]))
            immediate = True

    start_date = datetime.combine(date=start_date, time=start_time, tzinfo=local_tzinfo)

    end_date = get_end_date(start_date=start_date, date_str=start_date_str, immediate=immediate)

    log("  start_date: " + str(start_date) + " " + str(type(start_date)) + "\n")
    log("  end_date: " + str(end_date) + " " + str(type(end_date)) + "\n")

    event_list = get_caldav_events(start_date, end_date)
    speech_text = '<speak>\n'

    if len(event_list) == 0:
        speech_text += 'No events were found for this time period'
    else:
        speech_text += '    The following events are on your calendar:\n'

        for ics_event in event_list:
            event_start = ics_event['DTSTART'].dt
            time_string = event_start.strftime('%I:%M %p')
            date_string = ''
            if (end_date - start_date).days > 1:
                date_string = f' on {event_start.strftime("%A, %B %d")}'

            # TODO: add days of week/dates for multi-day queries
            speech_text += (f'    <break time="1s"/>at {time_string}{date_string} is '
                            f'{get_event_name(ics_event)}\n')

    speech_text += '</speak>'
    log("  text: " + speech_text + "\n")

    return statement(speech_text).simple_card('Calendar Events', speech_text)


def get_start_date(date_str):
    if date_str is None:
        date_str = ''
    date_str = re.sub('X$', '0', date_str)

    # year and week number
    match = re.match('^(\d{4})-W(\d{2})$', date_str)
    if match is not None:
        # take a day back because day 1 of the week is monday
        return date.fromisocalendar(year=int(match[1]), week=int(match[2]), day=1) + timedelta(days=-1)

    # weekend
    match = re.match('(\d{4})-W(\d{2})-WE$', date_str)
    if match is not None:
        return date.fromisocalendar(year=int(match[1]), week=int(match[2]), day=6)

    # month
    match = re.match('^(\d{4})-(\d{2})$', date_str)
    if match is not None:
        return date(year=int(match[1]), month=int(match[2]), day=1)

    # year
    match = re.match('^(\d{4})$', date_str)
    if match is not None:
        return date(year=int(match[1]), month=1, day=1)

    # complete date
    match = re.match('^(\d{4})-(\d{2})-(\d{2})$', date_str)
    if match is not None:
        return date(year=int(match[1]), month=int(match[2]), day=int(match[3]))

    # i give up
    return date.today()


def get_end_date(start_date, date_str, immediate=False):
    if date_str is None:
        date_str = ''
    date_str = re.sub('X$', '0', date_str)

    # year and week number
    match = re.match('^(\d{4})-W(\d{2})$', date_str)
    if match is not None:
        return start_date + timedelta(days=7)

    # weekend
    match = re.match('(\d{4})-W(\d{2})-WE$', date_str)
    if match is not None:
        return start_date + timedelta(days=1)

    # month
    match = re.match('^(\d{4})-(\d{2})$', date_str)
    if match is not None:
        month = int(match[2])
        if month == 12:
            month = 1
        else:
            month = month + 1
        return start_date.replace(month=month) + timedelta(days=-1)

    # year
    match = re.match('^(\d{4})$', date_str)
    if match is not None:
        year = match[1] + 1
        return start_date.replace(year=year) + timedelta(days=-1)

    # complete date or otherwise
    if immediate:
        return start_date + timedelta(hours=3)

    return start_date + timedelta(days=1)


def get_event_name(ics_event):
    # see: https://stackoverflow.com/questions/40135637/error-unable-to-parse-the-provided-ssml-the-provided-text-is
    # -not-valid-ssml
    name = ics_event['SUMMARY']
    name = name.replace('&', ' and ')
    name = name.replace('*', '')
    return name


# We do have a minor problem here. There is no timezone information in the date/time objects...
# ... we assume the server's timezone, but it could be that this is wrong. So if created events are off by some hour(s)
# this is the reason. If someone wants to provide a simple PR then this would be great :-)
# noinspection SpellCheckingInspection
@ask.intent('SetEventIntent', convert={'start_date': 'date', 'start_time': 'time', 'duration': 'timedelta'})
def set_event(start_date, start_time, duration, eventtype, location):
    log("Creating event!\n")
    log("  date (from user): " + str(start_date) + "\n")
    log("  time (from user): " + str(start_time) + "\n")
    log("  duration (from user): " + str(duration) + "\n")
    log("  eventtype (from user): " + str(eventtype) + "\n")
    log("  location (from user): " + str(location) + "\n")
    speech_text = "Date could not be understood!"

    if eventtype is None:
        eventtype = 'Meeting'

    if start_date is None:
        start_date = datetime.today()

    if duration is None:
        duration = timedelta(hours=1)

    d = datetime.combine(start_date, start_time)

    creation_date = datetime.now().strftime("%Y%m%dT%H%M%S")
    start_date = d.strftime("%Y%m%dT%H%M%S")
    end_date = (d + duration).strftime("%Y%m%dT%H%M%S")

    log("  startDate: " + str(start_date) + "\n")
    log("  endDate: " + str(end_date) + "\n")

    vcal = "BEGIN:VCALENDAR" + "\n"
    vcal += "VERSION:2.0" + "\n"
    vcal += "PRODID:-//Example Corp.//CalDAV Client//EN" + "\n"
    vcal += "BEGIN:VEVENT" + "\n"
    vcal += "UID:1234567890" + "\n"
    vcal += "DTSTAMP:" + creation_date + "\n"
    vcal += "DTSTART:" + start_date + "\n"
    vcal += "DTEND:" + end_date + "\n"
    vcal += "SUMMARY:" + eventtype + "\n"
    vcal += "END:VEVENT" + "\n"
    vcal += "END:VCALENDAR"

    log("  entry: " + vcal + "\n")

    calendars = connect_calendar()
    if len(calendars) <= 0:
        speech_text = "Unfortunately I could not connect to your calendar"
        log("ERROR: " + speech_text + "\n")
    else:
        # This could be sooo much easier if we had something like "if (calendar.isReadOnly())"
        i = 0
        log("  found calendar: #" + str(len(calendars)) + "\n")
        for calendar in calendars:
            log("  [" + str(i + 1) + "]: " + str(calendar) + "\n")
            try:
                event = calendar.add_event(vcal)
                speech_text = "Event has been added!"

                # Everything worked out well and event has been entered into one calendar -> we do not have to try
                # other calendars and therefore skip the loop
                break
            except Exception as te:
                if i >= len(calendars):
                    speech_text = "All of your calendars are read-only"
                    log("ERROR: " + speech_text + "\n")
                    log("ERROR: " + str(te) + "\n")
                    pass
                else:
                    log("  Couldn't write to calendar: " + str(calendar) + ". Try the next calendar...\n")
                    # Try using the next calendar... we will fail when the event could not be added to any calendar
                    i = i + 1

    log("  text: " + speech_text + "\n")
    return statement(speech_text).simple_card('Calendar Events', speech_text)


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=config["calexaPort"])

