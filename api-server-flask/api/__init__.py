# -*- encoding: utf-8 -*-
"""
MySQL-only Flask Application Initialization
Copyright (c) 2019 - present AppSeed.us
"""

import json
from flask import Flask
from flask_cors import CORS

from .routes import rest_api
from .db_manager import initialize_database
# Import dashboard routes to register them with rest_api
from . import dashboard_routes

app = Flask(__name__)

# Load configuration
app.config.from_object('api.config.BaseConfig')

# Initialize Flask-RESTX
rest_api.init_app(app)

# Enable CORS
CORS(app)

# Initialize MySQL database at startup
try:
    initialize_database()
    print("✅ MySQL database initialized successfully!")
except Exception as e:
    print(f"❌ Failed to initialize MySQL database: {str(e)}")
    raise e


# Custom error handlers
@app.after_request
def after_request(response):
    """
    Sends back a custom error with {"success", "msg"} format
    """
    if int(response.status_code) >= 400:
        try:
            response_data = json.loads(response.get_data())
            if "errors" in response_data:
                response_data = {"success": False,
                                 "msg": response_data["errors"]}
                response.set_data(json.dumps(response_data))
            response.headers.add('Content-Type', 'application/json')
        except json.JSONDecodeError:
            # Handle non-JSON responses
            response_data = {"success": False, "msg": "An error occurred"}
            response.set_data(json.dumps(response_data))
            response.headers.add('Content-Type', 'application/json')
    return response


# Health check endpoint
@app.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        from .db_manager import mysql_manager
        # Test database connection
        with mysql_manager.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1 as test')
                result = cursor.fetchone()

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


# Database status endpoint
@app.route('/api/status')
def api_status():
    """API status endpoint with database info"""
    try:
        from .db_manager import mysql_manager
        from .models import Warehouse, Company, PotentialOrder

        # Test database and get basic stats
        warehouses_count = len(Warehouse.get_all())
        companies_count = len(Company.get_all())

        # Get order counts by status
        status_counts = {}
        for status in ['Open', 'Picking', 'Packing', 'Dispatch Ready', 'Completed', 'Partially Completed']:
            status_counts[status.lower().replace(' ', '_')] = PotentialOrder.count_by_status(status)

        return {
            "status": "operational",
            "database": "MySQL",
            "connection": "active",
            "stats": {
                "warehouses": warehouses_count,
                "companies": companies_count,
                "orders_by_status": status_counts
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