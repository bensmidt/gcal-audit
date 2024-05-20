# standard library imports
import os.path
from datetime import datetime, timedelta
import logging
import re

# 3rd party imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

DEBUG = True
SECS_IN_DAY = 86400
SECS_IN_MINUTE = 60
MINUTES_IN_HOUR = 60
# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def authenticate_user() -> Credentials:
    """
    Authenticate the user with the Google Calendar API.

    Returns
    -------
    Credentials: The user credentials.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes the first time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open("token.json", "w") as token:
                token.write(creds.to_json())
    return creds


def query_events_from_date(date: str) -> list[dict]:
    """
    Query the user's calendar for events on a specific date.
    """
    creds = authenticate_user()
    try:
        service = build("calendar", "v3", credentials=creds)

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=date + "T00:00:00-05:00",  # Start of the date
                timeMax=date + "T23:59:59-05:00",  # End of the date (inclusive)
                singleEvents=True,
                orderBy="startTime",
                fields="items(start, end, summary, description)",
            ).execute()
        )
        events = events_result.get("items", [])

        if DEBUG:
            for event in events:
                datetime_start = datetime.fromisoformat(event["start"]["dateTime"])
                datetime_end = datetime.fromisoformat(event["end"]["dateTime"])
                logging.debug("{}:{:02d}-{}:{:02d} {}".format(
                    datetime_start.hour % 12, datetime_start.minute,
                    datetime_end.hour % 12, datetime_end.minute, event["summary"]))
        return events

    except HttpError as error:
        logging.error(f"An error occurred: {error}")


def extract_duration(event: dict) -> timedelta:
    """Extract the duration of an event in seconds.
    
    Parameters
    ----------
    event: dict
        The event to extract the duration from.
        
    Returns
    -------
    timedelta
        The duration of the event.
    """
    datetime_start = datetime.fromisoformat(event["start"]["dateTime"])
    datetime_end = datetime.fromisoformat(event["end"]["dateTime"])
    return datetime_end - datetime_start


def extract_event_types(event: dict) -> list[str]:
    """Extract the event types from the event.
    
    Parameters
    ----------
    event: dict
        The event to extract the event types from.
        
    Returns
    -------
    list[str]
        The event types.
    """
    if "description" not in event:
        return [event["summary"]]
    
    pattern = r"\[Tags:(.*?)\]"
    matches = re.findall(pattern, event["description"])
    if not matches:
        return [event["summary"]]
    
    event_types = []
    for match in matches[0].split(","):
        event_types.append(f"{match.strip()}")

    return event_types


def categorize_events(events: list[dict]) -> dict:
    """Categorize the events.

    Parameters
    ----------
    events: list[dict]
        The events to categorize.

    Returns
    -------
    dict
        The categorization of the events.
    """
    durations = {}
    for event in events:
        event_types = extract_event_types(event)
        event_duration = extract_duration(event).total_seconds()
        for event_type in event_types:
            durations.update({
                event_type: durations.get(event_type, 0) + event_duration
            })

    # Sort the durations dictionary by values (descending order)
    return dict(sorted(durations.items(), key=lambda item: item[1], reverse=True))


def print_analysis(categories: dict):
    """Print the analysis of the event categories.
    
    Parameters
    ----------
    categories: dict
        The categorized events.
        
    Returns
    -------
    None
    """
    # title
    event_type_max_len = max(len(event_type) for event_type in categories.keys())
    title = f"| {'Event Type':^{event_type_max_len}} | {'Duration':^8} | {'% of Day':^8} |"
    print(f"+{'-' * (len(title)-2)}+")
    print(title)
    print(f"+{'-' * (len(title)-2)}+")
    # data
    for event_type, seconds in categories.items():
        minutes = seconds // SECS_IN_MINUTE
        hours = minutes // MINUTES_IN_HOUR
        minutes = minutes % MINUTES_IN_HOUR
        duration = f"{int(hours)}:{int(minutes):02d}"
        percent_of_day = f"{round((seconds / SECS_IN_DAY) * 100, 2)}"
        print(f"| {event_type:{event_type_max_len}} | {duration:^8} | {percent_of_day:^8} |")
    print(f"+{'-' * (len(title)-2)}+")


def main():
    # choose analyzation period
    date = input("Enter the date (YYYY-MM-DD): ")
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    # analyze the events
    events = query_events_from_date(date)
    if not events:
        print(f"No events found for {date}")
        return
    categories = categorize_events(events)
    print_analysis(categories)


if __name__ == "__main__":
    main()
