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

import apiai
from telegram import ReplyKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CommandHandler, ConversationHandler, MessageHandler, Filters, Updater

from config import DATE_FORMAT, CLASSES_HOURS, DB_FILE, BOT_TOKEN
from db import create_connection, execute_insert, add_classes_dates_sql, upsert_user
from tools import LIST_OF_ADMINS


conn = create_connection(DB_FILE)

updater = Updater(token=BOT_TOKEN)
dispatcher = updater.dispatcher

logging.basicConfig(filename='time_chart_bot.log',
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# classes adding process
START, END = range(2)


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


def unknown(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text="Извини, не знаю такой команды.")


def error(bot, update, error):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, error)


# messages
def text_msg(bot, update):
    if update.message.text.lower() == "запиши меня":
        keyboard = [[
            InlineKeyboardButton("Завтра", callback_data=str(dt.date.today()+dt.timedelta(days=1))),
            InlineKeyboardButton("Послезавтра", callback_data=str(dt.date.today()+dt.timedelta(days=2))),
        ]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
        bot.send_message(chat_id=update.message.chat_id,
                         text="На когда?",
                         reply_markup=reply_markup)
    else:
        # handle continuation of registration
        # reply_markup = ReplyKeyboardRemove()
        # bot.send_message(chat_id=update.message.chat_id,
        #                  text="Ok, записал на {}".format(update.message.text),
        #                  reply_markup=reply_markup)        
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


def run_bot():
    start_cmd_handler = CommandHandler('start', start_cmd)
    add_classes_handler = CommandHandler('add', add, pass_args=True)
    unknown_handler = MessageHandler(Filters.command, unknown)

    text_msg_handler = MessageHandler(Filters.text, text_msg)

    dispatcher.add_handler(start_cmd_handler)
    dispatcher.add_handler(add_classes_handler)
    dispatcher.add_handler(unknown_handler)

    # Add subscribe handler with the states CHOOSE_DATE, CHOOSE_TIME
    # subscribe_conv_handler = ConversationHandler(
    #     entry_points=[CommandHandler('start', start)],
    #
    #     states={
    #         GENDER: [RegexHandler('^(Boy|Girl|Other)$', gender)],
    #
    #         PHOTO: [MessageHandler(Filters.photo, photo),
    #                 CommandHandler('skip', skip_photo)],
    #
    #         LOCATION: [MessageHandler(Filters.location, location),
    #                    CommandHandler('skip', skip_location)],
    #
    #         BIO: [MessageHandler(Filters.text, bio)]
    #     },
    #
    #     fallbacks=[CommandHandler('cancel', cancel)]
    # )
    #
    # dispatcher.add_handler(add_conv_handler)

    dispatcher.add_handler(text_msg_handler)

    # log all errors
    dispatcher.add_error_handler(error)

    updater.start_polling(clean=True)

    updater.idle()


if __name__ == '__main__':
    run_bot()
