"""
Add newsletter tracking/unsubscribe fields, tables, and indexes.
Run: python migrations/add_newsletter_tracking_and_unsubscribes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import engine


def _run(conn, sql: str, label: str):
    try:
        conn.execute(text(sql))
        conn.commit()
        print(f"OK: {label}")
    except Exception as e:
        conn.rollback()
        msg = str(e).lower()
        if (
            "duplicate column" in msg
            or "already exists" in msg
            or "1060" in msg
            or "1061" in msg
            or "1826" in msg
        ):
            print(f"SKIP: {label} already exists")
        else:
            raise


def run():
    with engine.connect() as conn:
        # leads table additions
        _run(
            conn,
            "ALTER TABLE leads ADD COLUMN is_unsubscribed TINYINT(1) NOT NULL DEFAULT 0",
            "leads.is_unsubscribed",
        )
        _run(
            conn,
            "ALTER TABLE leads ADD COLUMN unsubscribed_at DATETIME NULL",
            "leads.unsubscribed_at",
        )
        _run(
            conn,
            "CREATE INDEX idx_leads_is_unsubscribed ON leads(is_unsubscribed)",
            "idx_leads_is_unsubscribed",
        )

        # newsletter_email_logs additions
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN provider_message_id VARCHAR(255) NULL",
            "newsletter_email_logs.provider_message_id",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN delivered_at DATETIME NULL",
            "newsletter_email_logs.delivered_at",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN opened_at DATETIME NULL",
            "newsletter_email_logs.opened_at",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN clicked_at DATETIME NULL",
            "newsletter_email_logs.clicked_at",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN failed_at DATETIME NULL",
            "newsletter_email_logs.failed_at",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN bounced_at DATETIME NULL",
            "newsletter_email_logs.bounced_at",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN unsubscribed_at DATETIME NULL",
            "newsletter_email_logs.unsubscribed_at",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN open_count INT NOT NULL DEFAULT 0",
            "newsletter_email_logs.open_count",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN click_count INT NOT NULL DEFAULT 0",
            "newsletter_email_logs.click_count",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN last_event_at DATETIME NULL",
            "newsletter_email_logs.last_event_at",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs ADD COLUMN updated_at DATETIME NULL",
            "newsletter_email_logs.updated_at",
        )
        _run(
            conn,
            "ALTER TABLE newsletter_email_logs MODIFY COLUMN status VARCHAR(20) NOT NULL DEFAULT 'queued'",
            "newsletter_email_logs.status default queued",
        )
        _run(
            conn,
            "CREATE INDEX idx_newsletter_email_logs_newsletter_status ON newsletter_email_logs(newsletter_id, status)",
            "idx_newsletter_email_logs_newsletter_status",
        )
        _run(
            conn,
            "CREATE UNIQUE INDEX uidx_newsletter_email_logs_provider_message_id ON newsletter_email_logs(provider_message_id)",
            "uidx_newsletter_email_logs_provider_message_id",
        )

        # unsubscribe audit table
        _run(
            conn,
            """
            CREATE TABLE newsletter_unsubscribes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                newsletter_id INT NOT NULL,
                lead_id INT NOT NULL,
                email VARCHAR(255) NOT NULL,
                token_hash VARCHAR(255) NULL,
                ip VARCHAR(100) NULL,
                user_agent VARCHAR(500) NULL,
                created_at DATETIME NULL,
                CONSTRAINT fk_newsletter_unsubscribes_newsletter
                    FOREIGN KEY (newsletter_id) REFERENCES newsletters(id),
                CONSTRAINT fk_newsletter_unsubscribes_lead
                    FOREIGN KEY (lead_id) REFERENCES leads(id)
            )
            """,
            "newsletter_unsubscribes table",
        )
        _run(
            conn,
            "CREATE INDEX idx_newsletter_unsubscribes_newsletter_created_at ON newsletter_unsubscribes(newsletter_id, created_at)",
            "idx_newsletter_unsubscribes_newsletter_created_at",
        )

    print("Migration complete.")


if __name__ == "__main__":
    run()
