"""
One-time migration: add type/target_url/entity_id columns to notifications.
Run: python migrations/add_notification_event_fields.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def _add_column_if_missing(conn, ddl: str, name: str):
    try:
        conn.execute(text(ddl))
        conn.commit()
        print(f"Added column: notifications.{name}")
    except Exception as e:
        if "Duplicate column" in str(e) or "1060" in str(e):
            print(f"Column notifications.{name} already exists, skipping.")
        else:
            raise


def run():
    with engine.connect() as conn:
        _add_column_if_missing(
            conn,
            "ALTER TABLE notifications ADD COLUMN type VARCHAR(50) NOT NULL DEFAULT 'general' AFTER message",
            "type",
        )
        _add_column_if_missing(
            conn,
            "ALTER TABLE notifications ADD COLUMN target_url VARCHAR(500) NULL AFTER is_read",
            "target_url",
        )
        _add_column_if_missing(
            conn,
            "ALTER TABLE notifications ADD COLUMN entity_id INT NULL AFTER target_url",
            "entity_id",
        )
    print("Migration complete.")


if __name__ == "__main__":
    run()
