"""
routes/admin.py
-----------------
GET    /api/v1/admin/dashboard     - admin dashboard + user management table
POST   /api/v1/admin/users         - create a new user (Cognito + RDS)
DELETE /api/v1/admin/users/<id>    - remove/deactivate a user (form-post w/ method override)
POST   /api/v1/admin/users/<id>/toggle - enable/disable a user

Every function here is @admin_required, which also enforces
@login_required. Tenant scope (g.tenant) always comes from the
session identity resolved from the validated JWT.
"""

import uuid

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session

from decorators import admin_required
from services.rds_service import list_users, create_user_record, delete_user_record, set_user_enabled
from services.cognito_service import create_cognito_user, delete_cognito_user, set_user_enabled as cognito_set_enabled
from logging_config import app_logger

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/api/v1/admin/dashboard", methods=["GET"])
@admin_required
def dashboard():
    search = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    data = list_users(g.tenant, search=search, page=page, page_size=8)
    return render_template(
        "admin_dashboard.html",
        tenant=g.tenant,
        search=search,
        data=data,
        identity=session.get("identity"),
    )


@admin_bp.route("/manage-users", methods=["GET"])
@admin_required
def manage_users_page():
    search = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    data = list_users(g.tenant, search=search, page=page, page_size=8)
    return render_template(
        "manage_users.html", tenant=g.tenant, search=search, data=data, identity=session.get("identity")
    )


@admin_bp.route("/api/v1/admin/users", methods=["POST"])
@admin_required
def create_user():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    role = request.form.get("role", "user").strip()
    user_id = request.form.get("user_id", "").strip() or str(uuid.uuid4())[:8]

    errors = []
    if not username:
        errors.append("Username is required.")
    if "@" not in email or "." not in email:
        errors.append("Please enter a valid email address.")
    if role not in ("admin", "user"):
        errors.append("Role must be either admin or user.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("admin.manage_users_page"))

    try:
        cognito_result = create_cognito_user(username=username, email=email, tenant=g.tenant, role=role)
        create_user_record(g.tenant, user_id=user_id, username=username, email=email, role=role)
        app_logger.info(
            "Admin created new user",
            extra={"tenant": g.tenant, "user_id": user_id, "role": role},
        )
        return render_template(
            "create_user.html",
            success=True,
            username=username,
            email=email,
            role=role,
            user_id=user_id,
            tenant=g.tenant,
            temp_password=cognito_result["temp_password"],
            identity=session.get("identity"),
        )
    except Exception:
        app_logger.exception("Failed to create user '%s'", username)
        flash("We couldn't create that user. Please try again.", "danger")
        return redirect(url_for("admin.manage_users_page"))


@admin_bp.route("/api/v1/admin/users/<user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    hard_delete = request.form.get("hard_delete") == "true"
    username = request.form.get("username", user_id)
    try:
        delete_cognito_user(username)
        delete_user_record(g.tenant, user_id, hard_delete=hard_delete)
        app_logger.info(
            "Admin deleted/deactivated user",
            extra={"tenant": g.tenant, "user_id": user_id},
        )
        flash(f"User '{username}' was successfully removed.", "success")
    except Exception:
        app_logger.exception("Failed to delete user_id=%s", user_id)
        flash("We couldn't remove that user. Please try again.", "danger")
    return redirect(url_for("admin.manage_users_page"))


@admin_bp.route("/api/v1/admin/users/<user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    enable = request.form.get("enable") == "true"
    username = request.form.get("username", user_id)
    try:
        cognito_set_enabled(username, enable)
        set_user_enabled(g.tenant, user_id, enable)
        flash(f"User '{username}' has been {'enabled' if enable else 'disabled'}.", "success")
    except Exception:
        app_logger.exception("Failed to toggle enabled state for user_id=%s", user_id)
        flash("We couldn't update that user's status. Please try again.", "danger")
    return redirect(url_for("admin.manage_users_page"))
