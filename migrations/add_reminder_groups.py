"""
One-time migration: reminder groups with shared schedule and assignees.
Run: python migrations/add_reminder_groups.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def run():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reminder_groups (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(500) NOT NULL,
                notes TEXT NULL,
                frequency VARCHAR(20) NOT NULL DEFAULT 'once',
                reminder_date DATE NULL,
                reminder_time TIME NULL,
                day_of_week INT NULL,
                day_of_month INT NULL,
                created_by_id INT NULL,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX ix_reminder_groups_id (id),
                INDEX ix_reminder_groups_created_by_id (created_by_id),
                FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """))
        conn.commit()
        print("Created table: reminder_groups (or already exists).")

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS reminder_group_user_association (
                reminder_group_id INT NOT NULL,
                user_id INT NOT NULL,
                PRIMARY KEY (reminder_group_id, user_id),
                FOREIGN KEY (reminder_group_id) REFERENCES reminder_groups(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("Created table: reminder_group_user_association (or already exists).")

        for col, sql in [
            ("group_id", "ALTER TABLE reminders ADD COLUMN group_id INT NULL AFTER created_by_id"),
            ("sort_order", "ALTER TABLE reminders ADD COLUMN sort_order INT NOT NULL DEFAULT 0 AFTER group_id"),
            ("use_custom_schedule", "ALTER TABLE reminders ADD COLUMN use_custom_schedule TINYINT(1) NOT NULL DEFAULT 0 AFTER sort_order"),
        ]:
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"Added reminders.{col}")
            except Exception as e:
                if "Duplicate column" in str(e) or "1060" in str(e):
                    print(f"reminders.{col} already exists, skipping.")
                else:
                    raise

        for sql in [
            "ALTER TABLE reminders ADD INDEX ix_reminders_group_id (group_id)",
            "ALTER TABLE reminders ADD CONSTRAINT fk_reminders_group_id FOREIGN KEY (group_id) REFERENCES reminder_groups(id) ON DELETE CASCADE",
        ]:
            try:
                conn.execute(text(sql))
                conn.commit()
                print("Added reminders.group_id index/FK")
            except Exception as e:
                if "Duplicate" in str(e) or "1061" in str(e) or "1826" in str(e) or "1068" in str(e):
                    print("reminders.group_id index/FK already exists, skipping.")
                else:
                    raise

    print("Migration complete.")


if __name__ == "__main__":
    run()
