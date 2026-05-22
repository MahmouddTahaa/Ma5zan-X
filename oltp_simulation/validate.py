"""
consistency checks w keda ya3ny

group a -> inventory
group b -> purchase orders
group c -> order integrity
group d -> history & state machine
group e -> inventory transactions
group f -> referential integrity
group g -> business rules
group h -> cross table reconciliation
"""

from datetime import timedelta
import oltp_simulation.config as config
from oltp_simulation.helpers import fetch_one, fetch_all, get_connection, execute


def _check(label, violated):
    """
    Helper to stamp a check result as PASS or FAIL and count violations.

    Args:
        label: Human-readable description of the check.
        violated: Number of violating rows found.

    Returns:
        Tuple of (passed: bool, flag: str, violated: int).
    """
    passed = violated == 0
    flag = "[FAIL]" if violated else "[PASS]"
    return passed, flag, violated


def a1_no_negative_stock(conn):
    """
    Check A1 — Inventory sanity: make sure no store has negative stock on hand.

    A negative quantity_on_hand would mean we sold or lost more than we ever had,
    which breaks the inventory ledger. If any row is below zero, the audit fails.
    """
    row = fetch_one(
        conn, "SELECT COUNT(*) FROM Store_Inventory WHERE quantity_on_hand < 0"
    )
    v = row[0] if row else 0
    passed, flag, _ = _check("A1: No negative quantity_on_hand", v)
    print(
        f"{flag} {flag[1:5]} A1: No negative quantity_on_hand"
        + (" " * 42)
        + f"({v} violations)"
    )
    return passed


def a2_tx_delta_matches_stock(conn):
    """
    Check A2 — Verify that the running sum of inventory transaction deltas
    lines up with the current stock level in Store_Inventory.

    Every sale, restock, return, and adjustment should net out to the
    quantity we claim is on the shelf right now.
    """
    sql = """
    WITH tx_sum AS (
        SELECT store_id, product_id, SUM(quantity_delta) AS total_delta
        FROM Inventory_Transaction
        GROUP BY store_id, product_id
    )
    SELECT si.store_id, si.product_id, si.quantity_on_hand, COALESCE(tx_sum.total_delta, 0)
    FROM Store_Inventory si
    LEFT JOIN tx_sum ON si.store_id = tx_sum.store_id AND si.product_id = tx_sum.product_id
    WHERE si.quantity_on_hand != COALESCE(tx_sum.total_delta, 0)
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("A2: Tx delta sum == quantity_on_hand", v)
    print(
        f"{flag} A2: Cumulative tx delta matches quantity_on_hand"
        + (" " * 17)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(
                f"       store={r[0]} product={r[1]} qty_on_hand={r[2]} tx_sum={r[3]}"
            )
    return passed


def a3_stock_reconciliation(conn):
    """
    Check A3 — Full stock reconciliation: received + returns + adjustments − sales.

    This rebuilds the expected stock from all movement types and compares it
    against the live Store_Inventory numbers. It catches missing transactions
    or math errors that A2 alone might not surface.
    """
    sql = """
    WITH sales AS (
        SELECT store_id, product_id, SUM(ABS(quantity_delta)) AS sold
        FROM Inventory_Transaction
        WHERE transaction_type = 'sale'
        GROUP BY store_id, product_id
    ),
    returns AS (
        SELECT it.store_id, it.product_id, SUM(it.quantity_delta) AS returned
        FROM Inventory_Transaction it
        WHERE it.transaction_type = 'return'
        GROUP BY it.store_id, it.product_id
    ),
    adjustments AS (
        SELECT it.store_id, it.product_id, SUM(it.quantity_delta) AS adj
        FROM Inventory_Transaction it
        WHERE it.transaction_type = 'adjustment'
        GROUP BY it.store_id, it.product_id
    ),
    received AS (
        SELECT po.store_id, poi.product_id, SUM(poi.quantity_received) AS rcvd
        FROM Purchase_Order_Item poi
        JOIN Purchase_Order po ON poi.po_id = po.po_id
        WHERE po.status = 'received'
        GROUP BY po.store_id, poi.product_id
    )
    SELECT si.store_id, si.product_id, si.quantity_on_hand,
           COALESCE(rc.rcvd,0) + COALESCE(rt.returned,0) + COALESCE(adj.adj,0) - COALESCE(s.sold,0) AS reconciled
    FROM Store_Inventory si
    LEFT JOIN sales s ON si.store_id = s.store_id AND si.product_id = s.product_id
    LEFT JOIN returns rt ON si.store_id = rt.store_id AND si.product_id = rt.product_id
    LEFT JOIN adjustments adj ON si.store_id = adj.store_id AND si.product_id = adj.product_id
    LEFT JOIN received rc ON si.store_id = rc.store_id AND si.product_id = rc.product_id
    WHERE si.quantity_on_hand != COALESCE(rc.rcvd,0) + COALESCE(rt.returned,0) + COALESCE(adj.adj,0) - COALESCE(s.sold,0)
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("A3: Stock reconciliation (rcvd+ret+adj-sold)", v)
    print(
        f"{flag} A3: Stock reconciled = received + returns + adj - sold"
        + (" " * 16)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(
                f"       store={r[0]} product={r[1]} qty_on_hand={r[2]} reconciled={r[3]}"
            )
    return passed


def a4_no_orphan_inventory(conn):
    """
    Check A4 — Every Store_Inventory row must have at least one 'restock' transaction.

    Without an initial restock, the inventory row is an orphan: it claims stock
    exists but has no paper trail explaining where it came from.
    """
    sql = """
    SELECT si.store_id, si.product_id
    FROM Store_Inventory si
    WHERE NOT EXISTS (
        SELECT 1 FROM Inventory_Transaction it
        WHERE it.store_id = si.store_id AND it.product_id = si.product_id
        AND it.transaction_type = 'restock'
    )
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("A4: No orphan store_inventory rows", v)
    print(
        f"{flag} A4: Every Store_Inventory has a restock tx"
        + (" " * 28)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       store={r[0]} product={r[1]}")
    return passed


def b1_po_qty_received_le_ordered(conn):
    """
    Check B1 — Purchase Order sanity: quantity_received must not exceed quantity_ordered.

    You cannot receive more stock from a supplier than you originally ordered.
    If this happens, either the PO data or the receipt log is wrong.
    """
    row = fetch_one(
        conn,
        "SELECT COUNT(*) FROM Purchase_Order_Item WHERE quantity_received > quantity_ordered",
    )
    v = row[0] if row else 0
    passed, flag, _ = _check("B1: quantity_received <= quantity_ordered", v)
    print(
        f"{flag} B1: quantity_received <= quantity_ordered"
        + (" " * 31)
        + f"({v} violations)"
    )
    return passed


def b2_po_total_price_matches_items(conn):
    """
    Check B2 — Verify that Purchase_Order.total_price equals the sum of
    (quantity_ordered * unit_price) across all Purchase_Order_Item rows.

    If the header total drifts from the line-item math, the PO is financially inconsistent.
    """
    sql = """
    SELECT po.po_id, po.total_price, ROUND(SUM(poi.quantity_ordered * poi.unit_price), 2) AS computed
    FROM Purchase_Order po
    JOIN Purchase_Order_Item poi ON po.po_id = poi.po_id
    GROUP BY po.po_id, po.total_price
    HAVING po.total_price != ROUND(SUM(poi.quantity_ordered * poi.unit_price), 2)
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("B2: PO total_price = SUM(qty*price)", v)
    print(
        f"{flag} B2: Purchase_Order.total_price matches line items"
        + (" " * 19)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       po_id={r[0]} total_price={r[1]} computed={r[2]}")
    return passed


def b3_received_po_has_restock_txs(conn):
    """
    Check B3 — A received Purchase Order must have matching 'restock' inventory transactions.

    When a PO is marked received, the stock should physically enter the store.
    This check ensures every PO line item has a corresponding restock tx.
    """
    sql = """
    SELECT po.po_id, po.status, COUNT(poi.po_item_id) AS items,
           (SELECT COUNT(*) FROM Inventory_Transaction it WHERE it.po_id = po.po_id AND it.transaction_type = 'restock') AS txs
    FROM Purchase_Order po
    JOIN Purchase_Order_Item poi ON po.po_id = poi.po_id
    WHERE po.status = 'received'
    GROUP BY po.po_id, po.status
    HAVING COUNT(poi.po_item_id) != (SELECT COUNT(*) FROM Inventory_Transaction it WHERE it.po_id = po.po_id AND it.transaction_type = 'restock')
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("B3: Received POs have matching restock txs", v)
    print(
        f"{flag} B3: Received POs have matching restock Inventory_Transactions"
        + (" " * 4)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       po_id={r[0]} items={r[2]} txs={r[3]}")
    return passed


def b4_pending_po_zero_received(conn):
    """
    Check B4 — Pending Purchase Orders must have zero items received so far.

    A PO that is still waiting on the supplier should not show any quantity_received.
    If it does, the status is stale or the receipt was logged incorrectly.
    """
    sql = """
    SELECT poi.po_item_id, po.po_id, po.status, poi.quantity_received
    FROM Purchase_Order_Item poi
    JOIN Purchase_Order po ON poi.po_id = po.po_id
    WHERE po.status = 'pending' AND poi.quantity_received > 0
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("B4: Pending POs have zero quantity_received", v)
    print(
        f"{flag} B4: Pending POs have quantity_received = 0"
        + (" " * 24)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       po_item_id={r[0]} po_id={r[1]} rcvd={r[3]}")
    return passed


def c1_order_totals_match(conn):
    """
    Check C1 — Order math: sub_total + delivery_fee must equal total_amount.

    This is a basic accounting check. If the numbers don't add up, the order
    pricing is broken or was updated without updating the dependent fields.
    """
    sql = """
    SELECT order_id, sub_total, delivery_fee, total_amount
    FROM [Order]
    WHERE ABS((sub_total + delivery_fee) - total_amount) > 0.01
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("C1: sub_total + delivery_fee = total_amount", v)
    print(
        f"{flag} C1: sub_total + delivery_fee = total_amount"
        + (" " * 26)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       order_id={r[0]} sub={r[1]} fee={r[2]} total={r[3]}")
    return passed


def c2_line_total_matches(conn):
    """
    Check C2 — Order_Item.line_total must equal quantity * unit_price.

    The line_total column is persisted and computed. This check makes sure
    no manual update or import corruption broke the computed value.
    """
    row = fetch_one(
        conn,
        "SELECT COUNT(*) FROM Order_Item WHERE ABS(line_total - (quantity * unit_price)) > 0.01",
    )
    v = row[0] if row else 0
    passed, flag, _ = _check("C2: line_total = quantity * unit_price", v)
    print(
        f"{flag} C2: line_total = quantity * unit_price (computed col)"
        + (" " * 18)
        + f"({v} violations)"
    )
    return passed


def c3_order_subtotal_matches_items(conn):
    """
    Check C3 — Order.sub_total must equal the sum of all Order_Item.line_total values.

    This validates that the header aggregates its line items correctly.
    Any drift means the order total is lying about what the customer actually bought.
    """
    sql = """
    SELECT o.order_id, o.sub_total, SUM(oi.line_total) AS items_total
    FROM [Order] o
    JOIN Order_Item oi ON o.order_id = oi.order_id
    GROUP BY o.order_id, o.sub_total
    HAVING ABS(o.sub_total - SUM(oi.line_total)) > 0.01
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("C3: Order.sub_total = SUM(line_total)", v)
    print(
        f"{flag} C3: Order.sub_total matches SUM(Order_Item.line_total)"
        + (" " * 14)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       order_id={r[0]} sub_total={r[1]} items_total={r[2]}")
    return passed


def c4_order_has_items(conn):
    """
    Check C4 — Every order must have at least one Order_Item row.

    An order with no line items is a ghost: it has a total but nothing was actually purchased.
    This usually signals a generation bug or a failed insert of the child records.
    """
    sql = """
    SELECT o.order_id FROM [Order] o
    WHERE NOT EXISTS (SELECT 1 FROM Order_Item oi WHERE oi.order_id = o.order_id)
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("C4: Every order has >= 1 Order_Item", v)
    print(
        f"{flag} C4: Every order has at least one Order_Item"
        + (" " * 26)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       order_id={r[0]}")
    return passed


def c5_order_has_history(conn):
    """
    Check C5 — Every order must have at least one Order_History record.

    The history table is the audit trail of status changes. An order without history
    is invisible to downstream analytics that rely on state-transition timestamps.
    """
    sql = """
    SELECT o.order_id FROM [Order] o
    WHERE NOT EXISTS (SELECT 1 FROM Order_History oh WHERE oh.order_id = o.order_id)
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("C5: Every order has >= 1 Order_History", v)
    print(
        f"{flag} C5: Every order has at least one Order_History record"
        + (" " * 13)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       order_id={r[0]}")
    return passed


def d1_history_matches_status(conn):
    """
    Check D1 — The latest Order_History entry must match the current status in [Order].

    If the order says 'delivered' but the newest history says 'pending',
    the state machine is out of sync. Includes auto-repair logic that
    deduplicates or inserts the missing history entry.
    """
    sql = """
    WITH latest AS (
        SELECT oh.order_id, oh.status AS hist_status, oh.changed_at,
               ROW_NUMBER() OVER (PARTITION BY oh.order_id ORDER BY oh.changed_at DESC) AS rn
        FROM Order_History oh
    )
    SELECT o.order_id, o.status AS order_status, l.hist_status
    FROM [Order] o
    JOIN latest l ON o.order_id = l.order_id AND l.rn = 1
    WHERE o.status != l.hist_status
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("D1: Latest Order_History matches [Order].status", v)
    print(
        f"{flag} D1: Latest Order_History.status = [Order].status"
        + (" " * 19)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       order_id={r[0]} order_status={r[1]} history_status={r[2]}")
        print(f"       Repairing...", end=" ", flush=True)
        fixed = 0
        for order_id, order_status, _hist_status in rows:
            existing = fetch_all(
                conn,
                "SELECT history_id, changed_at FROM Order_History "
                "WHERE order_id = ? AND status = ? ORDER BY changed_at DESC",
                (order_id, order_status),
            )
            if existing:
                if len(existing) > 1:
                    for row in existing[1:]:
                        execute(
                            conn,
                            "DELETE FROM Order_History WHERE history_id = ?",
                            (row[0],),
                        )
                prev_row = fetch_one(
                    conn,
                    "SELECT MAX(changed_at) FROM Order_History "
                    "WHERE order_id = ? AND status != ?",
                    (order_id, order_status),
                )
                new_ts = (prev_row[0] if prev_row else existing[0][1]) + timedelta(
                    seconds=1
                )
                execute(
                    conn,
                    "UPDATE Order_History SET changed_at = ? WHERE history_id = ?",
                    (new_ts, existing[0][0]),
                )
            else:
                last_ts_row = fetch_one(
                    conn,
                    "SELECT MAX(changed_at) FROM Order_History WHERE order_id = ?",
                    (order_id,),
                )
                last_ts = last_ts_row[0] if last_ts_row else None
                if last_ts is None:
                    continue
                execute(
                    conn,
                    "INSERT INTO Order_History (order_id, status, changed_at) VALUES (?, ?, ?)",
                    (order_id, order_status, last_ts + timedelta(seconds=1)),
                )
            fixed += 1
        print(f"{fixed} rows \u2713")
    return passed


def d2_valid_status_transitions(conn):
    """
    Check D2 — Order status transitions must follow the allowed state machine.

    Valid paths are: pending → confirmed, pending → cancelled,
    confirmed → delivered, and confirmed → cancelled.
    Any other jump (e.g., pending → delivered) is impossible in real life
    and signals a data-generation or update bug. Auto-repair deletes invalid rows.
    """
    valid = [
        ("pending", "confirmed"),
        ("pending", "cancelled"),
        ("confirmed", "delivered"),
        ("confirmed", "cancelled"),
    ]
    sql = """
    WITH ordered AS (
        SELECT oh.order_id, oh.status, oh.changed_at,
               LAG(oh.status) OVER (PARTITION BY oh.order_id ORDER BY oh.changed_at) AS prev_status
        FROM Order_History oh
    )
    SELECT order_id, prev_status, status, changed_at
    FROM ordered
    WHERE prev_status IS NOT NULL
    """
    rows = fetch_all(conn, sql)
    violations = []
    for order_id, prev, curr, ts in rows:
        if (prev, curr) not in valid:
            violations.append((order_id, prev, curr, ts))
    v = len(violations)
    passed, flag, _ = _check("D2: Status transitions are valid", v)
    print(
        f"{flag} D2: All status transitions are valid"
        + (" " * 31)
        + f"({v} violations)"
    )
    if violations:
        for r in violations[:3]:
            print(f"       order_id={r[0]} {r[1]}->{r[2]} at {r[3]}")
        print(
            f"       Repairing: deleting invalid transition rows...",
            end=" ",
            flush=True,
        )
        fixed = 0
        for order_id, prev, curr, ts in violations:
            bad_row = fetch_one(
                conn,
                "SELECT history_id FROM Order_History WHERE order_id = ? AND status = ? AND changed_at = ?",
                (order_id, curr, ts),
            )
            if bad_row:
                execute(
                    conn,
                    "DELETE FROM Order_History WHERE history_id = ?",
                    (bad_row[0],),
                )
                fixed += 1
        print(f"{fixed} rows \u2713")
    return passed


def d3_no_duplicate_consecutive_statuses(conn):
    """
    Check D3 — No two consecutive Order_History rows should have the same status.

    Writing 'confirmed' twice in a row is redundant noise. It bloats the audit trail
    without adding information. Auto-repair deletes the duplicate rows.
    """
    sql = """
    WITH ordered AS (
        SELECT oh.order_id, oh.status, oh.changed_at,
               LAG(oh.status) OVER (PARTITION BY oh.order_id ORDER BY oh.changed_at) AS prev_status
        FROM Order_History oh
    )
    SELECT order_id, status, changed_at FROM ordered
    WHERE prev_status = status
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("D3: No duplicate consecutive statuses", v)
    print(
        f"{flag} D3: No consecutive Order_History rows with same status"
        + (" " * 7)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       order_id={r[0]} status={r[1]} at {r[2]}")
        print(
            f"       Repairing: deleting duplicate status rows...", end=" ", flush=True
        )
        fixed = 0
        for order_id, status, ts in rows:
            bad_row = fetch_one(
                conn,
                "SELECT history_id FROM Order_History WHERE order_id = ? AND status = ? AND changed_at = ?",
                (order_id, status, ts),
            )
            if bad_row:
                execute(
                    conn,
                    "DELETE FROM Order_History WHERE history_id = ?",
                    (bad_row[0],),
                )
                fixed += 1
        print(f"{fixed} rows \u2713")
    return passed


def e1_sale_tx_has_order(conn):
    """
    Check E1 — Sale and return inventory transactions must reference a valid order.

    A sale or return that is not tied to an order is unexplainable stock movement:
    we cannot tell who bought or returned the product, or why.
    """
    row = fetch_one(
        conn,
        "SELECT COUNT(*) FROM Inventory_Transaction WHERE transaction_type IN ('sale', 'return') AND order_id IS NULL",
    )
    v = row[0] if row else 0
    passed, flag, _ = _check("E1: sale/return txs reference a valid order", v)
    print(
        f"{flag} E1: Sale/return transactions have non-null order_id"
        + (" " * 17)
        + f"({v} violations)"
    )
    return passed


def e2_restock_tx_has_po(conn):
    """
    Check E2 — Restock inventory transactions must reference a valid Purchase Order.

    If stock suddenly appears on the shelf with no PO paper trail, we have no idea
    where it came from or whether the supplier was ever paid.
    """
    row = fetch_one(
        conn,
        "SELECT COUNT(*) FROM Inventory_Transaction WHERE transaction_type = 'restock' AND po_id IS NULL",
    )
    v = row[0] if row else 0
    passed, flag, _ = _check("E2: restock txs reference a valid PO", v)
    print(
        f"{flag} E2: Restock transactions have non-null po_id"
        + (" " * 23)
        + f"({v} violations)"
    )
    return passed


def e3_adjustment_tx_no_order_po(conn):
    """
    Check E3 — Adjustment transactions must have no order or PO reference.

    Adjustments are standalone events (damage, found extra, spoilage). If they point
    to an order or PO, they are masquerading as a business transaction they are not.
    """
    row = fetch_one(
        conn,
        "SELECT COUNT(*) FROM Inventory_Transaction WHERE transaction_type = 'adjustment' AND (order_id IS NOT NULL OR po_id IS NOT NULL)",
    )
    v = row[0] if row else 0
    passed, flag, _ = _check("E3: adjustment txs have null order_id and po_id", v)
    print(
        f"{flag} E3: Adjustment transactions have no order or PO reference"
        + (" " * 10)
        + f"({v} violations)"
    )
    return passed


def e4_delta_sign_matches_type(conn):
    """
    Check E4 — The sign of quantity_delta must match the transaction type.

    Sales decrease stock (negative), while restocks and returns increase it (positive).
    A positive sale or negative return is a logical contradiction in the ledger.
    """
    sql = """
    SELECT transaction_id, transaction_type, quantity_delta FROM Inventory_Transaction
    WHERE (transaction_type = 'sale' AND quantity_delta > 0)
       OR (transaction_type = 'restock' AND quantity_delta < 0)
       OR (transaction_type = 'return' AND quantity_delta < 0)
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("E4: quantity_delta sign matches transaction_type", v)
    print(
        f"{flag} E4: Delta sign matches type (sale<0, restock>0, return>0)"
        + (" " * 8)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       tx_id={r[0]} type={r[1]} delta={r[2]}")
    return passed


def e5_sequential_quantity_consistency(conn):
    """
    Check E5 — Running quantity_after must be sequentially consistent per product per store.

    For every inventory transaction, prev.quantity_after + quantity_delta should equal
    the current quantity_after. A mismatch means the ledger was edited out of order
    or a transaction was inserted with the wrong running total.
    """
    sql = """
    WITH ordered AS (
        SELECT it.transaction_id, it.store_id, it.product_id, it.quantity_delta, it.quantity_after, it.timestamp_occurred,
               LAG(it.quantity_after) OVER (PARTITION BY it.store_id, it.product_id ORDER BY it.timestamp_occurred, it.transaction_id) AS prev_qty_after
        FROM Inventory_Transaction it
    ),
    mismatches AS (
        SELECT * FROM ordered
        WHERE prev_qty_after IS NOT NULL
          AND (prev_qty_after + quantity_delta) != quantity_after
    )
    SELECT COUNT(*) FROM mismatches
    """
    row = fetch_one(conn, sql)
    v = row[0] if row else 0
    passed, flag, _ = _check("E5: quantity_after is sequentially consistent", v)
    print(
        f"{flag} E5: prev.quantity_after + delta = quantity_after"
        + (" " * 20)
        + f"({v} violations)"
    )
    return passed


def f1_f6_referential_integrity(conn):
    """
    Check F1–F6 — Batch referential integrity scan across six foreign-key relationships.

    Covers: Order→Store, Order→Customer, Order_Item→Product, Store_Inventory→Store/Product,
    Inventory_Transaction→Store/Product, and Customer→Zone. Dangling FKs break joins
    and silently drop rows from reports.
    """
    checks = [
        (
            "F1",
            "[Order].store_id → Dark_Store",
            "SELECT COUNT(*) FROM [Order] o WHERE o.store_id NOT IN (SELECT store_id FROM Dark_Store)",
        ),
        (
            "F2",
            "[Order].customer_id → Customer",
            "SELECT COUNT(*) FROM [Order] o WHERE o.customer_id NOT IN (SELECT customer_id FROM Customer)",
        ),
        (
            "F3",
            "Order_Item.product_id → Product",
            "SELECT COUNT(*) FROM Order_Item oi WHERE oi.product_id NOT IN (SELECT product_id FROM Product)",
        ),
        (
            "F4",
            "Store_Inventory FK → valid store/product",
            "SELECT COUNT(*) FROM Store_Inventory si WHERE si.store_id NOT IN (SELECT store_id FROM Dark_Store) OR si.product_id NOT IN (SELECT product_id FROM Product)",
        ),
        (
            "F5",
            "Inventory_Transaction FK → valid store/product",
            "SELECT COUNT(*) FROM Inventory_Transaction it WHERE it.store_id NOT IN (SELECT store_id FROM Dark_Store) OR it.product_id NOT IN (SELECT product_id FROM Product)",
        ),
        (
            "F6",
            "Customer.zone_id → Zone",
            "SELECT COUNT(*) FROM Customer c WHERE c.zone_id NOT IN (SELECT zone_id FROM Zone)",
        ),
    ]
    all_passed = True
    for code, desc, sql in checks:
        row = fetch_one(conn, sql)
        v = row[0] if row else 0
        passed, flag, _ = _check(f"{code}: {desc}", v)
        print(f"{flag} {code}: {desc}" + (" " * (60 - len(desc))) + f"({v} violations)")
        if not passed:
            all_passed = False
    return all_passed


def g1_reorder_valid(conn):
    """
    Check G1 — Reorder thresholds must be sensible: reorder_point > 0 and
    reorder_quantity must exceed reorder_point.

    A reorder_point of zero means 'never restock', and a reorder_quantity smaller
    than the trigger threshold means we are ordering less than the alert level.
    """
    row = fetch_one(
        conn,
        "SELECT COUNT(*) FROM Store_Inventory WHERE reorder_point <= 0 OR reorder_quantity <= reorder_point",
    )
    v = row[0] if row else 0
    passed, flag, _ = _check(
        "G1: reorder_point > 0 and reorder_quantity > reorder_point", v
    )
    print(
        f"{flag} G1: reorder_point > 0, reorder_quantity > reorder_point"
        + (" " * 12)
        + f"({v} violations)"
    )
    return passed


def g2_all_products_in_all_stores(conn):
    """
    Check G2 — Every dark store must carry inventory for every product in the catalog.

    If a store is missing a product, it cannot fulfill orders containing that SKU,
    which breaks the assumption that all stores serve the full assortment.
    """
    sql = """
    SELECT store_id, COUNT(*) AS cnt FROM Store_Inventory GROUP BY store_id
    """
    rows = fetch_all(conn, sql)
    total_products = fetch_one(conn, "SELECT COUNT(*) FROM Product")[0]
    violations = [r for r in rows if r[1] != total_products]
    v = len(violations)
    passed, flag, _ = _check("G2: Every store has all products in inventory", v)
    print(
        f"{flag} G2: Each store has inventory for all {total_products} products"
        + (" " * 11)
        + f"({v} violations)"
    )
    if violations:
        for r in violations[:3]:
            print(
                f"       store_id={r[0]} has {r[1]} products (expected {total_products})"
            )
    return passed


def g3_one_initial_po_per_store(conn):
    """
    Check G3 — Each store must have at least one received Purchase Order.

    A store with zero received POs has no provenance for its initial stock.
    This check ensures the seeding layer created the baseline restock for every hub.
    """
    sql = """
    SELECT store_id, COUNT(*) AS cnt FROM Purchase_Order WHERE status = 'received' GROUP BY store_id
    """
    rows = fetch_all(conn, sql)
    expected_stores = fetch_one(conn, "SELECT COUNT(*) FROM Dark_Store")[0]
    violations = [r for r in rows if r[1] < 1]
    v = len(violations)
    # also check there are no stores without any received PO
    store_ids_with_po = {r[0] for r in rows}
    all_stores = {r[0] for r in fetch_all(conn, "SELECT store_id FROM Dark_Store")}
    missing = all_stores - store_ids_with_po
    v = len(missing)
    passed, flag, _ = _check("G3: Every store has an initial received PO", v)
    print(
        f"{flag} G3: Each store has at least one received Purchase_Order"
        + (" " * 11)
        + f"({v} violations)"
    )
    if missing:
        for sid in list(missing)[:3]:
            print(f"       store_id={sid} has no received PO")
    return passed


def g4_delivery_fee_matches_zone(conn):
    """
    Check G4 — The delivery_fee on every order must match the customer's zone delivery fee.

    If the order charges a different fee than the zone table dictates, either the
    zone was changed after the order was placed, or the fee was miscalculated at checkout.
    """
    sql = """
    SELECT o.order_id, o.delivery_fee AS order_fee, z.delivery_fee AS zone_fee
    FROM [Order] o
    JOIN Customer c ON o.customer_id = c.customer_id
    JOIN Zone z ON c.zone_id = z.zone_id
    WHERE o.delivery_fee != z.delivery_fee
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("G4: Order.delivery_fee matches Customer's Zone", v)
    print(
        f"{flag} G4: Order.delivery_fee matches customer zone delivery_fee"
        + (" " * 8)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       order_id={r[0]} order_fee={r[1]} zone_fee={r[2]}")
    return passed


def g5_order_created_before_history(conn):
    """
    Check G5 — An order cannot have a history entry dated before the order itself was created.

    Time-travelling status changes are impossible. If found, they indicate a clock-skew
    bug or an incorrect manual edit of the changed_at timestamp.
    """
    sql = """
    SELECT o.order_id, o.created_at, oh.changed_at
    FROM [Order] o
    JOIN Order_History oh ON o.order_id = oh.order_id
    WHERE oh.changed_at < o.created_at
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("G5: Order.created_at <= Order_History.changed_at", v)
    print(
        f"{flag} G5: Order.created_at <= all Order_History.changed_at"
        + (" " * 15)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       order_id={r[0]} created={r[1]} history={r[2]}")
    return passed


def h1_cancelled_after_confirmed_has_returns(conn):
    """
    Check H1 — Orders cancelled after confirmation must have a corresponding 'return' transaction.

    Once an order is confirmed, stock is deducted from the shelf. If the order is later
    cancelled, that stock must be put back. Missing return transactions mean inventory
    quietly vanished without explanation.
    """
    sql = """
    SELECT o.order_id
    FROM [Order] o
    WHERE o.status = 'cancelled'
      AND EXISTS (SELECT 1 FROM Order_History oh WHERE oh.order_id = o.order_id AND oh.status = 'confirmed')
      AND NOT EXISTS (SELECT 1 FROM Inventory_Transaction it WHERE it.order_id = o.order_id AND it.transaction_type = 'return')
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("H1: Cancelled-after-confirmed has stock reversed", v)
    print(
        f"{flag} H1: Orders cancelled after confirmation have return txs"
        + (" " * 14)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(
                f"       order_id={r[0]} was confirmed then cancelled but no return tx"
            )
    return passed


def h2_confirmed_orders_have_sale_txs(conn):
    """
    Check H2 — Every confirmed or delivered order must have matching 'sale' inventory transactions.

    Confirmation means the stock was physically picked and reserved. If there is no sale tx
    for an item, the inventory ledger is missing the deduction that justifies the lower shelf count.
    """
    sql = """
    SELECT oi.order_id, oi.product_id, oi.quantity
    FROM Order_Item oi
    JOIN [Order] o ON oi.order_id = o.order_id
    WHERE o.status IN ('confirmed', 'delivered')
      AND NOT EXISTS (
          SELECT 1 FROM Inventory_Transaction it
          WHERE it.order_id = oi.order_id
            AND it.product_id = oi.product_id
            AND it.transaction_type = 'sale'
            AND ABS(it.quantity_delta) = oi.quantity
      )
    """
    rows = fetch_all(conn, sql)
    v = len(rows)
    passed, flag, _ = _check("H2: Confirmed/delivered orders have sale txs", v)
    print(
        f"{flag} H2: Confirmed/delivered Order_Items have matching sale txs"
        + (" " * 8)
        + f"({v} violations)"
    )
    if rows:
        for r in rows[:3]:
            print(f"       order_id={r[0]} product={r[1]} qty={r[2]}")
    return passed


def run_all():
    print("=" * 70)
    print("  OLTP CONSISTENCY AUDIT")
    print("=" * 70)
    print()

    conn = get_connection()
    try:
        groups = [
            (
                "GROUP A: Inventory Stock Integrity",
                [
                    a1_no_negative_stock,
                    a2_tx_delta_matches_stock,
                    a3_stock_reconciliation,
                    a4_no_orphan_inventory,
                ],
            ),
            (
                "GROUP B: Purchase Order Integrity",
                [
                    b1_po_qty_received_le_ordered,
                    b2_po_total_price_matches_items,
                    b3_received_po_has_restock_txs,
                    b4_pending_po_zero_received,
                ],
            ),
            (
                "GROUP C: Order Integrity",
                [
                    c1_order_totals_match,
                    c2_line_total_matches,
                    c3_order_subtotal_matches_items,
                    c4_order_has_items,
                    c5_order_has_history,
                ],
            ),
            (
                "GROUP D: Order History & State Machine",
                [
                    d1_history_matches_status,
                    d2_valid_status_transitions,
                    d3_no_duplicate_consecutive_statuses,
                ],
            ),
            (
                "GROUP E: Inventory Transaction Integrity",
                [
                    e1_sale_tx_has_order,
                    e2_restock_tx_has_po,
                    e3_adjustment_tx_no_order_po,
                    e4_delta_sign_matches_type,
                    e5_sequential_quantity_consistency,
                ],
            ),
            (
                "GROUP F: Referential Integrity",
                [
                    f1_f6_referential_integrity,
                ],
            ),
            (
                "GROUP G: Business Rule Checks",
                [
                    g1_reorder_valid,
                    g2_all_products_in_all_stores,
                    g3_one_initial_po_per_store,
                    g4_delivery_fee_matches_zone,
                    g5_order_created_before_history,
                ],
            ),
            (
                "GROUP H: Cross-table Reconciliation",
                [
                    h1_cancelled_after_confirmed_has_returns,
                    h2_confirmed_orders_have_sale_txs,
                ],
            ),
        ]

        passed = 0
        failed = 0

        for group_name, checks in groups:
            print(f"\n--- {group_name} ---")
            for check_fn in checks:
                if check_fn(conn):
                    passed += 1
                else:
                    failed += 1

        total = passed + failed
        print()
        print("=" * 70)
        print(f"  SUMMARY: {passed} passed, {failed} failed, {total} total")
        print("=" * 70)

    finally:
        conn.close()
