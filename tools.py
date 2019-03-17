import os
from functools import wraps


LIST_OF_ADMINS = [
    512834590,  # my id
    616873314,
    # int(os.environ['ADMIN_ID']),
]


def restricted(func):
    @wraps(func)
    def wrapped(bot, update, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in LIST_OF_ADMINS:
            print("Unauthorized access denied for {}.".format(user_id))
            return
        return func(bot, update, *args, **kwargs)
    return wrapped
