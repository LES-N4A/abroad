"""Health check endpoint for monitoring."""
from flask import Blueprint, jsonify, current_app
from db import get_db

health_bp = Blueprint("health", __name__)


@health_bp.route("/health")
def health_check():
    """
    Health check endpoint for load balancers and monitoring.

    Returns:
        200 if all systems operational
        503 if any critical system is down
    """
    checks = {
        "status": "healthy",
        "timestamp": current_app.config.get("START_TIME", "unknown"),
        "checks": {}
    }

    # Check database
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        checks["checks"]["database"] = "ok"
    except Exception as e:
        checks["status"] = "unhealthy"
        checks["checks"]["database"] = f"error: {str(e)}"

    # Check Redis (only when Redis is actually enabled)
    if current_app.config.get("ENABLE_REDIS"):
        try:
            import redis
            r = redis.from_url(current_app.config["REDIS_URL"])
            r.ping()
            checks["checks"]["redis"] = "ok"
        except Exception as e:
            checks["status"] = "unhealthy"
            checks["checks"]["redis"] = f"error: {str(e)}"

    # Check Celery (only when Redis, and therefore the broker, is enabled)
    if current_app.config.get("ENABLE_REDIS") and current_app.config.get("CELERY_BROKER_URL"):
        try:
            from tasks import celery
            celery.control.ping(timeout=1)
            checks["checks"]["celery"] = "ok"
        except Exception as e:
            checks["checks"]["celery"] = f"warning: {str(e)}"

    # Return appropriate status code
    status_code = 200 if checks["status"] == "healthy" else 503

    return jsonify(checks), status_code


@health_bp.route("/health/ready")
def readiness_check():
    """Kubernetes readiness probe."""
    return jsonify({"status": "ready"}), 200


@health_bp.route("/health/live")
def liveness_check():
    """Kubernetes liveness probe."""
    return jsonify({"status": "alive"}), 200
