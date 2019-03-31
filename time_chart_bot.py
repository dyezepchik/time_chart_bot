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
 - /remove 2018-04-29 [2018-05-03] [12:00]
    Removes all schedule and upcoming classes for the given date(s)
    Args: date or dates range
 - /cancel
    Cancels current conversation with bot.

Conversation:
 To ask bot to subscribe you to a classes write it: "З(з)апиши меня" starting
 with a capital or a lowercase letter. To ask bot to unsubscribe you from a class
 write: О[о]тпиши меня or О[о]тмени запись.
 Then follow it's instructions.
"""
# TODO: Try pendulum https://github.com/sdispater/pendulum
import datetime as dt
import json
import re

from collections import defaultdict
from itertools import product, zip_longest

import apiai
import xlsxwriter

from psycopg2 import Error as DBError
from telegram import InlineKeyboardButton, ReplyKeyboardRemove
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
from tools import LIST_OF_ADMINS, logger, ReplyKeyboardWithCancel, WEEKDAYS


conn = db.create_connection(DATABASE_URL)

# Conversation states
ASK_PLACE_STATE,\
    ASK_DATE_STATE,\
    ASK_TIME_STATE,\
    RETURN_UNSUBSCRIBE_STATE,\
    ASK_FIRST_NAME_STATE, \
    ASK_LAST_NAME_STATE, \
    REMOVE_SCHEDULE_STATE = range(7)

# classes states
CLOSED, OPEN = False, True

# regex
place_regex = re.compile("^({})$".format("|".join(PLACES)), flags=re.IGNORECASE)
date_regex = re.compile("^([0-9]{4}-[0-9]{2}-[0-9]{2}).*")
time_regex = re.compile("^(" + "|".join(CLASSES_HOURS) + ")$")


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
                          "Удалить запись можно написав мне \"Отпиши меня\" или \"Отмени запись\. "
                          "А сейчас представься пожалуйста, чтобы я знал, кого я записываю на занятия. "
                          "Напиши свое имя.")
    return ASK_FIRST_NAME_STATE


def check_dates(start, end):
    """Check given dates correctness"""
    if not start or not end:
        return 1, "Косяк! Что-то не получилось."
    if start > end:
        return 1, "Нет, ну дата начала должна быть раньше даты окончания. Попробуй еще раз."
    elif (end - start).days > 6:
        return 1, "Можно добавлять/удалять не больше шести дат за раз. Попробуй еще раз."
    elif start < dt.date.today():
        return 1, "Дата начала уже в прошлом. Нужно указывать даты в будущем. Попробуй еще раз."
    return None, None


def add(bot, update, args):
    start, end = None, None
    user_id = update.effective_user.id
    if user_id not in LIST_OF_ADMINS:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Ага, счас! Только администратору можно!")
        return
    if len(args) == 2:
        try:
            start = dt.datetime.strptime(args[0], DATE_FORMAT).date()
            end = dt.datetime.strptime(args[1], DATE_FORMAT).date()
        except (ValueError, TypeError) as e:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Ой, наверное дата в каком-то кривом формате. Попробуй еще раз так 2019-05-01")
            return
        error, msg = check_dates(start, end)
        if error:
            bot.send_message(chat_id=update.message.chat_id, text=msg)
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
                         text="Расписание покажу только администратору!")
        return
    schedule = db.execute_select(db.get_full_schedule_sql, (dt.date.today().isoformat(),))
    user_ids = list(set(map(lambda x: x[6], schedule)))
    user_count = db.execute_select(db.get_user_visits_count, (dt.date.today().isoformat(), user_ids))
    user_count = dict(user_count)
    lines = [(line[0], str(line[1]), line[2],  # place, date, time
                       str(line[3]), "({})".format(line[5]), str(line[4]),  # Name (Nickname) Last Name
                       str(user_count.get(line[6], 0)))  # visit count
             for line in schedule]
    # partition by places
    records_by_date_place = defaultdict(list)
    for line in lines:
        # group by date+place
        records_by_date_place[(line[1], line[0])].append(line)
    # text = ""
    # for _, lines in records_by_place.items():
    #     text += "\n".join(lines) + "\n\n"
    # bot.send_message(chat_id=update.message.chat_id, text=text)
    workbook = xlsxwriter.Workbook('/tmp/schedule.xlsx')
    merge_format = workbook.add_format({
        'align': 'center',
        'bold': True,
    })
    worksheet = workbook.add_worksheet()
    row = 0
    for key in sorted(records_by_date_place.keys()):
        records = records_by_date_place[key]
        row += 1
        # merge cells and write 'day date place'
        date = dt.datetime.strptime(key[0], DATE_FORMAT).date()
        day = WEEKDAYS[date.weekday()]
        place = key[1]
        worksheet.merge_range(row, 1, row, 4, '{} {} {}'.format(day, date, place), merge_format)
        row += 1
        # write time slots
        col = 1
        for time in CLASSES_HOURS:
            worksheet.write(row, col, time)
            col += 1
        row += 1
        students_lists = defaultdict(list)
        for line in sorted(records, key=lambda x: x[5]):  # sort by last name
            students_lists[line[2]].append(line[5])
        lines = []
        for time in CLASSES_HOURS:
            lines.append(students_lists[time])
        for line in zip_longest(*lines, fillvalue=""):
            col = 1
            for val in line:
                worksheet.write(row, col, val)
                col += 1
            row += 1
    workbook.close()
    bot.send_document(chat_id=update.message.chat_id, document=open('/tmp/schedule.xlsx', 'rb'))


def remove_classes(date, time=None, place=None):
    """Remove classes from schedule

    :param date: the date to remove classes from
    :param time: is optional, if given only this time is removed
    :return: None
    """
    if not time:
        # remove schedule records for classes for given date
        classes_ids = db.execute_select(db.get_classes_ids_by_date_sql, (date, place))
        classes_ids = list(map(lambda x: x[0], classes_ids))
    else:
        # remove schedule records for classes for given date and time
        classes_ids = db.execute_select(db.get_classes_ids_by_date_time_sql, (date, time, place))
        classes_ids = list(map(lambda x: x[0], classes_ids))
    db.execute_insert(db.get_delete_schedules_for_classes_sql, (classes_ids,))
    db.execute_insert(db.get_delete_classes_sql, (classes_ids,))


def remove_schedule_continue(bot, update, user_data):
    response = update.message.text.strip()
    if response == "Отмена":
        bot.send_message(chat_id=update.message.chat_id,
                         text="Отменил. Попробуй заново.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    match = place_regex.match(response)
    if match:
        place = [match.group(1)]
    elif response == "Обе":
        place = PLACES
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Не распознал площадку. Не удалось удалить.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    start = user_data.get("start")
    end = user_data.get("end")
    time = user_data.get("time")
    if not end:
        end = start
    if start and end:
        day = start
        while day <= end:
            try:
                remove_classes(day, time, place)
            except DBError:
                bot.send_message(chat_id=update.message.chat_id,
                                 text="Косяк! Что-то не получилось.",
                                 reply_markup=ReplyKeyboardRemove())
                return ConversationHandler.END
            day += dt.timedelta(days=1)
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Что-то пошло не так. Непонятно что удалять.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    message = "Ок, удалил расписание на {}".format(start)
    if end != start:
        message += " - {}".format(end)
    if time:
        message += " {}".format(time)
    message += " на площадку {}.".format(place)
    bot.send_message(chat_id=update.message.chat_id,
                     text=message,
                     reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def remove(bot, update, args, user_data):
    """Set dates of classes to remove"""
    # init vars
    start, end, time = None, None, None
    user_id = update.effective_user.id
    if user_id not in LIST_OF_ADMINS:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Только администратор удалять расписание!",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if len(args) == 3:  # start_date end_date time_slot
        try:
            start = dt.datetime.strptime(args[0], DATE_FORMAT).date()
            end = dt.datetime.strptime(args[1], DATE_FORMAT).date()
            match = time_regex.match(args[2])
            time = match.group(1)
        except (AttributeError, TypeError, ValueError) as e:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Ой, наверное дата или время в каком-то кривом формате. "
                                  "Попробуй еще раз так 2019-05-01 2019-05-02 12:00.",
                             reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        error, msg = check_dates(start, end)
        if error:
            bot.send_message(chat_id=update.message.chat_id,
                             text=msg,
                             reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
    elif len(args) == 2:  # start_date end_date | date time_slot
        try:
            start = dt.datetime.strptime(args[0], DATE_FORMAT).date()
            end = dt.datetime.strptime(args[1], DATE_FORMAT).date()
        except (ValueError, TypeError) as e:
            try:
                start = dt.datetime.strptime(args[0], DATE_FORMAT).date()
                match = time_regex.match(args[1])
                time = match.group(1)
            except:
                bot.send_message(chat_id=update.message.chat_id,
                                 text="Ошибка! Наверное дата или время в каком-то кривом формате."
                                      " Попробуй еще раз.",
                                 reply_markup=ReplyKeyboardRemove())
                return ConversationHandler.END
        if start and end:
            error, msg = check_dates(start, end)
            if error:
                bot.send_message(chat_id=update.message.chat_id,
                                 text=msg,
                                 reply_markup=ReplyKeyboardRemove())
                return ConversationHandler.END
        else:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Что-то некорректно с датами или временем. Попробуй еще раз.",
                             reply_markup=ReplyKeyboardRemove())
    elif len(args) == 1:  # date
        try:
            date = dt.datetime.strptime(args[0], DATE_FORMAT).date()
        except (ValueError, TypeError) as e:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Ой, наверное дата в каком-то кривом формате. Попробуй еще раз так: 2019-05-01.",
                             reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        if date < dt.date.today():
            bot.send_message(chat_id=update.message.chat_id,
                             text="Вы пытаетесь удалить расписание на дату, которая уже в прошлом.",
                             reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
    else:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Непонятно что удалять.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    user_data["start"] = start
    user_data["end"] = end
    user_data["time"] = time

    choises = PLACES + ["Обе"]
    keyboard = [[InlineKeyboardButton(place, callback_data=place)] for place in choises]
    reply_markup = ReplyKeyboardWithCancel(keyboard, one_time_keyboard=True)
    bot.send_message(chat_id=update.message.chat_id, text="С какой площадки удаляем?", reply_markup=reply_markup)
    return REMOVE_SCHEDULE_STATE


def unknown(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text="Извини, не знаю такой команды.")


def error(bot, update, error):
    """Log Errors caused by Updates."""
    bot.send_message(chat_id=update.message.chat_id, text="Произошла какая-то ошибка. Попробуй еще раз.")
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
                         text="У тебя уже есть две записи. Сначала отмени другую запись.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(place, callback_data=place)] for place in PLACES]
    reply_markup = ReplyKeyboardWithCancel(keyboard, one_time_keyboard=True)
    bot.send_message(chat_id=update.message.chat_id,
                     text="На какую площадку хочешь?",
                     reply_markup=reply_markup)
    return ASK_PLACE_STATE


def ask_date(bot, update, user_data):
    msg = update.message.text.strip()
    if msg == "Отмена":
        bot.send_message(chat_id=update.message.chat_id,
                         text="Отменил. Попробуй заново.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    match = place_regex.match(msg)
    place = match.group(1)
    user_data['place'] = place
    open_dates = db.execute_select(db.get_open_classes_dates_sql, (dt.date.today().isoformat(), place))
    if open_dates:
        # show count of open time slots per day in the given place
        keyboard = [[InlineKeyboardButton("{} (свободно слотов {})".format(date, count), callback_data=str(date))]
                    for date, count in open_dates]
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
    msg = update.message.text.strip()
    if msg == "Отмена":
        bot.send_message(chat_id=update.message.chat_id,
                         text="Отменил. Попробуй заново.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    match = date_regex.match(msg)
    if not match:
        bot.send_message(chat_id=update.message.chat_id,
                         text="Плхоже, это была некорректная дата. Попробуй еще раз.",
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    date = match.group(1)
    # check for existing subscription for the date, 2 subs are not allowed per user per date
    user_id = update.effective_user.id
    subs = db.execute_select(db.get_user_subscriptions_for_date_sql, (user_id, date))
    if len(subs) > 0:
        bot.send_message(chat_id=update.message.chat_id,
                         text="У тебя уже есть запись на {}. "
                              "Чтобы записаться отмени ранее сделанную запись.".format(date),
                         reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    user_data['date'] = date
    place = user_data['place']
    time_slots = db.execute_select(db.get_open_classes_time_sql, (date, place))
    time_slots = map(lambda x: x[0], time_slots)
    # TODO: show count of open time slots
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
    user_id = update.effective_user.id
    user_subs = db.execute_select(db.get_user_subscriptions_sql, (user_id, dt.date.today().isoformat()))
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
    try:
        msg = update.message.text.strip()
        if msg == "Отмена":
            bot.send_message(chat_id=update.message.chat_id,
                             text="Отменил. Попробуй заново.",
                             reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        place, date, time = msg.split(" ")
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
                     text="Спасибо. Я тебя записал. {} {}, правильно? Если нет,"
                          " то используй команду /start чтобы изменить данные о себе."
                          " Если всё верно, попробуй записаться. Напиши 'Запиши меня'.".format(user[2], user[3]))
    return ConversationHandler.END


def end_conversation(bot, update):
    user = update.message.from_user
    logger.debug("User %s canceled the conversation.", user.first_name)
    bot.send_message(chat_id=update.message.chat_id,
                     text='Ок. На том и порешим пока.',
                     reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def run_bot():
    pp = PicklePersistence(filename='conversationbot')
    updater = Updater(token=BOT_TOKEN, persistence=pp)
    dispatcher = updater.dispatcher

    add_classes_handler = CommandHandler('add', add, pass_args=True)
    show_schedule_handler = CommandHandler('schedule', schedule)
    cancel_handler = CommandHandler('cancel', end_conversation)
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
            ASK_FIRST_NAME_STATE: [MessageHandler(Filters.text, store_first_name)],
            ASK_LAST_NAME_STATE: [MessageHandler(Filters.text, store_last_name)],
        },
        fallbacks=[CommandHandler('cancel', end_conversation)],
        name="identity_conversation",
        # persistent=True
    )

    dispatcher.add_handler(identity_handler)
    dispatcher.add_handler(add_classes_handler)
    dispatcher.add_handler(show_schedule_handler)
    dispatcher.add_handler(cancel_handler)
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
