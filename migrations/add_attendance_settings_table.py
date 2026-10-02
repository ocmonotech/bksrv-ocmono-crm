"""Create attendance_settings table (id=1 row seeded on first API use)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from database import engine


def main() -> None:
    with engine.begin() as conn:
        r = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'attendance_settings'"
            )
        )
        if int(r.scalar() or 0) > 0:
            print("Skip attendance_settings (exists)")
            return
        conn.execute(
            text(
                """
                CREATE TABLE attendance_settings (
                  id INT NOT NULL PRIMARY KEY,
                  on_duty_first_half TIME NOT NULL,
                  off_duty_first_half TIME NOT NULL,
                  on_duty_second_half TIME NOT NULL,
                  off_duty_second_half TIME NOT NULL,
                  half_day_min_hours_first_half DOUBLE NOT NULL,
                  half_day_min_hours_second_half DOUBLE NOT NULL,
                  late_mark_after TIME NOT NULL,
                  overtime_checkin_before TIME NULL,
                  overtime_checkout_after TIME NULL,
                  updated_at DATETIME(6) NULL,
                  updated_by_username VARCHAR(50) NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        )
        print("Created attendance_settings")


if __name__ == "__main__":
    main()
