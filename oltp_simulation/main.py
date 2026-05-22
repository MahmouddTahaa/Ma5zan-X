"""
Dark Store Inventory — OLTP Event Producer
CLI entry point for seeding master data and generating simulated events.
"""

import click
from oltp_simulation.helpers import get_connection
from oltp_simulation.master_data_seeder import run_seeder
from oltp_simulation.event_generator import run_simulation
from oltp_simulation.validate import run_all as run_validation
import oltp_simulation.config as config


@click.group()
def cli():
    """Dark Store Inventory — OLTP Event Producer"""


@cli.command()
def seed():
    """Layer 1: Seed master data (categories, products, stores, customers, inventory)."""
    conn = get_connection()
    try:
        run_seeder(conn)
    finally:
        conn.close()


@cli.command()
@click.option(
    "--orders",
    default=config.N_ORDERS_DEFAULT,
    show_default=True,
    help="Number of orders to generate",
)
@click.option(
    "--seed-first/--no-seed",
    default=True,
    show_default=True,
    help="Run layer 1 seeder before layer 2",
)
def generate(orders, seed_first):
    """Layer 2: Generate simulated business events."""
    conn = get_connection()
    try:
        if seed_first:
            run_seeder(conn)
        run_simulation(conn, orders)
    finally:
        conn.close()


@cli.command()
@click.option(
    "--orders",
    default=config.N_ORDERS_DEFAULT,
    show_default=True,
    help="Number of orders to generate",
)
def run(orders):
    """Full pipeline: seed master data + generate events."""
    conn = get_connection()
    try:
        run_seeder(conn)
        run_simulation(conn, orders)
    finally:
        conn.close()


@cli.command()
def validate():
    """Run consistency audit across all OLTP tables."""
    run_validation()


@cli.command()
def diagnose():
    """Test connection and print diagnostics."""
    masked = config.DB_CONN_STRING
    import re

    masked = re.sub(r"PWD=[^;]+", "PWD=***", masked)
    print(f"Connection string: {masked}")
    print()
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]
        print(f"Connected to: {version}")
        cursor.execute("SELECT DB_NAME()")
        db = cursor.fetchone()[0]
        print(f"Current database: {db}")
        cursor.execute("SELECT COUNT(*) FROM sys.tables")
        table_count = cursor.fetchone()[0]
        print(f"Tables in database: {table_count}")
        conn.close()
        print("\nConnection OK. You can now run: python main.py seed")
    except Exception as e:
        print(f"Connection FAILED: {e}")
        print()
        print("Common fixes:")
        print(
            "  1. Check .env — is MSSQL_INSTANCE correct? Try SQLEXPRESS or MSSQLSERVER"
        )
        print("  2. Check SQL Server is running: services.msc → SQL Server (INSTANCE)")
        print(
            "  3. Enable TCP/IP: SQL Server Configuration Manager → Protocols → TCP/IP → Enable"
        )
        print("  4. Try different driver (run: Get-OdbcDriver | Select-Object Name)")


if __name__ == "__main__":
    cli()
