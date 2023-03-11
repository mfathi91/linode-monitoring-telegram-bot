import datetime
import logging
import math
import os
import sys
from http import HTTPStatus
from pathlib import Path
from typing import Tuple
import threading
import time


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
    level=logging.INFO,
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


# ------------------ start command --------------------
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logging.info("User %s issued /start command", update.message.from_user.first_name)
    await update.message.reply_text(text=f'فرمان مورد نظر را از منو انتخاب کنید')
    return ConversationHandler.END


# ------------------ status conversation --------------------
async def status_choose_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logging.info("User %s issued /status command", update.message.from_user.first_name)
    reply_keyboard = [[linode.label] for linode in config.get_user_linodes(update.message.chat_id)]
    await update.message.reply_text(
        'سرور مورد نظر را انتخاب کنید',
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True
        ),
    )
    return STATUS_END


async def status_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    linode_label = update.message.text
    if config.can_user_access_linode(update.message.chat_id, linode_label):
        linode_id = config.get_linode_by_label(linode_label).id

        await update.message.reply_text(
            "در حال پردازش...",
            reply_markup=ReplyKeyboardRemove()
        )

        network_usage_1h, network_usage_24h, network_usage_30d = get_network_usage(linode_id)
        response = 'حجم ترافیک مصرفی تقریبی در 1 ساعت گذشته:' \
                   f'\n{human_readable(network_usage_1h) or "-"}\n\n' \
                   'حجم ترافیک مصرفی تقریبی در 24 ساعت گذشته:' \
                   f'\n{human_readable(network_usage_24h) or "-"}\n\n' \
                   f'حجم ترافیک مصرفی تقریبی در {datetime.datetime.today().day} روز گذشته (از ابتدای ماه):' \
                   f'\n{human_readable(network_usage_30d) or "-"}\n\n'
        await update.message.reply_text(
            response,
            reply_markup=ReplyKeyboardRemove(),
        )

        await update.message.reply_text(
            'توجه: چنانچه ترافیک روزانه شما از 35 گیگابایت، '
            'و ترافیک ماهانه شما از 1000 گیگابایت بیشتر شود، '
            'این امکان وجود دارد که سرور ایرانی، سرویس شما '
            'را محدود کند.',
            reply_markup=ReplyKeyboardRemove(),
        )

        return ConversationHandler.END


# ------------------ about command --------------------
async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logging.info("User %s issued /about command", update.message.from_user.first_name)
    await update.message.reply_text(text=f'VPN Monitoring Telegram Bot v{version_env}')
    return ConversationHandler.END


# ----------- cancel current operation for all the conversations -------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logging.info("User %s issued /cancel command", update.message.from_user.first_name)
    context.chat_data.clear()
    await update.message.reply_text(
        'اوکی. پردازش کنسل شد.', reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


# --------------------- Utility methods -----------------------
def human_readable(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def get_authorization_header():
    return {'Authorization': f"Bearer {config.get_linode_pat()}"}


def get_network_usage(linode_id: str) -> Tuple[int, int, int]:
    network_stats = get_network_stats(linode_id)
    network_usage_past_1h = None
    network_usage_past_24h = None
    if network_stats:
        network_usage_past_1h = get_network_usage_from_stats(network_stats, '1h')
        network_usage_past_24h = get_network_usage_from_stats(network_stats, '24h')
    network_usage_past_30d = get_network_usage_past_30d(linode_id)
    return network_usage_past_1h, network_usage_past_24h, network_usage_past_30d


def get_network_stats(linode_id: str):
    headers = {'Authorization': f"Bearer {config.get_linode_pat()}"}
    response = requests.get(f'{config.get_linode_url()}/instances/{linode_id}/stats', headers=headers)
    if response.status_code == HTTPStatus.OK:
        return response.json()


def get_network_usage_past_30d(linode_id: str) -> int:
    response = requests.get(f'{config.get_linode_url()}/instances/{linode_id}/transfer', headers=get_authorization_header())
    if response.status_code == HTTPStatus.OK:
        response_json = response.json()
        if 'used' in response_json:
            return response_json['used']


def get_network_usage_from_stats(network_stats, duration: str) -> int:
    if 'data' in network_stats:
        bit_per_second_each_5m = [sample[1] for sample in network_stats['data']['netv4']['out']]
        # Samples are in 5-minute intervals
        bits_per_second = [(b * 5 * 60) for b in bit_per_second_each_5m]
        if duration == '1h':
            return int(sum(bits_per_second[-1:-13:-1]) // 8)
        elif duration == '24h':
            return int(sum(bits_per_second) // 8)
        else:
            raise ValueError('Unsupported operation error')


# -------------- background task for network control ----------------
def background_task_network_limiter(interval: int):
    while True:
        for linode in config.get_linodes():
            network_stats = get_network_stats(linode.id)
            if network_stats:
                actual_network_usage_24h_bytes = get_network_usage_from_stats(network_stats, '24h')
                if actual_network_usage_24h_bytes:
                    actual_network_usage_24h_gb = int(actual_network_usage_24h_bytes / 1024 / 1024 / 1024)
                    if actual_network_usage_24h_gb > linode.max_daily_network_gb and get_linode_status(linode.id) == 'running':
                        logging.info(f'[{linode.label}] is consuming [{actual_network_usage_24h_gb} GB], '
                                     f'which is more than the allowed limit [{linode.max_daily_network_gb} GB]. '
                                     f'Attempting to shut it down...')
                        if shutdown_linode(linode.id):
                            logging.info(f'[{linode.label}] shut down successfully.')
                        else:
                            logging.warning(f'Unable to shut down [{linode.label}].')
        time.sleep(interval)


def shutdown_linode(linode_id: str):
    post_headers = {'Content-Type': 'application/json'}
    post_headers.update(get_authorization_header())
    response = requests.post(f'{config.get_linode_url()}/instances/{linode_id}/shutdown', headers=post_headers)
    if response.status_code == HTTPStatus.OK and get_linode_status(linode_id) in ('offline', 'shutting_down'):
        return True


def get_linode_status(linode_id: str):
    response = requests.get(f'{config.get_linode_url()}/instances/{linode_id}', headers=get_authorization_header())
    if response.status_code == HTTPStatus.OK:
        response_json = response.json()
        return response_json.get('status')


# --------------------- main method -----------------------
def main():
    # Add start command handler
    application.add_handler(CommandHandler('start', start_handler, filters.User(config.get_chat_ids())))

    # Add conversation handler for getting wallet status
    wallet_status_handler = ConversationHandler(
        entry_points=[CommandHandler('status', status_choose_wallet, filters.User(config.get_chat_ids()))],
        states={
            STATUS_END: [MessageHandler(filters.Regex(f'^({"|".join(config.get_linode_labels())})$'), status_end)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(wallet_status_handler)

    # Add command handler to get general information about the bot
    application.add_handler(CommandHandler('about', about_handler, filters.User(config.get_chat_ids())))

    # Start the background task to ensure linodes network usage doesn't exceed a certain limit
    network_usage_limiter = threading.Thread(target=background_task_network_limiter, daemon=True, args=(5*60,))
    network_usage_limiter.start()

    # Start the Bot
    application.run_polling()


if __name__ == '__main__':
    main()
