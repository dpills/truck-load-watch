import logging
import os
import sys

from dotenv import load_dotenv
from pymongo import MongoClient
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler, Updater

load_dotenv()

LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", logging.INFO)
MONGO_URI = os.getenv("MONGO_URI")

if os.getenv("ENVIRONMENT") == "dev":
    BOT_TOKEN = os.getenv("BOT_TOKEN_DEV")
    MONGO_DB = os.getenv("MONGO_DB_DEV")
else:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    MONGO_DB = os.getenv("MONGO_DB")

logging.basicConfig(
    stream=sys.stdout,
    level=LOGGING_LEVEL,
    format="[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",  # noqa: E501
    datefmt="%d/%b/%Y %H:%M:%S",
)
logger = logging.getLogger("watch-bot")

db = MongoClient(MONGO_URI)[MONGO_DB]


def disable(update: Update, context: CallbackContext) -> None:
    """Disable load watcher"""
    logger.info("disable")
    r = db.settings.update_one({"key": "status"}, {"$set": {"enabled": False}})
    logger.info(f"Disabled watcher: {r}")
    update.message.reply_text("Load watching disabled ❌")


def enable(update: Update, context: CallbackContext) -> None:
    """Enable load watcher"""
    logger.info("enable")
    r = db.settings.update_one({"key": "status"}, {"$set": {"enabled": True}})
    logger.info(f"Enabled watcher: {r}")
    update.message.reply_text("Load watching enabled ✅")


def status(update: Update, context: CallbackContext) -> None:
    """Get load watcher status"""
    logger.info("status")
    status_doc = db.settings.find_one({"key": "status"})
    logger.info(status_doc)

    status = "disabled ❌"
    if status_doc.get("enabled"):
        status = "enabled ✅"

    update.message.reply_text(f"Current status: {status}")


def logic(update: Update, context: CallbackContext) -> None:
    """Get the current load matching logic"""
    logger.info("logic")
    logic_doc = db.settings.find_one({"key": "logic"})
    logger.info(logic_doc)

    text = "Current active logic for matching new loads\n\n"

    for key, value in logic_doc.items():
        if isinstance(value, list):
            text += f"{key}: {', '.join(value)}\n"

    update.message.reply_text(text)


def updateDestinations(update: Update, context: CallbackContext) -> None:
    """
    Update list of destinations used to match new loads.
    Add them with spaces after the command.
    Example: /updateDestinations greensboro charlotte harrisburg
    """
    logger.info(context.args)
    if not context.args:
        return update.message.reply_text(
            "Please provide destinations. "
            "Example: /updateDestinations greensboro charlotte harrisburg"
        )

    new_data = [c.strip() for c in context.args]
    r = db.settings.update_one(
        {"key": "logic"}, {"$set": {"destinations": new_data}}
    )
    logger.info(f"Destination logic updated: {r}")
    update.message.reply_text("Destination logic updated")


def updateConsignees(update: Update, context: CallbackContext) -> None:
    """
    Update list of consignees used to match new loads.
    Add them with spaces after the command.
    Example: /updateConsignees coilplus
    """
    logger.info(context.args)
    if not context.args:
        return update.message.reply_text(
            "Please provide consignees. " "Example: /updateConsignees coilplus"
        )

    new_data = [c.strip() for c in context.args]
    r = db.settings.update_one(
        {"key": "logic"}, {"$set": {"consignees": new_data}}
    )
    logger.info(f"Consignees logic updated: {r}")
    update.message.reply_text("Consignees logic updated")


def updateShipModes(update: Update, context: CallbackContext) -> None:
    """
    Update list of ship modes used to match new loads.
    Add them with spaces after the command.
    Example: /updateShipModes coil
    """
    logger.info(context.args)
    if not context.args:
        return update.message.reply_text(
            "Please provide ship modes. " "Example: /updateShipModes coil"
        )

    new_data = [c.strip() for c in context.args]
    r = db.settings.update_one(
        {"key": "logic"}, {"$set": {"ship_modes": new_data}}
    )
    logger.info(f"Ship modes logic updated: {r}")
    update.message.reply_text("Ship modes logic updated")


def help(update: Update, context: CallbackContext) -> None:
    """List commands"""
    logger.info("help")
    cmds = {
        "/status": status.__doc__,
        "/enable": enable.__doc__,
        "/disable": disable.__doc__,
        "/logic": logic.__doc__,
        "/updateDestinations": updateDestinations.__doc__,
        "/updateConsignees": updateConsignees.__doc__,
        "/updateShipModes": updateShipModes.__doc__,
    }

    text = "Supported Commands\n\n"
    for cmd, descr in cmds.items():
        text += f"{cmd} - {descr}\n"

    update.message.reply_text(text)


updater = Updater(BOT_TOKEN)
updater.dispatcher.add_handler(CommandHandler("help", help))
updater.dispatcher.add_handler(CommandHandler("status", status))
updater.dispatcher.add_handler(CommandHandler("disable", disable))
updater.dispatcher.add_handler(CommandHandler("enable", enable))
updater.dispatcher.add_handler(CommandHandler("logic", logic))
updater.dispatcher.add_handler(
    CommandHandler("updateDestinations", updateDestinations, pass_args=True)
)
updater.dispatcher.add_handler(
    CommandHandler("updateConsignees", updateConsignees, pass_args=True)
)
updater.dispatcher.add_handler(
    CommandHandler("updateShipModes", updateShipModes, pass_args=True)
)

updater.start_polling()
updater.idle()
