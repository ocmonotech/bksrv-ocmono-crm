"""
One-time migration: create file_records table for File Manager.
Run: python migrations/add_file_records_table.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def run():
    ddl = """
    CREATE TABLE IF NOT EXISTS file_records (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        name VARCHAR(255) NOT NULL,
        extension VARCHAR(50) NULL,
        mime_type VARCHAR(255) NULL,
        size_bytes BIGINT NOT NULL DEFAULT 0,
        category VARCHAR(100) NULL,
        tags TEXT NULL,
        notes TEXT NULL,
        last_modified_at DATETIME NULL,
        uploaded_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX ix_file_records_id (id),
        INDEX ix_file_records_user_id (user_id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """
    with engine.connect() as conn:
        conn.execute(text(ddl))
        conn.commit()
    print("Created table: file_records (or already exists).")
    print("Migration complete.")


if __name__ == "__main__":
    run()

