"""
One-time migration: per-user snooze state for reminders.
Run: python migrations/add_reminder_snoozes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def run():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reminder_snoozes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                reminder_id INT NOT NULL,
                user_id INT NOT NULL,
                snoozed_until DATETIME NOT NULL,
                snoozed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_reminder_snooze_user (reminder_id, user_id),
                INDEX ix_reminder_snoozes_reminder_id (reminder_id),
                INDEX ix_reminder_snoozes_user_id (user_id),
                FOREIGN KEY (reminder_id) REFERENCES reminders(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
    print("Created table: reminder_snoozes (or already exists).")
    print("Migration complete.")


if __name__ == "__main__":
    run()
