"""
One-time migration: add path and method columns to activity_logs.
Run: python migrations/add_activity_log_columns.py
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text

def run():
    with engine.connect() as conn:
        # Add path column if not exists (MySQL 8.0 doesn't have IF NOT EXISTS for columns, so we use a try/except or check)
        try:
            conn.execute(text("ALTER TABLE activity_logs ADD COLUMN path VARCHAR(500) NULL AFTER activity_type"))
            conn.commit()
            print("Added column: activity_logs.path")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print("Column activity_logs.path already exists, skipping.")
            else:
                raise
        try:
            conn.execute(text("ALTER TABLE activity_logs ADD COLUMN method VARCHAR(10) NULL AFTER path"))
            conn.commit()
            print("Added column: activity_logs.method")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print("Column activity_logs.method already exists, skipping.")
            else:
                raise
    print("Migration complete.")

if __name__ == "__main__":
    run()
