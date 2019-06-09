"""Time chart bot documentation

Commands:
   /start
    On start bot checks if user exists in database already and adds him if not.
    After this asks user to introduce himself.
   /add 2018-04-29 [2018-05-04]
    Adds a new schedule for an ongoing period between start and end dates
    Args: date ot dates range
   /schedule
    Gives the full schedule of your upcoming classes
   /remove 2018-04-29 [2018-05-03] [12:00]
    Removes all schedule and upcoming classes for the given date(s)
    Args: date or dates range
   /cancel
    Cancels current conversation with bot.

Conversation:
 To ask bot to subscribe you to a classes write it: "З(з)апиши меня" starting
 with a capital or a lowercase letter. To ask bot to unsubscribe you from a class
 write: О[о]тпиши меня or О[о]тмени запись.
 Then follow it's instructions.
"""
# TODO: Try pendulum https://github.com/sdispater/pendulum
import json

import apiai
from telegram import ReplyKeyboardRemove
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    Filters,
    MessageHandler,
    PicklePersistence,
    RegexHandler,
    Updater
)

import db
from admin_handlers import (
    add,
    add_schedule_continue,
    allow, disallow,
    inline_handler,
    register,
    remove,
    remove_schedule_continue,
    schedule
)
from config import (
    ASK_DATE_STATE,
    ASK_GROUP_NUM_STATE,
    ASK_LAST_NAME_STATE,
    ASK_PLACE_STATE,
    ASK_TIME_STATE,
    BOT_TOKEN,
    DATABASE_URL,
    REMOVE_SCHEDULE_STATE,
    RETURN_UNSUBSCRIBE_STATE
)
from tools import logger
from user_handlers import (
    ask_date,
    ask_place,
    ask_time,
    ask_unsubscribe,
    start_cmd,
    store_group_num,
    store_last_name,
    store_sign_up,
    unsubscribe
)

conn = db.create_connection(DATABASE_URL)


def error(bot, update, error):
    """Log Errors caused by Updates."""
    bot.send_message(chat_id=update.message.chat_id, text="Произошла какая-то ошибка. Попробуй еще раз.")
    logger.warning('Update "%s" caused error "%s"', update, error)


def text_msg(bot, update):
    """Handler for all other text messages

    Are passed to DialogFlow AI
    """
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


def end_conversation(bot, update):
    user_id = update.effective_user.id
    logger.debug("User %s canceled the conversation.", user_id)
    bot.send_message(chat_id=update.message.chat_id,
                     text='Ок. На том и порешим пока.',
                     reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def unknown(bot, update):
    logger.info("User {} {} typed: {}".format(update.effective_user.id,
                                              update.effective_user.username,
                                              update.message.text))
    bot.send_message(chat_id=update.message.chat_id, text="Извини, не знаю такой команды.")


def run_bot():
    pp = PicklePersistence(filename='conversationbot')
    updater = Updater(token=BOT_TOKEN, persistence=pp)
    dispatcher = updater.dispatcher

    add_dialog_handler = CommandHandler('add', add, pass_user_data=True)
    add_classes_handler = CommandHandler('add_schedule', add_schedule_continue, pass_args=True)
    callback_handler = CallbackQueryHandler(inline_handler, pass_user_data=True)
    show_schedule_handler = CommandHandler('schedule', schedule, pass_args=True)
    cancel_handler = CommandHandler('cancel', end_conversation)
    allow_handler = CommandHandler('open', allow)
    disallow_handler = CommandHandler('close', disallow)
    register_handler = CommandHandler('reg', register, pass_user_data=True)
    remove_schedule_handler = ConversationHandler(
        entry_points=[CommandHandler('remove', remove, pass_args=True, pass_user_data=True)],
        states={
            REMOVE_SCHEDULE_STATE: [MessageHandler(Filters.text, remove_schedule_continue, pass_user_data=True)],
        },
        fallbacks=[CommandHandler('cancel', end_conversation)],
        name="remove_schedule",
        # persistent=True
    )
    unknown_handler = MessageHandler(Filters.command, unknown)

    # Add user identity handler on /start command
    identity_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_cmd)],
        states={
            ASK_GROUP_NUM_STATE: [MessageHandler(Filters.text, store_group_num)],
            ASK_LAST_NAME_STATE: [MessageHandler(Filters.text, store_last_name)],
        },
        fallbacks=[CommandHandler('cancel', end_conversation)],
        name="identity_conversation",
        # persistent=True
    )

    dispatcher.add_handler(identity_handler)
    dispatcher.add_handler(add_dialog_handler)
    dispatcher.add_handler(add_classes_handler)
    dispatcher.add_handler(callback_handler)
    dispatcher.add_handler(show_schedule_handler)
    dispatcher.add_handler(cancel_handler)
    dispatcher.add_handler(allow_handler)
    dispatcher.add_handler(disallow_handler)
    dispatcher.add_handler(register_handler)
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
        # persistent=True
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
        # persistent=True
    )
    dispatcher.add_handler(unsubscribe_conv_handler)

    text_msg_handler = MessageHandler(Filters.text, unknown)
    dispatcher.add_handler(text_msg_handler)

    # log all errors
    dispatcher.add_error_handler(error)

    updater.start_polling(clean=True)

    updater.idle()


if __name__ == '__main__':
    run_bot()
