import datetime as dt
from collections import defaultdict
from itertools import product, zip_longest

import xlsxwriter
from psycopg2 import Error as DBError
from telegram import InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import ConversationHandler

import db
import student_lists
import telegramcalendar
from config import (
    CLASSES_HOURS,
    DATE_FORMAT,
    PLACES,
    REMOVE_SCHEDULE_STATE,
    WEEKDAYS
)
from tools import (
    ReplyKeyboardWithCancel,
    logger,
    place_regex,
    restricted,
    time_regex
)


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


@restricted()
def add(bot, update, user_data):
    """Handler for 'add' command, which adds schedule for new dates

    Handler actually only creates calendar keyboard
    """
    try:
        del(user_data['start'])
        del(user_data['end'])
    except KeyError:
        pass
    update.message.reply_text("Выбери первую дату: ",
                              reply_markup=telegramcalendar.create_calendar())


def inline_handler(bot, update, user_data):
    component = update.callback_query.data.split(";")[0]

    if component == telegramcalendar.COMPONENT:
        selected, date = telegramcalendar.process_calendar_selection(bot, update)
        if selected:
            if not user_data.get('start'):
                user_data['start'] = date.strftime("%Y-%m-%d")
                update.effective_message.reply_text("Выбери вторую дату: ",
                                                    reply_markup=telegramcalendar.create_calendar())
            else:
                user_data['end'] = date.strftime("%Y-%m-%d")
                date_range = "{} {}".format(user_data['start'], user_data['end'])
                keyboard = [[InlineKeyboardButton(f'/add_schedule {date_range}')]]
                reply_markup = ReplyKeyboardWithCancel(keyboard, one_time_keyboard=True)
                bot.send_message(chat_id=update.callback_query.from_user.id,
                                 text=f"Выбраны даты: {user_data['start']} - {user_data['end']}",
                                 reply_markup=reply_markup)
    elif component == student_lists.COMPONENT:
        selected, user_id = student_lists.process_user_selection(bot, update)
        if selected:
            user_data['student_id'] = user_id
            keyboard = [[InlineKeyboardButton('Запиши меня')]]
            reply_markup = ReplyKeyboardWithCancel(keyboard, one_time_keyboard=True)
            bot.send_message(chat_id=update.callback_query.from_user.id,
                             text=f"Добавляем студента: {user_id}",
                             reply_markup=reply_markup)


def add_schedule_continue(bot, update, args):
    start, end = None, None
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


@restricted(msg="Только администратор может удалять расписание!", returns=ConversationHandler.END)
def remove(bot, update, args, user_data):
    """Handler for 'remove' schedule command

    Handles dates of classes to remove
    """
    start, end, time = None, None, None
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
            start = dt.datetime.strptime(args[0], DATE_FORMAT).date()
        except (ValueError, TypeError) as e:
            bot.send_message(chat_id=update.message.chat_id,
                             text="Ой, наверное дата в каком-то кривом формате. Попробуй еще раз так: 2019-05-01.",
                             reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        if start < dt.date.today():
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


@restricted(msg="Расписание покажу только администратору!")
def schedule(bot, update, args):
    if len(args) > 0 and args[0] not in ('++', 'all'):
        bot.send_message(chat_id=update.message.chat_id, text="Наверное аргумент неправильный.")
        return
    add_count = args[0] == '++'
    full_schedule = args[0] == 'all'
    if full_schedule:
        schedule = db.execute_select(db.get_full_schedule_sql, (dt.date(2019, 4, 1).isoformat(),))
    else:
        schedule = db.execute_select(db.get_full_schedule_sql, (dt.date.today().isoformat(),))
    user_ids = list(set(map(lambda x: x[5] or 'unknown', schedule)))
    user_count = db.execute_select(db.get_user_visits_count, (dt.date.today().isoformat(), user_ids))
    user_count = dict(user_count)
    lines = [(line[0], str(line[1]), line[2],  # place, date, time
                       str(line[3]), line[4],  # GroupNum LastName
                       str(user_count.get(line[5], 0)))  # visit count
             for line in schedule]
    # partition by places
    records_by_date_place = defaultdict(list)
    for line in lines:
        # group by date+place
        records_by_date_place[(line[1], line[0])].append(line)
    workbook = xlsxwriter.Workbook('/tmp/schedule.xlsx')
    try:
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
            worksheet.merge_range(row, 1, row, 4, f"{day}, {date}, {place}", merge_format)
            row += 1
            # write time slots
            col = 1
            for time in CLASSES_HOURS:
                worksheet.write(row, col, time)
                col += 1
            row += 1
            students_lists = defaultdict(list)
            for line in sorted(records, key=lambda x: x[4] or ''):  # sort by last name
                string = f"{line[3]} {line[4]} ({line[5]})" if add_count else f"{line[3]} {line[4]}"
                students_lists[line[2]].append(string)
            lines = []
            for time in CLASSES_HOURS:
                lines.append(students_lists[time])
            for line in zip_longest(*lines, fillvalue=""):
                col = 1
                for val in line:
                    worksheet.write(row, col, val)
                    col += 1
                row += 1
    except Exception as e:
        logger.error(e)
    finally:
        workbook.close()
        bot.send_document(chat_id=update.message.chat_id, document=open('/tmp/schedule.xlsx', 'rb'))


@restricted(msg="Только администратор может разрешать запись на занятия!")
def allow(bot, update):
    """Handler for 'allow' command.

    Allows users to subscribe for opened classes
    """
    db.execute_insert(db.set_settings_param_value, ("yes", "allow"))
    bot.send_message(chat_id=update.message.chat_id,
                     text="Запись для курсантов открыта.")


@restricted(msg="Только администратор может закрывать запись на занятия!")
def disallow(bot, update):
    """Handler for 'disallow' command.

    Disallows users to subscribe for opened classes.
    """
    db.execute_insert(db.set_settings_param_value, ("no", "allow"))
    bot.send_message(chat_id=update.message.chat_id,
                     text="Запись для курсантов закрыта.")


@restricted(msg="Только администратор может записывать курсантов на занятия!")
def register(bot, update, user_data):
    """Handler for 'reg' command.

    Registers one of students to a class.
    Actually this handler only shows inline keyboard containing students list
    """
    try:
        del(user_data['student_id'])
    except KeyError:
        pass
    update.message.reply_text("Выбери кого добавляем: ",
                              reply_markup=student_lists.user_kbd())
