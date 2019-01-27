import logging
import sqlite3

from sqlite3 import Error

from config import DB_FILE


create_users_table = """
CREATE TABLE IF NOT EXISTS users (
 id integer PRIMARY KEY,
 nick_name text NOT NULL,
 first_name text,
 last_name text
);
"""

create_classes_table = """
CREATE TABLE IF NOT EXISTS classes (
 id integer PRIMARY KEY,
 date text NOT NULL,
 time text NOT NULL,
 open bool NOT NULL,
 UNIQUE(date, time)
);
"""

create_schedule_table = """
CREATE TABLE IF NOT EXISTS schedule (
 user_id integer NOT NULL,
 class_id integer NOT NULL,
 FOREIGN KEY (user_id) REFERENCES users (id)
 FOREIGN KEY (class_id) REFERENCES classes (id)
);
"""

add_classes_dates_sql = """
INSERT INTO classes (date, time, open)
VALUES (?,?,?);
 """

get_user_sql = """
SELECT * FROM users WHERE id=?;
"""

add_user_sql = """
INSERT INTO users (id, nick_name, first_name, last_name)
VALUES (?,?,?,?);
"""

update_user_sql = """
UPDATE users
SET nick_name = ?,
    first_name = ?,
    last_name = ?
WHERE
    id = ?;
"""

get_open_classes_dates_sql = """
SELECT date, count(*) from classes 
WHERE date > ? AND open = 1
GROUP BY date
ORDER BY date;
"""

get_open_classes_time_sql = """
SELECT time FROM classes WHERE date = ? AND open = 1;
"""

set_user_subscription_sql = """
INSERT INTO schedule (user_id, class_id) VALUES (?,?);
"""

get_class_id_sql = """
SELECT id from classes WHERE date = ? AND time = ?;
"""

get_full_schedule_sql = """
SELECT date, time, first_name, last_name, nick_name 
FROM classes cl 
JOIN schedule sch ON cl.id=sch.class_id 
JOIN users us ON us.id=sch.user_id
WHERE cl.date>? 
ORDER BY cl.date, cl.time;
"""

get_user_subscriptions_sql = """
SELECT cl.date, cl.time FROM schedule sch 
JOIN classes cl ON sch.class_id=cl.id
WHERE sch.user_id = ? and cl.date >= ?;
"""

delete_user_subscription_sql = """
DELETE FROM schedule WHERE user_id = ? AND class_id = ?;
"""

get_people_count_per_time_slot_sql = """
SELECT COUNT(*) FROM schedule sch 
JOIN classes cl ON sch.class_id=cl.id
WHERE cl.date = ? AND cl.TIME = ?;
"""

set_class_state = """
UPDATE classes
SET open = ?
WHERE
    id = ?;
"""


def create_connection(db_file):
    """ create a database connection to a SQLite database """
    try:
        conn = sqlite3.connect(db_file)
        logging.debug("Db connection established.")
        return conn
    except Error as e:
        logging.error("sqlite3 error: {}", e)
    return None


def execute_insert(sql, values):
    """Execute given sql"""
    conn = create_connection(DB_FILE)
    with conn:
        try:
            c = conn.cursor()
            c.execute(sql, values)
            conn.commit()
        except Error as e:
            conn.rollback()
            logging.error("sqlite3 error: {}", e)
            raise e


def execute_select(sql, values):
    """Execute given sql"""
    conn = create_connection(DB_FILE)
    with conn:
        try:
            cur = conn.cursor()
            cur.execute(sql, values)
            return cur.fetchall()
        except Error as e:
            logging.error("sqlite3 error: {}", e)
            raise e


def upsert_user(user_id, nick_name, first_name, last_name):
    """Add a new user to the db ot update the record"""
    if execute_select(get_user_sql, (user_id,)):
        execute_insert(update_user_sql, (nick_name, first_name, last_name, user_id))
    else:
        execute_insert(add_user_sql, (user_id, nick_name, first_name, last_name))


def migrate(conn):
    # create tables
    sqls = [
        create_users_table,
        create_classes_table,
        create_schedule_table
    ]
    c = conn.cursor()
    for sql in sqls:
        c.execute(sql)
    conn.commit()


if __name__ == "__main__":
    conn = create_connection(DB_FILE)
    migrate(conn)
