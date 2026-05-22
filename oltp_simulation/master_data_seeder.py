"""
Layer 1 — Master Data Seeder
"""

import time
from datetime import datetime, timedelta
import random
import oltp_simulation.config as config
from oltp_simulation.helpers import (
    fetch_one,
    fetch_all,
    execute,
    insert_and_get_id,
    fake_egyptian_phone,
    fake_eg_address,
    fake_price,
)

SUPPLIER_NAMES = [
    "Al-Madina Dairy Co.",
    "Delta Foods Egypt",
    "Cairo Fresh Farms",
    "Arab Dairy",
    "Juhayna Food Industries",
    "Edita Food Industries",
    "Farm Frites Egypt",
    "Al-Ahram Beverages",
    "Faragalla Group",
    "Obour Land",
    "Wadi Food",
    "Halwani Bros.",
    "Arabian Food Industries",
    "Green Valley Egypt",
    "El-Maleka Food Industries",
]


def seed_categories(conn):
    print("[SEEDER] Seeding Categories...", end=" ", flush=True)
    t0 = time.time()
    count = 0
    for cat_name, cat_info in config.CATALOG.items():
        exists = fetch_one(
            conn, "SELECT COUNT(*) FROM Category WHERE name = ?", (cat_name,)
        )
        if exists and exists[0] > 0:
            continue
        execute(
            conn,
            "INSERT INTO Category (name, requires_cold_chain) VALUES (?, ?)",
            (cat_name, 1 if cat_info["requires_cold_chain"] else 0),
        )
        count += 1
    elapsed = (time.time() - t0) * 1000
    print(f"{count} rows \u2713 ({elapsed:.0f}ms)")


def seed_suppliers(conn):
    print("[SEEDER] Seeding Suppliers...", end=" ", flush=True)
    t0 = time.time()
    count = 0
    for name in SUPPLIER_NAMES:
        exists = fetch_one(
            conn, "SELECT COUNT(*) FROM Supplier WHERE name = ?", (name,)
        )
        if exists and exists[0] > 0:
            continue
        execute(
            conn,
            "INSERT INTO Supplier (name, phone, email) VALUES (?, ?, ?)",
            (
                name,
                fake_egyptian_phone(),
                f"info@{name.lower().replace(' ', '').replace('.', '')[:20]}.com.eg",
            ),
        )
        count += 1
    elapsed = (time.time() - t0) * 1000
    print(f"{count} rows \u2713 ({elapsed:.0f}ms)")


def seed_products(conn):
    print("[SEEDER] Seeding Products...", end=" ", flush=True)
    t0 = time.time()
    rows = fetch_all(conn, "SELECT category_id, name FROM Category")
    cat_id_map = {row[1]: row[0] for row in rows}
    count = 0
    for cat_name, cat_info in config.CATALOG.items():
        cat_id = cat_id_map.get(cat_name)
        if cat_id is None:
            continue
        for prod_name, sku, shelf_life in cat_info["products"]:
            exists = fetch_one(
                conn, "SELECT COUNT(*) FROM Product WHERE SKU = ?", (sku,)
            )
            if exists and exists[0] > 0:
                pname = fetch_one(
                    conn, "SELECT name FROM Product WHERE SKU = ?", (sku,)
                )
                if pname and pname[0] != prod_name:
                    execute(
                        conn,
                        "UPDATE Product SET name = ?, shelf_life_days = ? WHERE SKU = ?",
                        (prod_name, shelf_life, sku),
                    )
                    count += 1
                continue
            execute(
                conn,
                "INSERT INTO Product (category_id, name, SKU, shelf_life_days) VALUES (?, ?, ?, ?)",
                (cat_id, prod_name, sku, shelf_life),
            )
            count += 1
    elapsed = (time.time() - t0) * 1000
    print(f"{count} rows \u2713 ({elapsed:.0f}ms)")


def seed_zones(conn):
    print("[SEEDER] Seeding Zones...", end=" ", flush=True)
    t0 = time.time()
    count = 0
    for zone in config.ZONES:
        exists = fetch_one(
            conn, "SELECT COUNT(*) FROM Zone WHERE name = ?", (zone["name"],)
        )
        if exists and exists[0] > 0:
            continue
        execute(
            conn,
            "INSERT INTO Zone (name, city, delivery_fee, Est_time_arrival) VALUES (?, ?, ?, ?)",
            (zone["name"], zone["city"], zone["delivery_fee"], zone["eta_min"]),
        )
        count += 1
    elapsed = (time.time() - t0) * 1000
    print(f"{count} rows \u2713 ({elapsed:.0f}ms)")


def seed_dark_stores(conn):
    print("[SEEDER] Seeding Dark Stores...", end=" ", flush=True)
    t0 = time.time()
    count = 0
    for store in config.STORES:
        exists = fetch_one(
            conn, "SELECT COUNT(*) FROM Dark_Store WHERE name = ?", (store["name"],)
        )
        if exists and exists[0] > 0:
            continue
        execute(
            conn,
            "INSERT INTO Dark_Store (name, city, street) VALUES (?, ?, ?)",
            (store["name"], store["city"], store["street"]),
        )
        count += 1
    elapsed = (time.time() - t0) * 1000
    print(f"{count} rows \u2713 ({elapsed:.0f}ms)")


def seed_customers(conn, count=50):
    print(f"[SEEDER] Seeding Customers...", end=" ", flush=True)
    t0 = time.time()
    zone_rows = fetch_all(conn, "SELECT zone_id FROM Zone")
    zone_ids = [r[0] for r in zone_rows]
    if not zone_ids:
        print("SKIP (no zones)")
        return
    existing = fetch_one(conn, "SELECT COUNT(*) FROM Customer", ())
    if existing and existing[0] >= count:
        print(f"SKIP ({existing[0]} already exist)")
        return
    inserted = 0
    from oltp_simulation.helpers import fake

    base_date = datetime(2024, 10, 1)
    while inserted < count:
        fn = fake.first_name()
        ln = fake.last_name()
        phone = fake_egyptian_phone()
        exists = fetch_one(
            conn, "SELECT COUNT(*) FROM Customer WHERE phone_number = ?", (phone,)
        )
        if exists and exists[0] > 0:
            continue
        days_ago = random.randint(0, 90)
        reg_ts = base_date + timedelta(days=days_ago)
        execute(
            conn,
            "INSERT INTO Customer (zone_id, first_name, last_name, phone_number, full_address, registered_time) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (random.choice(zone_ids), fn, ln, phone, fake_eg_address(), reg_ts),
        )
        inserted += 1
    elapsed = (time.time() - t0) * 1000
    print(f"{inserted} rows \u2713 ({elapsed:.0f}ms)")


def seed_store_inventory(conn):
    print("[SEEDER] Seeding Store Inventory...", end=" ", flush=True)
    t0 = time.time()
    store_rows = fetch_all(conn, "SELECT store_id FROM Dark_Store")
    prod_rows = fetch_all(conn, "SELECT product_id FROM Product")
    store_ids = [r[0] for r in store_rows]
    prod_ids = [r[0] for r in prod_rows]
    count = 0
    for sid in store_ids:
        for pid in prod_ids:
            exists = fetch_one(
                conn,
                "SELECT COUNT(*) FROM Store_Inventory WHERE store_id = ? AND product_id = ?",
                (sid, pid),
            )
            if exists and exists[0] > 0:
                continue
            qty = random.randint(150, 500)
            execute(
                conn,
                "INSERT INTO Store_Inventory (store_id, product_id, quantity_on_hand, reorder_point, reorder_quantity) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, pid, qty, 20, 100),
            )
            count += 1
    elapsed = (time.time() - t0) * 1000
    print(f"{count} rows \u2713 ({elapsed:.0f}ms)")


def seed_initial_purchase_orders(conn):
    print("[SEEDER] Seeding Initial Purchase Orders...", end=" ", flush=True)
    t0 = time.time()
    store_ids = [r[0] for r in fetch_all(conn, "SELECT store_id FROM Dark_Store")]
    supplier_id = fetch_one(conn, "SELECT MIN(supplier_id) FROM Supplier")[0]
    base_ts = datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=7)
    po_count = 0
    item_count = 0
    tx_count = 0

    for sid in store_ids:
        exists = fetch_one(
            conn, "SELECT COUNT(*) FROM Purchase_Order WHERE store_id = ?", (sid,)
        )
        if exists and exists[0] > 0:
            continue

        total_price = 0.0
        po_id = insert_and_get_id(
            conn,
            "INSERT INTO Purchase_Order (store_id, supplier_id, status, total_price, ordered_at, received_at) "
            "OUTPUT INSERTED.po_id "
            "VALUES (?, ?, 'received', 0, ?, ?)",
            (sid, supplier_id, base_ts, base_ts),
        )

        inv_rows = fetch_all(
            conn,
            "SELECT product_id, quantity_on_hand FROM Store_Inventory WHERE store_id = ?",
            (sid,),
        )
        for pid, qty in inv_rows:
            unit_price = round(random.uniform(5, 50) * 0.70, 2)
            execute(
                conn,
                "INSERT INTO Purchase_Order_Item (po_id, product_id, quantity_ordered, quantity_received, unit_price) "
                "VALUES (?, ?, ?, ?, ?)",
                (po_id, pid, qty, qty, unit_price),
            )
            total_price += qty * unit_price
            execute(
                conn,
                "INSERT INTO Inventory_Transaction (store_id, product_id, transaction_type, po_id, quantity_delta, quantity_after, timestamp_occurred) "
                "VALUES (?, ?, 'restock', ?, ?, ?, ?)",
                (sid, pid, po_id, qty, qty, base_ts),
            )
            item_count += 1
            tx_count += 1

        execute(
            conn,
            "UPDATE Purchase_Order SET total_price = ? WHERE po_id = ?",
            (round(total_price, 2), po_id),
        )
        po_count += 1

    elapsed = (time.time() - t0) * 1000
    print(
        f"{po_count} POs, {item_count} items, {tx_count} txs \u2713 ({elapsed:.0f}ms)"
    )


def run_seeder(conn):
    t0 = time.time()
    seed_categories(conn)
    seed_suppliers(conn)
    seed_products(conn)
    seed_zones(conn)
    seed_dark_stores(conn)
    seed_customers(conn, config.N_CUSTOMERS_SEED)
    seed_store_inventory(conn)
    seed_initial_purchase_orders(conn)
    elapsed = time.time() - t0
    total = (
        fetch_one(conn, "SELECT COUNT(*) FROM Category")[0]
        + fetch_one(conn, "SELECT COUNT(*) FROM Supplier")[0]
        + fetch_one(conn, "SELECT COUNT(*) FROM Product")[0]
        + fetch_one(conn, "SELECT COUNT(*) FROM Zone")[0]
        + fetch_one(conn, "SELECT COUNT(*) FROM Dark_Store")[0]
        + fetch_one(conn, "SELECT COUNT(*) FROM Customer")[0]
        + fetch_one(conn, "SELECT COUNT(*) FROM Store_Inventory")[0]
        + fetch_one(conn, "SELECT COUNT(*) FROM Purchase_Order")[0]
    )
    print(f"[SEEDER] Done. {total} total rows in {elapsed:.1f}s")
