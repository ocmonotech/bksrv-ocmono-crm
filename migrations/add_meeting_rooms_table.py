"""
One-time migration: create meeting_rooms table.
Run: python migrations/add_meeting_rooms_table.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def run():
    ddl = """
    CREATE TABLE IF NOT EXISTS meeting_rooms (
        id INT AUTO_INCREMENT PRIMARY KEY,
        room_id VARCHAR(64) NOT NULL,
        title VARCHAR(255) NULL,
        created_by_id INT NOT NULL,
        created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
        is_active TINYINT(1) NOT NULL DEFAULT 1,
        UNIQUE KEY uq_meeting_rooms_room_id (room_id),
        INDEX ix_meeting_rooms_room_id (room_id),
        INDEX ix_meeting_rooms_created_by_id (created_by_id),
        FOREIGN KEY (created_by_id) REFERENCES users (id)
    )
    """
    with engine.connect() as conn:
        conn.execute(text(ddl))
        conn.commit()
    print("Created table: meeting_rooms (or already exists).")
    print("Migration complete.")


if __name__ == "__main__":
    run()
