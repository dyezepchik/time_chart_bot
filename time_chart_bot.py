"""Time chart bot documentation

Commands:
 - /start
    On start bot checks if user exists in database already and adds him if not
 - /add [2018-04-29 2018-05-04]
    Adds a new schedule for an ongoing period between start and end dates

"""
# Try pendulum https://github.com/sdispater/pendulum
import datetime as dt
import json
import logging
import re

import apiai
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

from config import DATE_FORMAT, CLASSES_HOURS, DB_FILE, BOT_TOKEN
from db import (
    create_connection,
    execute_insert,
    execute_select,
    add_classes_dates_sql,
    get_open_classes_dates_sql,
    get_open_classes_time_sql,
    upsert_user,
    set_user_date_time_sql,
    get_class_id_sql,
    get_full_schedule_sql,
    get_user_subscriptions_count_sql
)

from tools import LIST_OF_ADMINS


conn = create_connection(DB_FILE)

logging.basicConfig(filename='time_chart_bot.log',
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states
DATE, TIME = range(2)

# regex
date_regex = re.compile("^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
time_regex = re.compile("^(" + "|".join(CLASSES_HOURS) + ")$")


# commands
def start_cmd(bot, update):
    user_id = update.effective_user.id
    nick = update.effective_user.username
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    upsert_user(user_id, nick, first_name, last_name)
    bot.send_message(chat_id=update.message.chat_id,
                     text="Привет! Я бот вместо мамки. Буду вас записывать на занятия. "
                          "Записаться можно при наличии времени в расписании, написав мне \"запиши меня\". "
                          "И я предложу выбрать из тех дат, которые остались свободными.")


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
                             text="Ой, наверное дата в каком-то кривом формате. Попробуй еще раз так 2018-05-01")
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
            for time in CLASSES_HOURS:
                try:
                    execute_insert(add_classes_dates_sql, (day.isoformat(), time, True))
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
    schedule = execute_select(get_full_schedule_sql, (dt.date.today().isoformat(),))
    lines = [" ".join((line[0], line[1], line[2], "({})".format(line[4]), line[3])) for line in schedule]
    text = "\n".join(lines)
    bot.send_message(chat_id=update.message.chat_id, text=text)


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


def ask_date(bot, update):
    # check for number of subscriptions for the user, not more than 2
    user_id = update.effective_user.id
    subs_count = execute_select(get_user_subscriptions_count_sql, (user_id, dt.date.today().isoformat()))[0][0]
    if subs_count > 1:
        bot.send_message(chat_id=update.message.chat_id,
                         text="У тебя уже есть две записи. Сначала отмени другую запись.")
        return ConversationHandler.END
    open_dates = execute_select(get_open_classes_dates_sql, (dt.date.today().isoformat(),))
    open_dates = map(lambda x: x[0], open_dates)
    keyboard = [[InlineKeyboardButton(str(date), callback_data=str(date))] for date in open_dates]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    bot.send_message(chat_id=update.message.chat_id,
                     text="На когда?",
                     reply_markup=reply_markup)
    return DATE


def store_date(bot, update, user_data):
    match = date_regex.match(update.message.text)
    if not match:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Плхоже, это была некорректная дата. Попробуй еще раз.")
        return ConversationHandler.END
    date = match.string
    user_data['date'] = date
    times = execute_select(get_open_classes_time_sql, (date,))
    times = map(lambda x: x[0], times)
    keyboard = [[InlineKeyboardButton(str(time), callback_data=str(time))] for time in times]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    bot.send_message(chat_id=update.message.chat_id,
                     text="Теперь выбери время",
                     reply_markup=reply_markup)
    return TIME


def store_time(bot, update, user_data):
    match = time_regex.match(update.message.text)
    if not match:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Плхоже, это было некорректное время. Попробуй еще раз.")
        return ConversationHandler.END
    time = match.string
    user_id = update.effective_user.id
    class_id = execute_select(get_class_id_sql, (user_data['date'], time))[0][0]
    execute_insert(set_user_date_time_sql, (user_id, class_id))
    bot.send_message(chat_id=update.message.chat_id,
                     text="Ok, записал на {} {}".format(user_data['date'], time))
    return ConversationHandler.END


def end_conversation(bot, update):
    user = update.message.from_user
    logger.debug("User %s canceled the conversation.", user.first_name)
    update.message.reply_text('Ок. На том и порешим пока.')

    return ConversationHandler.END


def run_bot():
    pp = PicklePersistence(filename='conversationbot')
    updater = Updater(token=BOT_TOKEN, persistence=pp)
    dispatcher = updater.dispatcher

    start_cmd_handler = CommandHandler('start', start_cmd)
    add_classes_handler = CommandHandler('add', add, pass_args=True)
    add_schedule_handler = CommandHandler('schedule', schedule)
    unknown_handler = MessageHandler(Filters.command, unknown)

    dispatcher.add_handler(start_cmd_handler)
    dispatcher.add_handler(add_classes_handler)
    dispatcher.add_handler(add_schedule_handler)
    dispatcher.add_handler(unknown_handler)

    # Add subscribe handler with the states CHOOSE_DATE, CHOOSE_TIME
    subscribe_conv_handler = ConversationHandler(
        entry_points=[RegexHandler(".*([Зз]апиши меня).*", ask_date)],
        states={
            DATE: [MessageHandler(Filters.text, store_date, pass_user_data=True)],
            TIME: [MessageHandler(Filters.text, store_time, pass_user_data=True)],
        },
        fallbacks=[CommandHandler('cancel', end_conversation)],
        name="subscribe_conversation",
        persistent=True
    )
    dispatcher.add_handler(subscribe_conv_handler)

    text_msg_handler = MessageHandler(Filters.text, text_msg)
    dispatcher.add_handler(text_msg_handler)

    # log all errors
    dispatcher.add_error_handler(error)

    updater.start_polling(clean=True)

    updater.idle()


if __name__ == '__main__':
    run_bot()
