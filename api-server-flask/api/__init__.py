# -*- encoding: utf-8 -*-
"""
MySQL-only Flask Application Initialization
Copyright (c) 2019 - present AppSeed.us
"""

import json
import logging
import os

from flask import Flask

_startup_logger = logging.getLogger(__name__)


def create_app(config_override: dict = None) -> Flask:
    """
    Application factory.

    Args:
        config_override: Optional dict of config values to overlay on top of the
                         environment-based config. Useful for testing.

    Returns:
        A configured Flask application instance.
    """
    app = Flask(__name__, template_folder='templates')

    # Load environment-specific configuration
    from .config import get_config
    app.config.from_object(get_config())

    # Flask sessions need a fixed secret key (used by Flask-Admin login)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'AnshulWMSSecretKey2024')

    if config_override:
        app.config.update(config_override)

    # Configure structured logging (must come before any logger calls)
    from .core.logging import configure_logging
    configure_logging(app)

    # Import rest_api from extensions (the canonical singleton) and
    # register all routes so @rest_api.route() decorators fire.
    from .extensions import rest_api
    from .routes import register_all_routes
    register_all_routes()
    rest_api.init_app(app)

    # Enable CORS
    from flask_cors import CORS
    CORS(app)

    # Initialize MySQL connection pool and create tables
    from .db_manager import initialize_database
    try:
        initialize_database()
        _startup_logger.info("MySQL database initialized successfully")
    except Exception as e:
        _startup_logger.critical("Failed to initialize MySQL database", exc_info=True)
        raise e

    # Initialize Flask-Admin
    from .admin import init_admin
    init_admin(app)

    # Register error handlers and utility endpoints
    _register_error_handlers(app)
    _register_utility_routes(app)

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.after_request
    def after_request(response):
        """Normalise error responses to {"success": false, "msg": "..."} shape."""
        if int(response.status_code) >= 400:
            try:
                response_data = json.loads(response.get_data())
                if "errors" in response_data:
                    response_data = {"success": False, "msg": response_data["errors"]}
                    response.set_data(json.dumps(response_data))
                response.headers.add('Content-Type', 'application/json')
            except json.JSONDecodeError:
                response_data = {"success": False, "msg": "An error occurred"}
                response.set_data(json.dumps(response_data))
                response.headers.add('Content-Type', 'application/json')
        return response


def _register_utility_routes(app: Flask) -> None:
    from .constants.order_states import OrderStatus

    @app.route('/health')
    def health_check():
        """Health check endpoint."""
        try:
            from .db_manager import mysql_manager
            with mysql_manager.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute('SELECT 1 as test')
                    cursor.fetchone()
            return {
                "status": "healthy",
                "database": "connected",
                "message": "MySQL warehouse management API is running"
            }, 200
        except Exception as e:
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e)
            }, 500

    @app.route('/api/status')
    def api_status():
        """API status endpoint with database info."""
        try:
            from .models import Warehouse, Company, PotentialOrder
            warehouses_count = len(Warehouse.get_all())
            companies_count = len(Company.get_all())
            status_counts = {
                s.to_frontend_slug().replace('-', '_'): PotentialOrder.count_by_status(s.value)
                for s in OrderStatus
            }
            return {
                "status": "operational",
                "database": "MySQL",
                "connection": "active",
                "stats": {
                    "warehouses": warehouses_count,
                    "companies": companies_count,
                    "orders_by_status": status_counts,
                },
                "version": "2.0.0-mysql"
            }, 200
        except Exception as e:
            return {
                "status": "error",
                "database": "MySQL",
                "connection": "failed",
                "error": str(e)
            }, 500

    @app.route('/api/version')
    def api_version():
        """Returns current deployed version and environment."""
        return {
            "version": os.getenv('APP_VERSION', '1.0.0'),
            "env":     os.getenv('APP_ENV', 'production'),
        }, 200


# Module-level app instance so `gunicorn api:app` continues to work unchanged.
app = create_app()
