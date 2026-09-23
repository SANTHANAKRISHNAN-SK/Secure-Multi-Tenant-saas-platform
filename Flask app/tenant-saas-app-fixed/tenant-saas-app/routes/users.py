"""
routes/users.py
----------------
GET  /users/details                (render profile page)
PUT  /api/v1/users/userdetails      (form-post, updates profile)
GET  /api/v1/users/dashboard        (renders user dashboard)
GET  /users/password-reset          (render password reset page)
PUT  /api/v1/users/password-reset   (form-post, changes user password)
"""

from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g

from decorators import login_required, profile_setup_required
from services.rds_service import get_user_by_id, upsert_user_profile, mark_password_changed
from services.kms_service import encrypt_field, decrypt_field
from services.cognito_service import change_password
from logging_config import app_logger

users_bp = Blueprint("users", __name__)


def _resolve_user_id(identity: dict) -> str:
    user_id = identity.get("user_id") or identity.get("username")
    if not user_id:
        raise ValueError("Authenticated identity is missing both user_id and username.")
    return user_id


def _profile_completion(record: dict) -> int:
    fields = ["username", "email", "phone", "department"]
    filled = sum(1 for f in fields if record.get(f))
    return int((filled / len(fields)) * 100)


def _get_current_identity() -> dict:
    return session.get("identity") or getattr(g, "identity", {})


def _wants_json() -> bool:
    """True only for genuine API callers, never for a browser page load.

    Behind CloudFront -> API Gateway (Cognito authorizer) every browser
    request also carries an `Authorization` header, so that header alone
    can no longer be used to detect an API client -- doing so made every
    redirect that lands on /api/v1/users/dashboard (post-login,
    profile save, password change, the sidebar link) render raw JSON.

    - `Accept: application/json` is always honoured (unchanged).
    - A bearer token without a browser signal still gets JSON
      (unchanged for programmatic clients).
    - A browser signal (a Flask session identity, or `text/html` in the
      Accept header) means "render the page".
    """
    accept = request.headers.get("Accept", "")
    if accept == "application/json":
        return True
    is_browser = bool(session.get("identity")) or "text/html" in accept
    return bool(request.headers.get("Authorization")) and not is_browser


@users_bp.route("/api/v1/users/dashboard", methods=["GET"])
@login_required
@profile_setup_required
def dashboard():
    if g.role == "admin":
        return redirect(url_for("admin.dashboard"))

    identity = _get_current_identity()
    user_id = _resolve_user_id(identity)
    record = get_user_by_id(g.tenant, user_id) or {}
    
    if _wants_json():
        return {
            "status": "success",
            "identity": identity,
            "record": record
        }, 200

    return render_template(
        "dashboard.html",
        identity=identity,
        record=record,
        profile_completion=_profile_completion(record),
    )


@users_bp.route("/users/details", methods=["GET"])
@login_required
def user_details_page():
    identity = _get_current_identity()
    user_id = _resolve_user_id(identity)
    record = get_user_by_id(g.tenant, user_id) or {}
    phone = record.get("phone") or ""
    if phone.startswith("demo-enc:") or phone.startswith("enc:"):
        record = dict(record)
        record["phone"] = decrypt_field(phone)
    return render_template(
        "user_profile.html",
        identity=identity,
        record=record,
        profile_completion=_profile_completion(record),
    )


@users_bp.route("/api/v1/users/userdetails", methods=["POST"])
@login_required
def user_details_update():
    identity = _get_current_identity()
    try:
        user_id = _resolve_user_id(identity)
    except ValueError:
        app_logger.exception("Missing identity while updating profile")
        flash("Your session is invalid. Please log in again.", "danger")
        return redirect(url_for("auth.login"))

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    department = request.form.get("department", "").strip()

    errors = []
    if not name:
        errors.append("Name is required.")
    if "@" not in email or "." not in email:
        errors.append("Please enter a valid email address.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("users.user_details_page"))

    try:
        upsert_user_profile(
            g.tenant,
            user_id,
            {
                "username": name,
                "email": email,
                "phone": encrypt_field(phone),
                "department": department,
            },
            role=identity.get("role", "user"),
        )
        identity["profile_complete"] = bool(phone and department)
        if "identity" in session:
            session["identity"] = identity
        flash("Profile updated successfully.", "success")

        next_endpoint = "admin.dashboard" if identity["role"] == "admin" else "users.dashboard"
        return redirect(url_for(next_endpoint))
    except Exception:
        app_logger.exception("Failed to update profile for user_id=%s", user_id)
        flash("Something went wrong while saving your profile. Please try again.", "danger")

    return redirect(url_for("users.user_details_page"))


@users_bp.route("/users/password-reset", methods=["GET"])
@login_required
def password_reset_page():
    return render_template("password_reset.html", identity=_get_current_identity())


@users_bp.route("/api/v1/users/password-reset", methods=["POST"])
@login_required
def password_reset_update():
    identity = _get_current_identity()
    try:
        user_id = _resolve_user_id(identity)
    except ValueError:
        app_logger.exception("Missing identity during password reset")
        flash("Your session is invalid. Please log in again.", "danger")
        return redirect(url_for("auth.login"))

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if new_password != confirm_password:
        flash("New password and confirmation do not match.", "danger")
        return redirect(url_for("users.password_reset_page"))

    access_token = session.get("access_token") or request.headers.get("Authorization", "").replace("Bearer ", "")

    try:
        change_password(access_token, current_password, new_password)
        mark_password_changed(g.tenant, user_id)
        flash("Password updated successfully.", "success")
        return redirect(url_for("users.user_details_page"))
    except ValueError as e:
        flash(str(e), "danger")
    except Exception:
        app_logger.exception("Password reset failed for user_id=%s", user_id)
        flash("Something went wrong while resetting your password. Please try again.", "danger")

    return redirect(url_for("users.password_reset_page"))