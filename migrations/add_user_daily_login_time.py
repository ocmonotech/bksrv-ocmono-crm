"""
One-time migration: create user_daily_login_time table.
Run: python migrations/add_user_daily_login_time.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text

SQL = """
CREATE TABLE IF NOT EXISTS user_daily_login_time (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    date DATE NOT NULL,
    total_seconds_logged_in INT NOT NULL DEFAULT 0,
    INDEX ix_user_daily_login_time_user_id (user_id),
    INDEX ix_user_daily_login_time_date (date),
    FOREIGN KEY (user_id) REFERENCES users(id)
)
"""

def run():
    with engine.connect() as conn:
        conn.execute(text(SQL))
        conn.commit()
        print("Created table: user_daily_login_time")
    print("Migration complete.")

if __name__ == "__main__":
    run()
