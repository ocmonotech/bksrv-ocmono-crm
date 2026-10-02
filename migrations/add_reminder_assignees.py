"""
One-time migration: add reminder assignees (created_by_id + reminder_user_association).
Run: python migrations/add_reminder_assignees.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def run():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reminder_user_association (
                reminder_id INT NOT NULL,
                user_id INT NOT NULL,
                PRIMARY KEY (reminder_id, user_id),
                FOREIGN KEY (reminder_id) REFERENCES reminders(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("Created table: reminder_user_association (or already exists).")

        try:
            conn.execute(text(
                "ALTER TABLE reminders ADD COLUMN created_by_id INT NULL AFTER user_id"
            ))
            conn.commit()
            print("Added reminders.created_by_id")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print("reminders.created_by_id already exists, skipping.")
            else:
                raise

        try:
            conn.execute(text(
                "ALTER TABLE reminders ADD INDEX ix_reminders_created_by_id (created_by_id)"
            ))
            conn.commit()
            print("Added index ix_reminders_created_by_id")
        except Exception as e:
            if "Duplicate" in str(e) or "1061" in str(e):
                print("Index ix_reminders_created_by_id already exists, skipping.")
            else:
                raise

        conn.execute(text("""
            UPDATE reminders
            SET created_by_id = user_id
            WHERE created_by_id IS NULL
        """))
        conn.commit()
        print("Backfilled reminders.created_by_id from user_id.")

        conn.execute(text("""
            INSERT IGNORE INTO reminder_user_association (reminder_id, user_id)
            SELECT id, user_id FROM reminders
        """))
        conn.commit()
        print("Backfilled reminder_user_association from existing reminders.")

    print("Migration complete.")


if __name__ == "__main__":
    run()
