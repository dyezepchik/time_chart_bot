import os


# bot config
BOT_TOKEN = os.environ['BOT_TOKEN']

CLASSES_HOURS = ["12:00", "14:00", "16:00", "18:00", "20:00"]

DATABASE_URL = os.environ['DATABASE_URL']

DATE_FORMAT = "%Y-%m-%d"

# Conversation states
(ASK_PLACE_STATE,
 ASK_DATE_STATE,
 ASK_TIME_STATE,
 RETURN_UNSUBSCRIBE_STATE,
 ASK_GROUP_NUM_STATE,
 ASK_LAST_NAME_STATE,
 REMOVE_SCHEDULE_STATE) = range(7)

# classes states
CLOSED, OPEN = False, True

LIST_OF_ADMINS = list(map(int, os.environ['ADMIN_IDS'].split(',')))

PEOPLE_PER_TIME_SLOT = 8

PLACES = [
    "МГАК",
    "Мотокафе",
]

WEEKDAYS = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье"
)

WEEKDAYS_SHORT = (
    "Пн",
    "Вт",
    "Ср",
    "Чт",
    "Пт",
    "Сб",
    "Вc"
)
