# standard library imports
import os.path
from datetime import datetime, timedelta
import logging
import socket
import re

# 3rd party imports
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SECS_IN_DAY = 86400
SECS_IN_MINUTE = 60
MINUTES_IN_HOUR = 60
# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
DAYS_OF_WEEK = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]


class DateInputter:

    def input_day(self) -> tuple[datetime, datetime]:
        date = input("Enter the day (YYYY-MM-DD). Press Enter for today:\n")
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        start_datetime = date + "T00:00:00-07:00"
        end_datetime = date + "T23:59:59-07:00"
        return (
            datetime.fromisoformat(start_datetime), datetime.fromisoformat(end_datetime)
        )

    def input_week(self) -> tuple[datetime, datetime]:
        date = input(
            "Enter the start day (YYYY-MM-DD) of the week. Press Enter for today:\n"
        )
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        start_datetime = date + "T00:00:00-07:00"
        date_obj = datetime.fromisoformat(date) + timedelta(days=6)
        end_datetime = date_obj.strftime("%Y-%m-%d") + "T23:59:59-07:00"
        return (
            datetime.fromisoformat(start_datetime), datetime.fromisoformat(end_datetime)
        )

    def input_datetime_range(self) -> tuple[datetime, datetime]:
        start_date = input("Enter the start day (YYYY-MM-DD). Press Enter for today:\n")
        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")
        start_time = input("Enter the start time (HH:MM): ")
        if not start_time:
            start_time = "00:00"
        end_date = input("Enter the end date (YYYY-MM-DD): ")
        if not end_date:
            end_date = start_date
        end_time = input("Enter the end time (HH:MM): ")
        if not end_time:
            end_time = "23:59"
        start_datetime = f"{start_date}T{start_time}:00-07:00"
        end_datetime = f"{end_date}T{end_time}:00-07:00"
        return (
            datetime.fromisoformat(start_datetime), datetime.fromisoformat(end_datetime)
        )


class GCalAuditor:

    def __init__(self):
        """Initialize the Google Calendar Auditor.

        Parameters
        ----------
        audit_first_tag_only: bool
            Whether to audit only the first tag in the event description.
        """
        self._audit_first_tag_only = None
        self._total_duration = None
        self._date_inputter = DateInputter()

    def authenticate_user(self) -> Credentials:
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

    def query_events(
        self, start_datetime: datetime, end_datetime: datetime
    ) -> list[dict]:
        """
        Query the user's calendar for events on a specific date.
        """
        self._total_duration = (end_datetime - start_datetime).total_seconds()
        creds = self.authenticate_user()
        try:
            service = build("calendar", "v3", credentials=creds)
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    # 07:00 is Pacific Time, 05:00 is Central Time
                    timeMin=start_datetime.strftime("%Y-%m-%d") + "T00:00:00-07:00",
                    timeMax=end_datetime.strftime("%Y-%m-%d") + "T23:59:59-07:00",
                    singleEvents=True,
                    orderBy="startTime",
                    fields="items(start, end, summary, description)",
                ).execute()
            )
            events = events_result.get("items", [])

            for event in events:
                event["start"]["dateTime"] = datetime.fromisoformat(
                    event["start"]["dateTime"]
                )
                event["end"]["dateTime"] = datetime.fromisoformat(
                    event["end"]["dateTime"]
                )
                logging.info("{}:{:02d}-{}:{:02d} {}".format(
                    event["start"]["dateTime"].hour % 12,
                    event["start"]["dateTime"].minute,
                    event["end"]["dateTime"].hour % 12,
                    event["end"]["dateTime"].minute,
                    event["summary"]))
            return events

        except HttpError as error:
            logging.error(f"An error occurred: {error}")

    def extract_event_categories(self, event: dict) -> list[str]:
        """Extract the event categories from the event.

        Parameters
        ----------
        event: dict
            The event to extract the event categories from.

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

        categories = []
        # audit first tag
        if self._audit_first_tag_only:
            return [matches[0].split(",")[0].strip()]
        # audit all tags
        for match in matches[0].split(","):
            categories.append(match.strip())

        return categories

    def categorize_events(self, events: list[dict]) -> dict:
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
            event_types = self.extract_event_categories(event)
            event_duration = (
                (event["end"]["dateTime"] - event["start"]["dateTime"])
            ).total_seconds()
            for event_type in event_types:
                durations.update({
                    event_type: durations.get(event_type, 0) + event_duration
                })

        # Sort the durations dictionary by values (descending order)
        return dict(sorted(durations.items(), key=lambda item: item[1], reverse=True))

    def print_analysis(self, categories: dict):
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
        col1 = f"{'Event Type':^{event_type_max_len}}"
        col2 = f"{'Duration':^8}"
        col3 = f"{'% of Total':^10}"
        title = f"| {col1} | {col2} | {col3} |"
        print(f"+{'-' * (len(title)-2)}+")
        print(title)
        print(f"+{'-' * (len(title)-2)}+")
        # data
        tracked_duration = 0
        for event_type, seconds in categories.items():
            tracked_duration += seconds
            minutes = seconds // SECS_IN_MINUTE
            hours = minutes // MINUTES_IN_HOUR
            minutes = minutes % MINUTES_IN_HOUR
            duration = f"{int(hours)}:{int(minutes):02d}"
            percent_of_total = f"{round((seconds / self._total_duration) * 100, 2):.2f}"
            col1 = f"{event_type:^{event_type_max_len}}"
            col2 = f"{duration:^8}"
            col3 = f"{percent_of_total:^10}"
            print(f"| {col1} | {col2} | {col3} |")
        print(f"+{'-' * (len(title)-2)}+")
        # total
        if self._audit_first_tag_only:
            minutes = tracked_duration // SECS_IN_MINUTE
            hours = minutes // MINUTES_IN_HOUR
            minutes = minutes % MINUTES_IN_HOUR
            duration = f"{int(hours)}:{int(minutes):02d}"
            percent_of_total = (
                f"{round((tracked_duration / self._total_duration) * 100, 2):.2f}"
            )
            col1 = f"{'Total':^{event_type_max_len}}"
            col2 = f"{duration:^8}"
            col3 = f"{percent_of_total:^10}"
            print(f"| {col1} | {col2} | {col3} |")
            print(f"+{'-' * (len(title)-2)}+")

    def set_tag_option(self):
        # audit the first tag only
        print("audit the first tag only?")
        audit_first_tag_only = input("Enter y/n: ")
        if audit_first_tag_only.lower() in ["yes", "y"]:
            self._audit_first_tag_only = True
        else:
            self._audit_first_tag_only = False

    def _audit(self, start_datetime: datetime, end_datetime: datetime):
        events = self.query_events(start_datetime, end_datetime)
        if not events:
            print(f"No events found for {start_datetime}-{end_datetime}")
            return
        categories = self.categorize_events(events)
        self.print_analysis(categories)

    def audit_day(self):
        self.set_tag_option()
        start_date, end_date = self._date_inputter.input_day()
        self._audit(start_date, end_date)

    def audit_week(self):
        self.set_tag_option()
        print(self._audit_first_tag_only)
        # audit week
        start_datetime, end_datetime = self._date_inputter.input_week()
        events = self.query_events(start_datetime, end_datetime)
        if not events:
            print(f"No events found for {start_datetime}-{end_datetime}")
            return
        categories = self.categorize_events(events)
        self.print_analysis(categories)

        # audit each day of the week
        cur_datetime = start_datetime
        while cur_datetime <= end_datetime:
            cur_events = []
            self._total_duration = SECS_IN_DAY
            print(DAYS_OF_WEEK[cur_datetime.weekday()], cur_datetime.date())
            for event in events:
                if event["start"]["dateTime"].day == cur_datetime.day:
                    cur_events.append(event)
            if not cur_events:
                print(f"No events found for {cur_datetime}")
                cur_datetime += timedelta(days=1)
                continue
            categories = self.categorize_events(cur_events)
            self.print_analysis(categories)
            cur_datetime += timedelta(days=1)

    def audit_datetime_range(self):
        self.set_tag_option()
        start_date, end_date = self._date_inputter.input_datetime_range()
        self._audit(start_date, end_date)

    def audit(self):
        print("Select from one of the following audit options:")
        options = ["day", "week", "datetime range"]
        count = 1
        for option in options:
            print(f"{count}. {option}")
            count += 1
        option = input(f"Select a number 1-{len(options)}: ")
        if option == "1":
            return self.audit_day()
        elif option == "2":
            return self.audit_week()
        elif option == "3":
            return self.audit_datetime_range()
        else:
            print("INVALID OPTION. TRY AGAIN.\n")
            return self.audit()


def main():
    gcal_auditor = GCalAuditor()
    gcal_auditor.audit()


if __name__ == "__main__":
    # ignore annoying logs from other libraries
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("requests").setLevel(logging.ERROR)
    logging.getLogger("google").setLevel(logging.ERROR)

    logger = logging.getLogger()
    fhandler = logging.FileHandler(filename="audit.log", mode="w")
    format_str = (
        f"[%(asctime)s {socket.gethostname()}] %(filename)s:%(funcName)s:%(lineno)s - %"
        f"(levelname)s: %(message)s"
    )
    formatter = logging.Formatter(format_str)
    fhandler.setFormatter(formatter)
    logger.addHandler(fhandler)
    logger.setLevel(logging.DEBUG)

    main()
