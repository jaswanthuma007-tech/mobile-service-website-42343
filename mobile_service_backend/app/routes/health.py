from flask_smorest import Blueprint
from flask.views import MethodView

blp = Blueprint("Health Check", "health_check", url_prefix="/", description="Health check routes")


@blp.route("/")
class RootHealthCheck(MethodView):
    """Legacy health check endpoint (kept for compatibility)."""

    def get(self):
        return {"message": "Healthy"}


@blp.route("/health")
class Health(MethodView):
    """Health check endpoint (required)."""

    def get(self):
        return {"status": "ok"}, 200
