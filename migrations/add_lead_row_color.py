"""
Add shared row highlight color to leads.
Run: python migrations/add_lead_row_color.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def _run(conn, sql: str, label: str):
    try:
        conn.execute(text(sql))
        conn.commit()
        print(f"OK: {label}")
    except Exception as e:
        conn.rollback()
        msg = str(e).lower()
        if "duplicate column" in msg or "already exists" in msg or "1060" in msg:
            print(f"SKIP: {label} already exists")
        else:
            raise


def run():
    with engine.connect() as conn:
        _run(
            conn,
            "ALTER TABLE leads ADD COLUMN row_color VARCHAR(32) NULL",
            "leads.row_color",
        )
    print("Migration complete.")


if __name__ == "__main__":
    run()
