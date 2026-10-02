"""
One-time migration: add call_note_date column to lead_calls table.
Run: python migrations/add_call_note_date_column.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def run():
    sql = "ALTER TABLE lead_calls ADD COLUMN call_note_date DATE NULL"
    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
            print("Added column: lead_calls.call_note_date")
        except Exception as e:
            # Allow rerun
            if "Duplicate column" in str(e) or "1060" in str(e):
                print("Column lead_calls.call_note_date already exists; skipping.")
            else:
                raise
    print("Migration complete.")


if __name__ == "__main__":
    run()

