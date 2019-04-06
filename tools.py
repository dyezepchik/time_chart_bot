import logging
import os
from functools import wraps

from telegram import ReplyKeyboardMarkup, InlineKeyboardButton

from config import LIST_OF_ADMINS


logging.basicConfig(filename='time_chart_bot.log',
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)


def restricted(func):
    @wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in LIST_OF_ADMINS:
            print("Unauthorized access denied for {}.".format(user_id))
            return
        return func(bot, update, *args, **kwargs)
    return wrapped


class ReplyKeyboardWithCancel(ReplyKeyboardMarkup):

    def __init__(self,
                 keyboard,
                 resize_keyboard=False,
                 one_time_keyboard=False,
                 selective=False,
                 **kwargs):
        keyboard.append([InlineKeyboardButton("Отмена", callback_data="/cancel")])
        super(ReplyKeyboardWithCancel, self).__init__(
            keyboard,
            resize_keyboard=resize_keyboard,
            one_time_keyboard=one_time_keyboard,
            selective=selective,
            **kwargs
        )
