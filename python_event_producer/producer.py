#!/usr/bin/env python3
"""
Dark Store Inventory — Python Event Producer Daemon

Continuously simulates realistic OLTP transactions against MSSQL.
Uses fast-forward time so Grafana dashboards stay lively.
"""

import os
import sys
import time
import signal
import random
from datetime import datetime, timedelta

import config
import event_logic
import traffic_model
import state_manager
from db import get_connection, jitter_minutes, fetch_all, fetch_one
from seeder import run_seeder


RUNNING = True


def _sigterm_handler(signum, frame):
    global RUNNING
    RUNNING = False


signal.signal(signal.SIGTERM, _sigterm_handler)
signal.signal(signal.SIGINT, _sigterm_handler)


def _next_workday_start(t: datetime) -> datetime:
    """Jump to next day 08:00."""
    t += timedelta(days=1)
    return t.replace(hour=config.SIM_START_HOUR, minute=0, second=0, microsecond=0)


def _flush_in_flight(conn, ref, in_flight, current_time):
    """Force all in-flight orders to a terminal state at end-of-day."""
    for order in in_flight[:]:
        if order.status == "pending":
            if random.random() < config.P_CONFIRM:
                result = event_logic.confirm_order(conn, ref, order, current_time)
                if result == "insufficient_stock":
                    event_logic.cancel_order(
                        conn, ref, order, current_time, "insufficient_stock"
                    )
                    print(
                        f"[{current_time.strftime('%H:%M')}] ORDER_CANCELLED       id={order.order_id} | reason=insufficient_stock (end-of-day)"
                    )
                else:
                    current_time += timedelta(seconds=1)
                    event_logic.deliver_order(conn, order, current_time)
                    print(
                        f"[{current_time.strftime('%H:%M')}] ORDER_DELIVERED       id={order.order_id} | fulfilled (end-of-day)"
                    )
            else:
                event_logic.cancel_order(conn, ref, order, current_time, "customer")
                print(
                    f"[{current_time.strftime('%H:%M')}] ORDER_CANCELLED       id={order.order_id} | reason=customer (end-of-day)"
                )
        elif order.status == "confirmed":
            event_logic.deliver_order(conn, order, current_time)
            print(
                f"[{current_time.strftime('%H:%M')}] ORDER_DELIVERED       id={order.order_id} | fulfilled (end-of-day)"
            )
        current_time += timedelta(seconds=1)
    return []


def _advance_in_flight(conn, ref, in_flight, current_time):
    """Check elapsed time on pending/confirmed orders and transition them."""
    orders_delivered = 0
    orders_cancelled = 0
    for order in in_flight[:]:
        if order.status in ("delivered", "cancelled"):
            continue
        elapsed = (current_time - order.created_at).total_seconds() / 60.0

        if order.status == "pending":
            threshold = jitter_minutes(
                random.randint(config.CONFIRM_DELAY_MIN, config.CONFIRM_DELAY_MAX)
            )
            if elapsed >= threshold:
                if random.random() < config.P_CONFIRM:
                    result = event_logic.confirm_order(conn, ref, order, current_time)
                    if result == "insufficient_stock":
                        event_logic.cancel_order(
                            conn, ref, order, current_time, "insufficient_stock"
                        )
                        orders_cancelled += 1
                        print(
                            f"[{current_time.strftime('%H:%M')}] ORDER_CANCELLED       id={order.order_id} | reason=insufficient_stock"
                        )
                    else:
                        print(
                            f"[{current_time.strftime('%H:%M')}] ORDER_CONFIRMED       id={order.order_id} | items={len(order.items)} | stock deducted"
                        )
                else:
                    event_logic.cancel_order(conn, ref, order, current_time, "customer")
                    orders_cancelled += 1
                    print(
                        f"[{current_time.strftime('%H:%M')}] ORDER_CANCELLED       id={order.order_id} | reason=customer"
                    )

        elif order.status == "confirmed":
            threshold = jitter_minutes(
                random.randint(config.DELIVER_DELAY_MIN, config.DELIVER_DELAY_MAX)
            )
            if elapsed >= threshold:
                if random.random() < config.P_DELIVER:
                    event_logic.deliver_order(conn, order, current_time)
                    orders_delivered += 1
                    print(
                        f"[{current_time.strftime('%H:%M')}] ORDER_DELIVERED       id={order.order_id} | fulfilled in {int(elapsed)} min"
                    )
                else:
                    event_logic.cancel_order(
                        conn, ref, order, current_time, "customer_post_confirm"
                    )
                    orders_cancelled += 1
                    print(
                        f"[{current_time.strftime('%H:%M')}] ORDER_CANCELLED       id={order.order_id} | reason=customer_post_confirm"
                    )

    # Prune terminal orders from the in-flight list
    in_flight[:] = [o for o in in_flight if o.status in ("pending", "confirmed")]
    return orders_delivered, orders_cancelled


def _generate_event(conn, ref, current_time, in_flight, stats):
    r = random.random()
    hour = current_time.hour

    if r < traffic_model.apply_traffic(config.P_ORDER_CREATE, hour):
        order = event_logic.create_order(conn, ref, current_time)
        if order:
            in_flight.append(order)
            stats["orders_created"] += 1
            print(
                f"[{current_time.strftime('%H:%M')}] ORDER_CREATED         id={order.order_id:<5} | cust={order.customer_id:<4} | store={order.store_id} | items={len(order.items)}"
            )

    elif r < traffic_model.apply_traffic(
        config.P_ORDER_CREATE + config.P_ADVANCE_ORDER, hour
    ):
        # Advance logic runs separately every tick; no extra action here
        pass

    elif r < traffic_model.apply_traffic(
        config.P_ORDER_CREATE + config.P_ADVANCE_ORDER + config.P_CUSTOMER_REG, hour
    ):
        cid = event_logic.register_customer(conn, ref, current_time)
        stats["customers_added"] += 1
        print(
            f"[{current_time.strftime('%H:%M')}] CUSTOMER_REGISTERED  id={cid}"
        )

    elif r < traffic_model.apply_traffic(
        config.P_ORDER_CREATE
        + config.P_ADVANCE_ORDER
        + config.P_CUSTOMER_REG
        + config.P_STOCK_ADJUST,
        hour,
    ):
        result = event_logic.adjust_stock(conn, ref, current_time)
        if result:
            stats["stock_adjustments"] += 1
            label = "shrinkage" if result < 0 else "found_extra"
            print(
                f"[{current_time.strftime('%H:%M')}] STOCK_ADJUSTED       delta={result:+d} | reason={label}"
            )

    elif r < traffic_model.apply_traffic(
        config.P_ORDER_CREATE
        + config.P_ADVANCE_ORDER
        + config.P_CUSTOMER_REG
        + config.P_STOCK_ADJUST
        + config.P_RESTOCK_CHECK,
        hour,
    ):
        pending_pos = fetch_all(
            conn,
            "SELECT po_id FROM Purchase_Order WHERE status = 'pending' ORDER BY ordered_at",
        )
        for (po_id,) in pending_pos:
            event_logic.receive_purchase_order(conn, ref, po_id, current_time)
            stats["po_received"] += 1
            print(
                f"[{current_time.strftime('%H:%M')}] PO_RECEIVED           po_id={po_id} | stock updated"
            )

        for sid in ref["store_ids"]:
            low_items = []
            stock_map = ref["stock"].get(sid, {})
            for pid, qty in stock_map.items():
                rp_row = fetch_one(
                    conn,
                    "SELECT reorder_point FROM Store_Inventory WHERE store_id = ? AND product_id = ?",
                    (sid, pid),
                )
                if rp_row and qty < rp_row[0]:
                    low_items.append(pid)
            if len(low_items) >= 1:
                pid_val = event_logic.create_purchase_order(conn, ref, sid, current_time)
                if pid_val:
                    stats["po_created"] += 1
                    print(
                        f"[{current_time.strftime('%H:%M')}] PO_CREATED            po_id={pid_val} | store={sid}"
                    )


def main():
    print("=" * 60)
    print("  DARK STORE INVENTORY — PYTHON EVENT PRODUCER")
    print(f"  Speed factor: {config.SIM_SPEED_FACTOR}s simulated / 1s real")
    print("=" * 60)
    print()

    conn = get_connection()

    # Idempotent seed
    table_count = fetch_one(conn, "SELECT COUNT(*) FROM sys.tables")[0]
    if table_count == 0:
        print("[PRODUCER] No tables found. Please run schema setup first.")
        sys.exit(1)

    # Check if we already have seed data
    category_count = fetch_one(conn, "SELECT COUNT(*) FROM Category")[0] or 0
    if category_count == 0:
        print("[PRODUCER] Seeding master data...")
        run_seeder(conn)
    else:
        print("[PRODUCER] Master data already present, skipping seed.")

    ref = event_logic._load_reference(conn)

    # Load persisted state or initialize
    sim_time, in_flight = state_manager.load_state()
    if sim_time is None:
        sim_time = datetime.now().replace(
            hour=config.SIM_START_HOUR, minute=0, second=0, microsecond=0
        )
        # If current real time is after start hour, shift to tomorrow to avoid backdated events
        if sim_time < datetime.now():
            sim_time += timedelta(days=1)
        in_flight = []
        print(f"[PRODUCER] Starting fresh simulation at {sim_time.strftime('%Y-%m-%d %H:%M')}")
    else:
        print(f"[PRODUCER] Resumed simulation at {sim_time.strftime('%Y-%m-%d %H:%M')} with {len(in_flight)} in-flight orders")

    stats = {
        "orders_created": 0,
        "orders_delivered": 0,
        "orders_cancelled": 0,
        "po_created": 0,
        "po_received": 0,
        "customers_added": 0,
        "stock_adjustments": 0,
    }

    last_hour = sim_time.hour

    try:
        while RUNNING:
            # --- Workday boundaries ---
            if sim_time.hour >= config.SIM_END_HOUR or sim_time.hour < config.SIM_START_HOUR:
                print(f"[{sim_time.strftime('%H:%M')}] NIGHT — flushing in-flight orders")
                in_flight = _flush_in_flight(conn, ref, in_flight, sim_time)
                sim_time = _next_workday_start(sim_time)
                print(f"[{sim_time.strftime('%H:%M')}] NEW DAY — simulation resumed")
                state_manager.save_state(sim_time, in_flight)
                continue

            # --- Advance in-flight orders every tick ---
            d, c = _advance_in_flight(conn, ref, in_flight, sim_time)
            stats["orders_delivered"] += d
            stats["orders_cancelled"] += c

            # --- Generate new event ---
            _generate_event(conn, ref, sim_time, in_flight, stats)

            # --- Hourly summary ---
            if sim_time.hour != last_hour:
                last_hour = sim_time.hour
                print(
                    f"[---] Hourly summary ({sim_time.strftime('%H:%M')}): created={stats['orders_created']}, delivered={stats['orders_delivered']}, cancelled={stats['orders_cancelled']}"
                )

            # --- Advance simulated clock ---
            sim_advance_minutes = random.randint(
                config.TICK_MIN_MINUTES, config.TICK_MAX_MINUTES
            )
            sim_advance_seconds = sim_advance_minutes * 60
            sim_time += timedelta(minutes=sim_advance_minutes)

            # --- Persist state ---
            state_manager.save_state(sim_time, in_flight)

            # --- Real sleep ---
            real_sleep = sim_advance_seconds / config.SIM_SPEED_FACTOR
            time.sleep(max(real_sleep, 0.01))

    except Exception as e:
        print(f"[PRODUCER] FATAL ERROR: {e}")
        raise
    finally:
        print("\n[PRODUCER] Shutting down gracefully...")
        state_manager.save_state(sim_time, in_flight)
        conn.close()
        print("[PRODUCER] Goodbye.")


if __name__ == "__main__":
    main()
