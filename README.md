# time_chart_bot
Some documentation is currently inside code docstrings

# What is this bot for?
The purpose of this bot is to allow people to subscribe to some classes forming a timetable for a classes owner. A classes owner/teacher/admin publishes a new schedule for certain period and it's initially empty. Then people start to ask bot to register them to the schedule.
Bot has some constraints for subscribers. Limit os subscriptions per person, limit of reople per time slot.
Admin has the ability to remove some dates from schedule.

# Technical info
Bot uses python-telegram-bot library to communicate to telegram and handle conversations, sqlite3 for storing users and classes schedule and also has the ability to connect to dialogflow to handle some smalltalk.
