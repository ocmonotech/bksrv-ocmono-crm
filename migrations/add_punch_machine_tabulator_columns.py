"""
Apply Tabulator-related punch machine schema changes (safe to re-run: skips existing columns).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from database import engine


def column_exists(conn, table: str, column: str) -> bool:
    r = conn.execute(
        text(
            """
            SELECT COUNT(*) AS c FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c
            """
        ),
        {"t": table, "c": column},
    )
    return int(r.scalar() or 0) > 0


def table_exists(conn, table: str) -> bool:
    r = conn.execute(
        text(
            """
            SELECT COUNT(*) AS c FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t
            """
        ),
        {"t": table},
    )
    return int(r.scalar() or 0) > 0


def main() -> None:
    with engine.begin() as conn:
        if not table_exists(conn, "punch_machine_imports"):
            print("punch_machine_imports missing; create_all will create fresh tables.")
            return
        for col, ddl in [
            ("detected_format", "ALTER TABLE punch_machine_imports ADD COLUMN detected_format VARCHAR(80) NULL"),
            ("report_year", "ALTER TABLE punch_machine_imports ADD COLUMN report_year INT NULL"),
            ("report_month", "ALTER TABLE punch_machine_imports ADD COLUMN report_month INT NULL"),
            ("statistics_json", "ALTER TABLE punch_machine_imports ADD COLUMN statistics_json LONGTEXT NULL"),
        ]:
            if not column_exists(conn, "punch_machine_imports", col):
                conn.execute(text(ddl))
                print(f"Added column punch_machine_imports.{col}")
            else:
                print(f"Skip punch_machine_imports.{col} (exists)")

        if not table_exists(conn, "punch_machine_schedule_days"):
            conn.execute(
                text(
                    """
                    CREATE TABLE punch_machine_schedule_days (
                      id INT AUTO_INCREMENT PRIMARY KEY,
                      import_id INT NOT NULL,
                      machine_user_key VARCHAR(80) NOT NULL,
                      username VARCHAR(50) NULL,
                      work_date DATE NOT NULL,
                      code VARCHAR(20) NULL,
                      INDEX ix_pmsd_import (import_id),
                      INDEX ix_pmsd_user_date (username, work_date),
                      CONSTRAINT fk_pmsd_import FOREIGN KEY (import_id) REFERENCES punch_machine_imports(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            )
            print("Created punch_machine_schedule_days")
        else:
            print("Skip punch_machine_schedule_days (exists)")

        if not table_exists(conn, "punch_machine_exception_days"):
            conn.execute(
                text(
                    """
                    CREATE TABLE punch_machine_exception_days (
                      id INT AUTO_INCREMENT PRIMARY KEY,
                      import_id INT NOT NULL,
                      machine_user_key VARCHAR(80) NOT NULL,
                      username VARCHAR(50) NULL,
                      work_date DATE NOT NULL,
                      late_min INT NULL,
                      early_min INT NULL,
                      absence_min INT NULL,
                      total_min INT NULL,
                      raw_json LONGTEXT NULL,
                      INDEX ix_pmed_import (import_id),
                      INDEX ix_pmed_user_date (username, work_date),
                      CONSTRAINT fk_pmed_import FOREIGN KEY (import_id) REFERENCES punch_machine_imports(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            )
            print("Created punch_machine_exception_days")
        else:
            print("Skip punch_machine_exception_days (exists)")


if __name__ == "__main__":
    main()
