"""
Layer 2 — Event Logic (business events)
"""

import random
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import config
from db import (
    get_connection,
    fetch_one,
    fetch_all,
    execute,
    insert_and_get_id,
    fake_price,
    jitter_minutes,
)


@dataclass
class OrderInFlight:
    order_id: int
    status: str
    created_at: datetime
    store_id: int
    customer_id: int
    items: list = field(default_factory=list)

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "store_id": self.store_id,
            "customer_id": self.customer_id,
            "items": self.items,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            order_id=d["order_id"],
            status=d["status"],
            created_at=datetime.fromisoformat(d["created_at"]),
            store_id=d["store_id"],
            customer_id=d["customer_id"],
            items=[tuple(x) for x in d["items"]],
        )


def _load_reference(conn):
    customers = fetch_all(conn, "SELECT customer_id, zone_id FROM Customer")
    customer_zone = {r[0]: r[1] for r in customers}
    customer_ids = list(customer_zone.keys())

    zones = fetch_all(conn, "SELECT zone_id, delivery_fee FROM Zone")
    zone_fees = {r[0]: r[1] for r in zones}

    stores = fetch_all(conn, "SELECT store_id FROM Dark_Store")
    store_ids = [r[0] for r in stores]

    products = fetch_all(conn, "SELECT product_id, category_id, name FROM Product")
    product_cat = {r[0]: r[1] for r in products}

    inv_rows = fetch_all(
        conn, "SELECT store_id, product_id, quantity_on_hand FROM Store_Inventory"
    )
    stock = {}
    for r in inv_rows:
        sid, pid, qty = r[0], r[1], r[2]
        stock.setdefault(sid, {})[pid] = qty

    cold_chain_products = set()
    for cat_name, cat_info in config.CATALOG.items():
        if cat_info["requires_cold_chain"]:
            prod_rows = fetch_all(
                conn,
                "SELECT product_id FROM Product p JOIN Category c ON p.category_id = c.category_id WHERE c.name = ?",
                (cat_name,),
            )
            for pr in prod_rows:
                cold_chain_products.add(pr[0])

    categories = fetch_all(conn, "SELECT category_id, name FROM Category")
    cat_price_ranges = {}
    for cid, cname in categories:
        if cname in config.CATALOG:
            cat_price_ranges[cid] = config.CATALOG[cname]["price_range"]

    suppliers = fetch_all(conn, "SELECT supplier_id FROM Supplier")
    supplier_ids = [r[0] for r in suppliers]

    return {
        "customer_zone": customer_zone,
        "customer_ids": customer_ids,
        "zone_fees": zone_fees,
        "store_ids": store_ids,
        "product_cat": product_cat,
        "stock": stock,
        "cold_chain_products": cold_chain_products,
        "cat_price_ranges": cat_price_ranges,
        "supplier_ids": supplier_ids,
    }


def _pick_order_items(ref, store_id, num_items):
    stock_map = ref["stock"].get(store_id, {})
    available = [(pid, qty) for pid, qty in stock_map.items() if qty > 0]
    if not available:
        return None
    n = min(num_items, len(available))
    chosen = random.sample(available, n)

    has_cold = any(pid in ref["cold_chain_products"] for pid, _ in chosen)
    if has_cold and random.random() < 0.30 and len(available) > n:
        extra_cold = [
            p
            for p in available
            if p[0] in ref["cold_chain_products"] and p not in chosen
        ]
        if extra_cold:
            chosen.append(random.choice(extra_cold))

    items = []
    for pid, avail_qty in chosen:
        cid = ref["product_cat"].get(pid)
        pr_range = ref["cat_price_ranges"].get(cid, (5, 50))
        qty = min(random.randint(1, 3), avail_qty)
        price = round(random.uniform(*pr_range), 2)
        items.append((pid, qty, price))
    return items


def create_order(conn, ref, current_time):
    customer_id = random.choice(ref["customer_ids"])
    store_id = random.choice(ref["store_ids"])
    zone_id = ref["customer_zone"].get(customer_id)
    delivery_fee = ref["zone_fees"].get(zone_id, 20.0)

    num_items = random.choices(
        [1, 2, 3, 4, 5], weights=config.ORDER_ITEM_COUNT_WEIGHTS, k=1
    )[0]
    items = _pick_order_items(ref, store_id, num_items)
    if items is None:
        return None

    sub_total = round(sum(qty * price for _, qty, price in items), 2)
    total_amount = round(float(sub_total) + float(delivery_fee), 2)

    payment_method = random.choices(
        config.PAYMENT_METHODS, weights=config.PAYMENT_WEIGHTS, k=1
    )[0]

    order_id = insert_and_get_id(
        conn,
        "INSERT INTO [Order] (store_id, customer_id, status, payment_method, sub_total, delivery_fee, total_amount, created_at) "
        "OUTPUT INSERTED.order_id "
        "VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)",
        (
            store_id,
            customer_id,
            payment_method,
            sub_total,
            delivery_fee,
            total_amount,
            current_time,
        ),
    )

    for pid, qty, price in items:
        execute(
            conn,
            "INSERT INTO Order_Item (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            (order_id, pid, qty, price),
        )

    execute(
        conn,
        "INSERT INTO Order_History (order_id, status, changed_at) VALUES (?, 'pending', ?)",
        (order_id, current_time),
    )

    return OrderInFlight(
        order_id=order_id,
        status="pending",
        created_at=current_time,
        store_id=store_id,
        customer_id=customer_id,
        items=items,
    )


def confirm_order(conn, ref, order, ts):
    for pid, qty, price in order.items:
        current_qty = ref["stock"].get(order.store_id, {}).get(pid, 0)
        if current_qty < qty:
            return "insufficient_stock"
    for pid, qty, price in order.items:
        ref["stock"][order.store_id][pid] -= qty
        execute(
            conn,
            "UPDATE Store_Inventory SET quantity_on_hand = quantity_on_hand - ?, last_updated = ? WHERE store_id = ? AND product_id = ?;"
            "INSERT INTO Inventory_Transaction (store_id, product_id, transaction_type, order_id, quantity_delta, quantity_after, timestamp_occurred) "
            "VALUES (?, ?, 'sale', ?, ?, ?, ?);",
            (
                qty,
                ts,
                order.store_id,
                pid,
                order.store_id,
                pid,
                order.order_id,
                -qty,
                ref["stock"][order.store_id][pid],
                ts,
            ),
        )
    execute(
        conn,
        "UPDATE [Order] SET status = 'confirmed' WHERE order_id = ?;"
        "INSERT INTO Order_History (order_id, status, changed_at) VALUES (?, 'confirmed', ?);",
        (order.order_id, order.order_id, ts),
    )
    order.status = "confirmed"
    return "ok"


def deliver_order(conn, order, ts):
    execute(
        conn,
        "UPDATE [Order] SET status = 'delivered' WHERE order_id = ?;"
        "INSERT INTO Order_History (order_id, status, changed_at) VALUES (?, 'delivered', ?);",
        (order.order_id, order.order_id, ts),
    )
    order.status = "delivered"


def cancel_order(conn, ref, order, ts, reason="customer"):
    if order.status == "confirmed":
        for pid, qty, price in order.items:
            ref["stock"][order.store_id][pid] += qty
            execute(
                conn,
                "UPDATE Store_Inventory SET quantity_on_hand = quantity_on_hand + ?, last_updated = ? WHERE store_id = ? AND product_id = ?;"
                "INSERT INTO Inventory_Transaction (store_id, product_id, transaction_type, order_id, quantity_delta, quantity_after, timestamp_occurred) "
                "VALUES (?, ?, 'return', ?, ?, ?, ?);",
                (
                    qty,
                    ts,
                    order.store_id,
                    pid,
                    order.store_id,
                    pid,
                    order.order_id,
                    qty,
                    ref["stock"][order.store_id][pid],
                    ts,
                ),
            )
    execute(
        conn,
        "UPDATE [Order] SET status = 'cancelled' WHERE order_id = ?;"
        "INSERT INTO Order_History (order_id, status, changed_at) VALUES (?, 'cancelled', ?);",
        (order.order_id, order.order_id, ts),
    )
    order.status = "cancelled"


def register_customer(conn, ref, ts):
    from db import fake, fake_egyptian_phone, fake_eg_address

    fn = fake.first_name()
    ln = fake.last_name()
    phone = fake_egyptian_phone()
    zone_id = random.choice(list(ref["zone_fees"].keys()))
    cust_id = insert_and_get_id(
        conn,
        "INSERT INTO Customer (zone_id, first_name, last_name, phone_number, full_address, registered_time) "
        "OUTPUT INSERTED.customer_id "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (zone_id, fn, ln, phone, fake_eg_address(), ts),
    )
    ref["customer_ids"].append(cust_id)
    ref["customer_zone"][cust_id] = zone_id
    return cust_id


def adjust_stock(conn, ref, ts):
    store_id = random.choice(ref["store_ids"])
    stock_map = ref["stock"].get(store_id, {})
    if not stock_map:
        return None
    pid = random.choice(list(stock_map.keys()))
    decrease = random.random() < 0.80
    qty = random.randint(1, 5)
    delta = -qty if decrease else qty
    if stock_map[pid] + delta < 0:
        delta = -stock_map[pid]

    if delta == 0:
        return None

    ref["stock"][store_id][pid] += delta
    reason = "damage" if decrease else "found_extra"

    execute(
        conn,
        "UPDATE Store_Inventory SET quantity_on_hand = quantity_on_hand + ?, last_updated = ? WHERE store_id = ? AND product_id = ?;"
        "INSERT INTO Inventory_Transaction (store_id, product_id, transaction_type, quantity_delta, quantity_after, timestamp_occurred) "
        "VALUES (?, ?, 'adjustment', ?, ?, ?);",
        (
            delta,
            ts,
            store_id,
            pid,
            store_id,
            pid,
            delta,
            ref["stock"][store_id][pid],
            ts,
        ),
    )
    return delta


def create_purchase_order(conn, ref, store_id, ts):
    low_stock = []
    stock_map = ref["stock"].get(store_id, {})
    for pid, qty in stock_map.items():
        row = fetch_one(
            conn,
            "SELECT reorder_point, reorder_quantity FROM Store_Inventory WHERE store_id = ? AND product_id = ?",
            (store_id, pid),
        )
        if row and qty < row[0]:
            low_stock.append((pid, qty, row[1]))

    if not low_stock:
        if random.random() < 0.50:
            chosen = random.sample(list(stock_map.keys()), k=min(3, len(stock_map)))
            low_stock = [(pid, stock_map[pid], 100) for pid in chosen]
        else:
            return None

    supplier_id = random.choice(ref["supplier_ids"])
    po_id = insert_and_get_id(
        conn,
        "INSERT INTO Purchase_Order (store_id, supplier_id, status, total_price, ordered_at) "
        "OUTPUT INSERTED.po_id "
        "VALUES (?, ?, 'pending', 0, ?)",
        (store_id, supplier_id, ts),
    )

    total = 0.0
    for pid, _, reorder_qty in low_stock:
        cid = ref["product_cat"].get(pid)
        pr_range = ref["cat_price_ranges"].get(cid, (5, 50))
        price = round(random.uniform(*pr_range) * 0.70, 2)
        execute(
            conn,
            "INSERT INTO Purchase_Order_Item (po_id, product_id, quantity_ordered, unit_price) VALUES (?, ?, ?, ?)",
            (po_id, pid, reorder_qty, price),
        )
        total += reorder_qty * price

    execute(
        conn,
        "UPDATE Purchase_Order SET total_price = ? WHERE po_id = ?",
        (round(total, 2), po_id),
    )
    return po_id


def receive_purchase_order(conn, ref, po_id, ts):
    items = fetch_all(
        conn,
        "SELECT poi.product_id, poi.quantity_ordered FROM Purchase_Order_Item poi WHERE poi.po_id = ?",
        (po_id,),
    )
    store_row = fetch_one(
        conn, "SELECT store_id FROM Purchase_Order WHERE po_id = ?", (po_id,)
    )
    if not store_row:
        return
    store_id = store_row[0]

    for pid, qty in items:
        ref["stock"].setdefault(store_id, {})[pid] = (
            ref["stock"].get(store_id, {}).get(pid, 0) + qty
        )
        execute(
            conn,
            "UPDATE Store_Inventory SET quantity_on_hand = quantity_on_hand + ?, last_updated = ? WHERE store_id = ? AND product_id = ?;"
            "UPDATE Purchase_Order_Item SET quantity_received = ? WHERE po_id = ? AND product_id = ?;"
            "INSERT INTO Inventory_Transaction (store_id, product_id, transaction_type, po_id, quantity_delta, quantity_after, timestamp_occurred) "
            "VALUES (?, ?, 'restock', ?, ?, ?, ?);",
            (
                qty,
                ts,
                store_id,
                pid,
                qty,
                po_id,
                pid,
                store_id,
                pid,
                po_id,
                qty,
                ref["stock"][store_id][pid],
                ts,
            ),
        )

    execute(
        conn,
        "UPDATE Purchase_Order SET status = 'received', received_at = ? WHERE po_id = ?",
        (ts, po_id),
    )
