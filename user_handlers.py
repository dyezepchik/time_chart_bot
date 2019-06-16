import datetime as dt
import re

from psycopg2 import Error as DBError
from telegram import InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ConversationHandler

import db
from config import (
    ASK_DATE_STATE,
    ASK_GROUP_NUM_STATE,
    ASK_LAST_NAME_STATE,
    ASK_PLACE_STATE,
    ASK_TIME_STATE,
    CLOSED,
    DATE_FORMAT,
    LIST_OF_ADMINS,
    OPEN,
    PEOPLE_PER_TIME_SLOT,
    PLACES,
    RETURN_UNSUBSCRIBE_STATE,
    WEEKDAYS_SHORT
)
from tools import (
    ReplyKeyboardWithCancel,
    date_regex,
    place_regex,
    time_regex
)


# commands
def start_cmd(bot, update):
    user_id = update.effective_user.id
    nick = update.effective_user.username or ""
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    db.upsert_user(user_id, nick, first_name, last_name)
    bot.send_message(chat_id=update.message.chat_id,
                     text="Привет! Я MD-помошник. Буду вас записывать на занятия. "
                          "Записаться можно при наличии времени в расписании, написав мне \"запиши меня\". "
                          "И я предложу выбрать из тех дат, которые остались свободными. "
                          "Удалить запись можно написав мне \"Отпиши меня\" или \"Отмени запись\". "
                          "А сейчас представься, пожалуйста, чтобы я знал, кого я записываю на занятия. "
                          "Напиши номер своей группы.")
    return ASK_GROUP_NUM_STATE


def ask_place(bot, update):
    """Entry point for 'subscribe' user conversation"""
    subscription_allowed = db.execute_select(db.get_settings_param_value, ("allow",))[0][0]
    if subscription_allowed == 'no':
        bot.send_message(chat_id=update.message.chat_id,
                         text="Сейчас запись на занятия закрыта.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    user_id = update.effective_user.id
    today = dt.date.today()
    if today.weekday() == 6:
        start_of_the_week = today + dt.timedelta(days=1)
    else:
        start_of_the_week = today - dt.timedelta(days=today.weekday())
    subs = db.execute_select(db.get_user_subscriptions_sql, (user_id, start_of_the_week.isoformat()))
    if user_id not in LIST_OF_ADMINS and len(subs) > 1:
        bot.send_message(chat_id=update.message.chat_id,
                         text="У тебя уже есть две записи на эту неделю. Сначала отмени другую запись.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(place, callback_data=place)] for place in PLACES]
    reply_markup = ReplyKeyboardWithCancel(keyboard, one_time_keyboard=True)
    bot.send_message(chat_id=update.message.chat_id,
                     text="На какую площадку хочешь?",
                     reply_markup=reply_markup)
    return ASK_PLACE_STATE


def ask_date(bot, update, user_data):
    """Asks date to subscribe to

    Dates are offered starting from 'tomorrow'. Users are not allowed to edit their subscriptions
    for 'today' and earlier.
    """
    msg = update.message.text.strip()
    if msg == "Отмена":
        bot.send_message(chat_id=update.message.chat_id,
                         text="Отменил. Попробуй заново.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    match = place_regex.match(msg)
    place = match.group(1)
    user_data['place'] = place
    open_dates = db.execute_select(db.get_open_classes_dates_sql,
                                   ((dt.date.today() + dt.timedelta(days=1)).isoformat(), place))
    if open_dates:
        keyboard = [[
            InlineKeyboardButton(
                "{} {} (свободно слотов {})".format(WEEKDAYS_SHORT[date.weekday()], date, count),
                callback_data=str(date)
            )
        ] for date, count in open_dates]
        reply_markup = ReplyKeyboardWithCancel(keyboard, one_time_keyboard=True)
        bot.send_message(chat_id=update.message.chat_id,
                         text="На когда?",
                         reply_markup=reply_markup)
        return ASK_DATE_STATE
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Нету открытых дат для записи.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END


def ask_time(bot, update, user_data):
    """Asks time to subscribe to

    Checks that the date given is not earlier than 'tomorrow'. Users are not allowed to edit their subscriptions
    for 'today' and earlier.
    """
    msg = update.message.text.strip()
    if msg == "Отмена":
        bot.send_message(chat_id=update.message.chat_id,
                         text="Отменил. Попробуй заново.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    match = date_regex.match(msg)
    if not match:
        # checks that the given message contains something similar to date
        bot.send_message(chat_id=update.message.chat_id,
                         text="Похоже, это была некорректная дата. Попробуй еще раз.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    date = match.group(1)
    try:
        # checks the actual date correctness
        date = dt.datetime.strptime(date, DATE_FORMAT).date()
    except ValueError:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Похоже, это была некорректная дата. Попробуй еще раз.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if date <= dt.date.today():
        bot.send_message(chat_id=update.message.chat_id,
                         text="Нельзя редактировать уже зафиксированные даты (сегодня и ранее)."
                              "Можно записываться на 'завтра' и позже.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    date = date.isoformat()
    # check for existing subscription for the date, 2 subs are not allowed per user per date
    user_id = update.effective_user.id
    subs = db.execute_select(db.get_user_subscriptions_for_date_sql, (user_id, date))
    if user_id not in LIST_OF_ADMINS and len(subs) > 0:
        bot.send_message(chat_id=update.message.chat_id,
                         text="У тебя уже есть запись на {}. "
                              "Чтобы записаться отмени ранее сделанную запись.".format(date),
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    user_data['date'] = date
    place = user_data['place']
    time_slots = db.execute_select(db.get_open_classes_time_sql, (date, place))
    time_slots = map(lambda x: x[0], time_slots)
    # TODO: show count of open positions per time
    keyboard = [[InlineKeyboardButton(str(time), callback_data=str(time))] for time in time_slots]
    reply_markup = ReplyKeyboardWithCancel(keyboard, one_time_keyboard=True)
    bot.send_message(chat_id=update.message.chat_id,
                     text="Теперь выбери время",
                     reply_markup=reply_markup)
    return ASK_TIME_STATE


def store_sign_up(bot, update, user_data):
    msg = update.message.text.strip()
    if msg == "Отмена":
        bot.send_message(chat_id=update.message.chat_id,
                         text="Отменил. Попробуй заново.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    match = time_regex.match(msg)
    if not match:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Плхоже, это было некорректное время. Попробуй еще раз.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    date = user_data['date']
    place = user_data['place']
    time = match.string
    user_id = update.effective_user.id
    # logic for admins to add students
    if user_id in LIST_OF_ADMINS:
        student_id = user_data.get('student_id')
        if student_id:
            user_id = student_id
            del (user_data['student_id'])
    class_id = db.execute_select(db.get_class_id_sql, (date, time, place))[0][0]
    db.execute_insert(db.set_user_subscription_sql, (user_id, class_id))
    # check if class is full (PEOPLE_PER_TIME_SLOT)
    people_count = db.execute_select(db.get_people_count_per_time_slot_sql, (date, time, place))[0][0]
    if people_count > PEOPLE_PER_TIME_SLOT:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Упс, на этот тайм слот уже записалось больше {} человек. "
                              "Попробуй еще раз на другой.".format(PEOPLE_PER_TIME_SLOT))
        db.execute_insert(db.delete_user_subscription_sql, (user_id, class_id))
    else:
        if people_count == PEOPLE_PER_TIME_SLOT:
            # set class open = False
            db.execute_insert(db.set_class_state, (CLOSED, class_id))
        bot.send_message(chat_id=update.message.chat_id,
                         text="Ok, записал на {} {} {}".format(place, date, time),
                         reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def ask_unsubscribe(bot, update):
    """Entry point for 'unsubscribe' user conversation

    Offer only subscriptions starting from 'tomorrow' for cancel.
    """
    subscription_allowed = db.execute_select(db.get_settings_param_value, ("allow",))[0][0]
    if subscription_allowed == 'no':
        bot.send_message(chat_id=update.message.chat_id,
                         text="Сейчас редактирование записи на занятия закрыто.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    user_id = update.effective_user.id
    user_subs = db.execute_select(db.get_user_subscriptions_sql,
                                  (user_id, (dt.date.today() + dt.timedelta(days=1)).isoformat()))
    if user_subs:
        keyboard = [[InlineKeyboardButton("{} {} {}".format(place, date, time), callback_data=(str(date), time))]
                    for place, date, time in user_subs]
        reply_markup = ReplyKeyboardWithCancel(keyboard, one_time_keyboard=True)
        bot.send_message(chat_id=update.message.chat_id,
                         text="Какое отменяем?",
                         reply_markup=reply_markup)
        return RETURN_UNSUBSCRIBE_STATE
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Нечего отменять, у тебя нет записи на ближайшие занятия.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END


def unsubscribe(bot, update):
    """Handler for 'unsubscribe' command

    The command allows user to unsubscribe himself from a specificclass.
    Removes him from schedule. Check that the date given is not 'today'
    or earlier.
    """
    try:
        msg = update.message.text.strip()
        if msg == "Отмена":
            bot.send_message(chat_id=update.message.chat_id,
                             text="Отменил. Попробуй заново.",
                             reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        place, date, time = msg.split(" ")
        try:
            class_date = dt.datetime.strptime(date, DATE_FORMAT).date()
        except ValueError:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Похоже, это была некорректная дата. Попробуй еще раз.",
                             reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        if class_date <= dt.date.today():
            bot.send_message(chat_id=update.message.chat_id,
                             text="Нельзя отменять запись в день занятия.",
                             reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        user_id = update.effective_user.id
        class_id = db.execute_select(db.get_class_id_sql, (date, time, place))[0][0]
        db.execute_insert(db.delete_user_subscription_sql, (user_id, class_id))
        people_count = db.execute_select(db.get_people_count_per_time_slot_sql, (date, time, place))[0][0]
        if people_count < PEOPLE_PER_TIME_SLOT:
            # set class open = True
            db.execute_insert(db.set_class_state, (OPEN, class_id))
        bot.send_message(chat_id=update.message.chat_id,
                         text="Ok, удалил запись на {} {} {}".format(place, date, time),
                         reply_markup=ReplyKeyboardRemove())
    except (ValueError, DBError):
        bot.send_message(chat_id=update.message.chat_id,
                         text="Что-то пошло не так. Попробуй еще раз.",
                         reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def store_group_num(bot, update):
    user_id = update.effective_user.id
    msg = update.message.text.strip().split()[0]
    group_num = re.match("\d+", msg)[0]
    if not group_num:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Я немного не понял. Просто напиши номер своей группы.")
        return ASK_GROUP_NUM_STATE
    db.execute_insert(db.update_user_group_sql, (int(group_num), user_id))
    bot.send_message(chat_id=update.message.chat_id,
                     text="Теперь напиши, пожалуйста, фамилию.")
    return ASK_LAST_NAME_STATE


def store_last_name(bot, update):
    user_id = update.effective_user.id
    surname = update.message.text.strip().split()[0]
    if not surname:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Я немного не понял. Просто напиши свою фамилию.")
        return ASK_LAST_NAME_STATE
    db.execute_insert(db.update_user_last_name_sql, (surname, user_id))
    user = db.execute_select(db.get_user_sql, (user_id,))[0]
    bot.send_message(chat_id=update.message.chat_id,
                     text="Спасибо. Я тебя записал. Твоя фамилия {}, и ты из {} группы правильно? Если нет,"
                          " то используй команду /start чтобы изменить данные о себе."
                          " Если всё верно, попробуй записаться. Напиши 'Запиши меня'.".format(user[3], user[4]))
    return ConversationHandler.END
