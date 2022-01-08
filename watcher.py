import logging
import os
import re
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pymongo import MongoClient
from pytz import timezone

load_dotenv()

LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", logging.INFO)
USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")
MONGO_URI = os.getenv("MONGO_URI")
MARKET_BASE_URL = os.getenv("MARKET_BASE_URL")

LOOP_SECONDS = int(os.getenv("LOOP_SECONDS", 5))

if os.getenv("ENVIRONMENT") == "dev":
    BOT_TOKEN = os.getenv("BOT_TOKEN_DEV")
    MONGO_DB = os.getenv("MONGO_DB_DEV")
    CHAT_ID = os.getenv("CHAT_ID_DEV")
else:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    MONGO_DB = os.getenv("MONGO_DB")
    CHAT_ID = os.getenv("CHAT_ID")

BOT_BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    stream=sys.stdout,
    level=LOGGING_LEVEL,
    format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",  # noqa: E501
    datefmt="%d/%b/%Y %H:%M:%S",
)
logger = logging.getLogger("truck-load-watch")

S = requests.session()
db = MongoClient(MONGO_URI)[MONGO_DB]

WEIGHT_RE = re.compile(r"(\d+) lbs")


def check_session():
    """
    Check that we have an authed session
    """
    cache_doc = db.cache.find_one({"key": "cookies"})
    if not cache_doc:
        return login()

    if (datetime.utcnow() - cache_doc["dt"]).total_seconds() / 3600 > 1:
        login()
    else:
        if not S.cookies.get_dict():
            S.cookies.update(cache_doc["cookies"])


def login():
    """
    Login for a new session
    """
    logger.info("Getting new session")
    r = S.post(
        f"{MARKET_BASE_URL}/core/jsp/CPLogin.jsp",
        data={
            "loginId": USERNAME,
            "password": PASSWORD,
            "mobile": True,
            "submit.x": 36,
            "submit.y": 13,
            "locale": "lo_DF",
        },
        allow_redirects=True,
    )
    logger.info(f"Login: {r}")

    r = db.cache.update_one(
        {"key": "cookies"},
        {
            "$set": {
                "key": "cookies",
                "cookies": S.cookies.get_dict(),
                "dt": datetime.utcnow(),
            }
        },
        upsert=True,
    )
    logger.info(f"Cached cookies: {r}")


def accept_load(accept_data: dict):
    """
    Accept new load

    Payload:
    {
        "initialized": True,
        "refreshLoads": False,
        "openPreassignedMarketIdList": "11111111,22222222",
        "openPreassignedShipmentIdList": "11111111,22222222",
        "postedByUserId": None,
        "biddingLocationId": 227871,
        "hideShipments28685": False,
        "action35399211": "accept",
        "submit.x": 30,
        "submit.y": 13,
    }
    """
    logger.info("Accepting new load")
    r = S.post(
        f"{MARKET_BASE_URL}/market/jsp/CPRespondToOffers.jsp",
        data={
            **accept_data,
            "postedByUserId": None,
            "biddingLocationId": 227871,
            "submit.x": 30,
            "submit.y": 13,
        },
    )
    logger.info(f"Accept Load: {r}")
    if not r.ok:
        return logger.info(r.reason)


def check_accepted_load_threshold():
    """
    Check the number of accepted loads for today
    """
    threshold = db.settings.find_one({"key": "load-threshold"})
    today = datetime.combine(datetime.utcnow(), datetime.min.time())
    accepted_loads = list(
        db.loads.find({"status": "accept", "dt": {"$gte": today}})
    )
    accepted_loads_cnt = len(accepted_loads)
    logger.info(f"Accepted load count: {accepted_loads_cnt}")

    return threshold["threshold"] - accepted_loads_cnt


def check_loads():
    """
    Truck Load Watcher
    """
    now_time = datetime.now(tz=timezone("US/Eastern")).time()
    if now_time.hour < 6 or now_time.hour > 18:
        logger.info(f"Current hour {now_time.hour} outside of 6 to 18")
        return "Outside of hours"

    status_doc = db.settings.find_one({"key": "status"})
    if status_doc:
        if not status_doc.get("enabled"):
            logger.info("disabled")
            return "Disabled"
    else:
        r = db.settings.insert_one({"key": "status", "enabled": True})
        logger.info("No status doc found: Enabling")

    remaining_loads = check_accepted_load_threshold()
    if remaining_loads <= 0:
        logger.info("load threshold already met")
        return "Done"

    check_session()
    r = S.get(f"{MARKET_BASE_URL}/market/jsp/CPRespondToOffers.jsp")
    logger.info(f"Fetch Offers: {r}")
    if not r.ok:
        return logger.info(r.reason)

    soup = BeautifulSoup(r.content, "html.parser")
    elems = soup.find_all("tr")
    form_elems = soup.find_all("form")

    accept_data = {}
    for form in form_elems:
        input_els = form.find_all("input")
        for input_el in input_els:
            name = input_el.get("name")
            value = input_el.get("value")
            if value == "true":
                value = True
            elif value == "false":
                value = False

            accept_data[name] = value

    data = []
    for tr in elems:
        data_row = []
        for e in tr.children:
            if hasattr(e, "attrs"):
                e_class = e.attrs.get("class")
                if e_class:
                    if any("data" in c for c in e_class):
                        data_input = e.find_all("input")
                        action_id = None
                        if data_input:
                            name = data_input[0].get("name")
                            value = data_input[0].get("value")
                            if value == "accept":
                                action_id = name

                        if action_id:
                            data_row.append(action_id)
                        else:
                            text = e.get_text().strip().replace("\n", "")
                            text = " ".join(
                                [t.strip() for t in text.split() if t.strip()]
                            )
                            if text:
                                data_row.append(text)

        if data_row:
            data.append(data_row)
            data_row = []

    if data:
        for entry in data:
            weight_res = re.search(WEIGHT_RE, entry[5])
            weight = int(weight_res.group(1))
            entry[5] = weight

        data = sorted(data, key=lambda x: x[5])

        logic = db.settings.find_one({"key": "logic"})

        text = "Hey 👋 I just accepted these loads for ya 😃\n\n"
        new_loads = 0
        action_ids = []
        for entry in data:
            dsm = int(entry[0])
            if not db.loads.find_one({"dsm": dsm}):
                origin = entry[1].split(" P:")
                dest = entry[2].split(" D:")

                weight = entry[5]
                origin_loc = origin[0]
                origin_dt = origin[1]
                dest_loc = dest[0]
                dest_dt = dest[1]
                consignee = entry[4]
                exc_ship_mode = entry[6]
                action_id = entry[8]

                if (
                    any(
                        d.lower() in dest_loc.lower()
                        for d in logic["destinations"]
                    )
                    and any(
                        c.lower() in consignee.lower()
                        for c in logic["consignees"]
                    )
                    and any(
                        s.lower() in exc_ship_mode.lower()
                        for s in logic["ship_modes"]
                    )
                ):
                    logger.info("Current logic matched")

                    if new_loads < remaining_loads:
                        logger.info("Under load threshold, taking new load")
                        new_loads += 1
                        action_ids.append(action_id)

                        text += (
                            f"Origin Loc: `{origin_loc}`\n"
                            f"Origin Date: `{origin_dt}`\n"
                            f"Dest Loc: `{dest_loc}`\n"
                            f"Dest Date: `{dest_dt}`\n"
                            f"Consignee: `{consignee}`\n"
                            f"Weight: `{weight}`\n"
                            f"Exc Ship Mode: `{exc_ship_mode}`\n\n"
                        )

                        r = db.loads.insert_one(
                            {
                                "dsm": dsm,
                                "action_id": action_id,
                                "origin_loc": origin_loc,
                                "origin_dt": origin_dt,
                                "dest_loc": dest_loc,
                                "dest_dt": dest_dt,
                                "consignee": consignee,
                                "weight": weight,
                                "exc_ship_mode": exc_ship_mode,
                                "status": "accept",
                                "dt": datetime.utcnow(),
                            }
                        )
                        logger.info(f"New load logged: {r}")

        if new_loads and action_ids:
            for aid in action_ids:
                accept_data[aid] = "accept"

            accept_load(accept_data)

            r = requests.post(
                f"{MARKET_BASE_URL}/sendMessage",
                data={
                    "chat_id": CHAT_ID,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                },
            )
            logger.info(f"Send Telegram Msg: {r}")
            if not r.ok:
                logger.info(r.reason)
        else:
            logger.info("No new loads found")


if __name__ == "__main__":
    print(f"Checking every {LOOP_SECONDS} seconds")
    while True:
        check_loads()
        time.sleep(LOOP_SECONDS)
