"""
One-time migration: add mouse_active_seconds to user_usage_snapshots.
Run: python migrations/add_user_usage_mouse_active.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text


def run():
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "ALTER TABLE user_usage_snapshots ADD COLUMN mouse_active_seconds INT NOT NULL DEFAULT 0 "
                "AFTER screen_active_seconds"
            ))
            conn.commit()
            print("Added column: user_usage_snapshots.mouse_active_seconds")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print("Column user_usage_snapshots.mouse_active_seconds already exists, skipping.")
            else:
                raise
    print("Migration complete.")


if __name__ == "__main__":
    run()
