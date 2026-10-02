"""
One-time migration: create user_groups and user_group_members; add assignment group columns.
Run: python migrations/add_user_groups.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text


def run():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_groups (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(150) NOT NULL,
                description TEXT NULL,
                created_by_id INT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_deleted TINYINT(1) NOT NULL DEFAULT 0,
                deleted_at DATETIME NULL,
                INDEX idx_user_groups_name (name),
                INDEX idx_user_groups_is_deleted (is_deleted),
                FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE SET NULL
            )
        """))
        conn.commit()
        print("Created table: user_groups")

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_group_members (
                user_group_id INT NOT NULL,
                user_id INT NOT NULL,
                PRIMARY KEY (user_group_id, user_id),
                FOREIGN KEY (user_group_id) REFERENCES user_groups(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """))
        conn.commit()
        print("Created table: user_group_members")

        for col, sql in [
            ("assigned_group_id", "ALTER TABLE assignments ADD COLUMN assigned_group_id INT NULL AFTER deleted_at"),
            ("assigned_group_name", "ALTER TABLE assignments ADD COLUMN assigned_group_name VARCHAR(150) NULL AFTER assigned_group_id"),
        ]:
            try:
                conn.execute(text(sql))
                conn.commit()
                print(f"Added assignments.{col}")
            except Exception as e:
                if "Duplicate column" in str(e) or "1060" in str(e):
                    print(f"assignments.{col} already exists, skipping.")
                else:
                    raise

        try:
            conn.execute(text(
                "ALTER TABLE assignments ADD CONSTRAINT fk_assignments_assigned_group "
                "FOREIGN KEY (assigned_group_id) REFERENCES user_groups(id) ON DELETE SET NULL"
            ))
            conn.commit()
            print("Added FK: assignments.assigned_group_id -> user_groups.id")
        except Exception as e:
            if "Duplicate" in str(e) or "1826" in str(e):
                print("FK assignments.assigned_group_id already exists, skipping.")
            else:
                raise
    print("Migration complete.")


if __name__ == "__main__":
    run()
