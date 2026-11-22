
import sqlite3
import os

DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reporting_database.db"
)


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables():
    conn = get_db_connection()

    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE,
                total_revenue REAL NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL DEFAULT 0,
                total_profit REAL NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS product_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_report_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                total_sold INTEGER NOT NULL DEFAULT 0,
                revenue REAL NOT NULL DEFAULT 0,
                cost REAL NOT NULL DEFAULT 0,
                profit REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (order_report_id)
                    REFERENCES orders_reports(id)
                    ON DELETE CASCADE,
                UNIQUE(order_report_id, product_id)
            )
        """)

        conn.commit()

    finally:
        conn.close()
