"""
routes/users.py
----------------
GET  /users/details                (render profile page)
PUT  /api/v1/users/userdetails      (form-post, updates profile - method override via hidden _method field)
GET  /api/v1/users/dashboard        (renders the end-user dashboard; redirects admins to /admin/dashboard)
GET  /users/password-reset          (render password reset page)
PUT  /api/v1/users/password-reset   (form-post, changes the user's Cognito password)

All tenant scoping comes from g.tenant (set by @login_required from
the session identity resolved out of the validated JWT) -- never from
the request body.

Identity resolution is centralized in `_resolve_user_id()` below so
the *same* identifier is used everywhere a user's row is looked up or
written: dashboard, profile read, profile write, and password reset.
Previously different call sites could fall back to `username` in
subtly different ways; that drift is what allowed a profile save to
succeed against one identifier while reads happened against another.
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
    """Single source of truth for 'which identifier do we use to look
    up/write this user's row'. Prefers the Cognito `sub`-derived
    `user_id` claim; falls back to `username` only if `user_id` isn't
    present on the identity (e.g. an older session). Every route in
    this module must go through this helper instead of re-deriving
    the identifier inline."""
    user_id = identity.get("user_id") or identity.get("username")
    if not user_id:
        raise ValueError("Authenticated identity is missing both user_id and username.")
    return user_id


def _profile_completion(record: dict) -> int:
    """Computes a simple profile-completion percentage used by the
    progress bar on the profile page."""
    fields = ["username", "email", "phone", "department"]
    filled = sum(1 for f in fields if record.get(f))
    return int((filled / len(fields)) * 100)


@users_bp.route("/api/v1/users/dashboard", methods=["GET"])
@login_required
@profile_setup_required
def dashboard():
    if g.role == "admin":
        return redirect(url_for("admin.dashboard"))

    identity = session["identity"]
    user_id = _resolve_user_id(identity)
    record = get_user_by_id(g.tenant, user_id) or {}
    return render_template(
        "dashboard.html",
        identity=identity,
        record=record,
        profile_completion=_profile_completion(record),
    )


@users_bp.route("/users/details", methods=["GET"])
@login_required
def user_details_page():
    identity = session["identity"]
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
    """Handles the profile update form submission. HTML forms cannot
    natively send PUT, so this endpoint accepts POST and represents
    the PUT /api/v1/users/userdetails operation from the spec.

    This now performs a real upsert: if the authenticated user has no
    row yet in their tenant table (e.g. first-ever profile save), one
    is created; otherwise the existing row is updated. Both paths are
    verified to have actually affected a row before we report success
    -- a prior version of this handler could report "success" even
    when zero rows were written."""
    identity = session["identity"]
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
        # Keep the session's profile_complete flag in sync so
        # @profile_setup_required stops redirecting here on the very
        # next request, without requiring the user to log in again.
        identity["profile_complete"] = bool(phone and department)
        session["identity"] = identity
        flash("Profile updated successfully.", "success")

        # Success: leave /users/details for the role-appropriate
        # dashboard instead of redirecting back to the form page.
        next_endpoint = "admin.dashboard" if identity["role"] == "admin" else "users.dashboard"
        return redirect(url_for(next_endpoint))
    except Exception:
        app_logger.exception("Failed to update profile for user_id=%s", user_id)
        flash("Something went wrong while saving your profile. Please try again.", "danger")

    # Validation errors and save failures land back on the form so
    # the user can correct/retry.
    return redirect(url_for("users.user_details_page"))


@users_bp.route("/users/password-reset", methods=["GET"])
@login_required
def password_reset_page():
    return render_template("password_reset.html", identity=session["identity"])


@users_bp.route("/api/v1/users/password-reset", methods=["POST"])
@login_required
def password_reset_update():
    """Handles the "change my password" form submission. Represents
    PUT /api/v1/users/password-reset (accepted as POST for the same
    method-override-via-hidden-field reason as userdetails).

    Calls Cognito's change_password API directly against the user's
    own session access token, so a user can only ever change their
    own password. On success, also syncs password_last_changed /
    first_login on the RDS profile row so the UI reflects it without
    requiring a re-login."""
    identity = session["identity"]
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

    access_token = session.get("access_token")

    try:
        change_password(access_token, current_password, new_password)
        mark_password_changed(g.tenant, user_id)
        flash("Password updated successfully.", "success")
        return redirect(url_for("users.user_details_page"))
    except ValueError as e:
        # Expected, user-facing failure (wrong current password, weak
        # new password, expired session, etc.) -- message is already
        # safe to show as-is.
        flash(str(e), "danger")
    except Exception:
        app_logger.exception("Password reset failed for user_id=%s", user_id)
        flash("Something went wrong while resetting your password. Please try again.", "danger")

    return redirect(url_for("users.password_reset_page"))
