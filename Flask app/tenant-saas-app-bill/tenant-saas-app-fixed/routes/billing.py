"""
routes/billing.py
------------------
GET /billing                    (render the Billing Dashboard page)
GET /api/v1/billing/usage       (JSON: current period usage + invoice math)
GET /api/v1/billing/invoices    (JSON: invoice history)

Tenant scope for every route here comes exclusively from g.tenant,
which decorators.py's @login_required sets from the server-side
session identity resolved out of the validated Cognito JWT. None of
these routes accept, read, or honor a client-supplied tenant_id --
there is no ?tenant_id= query param handling anywhere in this file,
so a request for another tenant's billing data is not just denied,
it's structurally impossible: the tenant identifier used for every
DynamoDB Query is always g.tenant, never anything from request.args.

An optional ?period=YYYY-MM query param is accepted for the JSON
endpoints (to look up a past billing period), but it only selects
*which month* to look up within the caller's own tenant partition --
it can never change *whose* data is returned.
"""

from flask import Blueprint, render_template, request, jsonify, g

from decorators import login_required
from services.billing_service import calculate_invoice, get_invoices, current_billing_period
from logging_config import app_logger

billing_bp = Blueprint("billing", __name__)


@billing_bp.route("/billing", methods=["GET"])
@login_required
def dashboard():
    period = request.args.get("period", "").strip() or current_billing_period()
    invoice = calculate_invoice(g.tenant, period)
    invoices = get_invoices(g.tenant, limit=12)
    return render_template(
        "billing_dashboard.html",
        invoice=invoice,
        invoices=invoices,
        current_period=current_billing_period(),
    )


@billing_bp.route("/api/v1/billing/usage", methods=["GET"])
@login_required
def usage():
    period = request.args.get("period", "").strip() or current_billing_period()
    invoice = calculate_invoice(g.tenant, period)
    app_logger.info("Billing usage viewed", extra={"tenant": g.tenant, "path": request.path})
    return jsonify({
        "tenant_id": invoice["tenant_id"],
        "billing_period": invoice["billing_period"],
        "plan": invoice["plan_display_name"],
        "included_requests": invoice["included_requests"],
        "usage_units": invoice["usage_units"],
        "overage_units": invoice["overage_units"],
    })


@billing_bp.route("/api/v1/billing/invoices", methods=["GET"])
@login_required
def invoices():
    app_logger.info("Billing invoices viewed", extra={"tenant": g.tenant, "path": request.path})
    return jsonify({
        "tenant_id": g.tenant,
        "invoices": get_invoices(g.tenant, limit=12),
    })
