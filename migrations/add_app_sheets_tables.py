"""
Create tables for the Sheets module (connected Google Sheets with bidirectional sync).
Run: python migrations/add_app_sheets_tables.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def run():
    statements = [
        """
        CREATE TABLE IF NOT EXISTS app_sheet_connections (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            sheet_url TEXT NOT NULL,
            sheet_id VARCHAR(200) NULL,
            sheet_name VARCHAR(200) NULL DEFAULT 'Sheet1',
            gid VARCHAR(50) NULL,
            sync_frequency VARCHAR(50) NULL DEFAULT 'Every 15 minutes',
            status VARCHAR(50) NULL DEFAULT 'Active',
            headers JSON NULL,
            row_count INT NULL DEFAULT 0,
            last_sync DATETIME NULL,
            next_sync DATETIME NULL,
            write_enabled TINYINT(1) NULL DEFAULT 1,
            errors INT NULL DEFAULT 0,
            created_at DATETIME NULL,
            updated_at DATETIME NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS app_sheet_rows (
            id INT AUTO_INCREMENT PRIMARY KEY,
            connection_id INT NOT NULL,
            row_number INT NOT NULL,
            data JSON NULL,
            checksum VARCHAR(64) NULL,
            dirty TINYINT(1) NULL DEFAULT 0,
            updated_from VARCHAR(20) NULL DEFAULT 'google',
            created_at DATETIME NULL,
            updated_at DATETIME NULL,
            UNIQUE KEY uq_app_sheet_row_number (connection_id, row_number),
            INDEX ix_app_sheet_rows_connection_id (connection_id),
            CONSTRAINT fk_app_sheet_rows_connection
                FOREIGN KEY (connection_id) REFERENCES app_sheet_connections (id)
                ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS app_sheet_sync_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            connection_id INT NOT NULL,
            connection_name VARCHAR(200) NOT NULL,
            status VARCHAR(50) NOT NULL,
            rows_synced INT NULL DEFAULT 0,
            message TEXT NULL,
            error_details TEXT NULL,
            created_at DATETIME NULL,
            INDEX ix_app_sheet_sync_logs_connection_id (connection_id)
        )
        """,
    ]
    with engine.connect() as conn:
        for ddl in statements:
            conn.execute(text(ddl))
        conn.commit()
    print("Created app_sheet_connections, app_sheet_rows, app_sheet_sync_logs (or already exist).")
    print("Migration complete.")


if __name__ == "__main__":
    run()
