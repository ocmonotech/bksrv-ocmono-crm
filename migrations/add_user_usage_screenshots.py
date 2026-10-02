"""
One-time migration: create user_usage_screenshots table for random daily screenshots.
Run: python3 migrations/add_user_usage_screenshots.py (with venv activated)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text

SQL = """
CREATE TABLE IF NOT EXISTS user_usage_screenshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    captured_at DATETIME NOT NULL,
    file_path VARCHAR(512) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_user_usage_screenshots_user_id (user_id),
    INDEX ix_user_usage_screenshots_captured_at (captured_at),
    FOREIGN KEY (user_id) REFERENCES users(id)
)
"""


def run():
    with engine.connect() as conn:
        conn.execute(text(SQL))
        conn.commit()
        print("Created table: user_usage_screenshots")
    print("Migration complete.")


if __name__ == "__main__":
    run()
