#!/bin/python
from requests_html import HTMLSession
from requests import HTTPError
from urllib.parse import parse_qs, urlparse
from time import sleep
from datetime import datetime, timedelta
from dateparser import parse as parse_datetime
import argparse
import sys
import os
import itertools

# iBooking studio IDs
STUDIOS = {
    "gløshaugen": 306,
    "dragvoll": 307,
    "portalen": 308,
    "dmmh": 402,
    "moholt": 540,
}

# iBooking activity IDs
ACTIVITIES = {"egentrening": 419380, "hall4": 75606, "hallAdragvoll": 516131}


def log_in(session: HTMLSession, username: str, password: str) -> None:
    session.post(
        "https://www.sit.no/trening",
        data={"name": username, "pass": password, "form_id": "user_login"},
    ).raise_for_status()


def get_token(session: HTMLSession) -> str:
    response = session.get("https://www.sit.no/trening/gruppe")
    response.raise_for_status()
    ibooking_src = response.html.find("#ibooking-iframe", first=True).attrs["src"]
    return parse_qs(urlparse(ibooking_src).query)["token"][0]


def get_schedule(session: HTMLSession, studio: int, token: str) -> dict:
    response = session.get(
        "https://ibooking.sit.no/webapp/api/Schedule/getSchedule",
        params={"studios": studio, "token": token},
    )
    response.raise_for_status()
    return response.json()

def get_resource_schedule(session: HTMLSession, studio: int, token: str) -> dict:
    response = session.get(
        "https://ibooking.sit.no/webapp/api/ResourceBooking/getSchedule",
        params={"sid": studio, "token": token, "resourceIds": 324},  # Without the resourceIds the "bookingOpensAt" is wrong...
    )
    response.raise_for_status()
    return response.json()

def add_resource_booking(session: HTMLSession, token: str, id: int) -> None:
    session.post(
        "https://ibooking.sit.no/webapp/api/ResourceBooking/addBooking",
        data={"token": token, "id": id},
    ).raise_for_status()

def book_resource(session: HTMLSession, start: datetime, activity_id: int, studio: int = None) -> bool:
    """
    Gløs studio id: 306
    resource id 324: any resource of type Hall
    Hall 4 activity id: 75606
    id is the unique time and activity
    """
    token = get_token(session)
    schedule = get_resource_schedule(session, studio, token)
    for day in schedule["days"]:
        if parse_datetime(day["date"]).date() == start.date():
            for training_class in itertools.chain.from_iterable([row["classes"] for row in day["rows"]]):
                if (
                    training_class["activity"]["id"] == activity_id
                    and parse_datetime(training_class["from"]) == training_start
                ):
                    booking_start = parse_datetime(day["bookingOpensAt"])
                    if datetime.now() < booking_start:
                        opens_in = booking_start - datetime.now()
                        print(
                            f"Booking opens in {str(opens_in).split('.')[0]}. Going to sleep ..."
                        )
                        sleep(opens_in.total_seconds())
                    try:
                        add_resource_booking(session, token, training_class["id"])
                    except HTTPError as e:
                        print(e.response)
                    return True
    return False


def add_booking(session: HTMLSession, token: str, class_id: int) -> None:
    session.post(
        "https://ibooking.sit.no/webapp/api/Schedule/addBooking",
        data={"classId": class_id, "token": token},
    ).raise_for_status()


def book(session: HTMLSession, training_start: datetime, studio: int) -> bool:
    token = get_token(session)
    schedule = get_schedule(session, studio, token)
    for day in schedule["days"]:
        if parse_datetime(day["date"]).date() == training_start.date():
            for training_class in day["classes"]:
                if (
                    training_class["activityId"] == ACTIVITIES["egentrening"]
                    and parse_datetime(training_class["from"]) == training_start
                ):
                    booking_start = parse_datetime(training_class["bookingOpensAt"])
                    if datetime.now() < booking_start:
                        opens_in = booking_start - datetime.now()
                        print(
                            f"Booking opens in {str(opens_in).split('.')[0]}. Going to sleep ..."
                        )
                        sleep(opens_in.total_seconds())
                    add_booking(session, token, training_class["id"])
                    return True
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Book training slots (egentrening) at Sit.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("username", type=str, help="Sit username (email)")
    parser.add_argument("password", type=str, help="Sit password")
    parser.add_argument(
        "--time",
        type=str,
        metavar="hhmm",
        help="start time (example: 0730)",
        required=True,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="number of days until training slot (0 is today)",
    )
    parser.add_argument(
        "--hall4",
        type=bool,
    )
    parser.add_argument(
        "--studio",
        type=str,
        default="gløshaugen",
        choices=STUDIOS.keys(),
        help="studio",
    )
    parser.add_argument("--max-tries", type=int, default=2, help="max number of tries")
    args = parser.parse_args()

    training_start = (datetime.now() + timedelta(days=args.days)).replace(
        hour=int(args.time[:2]), minute=int(args.time[2:]), second=0, microsecond=0
    )
    if args.password == "ENV":
        args.password = os.environ["password"]
    success = False
    current_try = 1
    while current_try <= args.max_tries:
        session = HTMLSession()
        try:
            log_in(session, args.username, args.password)
            if args.hall4:
                success = book_resource(session, training_start, ACTIVITIES["hall4"])
                # success = book_resource(session, training_start, ACTIVITIES["hallAdragvoll"])
            else:
                success = book(session, training_start, STUDIOS[args.studio])
            print(
                "Slot booked!"
                if success
                else "Could not find a training slot matching the provided parameters."
            )
            break
        except Exception as e:
            if current_try == args.max_tries:
                print("An error occurred.", e)
        finally:
            session.close()
            current_try += 1

    sys.exit(0 if success else 1)
