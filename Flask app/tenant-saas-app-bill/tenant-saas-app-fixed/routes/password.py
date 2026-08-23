"""
routes/password.py
--------------------
POST /api/v1/password/reset (form-post from the password reset page)
GET  /password/reset          (renders the page itself)

Renders HTML only -- never JSON, per project requirements.

This is a voluntary, self-service "Change Password" page (linked from
the sidebar/topbar in base.html), NOT the first-login forced password
change. That forced change ("New Password Required") is handled
entirely by Cognito's Hosted UI itself before the browser is ever
redirected back to /auth/callback -- see decorators.py's
profile_setup_required for why Flask no longer needs its own gate for
that. This page calls Cognito's real change_password API using the
access token stored in the session after the OAuth2 token exchange
(routes/auth_pages.py), which requires the user to already know their
current password -- exactly the Cognito change-password API contract.
"""

import re

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from decorators import login_required
from services.cognito_service import change_password
from config import config
from logging_config import app_logger

password_bp = Blueprint("password", __name__)

_PASSWORD_RULES = {
    "min_length": 10,
    "upper": re.compile(r"[A-Z]"),
    "lower": re.compile(r"[a-z]"),
    "digit": re.compile(r"\d"),
    "symbol": re.compile(r"[!@#$%^&*()_\-+=\[\]{};:'\",.<>/?]"),
}


def _password_errors(password: str, confirm: str) -> list:
    errors = []
    if len(password) < _PASSWORD_RULES["min_length"]:
        errors.append(f"Password must be at least {_PASSWORD_RULES['min_length']} characters long.")
    if not _PASSWORD_RULES["upper"].search(password):
        errors.append("Password must include at least one uppercase letter.")
    if not _PASSWORD_RULES["lower"].search(password):
        errors.append("Password must include at least one lowercase letter.")
    if not _PASSWORD_RULES["digit"].search(password):
        errors.append("Password must include at least one number.")
    if not _PASSWORD_RULES["symbol"].search(password):
        errors.append("Password must include at least one special character.")
    if password != confirm:
        errors.append("New password and confirmation do not match.")
    return errors


@password_bp.route("/password/reset", methods=["GET"])
@login_required
def reset_page():
    return render_template("password_reset.html", identity=session.get("identity"))


@password_bp.route("/api/v1/password/reset", methods=["POST"])
@login_required
def reset_submit():
    identity = session["identity"]
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    errors = _password_errors(new_password, confirm_password)
    if not current_password:
        errors.insert(0, "Current password is required.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template("password_reset.html", identity=identity)

    access_token = session.get("access_token", "")
    if not access_token and not config.DEMO_MODE:
        # Can genuinely happen for an old session cookie from before
        # this fix was deployed. Send them through a fresh login
        # rather than calling Cognito with an empty access token.
        app_logger.warning(
            "Password change attempted with no access_token in session for user_id=%s", identity.get("sub")
        )
        flash("Your session needs to be refreshed before changing your password. Please sign in again.", "warning")
        return redirect(url_for("auth_pages.login"))

    try:
        change_password(
            access_token=access_token,
            previous_password=current_password,
            proposed_password=new_password,
        )
        identity["password_reset_done"] = True
        identity["first_login"] = False
        session["identity"] = identity
        app_logger.info("Password changed", extra={"user_id": identity.get("sub"), "tenant": identity["tenant"]})
        flash("Your password has been updated successfully.", "success")
        if not identity.get("profile_complete"):
            return redirect(url_for("users.user_details_page"))
        if identity["role"] == "admin":
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("users.dashboard"))
    except Exception:
        app_logger.exception("Password change failed for user_id=%s", identity.get("sub"))
        flash("We couldn't update your password. Please check your current password and try again.", "danger")
        return render_template("password_reset.html", identity=identity)
