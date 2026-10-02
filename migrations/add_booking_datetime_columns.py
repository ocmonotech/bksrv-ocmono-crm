"""
One-time migration: store actual booking date/time on appointment rows.
Run: python migrations/add_booking_datetime_columns.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def add_columns(conn, table: str):
    for col, ddl in [
        ("booking_date", f"ALTER TABLE {table} ADD COLUMN booking_date DATE NULL"),
        ("start_time", f"ALTER TABLE {table} ADD COLUMN start_time TIME NULL"),
        ("end_time", f"ALTER TABLE {table} ADD COLUMN end_time TIME NULL"),
    ]:
        try:
            conn.execute(text(ddl))
            conn.commit()
            print(f"Added {table}.{col}")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print(f"{table}.{col} already exists, skipping.")
            else:
                raise


def run():
    with engine.connect() as conn:
        add_columns(conn, "appointment_bookings")
        add_columns(conn, "campaign_appointment_bookings")
    print("Migration complete.")


if __name__ == "__main__":
    run()
