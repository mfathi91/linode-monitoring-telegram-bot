import logging
import math
import os
import sys
from http import HTTPStatus
from pathlib import Path
from typing import Tuple

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
    reply_keyboard = [[linode.label] for linode in config.get_access_linodes(update.message.chat_id)]
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
        linode_id = [li.id for li in config.get_linodes() if li.label == linode_label][0]

        await update.message.reply_text(
            "در حال پردازش...",
            reply_markup=ReplyKeyboardRemove()
        )

        network_usage_1h, network_usage_24h, network_usage_30d = get_network_usage(linode_id)
        response = 'حجم ترافیک مصرفی تقریبی در ۱ ساعت گذشته:' \
                   f'\n{network_usage_1h or "-"}\n\n' \
                   'حجم ترافیک مصرفی تقریبی در ۲۴ ساعت گذشته:' \
                   f'\n{network_usage_24h or "-"}\n\n' \
                   f'حجم ترافیک مصرفی تقریبی در ۳۰ روز گذشته:' \
                   f'\n{network_usage_30d or "-"}\n\n'
        await update.message.reply_text(
            response,
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
def convert_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def get_authorization_header():
    return {'Authorization': f"Bearer {config.get_linode_pat()}"}


def get_network_usage(linode_id: str) -> Tuple[str, str, str]:
    network_stats = get_network_stats(linode_id)
    network_usage_past_1h = get_network_usage_from_stats(network_stats, '1h')
    network_usage_past_24h = get_network_usage_from_stats(network_stats, '24h')
    network_usage_past_30d = get_network_usage_past_30d(linode_id)
    return network_usage_past_1h, network_usage_past_24h, network_usage_past_30d


def get_network_stats(linode_id: str):
    headers = {'Authorization': f"Bearer {config.get_linode_pat()}"}
    response = requests.get(f'{config.get_linode_url()}/instances/{linode_id}/stats', headers=headers)
    if response.status_code == HTTPStatus.OK:
        return response.json()


def get_network_usage_past_30d(linode_id: str) -> str:
    response = requests.get(f'{config.get_linode_url()}/instances/{linode_id}/transfer', headers=get_authorization_header())
    if response.status_code == HTTPStatus.OK:
        response_json = response.json()
        if 'used' in response_json:
            return convert_size(response_json['used'])


def get_network_usage_from_stats(network_stats, duration: str) -> str:
    if 'data' in network_stats:
        bit_per_second_each_5m = [sample[1] for sample in network_stats['data']['netv4']['out']]
        # Samples are in 5-minute intervals
        bits_per_second = [(b * 5 * 60) for b in bit_per_second_each_5m]
        if duration == '1h':
            return convert_size(sum(bits_per_second[-1:-13:-1]) / 8)
        elif duration == '24h':
            return convert_size(sum(bits_per_second) / 8)
        else:
            raise ValueError('Unsupported operation error')


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

    # Start the Bot
    application.run_polling()


if __name__ == '__main__':
    main()
