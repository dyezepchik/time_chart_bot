"""Time chart bot documentation

Commands:
 - /start
    On start bot checks if user exists in database already and adds him if not.
    After this asks user to introduce himself.
 - /add 2018-04-29 [2018-05-04]
    Adds a new schedule for an ongoing period between start and end dates
    Args: date ot dates range
 - /schedule
    Gives the full schedule of your upcoming classes
 - /remove 2018-04-29 [2018-05-03]
    Removes all schedule and upcoming classes for the given date(s)
    Args: date or dates range

Conversation:
 To ask bot to subscribe you to a classes write to it: "З(з)апиши меня" starting
 with a capital or lowercase letter. To ask bot to unsubscribe you from a class
 write: О[о]тпиши меня or О[о]тмени запись.
 Then follow it's instructions.
"""
# TODO: Try pendulum https://github.com/sdispater/pendulum
import datetime as dt
import json
import logging
import re

from collections import defaultdict
from itertools import product

import apiai

from psycopg2 import Error as DBError
from telegram import ReplyKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    CommandHandler,
    ConversationHandler,
    PicklePersistence,
    RegexHandler,
    MessageHandler,
    Filters,
    Updater
)

import db

from config import DATE_FORMAT, CLASSES_HOURS, DATABASE_URL, BOT_TOKEN, PEOPLE_PER_TIME_SLOT, PLACES
from tools import LIST_OF_ADMINS


conn = db.create_connection(DATABASE_URL)

logging.basicConfig(filename='time_chart_bot.log',
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states
ASK_PLACE_STATE,\
    ASK_DATE_STATE,\
    ASK_TIME_STATE,\
    RETURN_UNSUBSCRIBE_STATE,\
    ASK_FIRST_NAME_STATE, \
    ASK_LAST_NAME_STATE = range(6)

# classes states
CLOSED, OPEN = False, True

# regex
place_regex = re.compile("^({})$".format("|".join(PLACES)), flags=re.IGNORECASE)
date_regex = re.compile("^([0-9]{4}-[0-9]{2}-[0-9]{2}).*")
time_regex = re.compile("^(" + "|".join(CLASSES_HOURS) + ")$")


# commands
def start_cmd(bot, update):
    user_id = update.effective_user.id
    nick = update.effective_user.username
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    db.upsert_user(user_id, nick, first_name, last_name)
    bot.send_message(chat_id=update.message.chat_id,
                     text="Привет! Я MD-помошник. Буду вас записывать на занятия. "
                          "Записаться можно при наличии времени в расписании, написав мне \"запиши меня\". "
                          "И я предложу выбрать из тех дат, которые остались свободными. "
                          "Удалить запись можно написав мне \"Отпиши меня\" или \"Отмени запись\. "
                          "А сейчас представься пожалуйста, чтобы я знал, кого я записываю на занятия. "
                          "Напиши свое имя.")
    return ASK_FIRST_NAME_STATE


def add(bot, update, args):
    start, end = None, None
    user_id = update.effective_user.id
    if user_id not in LIST_OF_ADMINS:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Ага, счас! Только мамке можно!")
        return
    if len(args) == 2:
        try:
            start = dt.datetime.strptime(args[0], DATE_FORMAT).date()
            end = dt.datetime.strptime(args[1], DATE_FORMAT).date()
        except (ValueError, TypeError) as e:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Ой, наверное дата в каком-то кривом формате. Попробуй еще раз так 2019-05-01")
            return
        if start > end:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Нет, ну дата начала должна быть все же раньше даты окончания. "
                                  "Попробуй еще раз.")
            return
        elif (end-start).days > 5:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Так, у нас многовато дней для записи, договаривались не больше пяти. "
                                  "Попробуй еще раз.")
            return
        elif start < dt.date.today():
            bot.send_message(chat_id=update.message.chat_id,
                             text="Дата начала уже в прошлом. Нужно указывать даты в будущем. "
                                  "Попробуй еще раз.")
            return
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Что-то дат не то количество... Должны быть: первый день и последний. "
                              "Попробуй еще раз.")
        return
    day = start
    if start and end:
        while day <= end:
            for place, time in product(PLACES, CLASSES_HOURS):
                try:
                    db.execute_insert(db.add_classes_dates_sql, (place, day.isoformat(), time, True))
                except:
                    bot.send_message(chat_id=update.message.chat_id, text="Косяк! Что-то не получилось")
                    return
            day += dt.timedelta(days=1)
    bot.send_message(chat_id=update.message.chat_id, text="Ок! Добавил даты с {} по {}. "
                                                          "Все верно?".format(start, end))


def schedule(bot, update):
    user_id = update.effective_user.id
    if user_id not in LIST_OF_ADMINS:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Только мамке покажу расписание!")
        return
    schedule = db.execute_select(db.get_full_schedule_sql, (dt.date.today().isoformat(),))
    user_ids = list(set(map(lambda x: x[6], schedule)))
    user_count = db.execute_select(db.get_user_visits_count, (dt.date.today().isoformat(), user_ids))
    user_count = dict(user_count)
    lines = [" ".join((line[0], str(line[1]), line[2],  # place, date, time
                       str(line[3]), "({})".format(line[5]), str(line[4]),  # Name (Nickname) Last Name
                       str(user_count.get(line[6], 0))))  # visit count
             for line in schedule]
    # partition by places
    records_by_place = defaultdict(list)
    for place in PLACES:
        for line in lines:
            if place in line:
                records_by_place[place].append(line)
    text = ""
    for _, lines in records_by_place.items():
        text += "\n".join(lines) + "\n\n"
    bot.send_message(chat_id=update.message.chat_id, text=text)


def remove_schedules_by_date(date):
    # remove schedule records for classes for given date
    classes_ids = db.execute_select(db.get_classes_ids_sql, (date,))
    classes_ids = list(map(lambda x: x[0], classes_ids))
    db.execute_insert(db.get_delete_schedules_for_classes_sql, (classes_ids,))
    db.execute_insert(db.get_delete_classes_sql, (classes_ids,))


def remove(bot, update, args):
    """Remove dates of classes"""
    user_id = update.effective_user.id
    if user_id not in LIST_OF_ADMINS:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Только мамке можно удалять расписание!")
        return
    if len(args) == 2:
        try:
            start = dt.datetime.strptime(args[0], DATE_FORMAT).date()
            end = dt.datetime.strptime(args[1], DATE_FORMAT).date()
        except (ValueError, TypeError) as e:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Ой, наверное дата в каком-то кривом формате. Попробуй еще раз так 2019-05-01.")
            return
        if start > end:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Нет, ну дата начала должна быть раньше даты окончания. "
                                  "Попробуй еще раз.")
            return
        elif (end - start).days > 5:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Можно удалять не больше пяти дат за раз. "
                                  "Попробуй еще раз.")
            return
        elif start < dt.date.today():
            bot.send_message(chat_id=update.message.chat_id,
                             text="Дата начала уже в прошлом. Нужно указывать даты в будущем. "
                                  "Попробуй еще раз.")
            return
        day = start
        if not start or not end:
            bot.send_message(chat_id=update.message.chat_id, text="Косяк! Что-то не получилось.")
            return
        while day <= end:
            try:
                remove_schedules_by_date(day)
            except DBError:
                bot.send_message(chat_id=update.message.chat_id, text="Косяк! Что-то не получилось.")
                return
            day += dt.timedelta(days=1)
    elif len(args) == 1:
        try:
            date = dt.datetime.strptime(args[0], DATE_FORMAT).date()
        except (ValueError, TypeError) as e:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Ой, наверное дата в каком-то кривом формате. Попробуй еще раз так 2019-05-01.")
            return
        remove_schedules_by_date(date)
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Непонятно что удалять.")
        return
    bot.send_message(chat_id=update.message.chat_id, text="Ок, удалил расписание на {}".format(date))


def unknown(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text="Извини, не знаю такой команды.")


def error(bot, update, error):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, error)


# messages
def text_msg(bot, update):
    request = apiai.ApiAI('e0f0ee1fd08b4160bdb26c69df632678').text_request()
    request.lang = 'ru'
    request.session_id = 'MotoChatAIBot'
    request.query = update.message.text
    response_json = json.loads(request.getresponse().read().decode('utf-8'))
    response = response_json['result']['fulfillment']['speech']
    if response:
        bot.send_message(chat_id=update.message.chat_id, text=response)
    else:
        bot.send_message(chat_id=update.message.chat_id, text='Я не совсем понял.')


def ask_place(bot, update):
    # check for number of subscriptions for the user, not more than 2
    user_id = update.effective_user.id
    subs = db.execute_select(db.get_user_subscriptions_sql, (user_id, dt.date.today().isoformat()))
    if len(subs) > 1:
        bot.send_message(chat_id=update.message.chat_id,
                         text="У тебя уже есть две записи. Сначала отмени другую запись.")
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(place, callback_data=place)] for place in PLACES]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    bot.send_message(chat_id=update.message.chat_id,
                     text="На какую площадку хочешь?",
                     reply_markup=reply_markup)
    return ASK_PLACE_STATE


def ask_date(bot, update, user_data):
    match = place_regex.match(update.message.text.strip())
    place = match.group(1)
    user_data['place'] = place
    open_dates = db.execute_select(db.get_open_classes_dates_sql, (dt.date.today().isoformat(), place))
    if open_dates:
        # show count of open time slots per day in the given place
        keyboard = [[InlineKeyboardButton("{} (свободно слотов {})".format(date, count),
                                          callback_data=str(date))] for date, count in open_dates]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        bot.send_message(chat_id=update.message.chat_id,
                         text="На когда?",
                         reply_markup=reply_markup)
        return ASK_DATE_STATE
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Нету открытых дат для записи.")
        return ConversationHandler.END


def ask_time(bot, update, user_data):
    match = date_regex.match(update.message.text.strip())
    if not match:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Плхоже, это была некорректная дата. Попробуй еще раз.")
        return ConversationHandler.END
    date = match.group(1)
    # check for existing subscription for the date, 2 subs are not allowed per user per date
    user_id = update.effective_user.id
    subs = db.execute_select(db.get_user_subscriptions_for_date_sql, (user_id, date))
    if len(subs) > 0:
        bot.send_message(chat_id=update.message.chat_id,
                         text="У тебя уже есть запись на {}. "
                              "Чтобы записаться отмени ранее сделанную запись.".format(date))
        return ConversationHandler.END
    user_data['date'] = date
    place = user_data['place']
    time_slots = db.execute_select(db.get_open_classes_time_sql, (date, place))
    time_slots = map(lambda x: x[0], time_slots)
    # TODO: show count of open time slots
    keyboard = [[InlineKeyboardButton(str(time), callback_data=str(time))] for time in time_slots]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    bot.send_message(chat_id=update.message.chat_id,
                     text="Теперь выбери время",
                     reply_markup=reply_markup)
    return ASK_TIME_STATE


def store_sign_up(bot, update, user_data):
    match = time_regex.match(update.message.text.strip())
    if not match:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Плхоже, это было некорректное время. Попробуй еще раз.")
        return ConversationHandler.END
    date = user_data['date']
    place = user_data['place']
    time = match.string
    user_id = update.effective_user.id
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
                         text="Ok, записал на {} {} {}".format(place, date, time))
    return ConversationHandler.END


def ask_unsubscribe(bot, update):
    user_id = update.effective_user.id
    user_subs = db.execute_select(db.get_user_subscriptions_sql, (user_id, dt.date.today().isoformat()))
    if user_subs:
        keyboard = [[InlineKeyboardButton("{} {} {}".format(place, date, time), callback_data=(str(date), time))]
                    for place, date, time in user_subs]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        bot.send_message(chat_id=update.message.chat_id,
                         text="Какое отменяем?",
                         reply_markup=reply_markup)
        return RETURN_UNSUBSCRIBE_STATE
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Нечего отменять, у тебя нет записи на ближайшие занятия.")
        return ConversationHandler.END


def unsubscribe(bot, update):
    try:
        place, date, time = update.message.text.split(" ")
        user_id = update.effective_user.id
        class_id = db.execute_select(db.get_class_id_sql, (date, time, place))[0][0]
        db.execute_insert(db.delete_user_subscription_sql, (user_id, class_id))
        people_count = db.execute_select(db.get_people_count_per_time_slot_sql, (date, time, place))[0][0]
        if people_count < PEOPLE_PER_TIME_SLOT:
            # set class open = True
            db.execute_insert(db.set_class_state, (OPEN, class_id))
        bot.send_message(chat_id=update.message.chat_id,
                         text="Ok, удалил запись на {} {} {}".format(place, date, time))
    except (ValueError, DBError):
        bot.send_message(chat_id=update.message.chat_id,
                         text="Что-то пошло не так. Попробуй еще раз.")
    return ConversationHandler.END


def store_first_name(bot, update):
    user_id = update.effective_user.id
    name = update.message.text.strip().split()[0]
    if not name:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Я немного не понял. Просто напиши свое имя.")
        return ASK_FIRST_NAME_STATE
    db.execute_insert(db.update_user_first_name_sql, (name, user_id))
    bot.send_message(chat_id=update.message.chat_id,
                     text="Теперь напиши пожалуйста фамилию.")
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
                     text="Спасибо. Я тебя записал. {} {}, правильно? "
                     "Используй команду /start чтобы изменить данные о себе.".format(user[2], user[3]))
    return ConversationHandler.END


def end_conversation(bot, update):
    user = update.message.from_user
    logger.debug("User %s canceled the conversation.", user.first_name)
    bot.send_message(chat_id=update.message.chat_id,
                     text='Ок. На том и порешим пока.')
    return ConversationHandler.END


def run_bot():
    pp = PicklePersistence(filename='conversationbot')
    updater = Updater(token=BOT_TOKEN, persistence=pp)
    dispatcher = updater.dispatcher

    add_classes_handler = CommandHandler('add', add, pass_args=True)
    add_schedule_handler = CommandHandler('schedule', schedule)
    remove_schedule_handler = CommandHandler('remove', remove, pass_args=True)
    unknown_handler = MessageHandler(Filters.command, unknown)

    # Add user identity handler on /start command
    identity_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_cmd)],
        states={
            ASK_FIRST_NAME_STATE: [MessageHandler(Filters.text, store_first_name)],
            ASK_LAST_NAME_STATE: [MessageHandler(Filters.text, store_last_name)],
        },
        fallbacks=[CommandHandler('cancel', end_conversation)],
        name="identity_conversation",
        persistent=True
    )

    dispatcher.add_handler(identity_handler)
    dispatcher.add_handler(add_classes_handler)
    dispatcher.add_handler(add_schedule_handler)
    dispatcher.add_handler(remove_schedule_handler)
    dispatcher.add_handler(unknown_handler)

    # Add subscribe handler with the states ASK_DATE_STATE, ASK_TIME_STATE
    sign_up_conv_handler = ConversationHandler(
        entry_points=[RegexHandler(".*([Зз]апиши меня).*", ask_place)],
        states={
            ASK_PLACE_STATE: [MessageHandler(Filters.text, ask_date, pass_user_data=True)],
            ASK_DATE_STATE: [MessageHandler(Filters.text, ask_time, pass_user_data=True)],
            ASK_TIME_STATE: [MessageHandler(Filters.text, store_sign_up, pass_user_data=True)],
        },
        fallbacks=[CommandHandler('cancel', end_conversation)],
        name="subscribe_conversation",
        persistent=True
    )
    dispatcher.add_handler(sign_up_conv_handler)

    # Add unsubscribe handler with the states
    unsubscribe_conv_handler = ConversationHandler(
        entry_points=[RegexHandler(".*([Оо]тпиши меня|[Оо]тмени запись).*", ask_unsubscribe)],
        states={
            RETURN_UNSUBSCRIBE_STATE: [MessageHandler(Filters.text, unsubscribe)],
        },
        fallbacks=[CommandHandler('cancel', end_conversation)],
        name="unsubscribe_conversation",
        persistent=True
    )
    dispatcher.add_handler(unsubscribe_conv_handler)

    text_msg_handler = MessageHandler(Filters.text, text_msg)
    dispatcher.add_handler(text_msg_handler)

    # log all errors
    dispatcher.add_error_handler(error)

    updater.start_polling(clean=True)

    updater.idle()


if __name__ == '__main__':
    run_bot()
