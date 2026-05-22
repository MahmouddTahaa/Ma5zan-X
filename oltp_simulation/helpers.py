import random
from datetime import datetime, timedelta
import pyodbc
from faker import Faker
import oltp_simulation.config as config

fake = Faker()


def get_connection():
    return pyodbc.connect(config.DB_CONN_STRING)


def execute(conn, sql, params=None):
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    conn.commit()
    return cursor


def fetch_one(conn, sql, params=None):
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    return cursor.fetchone()


def fetch_all(conn, sql, params=None):
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    return cursor.fetchall()


def insert_and_get_id(conn, sql, params=None):
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else None


def fake_egyptian_phone():
    prefixes = ["010", "011", "012", "015"]
    return random.choice(prefixes) + " " + str(random.randint(10000000, 99999999))


def fake_eg_address():
    areas = [
        "El Tahrir St",
        "Abbas El-Akkad St",
        "Road 9",
        "26th of July St",
        "90th Street",
        "El Merghany St",
        "Faisal St",
        "El Nasr St",
        "Gameat El Dewal St",
        "Haram St",
        "Makram Ebeid St",
        "El Nozha St",
    ]
    return f"{random.randint(1, 250)} {random.choice(areas)}, {fake.city()}"


def fake_price(min_val, max_val):
    return round(random.uniform(min_val, max_val), 2)


def random_within_workday(start_hour, end_hour):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today + timedelta(hours=start_hour)
    end = today + timedelta(hours=end_hour)
    delta = (end - start).total_seconds()
    return start + timedelta(seconds=random.randint(0, int(delta)))


def jitter_minutes(base_minutes, pct=0.3):
    lo = max(1, int(base_minutes * (1 - pct)))
    hi = int(base_minutes * (1 + pct))
    return random.randint(lo, hi)


def weighted_choice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]


def db_exists(conn, table, column, value):
    row = fetch_one(
        conn, f"SELECT COUNT(*) FROM [{table}] WHERE [{column}] = ?", (value,)
    )
    return row[0] > 0 if row else False


def db_exists_pair(conn, table, col1, val1, col2, val2):
    row = fetch_one(
        conn,
        f"SELECT COUNT(*) FROM [{table}] WHERE [{col1}] = ? AND [{col2}] = ?",
        (val1, val2),
    )
    return row[0] > 0 if row else False
