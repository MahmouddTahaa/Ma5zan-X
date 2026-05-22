"""
State persistence — survives container restarts
"""

import sqlite3
import json
from datetime import datetime
import config
from event_logic import OrderInFlight


def _init():
    conn = sqlite3.connect(config.STATE_DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sim_clock (id INTEGER PRIMARY KEY CHECK (id = 1), simulated_time TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS in_flight_orders (order_id INTEGER PRIMARY KEY, data TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()


def save_state(simulated_time: datetime, in_flight_orders: list):
    _init()
    conn = sqlite3.connect(config.STATE_DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO sim_clock (id, simulated_time) VALUES (1, ?)",
        (simulated_time.isoformat(),),
    )
    conn.execute("DELETE FROM in_flight_orders")
    for order in in_flight_orders:
        conn.execute(
            "INSERT INTO in_flight_orders (order_id, data) VALUES (?, ?)",
            (order.order_id, json.dumps(order.to_dict())),
        )
    conn.commit()
    conn.close()


def load_state():
    _init()
    conn = sqlite3.connect(config.STATE_DB_PATH)
    row = conn.execute("SELECT simulated_time FROM sim_clock WHERE id = 1").fetchone()
    sim_time = datetime.fromisoformat(row[0]) if row else None
    orders = []
    if sim_time:
        # Discard stale state (> 1 day old) to avoid phantom in-flight orders
        age_hours = (datetime.now() - sim_time).total_seconds() / 3600
        if age_hours < 48:
            for r in conn.execute("SELECT data FROM in_flight_orders"):
                try:
                    orders.append(OrderInFlight.from_dict(json.loads(r[0])))
                except Exception:
                    pass
    conn.close()
    return sim_time, orders


def clear_state():
    _init()
    conn = sqlite3.connect(config.STATE_DB_PATH)
    conn.execute("DELETE FROM sim_clock")
    conn.execute("DELETE FROM in_flight_orders")
    conn.commit()
    conn.close()
