"""
One-time migration: create reminders table.
Run: python migrations/add_reminders_table.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def run():
    ddl = """
    CREATE TABLE IF NOT EXISTS reminders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        title VARCHAR(500) NOT NULL,
        notes TEXT NULL,
        frequency VARCHAR(20) NOT NULL DEFAULT 'once',
        reminder_date DATE NULL,
        reminder_time TIME NULL,
        day_of_week INT NULL,
        day_of_month INT NULL,
        is_active TINYINT(1) NOT NULL DEFAULT 1,
        created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX ix_reminders_id (id),
        INDEX ix_reminders_user_id (user_id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """
    with engine.connect() as conn:
        conn.execute(text(ddl))
        conn.commit()
    print("Created table: reminders (or already exists).")
    print("Migration complete.")


if __name__ == "__main__":
    run()
