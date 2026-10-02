"""
One-time migration: add is_deleted and deleted_at for soft delete.
Run: python migrations/add_soft_delete_columns.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text


def add_soft_delete(conn, table: str):
    for col, sql in [
        ("is_deleted", f"ALTER TABLE {table} ADD COLUMN is_deleted TINYINT(1) NOT NULL DEFAULT 0"),
        ("deleted_at", f"ALTER TABLE {table} ADD COLUMN deleted_at DATETIME NULL"),
    ]:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"Added {table}.{col}")
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                print(f"{table}.{col} already exists, skipping.")
            else:
                raise


def run():
    tables = [
        "assignments",
        "tasks",
        "leads",
        "clients",
        "todos",
        "message_templates",
        "lead_calls",
        "lead_notes",
        "campaigns",
        "projects",
        "newsletters",
        "users",
        "lead_tasks",
    ]
    with engine.connect() as conn:
        for table in tables:
            add_soft_delete(conn, table)
    print("Migration complete.")


if __name__ == "__main__":
    run()
