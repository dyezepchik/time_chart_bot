import logging
import psycopg2

from psycopg2 import DatabaseError

from config import DATABASE_URL


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
 id SERIAL PRIMARY KEY,
 date DATE NOT NULL,
 time text NOT NULL,
 open bool NOT NULL,
 UNIQUE(date, time)
);
"""

create_schedule_table = """
CREATE TABLE IF NOT EXISTS schedule (
 user_id integer NOT NULL,
 class_id integer NOT NULL,
 FOREIGN KEY (user_id) REFERENCES users (id),
 FOREIGN KEY (class_id) REFERENCES classes (id)
);
"""

add_classes_dates_sql = """
INSERT INTO classes (date, time, open)
VALUES (%s,%s,%s);
 """

get_user_sql = """
SELECT * FROM users WHERE id=%s;
"""

add_user_sql = """
INSERT INTO users (id, nick_name, first_name, last_name)
VALUES (%s,%s,%s,%s);
"""

update_user_sql = """
UPDATE users
SET nick_name = %s,
    first_name = %s,
    last_name = %s
WHERE
    id = %s;
"""

get_open_classes_dates_sql = """
SELECT date, count(*) from classes 
WHERE date > %s AND open is true
GROUP BY date
ORDER BY date;
"""

get_open_classes_time_sql = """
SELECT time FROM classes WHERE date = %s AND open is true;
"""

set_user_subscription_sql = """
INSERT INTO schedule (user_id, class_id) VALUES (%s,%s);
"""

get_class_id_sql = """
SELECT id from classes WHERE date = %s AND time = %s;
"""

get_classes_ids_sql = """
SELECT id from classes WHERE date = %s;
"""

get_full_schedule_sql = """
SELECT date, time, first_name, last_name, nick_name 
FROM classes cl 
JOIN schedule sch ON cl.id=sch.class_id 
JOIN users us ON us.id=sch.user_id
WHERE cl.date>%s 
ORDER BY cl.date, cl.time;
"""

get_user_subscriptions_sql = """
SELECT cl.date, cl.time FROM schedule sch 
JOIN classes cl ON sch.class_id=cl.id
WHERE sch.user_id = %s and cl.date >= %s;
"""

delete_user_subscription_sql = """
DELETE FROM schedule WHERE user_id = %s AND class_id = %s;
"""

get_people_count_per_time_slot_sql = """
SELECT COUNT(*) FROM schedule sch 
JOIN classes cl ON sch.class_id=cl.id
WHERE cl.date = %s AND cl.TIME = %s;
"""

set_class_state = """
UPDATE classes
SET open = %s
WHERE
    id = %s;
"""


get_delete_schedules_for_classes_sql = """
    DELETE FROM schedule WHERE class_id = ANY(%s);
"""


get_delete_classes_sql = """
    DELETE FROM classes WHERE id = ANY(%s);
"""


def create_connection(conn_string):
    """ create a database connection to a SQLite database """
    try:
        conn = psycopg2.connect(conn_string, sslmode='require')
        logging.debug("Db connection established.")
        return conn
    except DatabaseError as e:
        logging.error("psycopg2 error: {}", e)
    return None


def execute_insert(sql, values):
    """Execute given sql"""
    conn = create_connection(DATABASE_URL)
    with conn:
        try:
            c = conn.cursor()
            c.execute(sql, values)
            conn.commit()
        except DatabaseError as e:
            conn.rollback()
            logging.error("psycopg2 error: {}", e)
            raise e


def execute_select(sql, values):
    """Execute given sql"""
    conn = create_connection(DATABASE_URL)
    with conn:
        try:
            cur = conn.cursor()
            cur.execute(sql, values)
            return cur.fetchall()
        except DatabaseError as e:
            logging.error("psycopg2 error: {}", e)
            raise e


def upsert_user(user_id, nick_name, first_name, last_name):
    """Add a new user to the db or update the record"""
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
    conn = create_connection(DATABASE_URL)
    migrate(conn)
