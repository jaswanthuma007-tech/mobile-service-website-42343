import os

from flask import Flask
from flask_cors import CORS
from flask_smorest import Api

from . import db
from .routes.api import blp as api_blp
from .routes.admin_tracking import blp as admin_tracking_blp
from .routes.health import blp as health_blp


app = Flask(__name__)
app.url_map.strict_slashes = False

# Initialize DB layer at startup.
# With Supabase/Postgres, this validates configuration and performs best-effort seeding.
db.init_schema()

# CORS: Prefer explicit allowed origins from env (comma-separated), fallback to '*'.
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*")
origins = [o.strip() for o in allowed_origins.split(",")] if allowed_origins != "*" else "*"
CORS(app, resources={r"/*": {"origins": origins}})

# OpenAPI/Swagger configuration (served at /docs)
app.config["API_TITLE"] = "Mobile Service Backend API"
app.config["API_VERSION"] = "v1"
app.config["OPENAPI_VERSION"] = "3.0.3"
app.config["OPENAPI_URL_PREFIX"] = "/docs"
app.config["OPENAPI_SWAGGER_UI_PATH"] = ""
app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"

api = Api(app)
api.register_blueprint(health_blp)
api.register_blueprint(api_blp)
api.register_blueprint(admin_tracking_blp)
