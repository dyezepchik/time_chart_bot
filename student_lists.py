"""
Base methods for user_list keyboard creation and processing.
"""

import db
from itertools import zip_longest
from math import ceil

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


COMPONENT = 'users'


def create_callback_data(action, group_num, user_id):
    """ Create the callback data associated to each button"""
    return ";".join([COMPONENT, action, str(group_num), str(user_id)])


def separate_callback_data(data):
    """ Separate the callback data"""
    return data.split(";")[1:]


def user_kbd(group_num=None):
    """
    Create an inline keyboard with the people list of the given group num
    :param int group_num: group number to use for kbd creation, if None the latest group num is used.
    :return: Returns the InlineKeyboardMarkup object with the people list.
    """
    if group_num is None:
        group_num = db.execute_select(db.get_latest_group_num)[0][0]
    students = db.execute_select(db.get_users_sql, (group_num,))
    rows_num = ceil(len(students)/2)
    stud_pairs = zip_longest(students[:rows_num], students[rows_num:])
    keyboard = []
    # First row - group num
    data_ignore = create_callback_data("IGNORE", group_num, -1)
    data_cancel = create_callback_data("CANCEL", group_num, -1)
    row = []
    row.append(InlineKeyboardButton(f"Группа {group_num}", callback_data=data_ignore))
    keyboard.append(row)
    # Main rows
    for pair in stud_pairs:
        row = []
        row.append(InlineKeyboardButton(pair[0][1], callback_data=create_callback_data("STUDENT", group_num, pair[0][0])))
        if pair[1]:
            row.append(InlineKeyboardButton(pair[1][1], callback_data=create_callback_data("STUDENT", group_num, pair[1][0])))
        keyboard.append(row)
    # Last row - Buttons
    row = []
    row.append(InlineKeyboardButton("<", callback_data=create_callback_data("PREV-GROUP", group_num, -1)))
    row.append(InlineKeyboardButton("Отмена", callback_data=data_cancel))
    row.append(InlineKeyboardButton(">", callback_data=create_callback_data("NEXT-GROUP", group_num, -1)))
    keyboard.append(row)

    return InlineKeyboardMarkup(keyboard)


def process_user_selection(bot, update):
    """
    Process the callback_query. This method generates a new kbd if forward or
    backward is pressed. This method should be called inside a CallbackQueryHandler.
    :param telegram.Bot bot: The bot, as provided by the CallbackQueryHandler
    :param telegram.Update update: The update, as provided by the CallbackQueryHandler
    :return: Returns a tuple (Boolean, user_id), indicating if a student is selected
    """
    ret_data = (False, None)
    query = update.callback_query
    (action, group_num, user_id) = separate_callback_data(query.data)
    if action == "IGNORE":
        bot.answer_callback_query(callback_query_id=query.id)
    elif action == "CANCEL":
        bot.edit_message_text(text="Отменил",
                              chat_id=query.message.chat_id,
                              message_id=query.message.message_id)
    elif action == "STUDENT":
        bot.edit_message_text(text=query.message.text,
                              chat_id=query.message.chat_id,
                              message_id=query.message.message_id)
        ret_data = True, user_id
    elif action == "PREV-GROUP":
        bot.edit_message_text(text=query.message.text,
                              chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              reply_markup=user_kbd(int(group_num)-1))
    elif action == "NEXT-GROUP":
        bot.edit_message_text(text=query.message.text,
                              chat_id=query.message.chat_id,
                              message_id=query.message.message_id,
                              reply_markup=user_kbd(int(group_num)+1))
    else:
        bot.answer_callback_query(callback_query_id=query.id, text="Something went wrong!")
        # UNKNOWN
    return ret_data
