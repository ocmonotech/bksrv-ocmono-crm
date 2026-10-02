"""
One-time migration: add notes column to project_timers table.
Run: python migrations/add_project_timer_notes_column.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def run():
    sql = "ALTER TABLE project_timers ADD COLUMN notes TEXT NULL"
    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
            print("Added column: project_timers.notes")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print("Column project_timers.notes already exists; skipping.")
            else:
                raise
    print("Migration complete.")


if __name__ == "__main__":
    run()
