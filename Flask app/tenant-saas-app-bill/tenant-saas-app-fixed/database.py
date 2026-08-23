"""
database.py
-----------
Schema bootstrap for the two tenant tables. This is intentionally
separate from services/rds_service.py (which handles day-to-day
CRUD): database.py is only ever invoked manually/at deploy time
(e.g. via an ECS one-off task or a migration step), never on the
normal request path.
"""

from logging_config import app_logger
from services.rds_service import get_connection
from config import config

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS `TenantA` (
        userId VARCHAR(64) PRIMARY KEY,
        username VARCHAR(128) NOT NULL UNIQUE,
        email VARCHAR(255) NOT NULL,
        role ENUM('admin', 'user') NOT NULL DEFAULT 'user',
        phone VARCHAR(64) DEFAULT '',
        department VARCHAR(128) DEFAULT '',
        profile_image VARCHAR(255) DEFAULT '',
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        password_last_changed DATE DEFAULT NULL,
        first_login BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
    """
    CREATE TABLE IF NOT EXISTS `TenantB` (
        userId VARCHAR(64) PRIMARY KEY,
        username VARCHAR(128) NOT NULL UNIQUE,
        email VARCHAR(255) NOT NULL,
        role ENUM('admin', 'user') NOT NULL DEFAULT 'user',
        phone VARCHAR(64) DEFAULT '',
        department VARCHAR(128) DEFAULT '',
        profile_image VARCHAR(255) DEFAULT '',
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        password_last_changed DATE DEFAULT NULL,
        first_login BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """,
]


def init_schema() -> None:
    """Creates the TenantA / TenantB tables if they do not already
    exist. Safe to run repeatedly (idempotent CREATE TABLE IF NOT
    EXISTS)."""
    if config.DEMO_MODE:
        app_logger.info("DEMO_MODE active - skipping real schema bootstrap")
        return

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for statement in _SCHEMA_STATEMENTS:
                cursor.execute(statement)
        conn.commit()
        app_logger.info("Database schema verified/created successfully")
    except Exception:
        conn.rollback()
        app_logger.exception("Failed to initialize database schema")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_schema()
