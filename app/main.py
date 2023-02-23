import logging
import math
import os
import sys
import uuid
from pathlib import Path

import matplotlib.pyplot as plt
import requests
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from configuration import Configuration

# Ensure the env variable is present
version_env = os.environ.get('VERSION', None)
volumes_dir_env = os.environ.get('VOLUMES_DIRECTORY', None)
if not version_env:
    raise RuntimeError('VERSION not defined as an environment variable')
if not volumes_dir_env:
    raise RuntimeError('VOLUMES_DIRECTORY not defined as an environment variable')
volumes_dir = Path(volumes_dir_env)

# Enable logging
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
file_handler = logging.FileHandler(Path.joinpath(volumes_dir, 'log.txt'))
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        console_handler,
        file_handler
    ]
)

# Create and initialize the configuration
config = Configuration(str(Path(volumes_dir, 'config.json')), logging)

# Build the application
logging.info(f'Detected version: {version_env}')
application = Application.builder().token(config.get_token()).build()

# State of the conversations
STATUS_END = 1


# ------------------ status conversation --------------------
async def status_choose_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logging.info("User %s issued /status command", update.message.from_user.first_name)
    reply_keyboard = [[linode.label] for linode in config.get_linodes()]
    await update.message.reply_text(
        'Which Linode do you want to see?',
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True
        ),
    )
    return STATUS_END


async def status_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    linode_label = update.message.text
    linode_id = [li.id for li in config.get_linodes() if li.label == linode_label][0]

    last_month_usage = get_last_month_usage(linode_id)
    if last_month_usage:
        response = f'Network usage in the last 30 days: {last_month_usage}'
    else:
        response = 'Statistics not available. Try again later.'

    await update.message.reply_text(
        response,
        reply_markup=ReplyKeyboardRemove(),
    )
    photo_path = get_last_24h_usage(linode_id)
    print(photo_path)
    with open(photo_path, 'rb') as ph:
        await update.message.reply_photo(
            photo=ph
        )
    return ConversationHandler.END


# ----------- cancel current operation for all the conversations -------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logging.info("User %s issued /cancel command", update.message.from_user.first_name)
    context.chat_data.clear()
    await update.message.reply_text(
        'Ok, the process is canceled.', reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# --------------------- Utility methods -----------------------
def convert_size(size_bytes: int):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def get_last_month_usage(linode_id: str):
    headers = {'Authorization': f"Bearer {config.get_linode_pat()}"}
    response = requests.get(f'{config.get_linode_url()}/instances/{linode_id}/transfer', headers=headers).json()
    return convert_size(response['used']) if 'used' in response else None


def get_last_24h_usage(linode_id: str) -> str:
    headers = {'Authorization': f"Bearer {config.get_linode_pat()}"}
    response = requests.get(f'{config.get_linode_url()}/instances/{linode_id}/stats', headers=headers).json()
    megabit_per_second = [elem[1]/1000000 for elem in response['data']['netv4']['out']]
    plt.cla()
    plt.plot(megabit_per_second)
    plt.xlabel('Time')
    plt.ylabel('Network Usage (megabit/sec)')
    plt.title('Network Usage in the Last 24 Hours')
    path = f'/tmp/{uuid.uuid4()}.png'
    plt.savefig(path)
    return path


def main():
    # Add conversation handler for getting wallet status
    wallet_status_handler = ConversationHandler(
        entry_points=[CommandHandler('status', status_choose_wallet, filters.User(config.get_chat_ids()))],
        states={
            STATUS_END: [MessageHandler(filters.Regex(f'^({"|".join(config.get_linode_labels())})$'), status_end)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(wallet_status_handler)

    # Start the Bot
    application.run_polling()


if __name__ == '__main__':
    main()
