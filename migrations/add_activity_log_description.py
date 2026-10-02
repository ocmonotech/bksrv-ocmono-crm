"""
One-time migration: add description column to activity_logs.
Run: python migrations/add_activity_log_description.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text

def run():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE activity_logs ADD COLUMN description VARCHAR(255) NULL AFTER activity_type"))
            conn.commit()
            print("Added column: activity_logs.description")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print("Column activity_logs.description already exists, skipping.")
            else:
                raise
    print("Migration complete.")

if __name__ == "__main__":
    run()
