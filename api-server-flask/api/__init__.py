# -*- encoding: utf-8 -*-
"""
MySQL-only Flask Application Initialization
Copyright (c) 2019 - present AppSeed.us
"""

import json
import logging
import os

from flask import Flask, request

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

    # Stop Flask-RESTX appending `str(exception)` to error bodies as `message`. It does
    # this by default, INDEPENDENTLY of DEBUG, and it merges on top of whatever an error
    # handler returns — so a 500 shipped the raw exception text to the client (the
    # KeyError that broke the dealer screen went out as {"message": "'username'"}, and a
    # failing query would send its SQL and column names the same way). The client gets
    # the handler's safe wording; the detail goes to the log. HTTPException descriptions
    # are unaffected: handle_unexpected_error passes those through deliberately.
    app.config['ERROR_INCLUDE_MESSAGE'] = False

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

    # Wire event-bus subscriptions (assignment reacts to inventory/order events).
    from .modules.fulfillment.assignment.handlers import register_handlers
    register_handlers()

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
    # The two clients read different keys, and an error body in the wrong shape is an
    # error the user never sees: the Flutter app reads `detail` and otherwise falls back
    # to rendering a bare "HTTP 500", while the React UI reads `msg`. Which one is asking
    # is decided by the path, so neither contract has to change.
    from .extensions import rest_api

    _V1_PREFIX = '/api/v1/'

    def _error_body(text, path):
        return ({"detail": text} if str(path).startswith(_V1_PREFIX)
                else {"success": False, "msg": text})

    @rest_api.errorhandler(Exception)
    def handle_unexpected_error(error):
        """Last resort for an exception no route handled.

        Without this, Flask-RESTX renders `{"message": "Internal Server Error"}` — no
        `detail`, so the mobile app could only show "HTTP 500" with no clue what broke,
        and the user's report was indistinguishable from a timeout. The exception itself
        is deliberately NOT sent to the client (it can carry SQL and column names); it
        goes to the log, with the route, so the two can be matched up afterwards.
        """
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            # 404/405/413/... already carry a meaningful, safe description.
            return _error_body(error.description, request.path), error.code
        _startup_logger.exception(
            "Unhandled exception on %s %s", request.method, request.path,
            extra={'path': request.path, 'method': request.method})
        return _error_body("Something went wrong on the server.", request.path), 500

    @app.after_request
    def after_request(response):
        """Normalise error bodies to whichever shape the caller's client understands."""
        if int(response.status_code) >= 400:
            path = request.path
            try:
                response_data = json.loads(response.get_data())
                # Flask-RESTX puts request-validation failures under `errors`, and its
                # own aborts under `message` — neither key is one the mobile app reads.
                if isinstance(response_data, dict) and "detail" not in response_data:
                    if "errors" in response_data:
                        response.set_data(json.dumps(
                            _error_body(response_data["errors"], path)))
                    elif "message" in response_data and path.startswith(_V1_PREFIX):
                        response.set_data(json.dumps(
                            _error_body(response_data["message"], path)))
                response.headers['Content-Type'] = 'application/json'
            except (json.JSONDecodeError, UnicodeDecodeError):
                # A non-JSON error body (Flask's HTML 404/405 pages) would otherwise
                # reach the client as markup it cannot parse.
                response.set_data(json.dumps(_error_body("An error occurred", path)))
                response.headers['Content-Type'] = 'application/json'
        return response


def _register_utility_routes(app: Flask) -> None:
    from .modules.fulfillment.order.constants import OrderStatus

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
