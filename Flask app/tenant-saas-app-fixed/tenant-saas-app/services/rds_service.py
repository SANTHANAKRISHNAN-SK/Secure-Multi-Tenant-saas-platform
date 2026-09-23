"""
services/rds_service.py
-------------------------
All Amazon RDS (MySQL) data access lives here, behind a small set of
functions that take `tenant` as an explicit parameter resolved from
the validated JWT -- NEVER from request.form/args/json. This is the
single choke point that enforces tenant isolation: every query is
scoped to exactly one of the two allow-listed tables (TenantA /
TenantB), selected via a strict whitelist lookup, and every value is
passed through parameterized queries (never string-interpolated) to
prevent SQL injection.
"""

from datetime import date

import pymysql
import pymysql.cursors

from config import config
from logging_config import app_logger
from services.secret_service import get_secret

# Whitelist of tenant -> table name. This is intentionally NOT built
# from user input (e.g. f"{tenant}" directly) so a malformed or
# spoofed tenant claim can never be used to reference an arbitrary
# table name.
_TENANT_TABLE_WHITELIST = {
    "TenantA": "TenantA",
    "TenantB": "TenantB",
}

# Columns that upsert_user_profile is allowed to write. Role/tenant
# are handled separately (role only via create-user/insert defaults;
# tenant is never a column value, it selects the table).
_EDITABLE_PROFILE_FIELDS = {"username", "email", "phone", "department", "profile_image"}

# In-memory mock database used only when DEMO_MODE=true.
_demo_db = {
    "TenantA": {
        "admin-001": {"userId": "admin-001", "username": "alice.admin", "email": "alice@tenanta.com",
                      "role": "admin", "phone": "+1-555-0101", "department": "IT Operations",
                      "enabled": True, "password_last_changed": "2026-06-01", "first_login": False},
        "user-001": {"userId": "user-001", "username": "bob.user", "email": "bob@tenanta.com",
                     "role": "user", "phone": "+1-555-0102", "department": "Finance",
                     "enabled": True, "password_last_changed": "2026-05-15", "first_login": False},
    },
    "TenantB": {
        "admin-101": {"userId": "admin-101", "username": "carla.admin", "email": "carla@tenantb.com",
                      "role": "admin", "phone": "+1-555-0201", "department": "Engineering",
                      "enabled": True, "password_last_changed": "2026-06-20", "first_login": False},
        "user-101": {"userId": "user-101", "username": "dan.user", "email": "dan@tenantb.com",
                     "role": "user", "phone": "+1-555-0202", "department": "Sales",
                     "enabled": True, "password_last_changed": "2026-07-01", "first_login": True},
    },
}


def _table_for_tenant(tenant: str) -> str:
    """Resolves a tenant identifier to its whitelisted table name.
    Raises if the tenant is not one of the known allow-listed tenants."""
    table = _TENANT_TABLE_WHITELIST.get(tenant)
    if not table:
        raise ValueError(f"Unknown or disallowed tenant: {tenant!r}")
    return table


def get_connection():
    """Opens a new pymysql connection using credentials fetched from
    Secrets Manager (never hardcoded, never in env vars in plaintext)."""
    secret = get_secret()
    return pymysql.connect(
        host=config.RDS_HOST,
        port=config.RDS_PORT,
        user=secret.get("db_username"),
        password=secret.get("db_password"),
        database=config.RDS_DB_NAME,
        connect_timeout=config.RDS_CONNECT_TIMEOUT,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def get_user_by_id(tenant: str, user_id: str) -> dict:
    """Fetches a single user row from the tenant-scoped table.

    Returns None if the user doesn't exist yet (this is a normal,
    expected state for a brand-new Cognito user who hasn't completed
    profile setup -- callers should treat None as "no profile yet",
    not as an error)."""
    table = _table_for_tenant(tenant)

    if config.DEMO_MODE:
        return _demo_db.get(tenant, {}).get(user_id)

    if not user_id:
        app_logger.warning("get_user_by_id called with empty user_id for tenant=%s", tenant)
        return None

    query = f"SELECT * FROM `{table}` WHERE userId = %s"  # table name is whitelisted, value is parameterized
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, (user_id,))
            return cursor.fetchone()
    except Exception:
        app_logger.exception("Failed fetching user_id=%s in tenant=%s", user_id, tenant)
        raise
    finally:
        conn.close()


def get_user_by_username(tenant: str, username: str) -> dict:
    """
    Looks up a tenant-scoped user record by username. This is the
    real join key between the validated Cognito identity
    (cognito:username claim) and the RDS profile row, since the
    Cognito `sub` is not stored as the RDS primary key in this schema
    -- `userId` is a separate, admin-assigned tenant identifier.
    """
    table = _table_for_tenant(tenant)

    if config.DEMO_MODE:
        for record in _demo_db.get(tenant, {}).values():
            if record.get("username") == username:
                return record
        return None

    if not username:
        app_logger.warning("get_user_by_username called with empty username for tenant=%s", tenant)
        return None

    query = f"SELECT * FROM `{table}` WHERE username = %s"
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, (username,))
            return cursor.fetchone()
    except Exception:
        app_logger.exception("Failed fetching username=%s in tenant=%s", username, tenant)
        raise
    finally:
        conn.close()


def list_users(tenant: str, search: str = "", page: int = 1, page_size: int = 10) -> dict:
    """Returns a paginated, optionally search-filtered list of users
    for a single tenant, plus aggregate counts used on the admin
    dashboard cards."""
    if config.DEMO_MODE:
        rows = list(_demo_db.get(tenant, {}).values())
        if search:
            s = search.lower()
            rows = [r for r in rows if s in r["username"].lower() or s in r["email"].lower()]
        total = len(rows)
        start = (page - 1) * page_size
        page_rows = rows[start:start + page_size]
        return {
            "rows": page_rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "admins": sum(1 for r in list(_demo_db.get(tenant, {}).values()) if r["role"] == "admin"),
            "users": sum(1 for r in list(_demo_db.get(tenant, {}).values()) if r["role"] == "user"),
            "active": sum(1 for r in list(_demo_db.get(tenant, {}).values()) if r["enabled"]),
            "disabled": sum(1 for r in list(_demo_db.get(tenant, {}).values()) if not r["enabled"]),
        }

    table = _table_for_tenant(tenant)
    offset = (page - 1) * page_size
    like_term = f"%{search}%"
    base_query = f"FROM `{table}` WHERE (username LIKE %s OR email LIKE %s)"
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS cnt {base_query}", (like_term, like_term))
            total = cursor.fetchone()["cnt"]
            cursor.execute(
                f"SELECT * {base_query} ORDER BY username LIMIT %s OFFSET %s",
                (like_term, like_term, page_size, offset),
            )
            rows = cursor.fetchall()
            cursor.execute(f"SELECT role, enabled, COUNT(*) AS cnt FROM `{table}` GROUP BY role, enabled")
            agg = cursor.fetchall()
        stats = {"admins": 0, "users": 0, "active": 0, "disabled": 0}
        for row in agg:
            if row["role"] == "admin":
                stats["admins"] += row["cnt"]
            else:
                stats["users"] += row["cnt"]
            stats["active" if row["enabled"] else "disabled"] += row["cnt"]
        return {
            "rows": rows, "total": total, "page": page, "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size), **stats,
        }
    except Exception:
        app_logger.exception("Failed listing users for tenant=%s", tenant)
        raise
    finally:
        conn.close()


def upsert_user_profile(tenant: str, user_id: str, fields: dict, role: str = "user") -> None:
    """Inserts or updates a user's editable profile fields
    (username/email/phone/department/profile_image).

    This is a REAL upsert: if no row exists yet for `user_id` in the
    tenant-scoped table, one is created (this is the common case for
    a brand-new Cognito user completing profile setup for the first
    time, whose row was never separately provisioned). If a row
    already exists, it is updated in place.

    `role` is only used to populate a *new* row's role column and is
    expected to come from the validated Cognito group membership
    (never from the request body) -- it is never used to change the
    role of an existing row via this function.

    Raises on any failure; callers must not assume success just
    because no exception surfaced from a prior version of this
    function -- a `False` "silent no-op" is no longer possible here,
    since either branch (INSERT or UPDATE) is checked for effect.
    """
    fields = {k: v for k, v in fields.items() if k in _EDITABLE_PROFILE_FIELDS}

    if config.DEMO_MODE:
        record = _demo_db.setdefault(tenant, {}).setdefault(user_id, {
            "userId": user_id,
            "username": fields.get("username", user_id),
            "email": fields.get("email", ""),
            "role": role,
            "phone": "",
            "department": "",
            "enabled": True,
            "password_last_changed": "-",
            "first_login": True,
        })
        record.update(fields)
        return

    table = _table_for_tenant(tenant)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # Lock the row (if any) for the duration of this
            # transaction so two concurrent saves for the same user
            # can't both see "no row" and both try to INSERT.
            cursor.execute(f"SELECT userId FROM `{table}` WHERE userId = %s FOR UPDATE", (user_id,))
            existing = cursor.fetchone()

            if existing:
                if not fields:
                    app_logger.info("No editable fields to update for user_id=%s tenant=%s", user_id, tenant)
                else:
                    set_clause = ", ".join(f"`{k}` = %s" for k in fields)
                    cursor.execute(
                        f"UPDATE `{table}` SET {set_clause} WHERE userId = %s",
                        (*fields.values(), user_id),
                    )
                    if cursor.rowcount == 0:
                        # Row existed a moment ago under the lock but
                        # the UPDATE affected nothing -- treat as a
                        # hard failure rather than a false "success".
                        raise RuntimeError(
                            f"UPDATE affected 0 rows for user_id={user_id!r} tenant={tenant!r}"
                        )
                app_logger.info("Updated profile for user_id=%s in tenant=%s", user_id, tenant)
            else:
                insert_fields = dict(fields)
                insert_fields["userId"] = user_id
                insert_fields.setdefault("username", user_id)
                insert_fields.setdefault("email", "")
                insert_fields["role"] = role
                insert_fields.setdefault("enabled", True)

                columns = ", ".join(f"`{k}`" for k in insert_fields)
                placeholders = ", ".join(["%s"] * len(insert_fields))
                cursor.execute(
                    f"INSERT INTO `{table}` ({columns}) VALUES ({placeholders})",
                    tuple(insert_fields.values()),
                )
                if cursor.rowcount == 0:
                    raise RuntimeError(
                        f"INSERT affected 0 rows for user_id={user_id!r} tenant={tenant!r}"
                    )
                app_logger.info("Created profile row for user_id=%s in tenant=%s", user_id, tenant)

        conn.commit()
    except Exception:
        conn.rollback()
        app_logger.exception("Failed upserting profile for user_id=%s tenant=%s", user_id, tenant)
        raise
    finally:
        conn.close()


def create_user_record(tenant: str, user_id: str, username: str, email: str, role: str) -> None:
    """Inserts a new tenant-scoped user record after the corresponding
    Cognito user + group assignment has been created."""
    if config.DEMO_MODE:
        _demo_db.setdefault(tenant, {})[user_id] = {
            "userId": user_id, "username": username, "email": email, "role": role,
            "phone": "", "department": "", "enabled": True,
            "password_last_changed": "-", "first_login": True,
        }
        return

    table = _table_for_tenant(tenant)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO `{table}` (userId, username, email, role, enabled) "
                f"VALUES (%s, %s, %s, %s, %s)",
                (user_id, username, email, role, True),
            )
        conn.commit()
        app_logger.info("Created RDS user record user_id=%s tenant=%s", user_id, tenant)
    except Exception:
        conn.rollback()
        app_logger.exception("Failed creating RDS user record for user_id=%s", user_id)
        raise
    finally:
        conn.close()


def delete_user_record(tenant: str, user_id: str, hard_delete: bool = False) -> None:
    """Deletes or deactivates a tenant-scoped user record. Soft-delete
    (disable) is the default/preferred path; hard delete is used only
    when the admin explicitly confirms permanent removal."""
    if config.DEMO_MODE:
        if hard_delete:
            _demo_db.get(tenant, {}).pop(user_id, None)
        else:
            row = _demo_db.get(tenant, {}).get(user_id)
            if row:
                row["enabled"] = False
        return

    table = _table_for_tenant(tenant)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if hard_delete:
                cursor.execute(f"DELETE FROM `{table}` WHERE userId = %s", (user_id,))
            else:
                cursor.execute(f"UPDATE `{table}` SET enabled = %s WHERE userId = %s", (False, user_id))
        conn.commit()
        app_logger.info("Removed/disabled RDS user record user_id=%s tenant=%s hard=%s",
                         user_id, tenant, hard_delete)
    except Exception:
        conn.rollback()
        app_logger.exception("Failed deleting/disabling RDS user record for user_id=%s", user_id)
        raise
    finally:
        conn.close()


def set_user_enabled(tenant: str, user_id: str, enabled: bool) -> None:
    """Enable/disable toggle used by the admin panel's Enable/Disable actions."""
    if config.DEMO_MODE:
        row = _demo_db.get(tenant, {}).get(user_id)
        if row:
            row["enabled"] = enabled
        return

    table = _table_for_tenant(tenant)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE `{table}` SET enabled = %s WHERE userId = %s", (enabled, user_id))
        conn.commit()
    except Exception:
        conn.rollback()
        app_logger.exception("Failed toggling enabled for user_id=%s", user_id)
        raise
    finally:
        conn.close()


def mark_password_changed(tenant: str, user_id: str) -> None:
    """Records that a user's password was just changed via Cognito.
    Called after a successful Cognito change_password/reset call so
    the RDS profile row's `password_last_changed` stays in sync, and
    clears `first_login` (a first-time-login forced password change
    is now complete)."""
    today = date.today().isoformat()

    if config.DEMO_MODE:
        row = _demo_db.get(tenant, {}).get(user_id)
        if row:
            row["password_last_changed"] = today
            row["first_login"] = False
        return

    table = _table_for_tenant(tenant)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE `{table}` SET password_last_changed = %s, first_login = %s WHERE userId = %s",
                (today, False, user_id),
            )
        conn.commit()
        app_logger.info("Recorded password change for user_id=%s tenant=%s", user_id, tenant)
    except Exception:
        conn.rollback()
        app_logger.exception("Failed recording password change for user_id=%s", user_id)
        raise
    finally:
        conn.close()
