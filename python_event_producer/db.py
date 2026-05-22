import random
import time
from datetime import datetime, timedelta
import pyodbc
from faker import Faker
import config

fake = Faker()


class ConnectionPool:
    """Simple persistent connection with auto-reconnect."""

    def __init__(self, conn_string, max_retries=3):
        self._conn_string = conn_string
        self._max_retries = max_retries
        self._conn = None

    def get(self):
        if self._conn is None:
            self._connect()
        return self._conn

    def _connect(self):
        last_err = None
        for attempt in range(1, self._max_retries + 1):
            try:
                self._conn = pyodbc.connect(self._conn_string, timeout=10)
                return
            except Exception as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise last_err

    def close(self):
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


_pool = ConnectionPool(config.DB_CONN_STRING)


def get_connection():
    return _pool.get()


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


def jitter_minutes(base_minutes, pct=0.3):
    lo = max(1, int(base_minutes * (1 - pct)))
    hi = int(base_minutes * (1 + pct))
    return random.randint(lo, hi)


def weighted_choice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]
