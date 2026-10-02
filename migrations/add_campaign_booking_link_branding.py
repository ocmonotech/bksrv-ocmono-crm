"""
One-time migration: optional title and logo_url on campaign_booking_links.
Run: python migrations/add_campaign_booking_link_branding.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def add_column(conn, table: str, col: str, ddl: str):
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
        add_column(
            conn,
            "campaign_booking_links",
            "page_title",
            "ALTER TABLE campaign_booking_links ADD COLUMN page_title VARCHAR(255) NULL",
        )
        add_column(
            conn,
            "campaign_booking_links",
            "logo_url",
            "ALTER TABLE campaign_booking_links ADD COLUMN logo_url VARCHAR(512) NULL",
        )
    print("Migration complete.")


if __name__ == "__main__":
    run()
