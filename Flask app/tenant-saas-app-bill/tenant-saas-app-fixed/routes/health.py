"""
routes/health.py
-----------------
GET /api/v1/health

The ONLY endpoint in the entire application permitted to return a raw
JSON response. Used by the Application Load Balancer's target group
health check and by ECS Fargate's container health check.
"""

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.route("/api/v1/health", methods=["GET"])
def health():
    """Lightweight liveness check. Deliberately avoids touching RDS or
    any external AWS service so that a transient dependency outage
    does not flap the ALB's health check and cause unnecessary task
    replacement."""
    return jsonify({"status": "healthy"}), 200
