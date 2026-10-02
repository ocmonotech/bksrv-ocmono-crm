"""
One-time migration: add location column to activity_logs.
Run: python migrations/add_activity_log_location.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text

def run():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE activity_logs ADD COLUMN location VARCHAR(255) NULL AFTER ip_address"))
            conn.commit()
            print("Added column: activity_logs.location")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print("Column activity_logs.location already exists, skipping.")
            else:
                raise
    print("Migration complete.")

if __name__ == "__main__":
    run()
