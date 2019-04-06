import os


# bot config
BOT_TOKEN = os.environ['BOT_TOKEN']

CLASSES_HOURS = ["12:00", "14:00", "16:00", "18:00"]

DATABASE_URL = os.environ['DATABASE_URL']

DATE_FORMAT = "%Y-%m-%d"

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
