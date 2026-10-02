"""
Add newsletter fields for Create Newsletter modal (sender, campaign targeting, rate limits).
Run: python migrations/add_newsletter_extra_fields.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text


def add_column(conn, sql: str, label: str):
    try:
        conn.execute(text(sql))
        conn.commit()
        print(f"Added {label}")
    except Exception as e:
        if "Duplicate column" in str(e) or "1060" in str(e):
            print(f"{label} already exists, skipping.")
        else:
            raise


def run():
    statements = [
        (
            "ALTER TABLE newsletters ADD COLUMN recipient_mode VARCHAR(30) NOT NULL DEFAULT 'selected_leads'",
            "newsletters.recipient_mode",
        ),
        (
            "ALTER TABLE newsletters ADD COLUMN campaign_id INT NULL",
            "newsletters.campaign_id",
        ),
        (
            "ALTER TABLE newsletters ADD COLUMN send_from_email VARCHAR(255) NULL",
            "newsletters.send_from_email",
        ),
        (
            "ALTER TABLE newsletters ADD COLUMN send_from_name VARCHAR(255) NULL",
            "newsletters.send_from_name",
        ),
        (
            "ALTER TABLE newsletters ADD COLUMN reply_to_email VARCHAR(255) NULL",
            "newsletters.reply_to_email",
        ),
        (
            "ALTER TABLE newsletters ADD COLUMN tracking_campaign_name VARCHAR(255) NULL",
            "newsletters.tracking_campaign_name",
        ),
        (
            "ALTER TABLE newsletters ADD COLUMN per_hour_limit INT NOT NULL DEFAULT 50",
            "newsletters.per_hour_limit",
        ),
        (
            "ALTER TABLE newsletters ADD COLUMN batch_interval_minutes INT NOT NULL DEFAULT 30",
            "newsletters.batch_interval_minutes",
        ),
        (
            "ALTER TABLE newsletters ADD COLUMN include_unsubscribe TINYINT(1) NOT NULL DEFAULT 1",
            "newsletters.include_unsubscribe",
        ),
    ]
    with engine.connect() as conn:
        for sql, label in statements:
            add_column(conn, sql, label)

        try:
            conn.execute(
                text(
                    "ALTER TABLE newsletters ADD CONSTRAINT fk_newsletters_campaign "
                    "FOREIGN KEY (campaign_id) REFERENCES campaigns(id)"
                )
            )
            conn.commit()
            print("Added fk_newsletters_campaign")
        except Exception as e:
            conn.rollback()
            if "Duplicate" in str(e) or "1826" in str(e) or "already exists" in str(e).lower():
                print("FK fk_newsletters_campaign already exists, skipping.")
            else:
                raise

    print("Migration complete.")


if __name__ == "__main__":
    run()
