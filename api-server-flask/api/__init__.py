# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

import os, json
import pymysql

from flask import Flask
from flask_cors import CORS

from .routes import rest_api
from .models import db
# Import dashboard routes to register them with rest_api
from . import dashboard_routes

# Install PyMySQL as MySQLdb for compatibility
pymysql.install_as_MySQLdb()

app = Flask(__name__)

app.config.from_object('api.config.BaseConfig')

db.init_app(app)
rest_api.init_app(app)
CORS(app)


# Initialize database at startup
def initialize_database():
    """Initialize database tables with MySQL support"""
    try:
        with app.app_context():
            print("🔄 Attempting to connect to MySQL database...")

            # Test database connection
            try:
                # Try to execute a simple query to test connection
                result = db.engine.execute('SELECT 1 as test')
                print("✅ MySQL database connection successful!")
                result.close()
            except Exception as conn_error:
                print(f"❌ MySQL connection failed: {str(conn_error)}")
                raise conn_error

            print("🔄 Creating database tables...")
            db.create_all()
            print("✅ MySQL database tables created successfully!")

            # Verify tables were created
            inspector = db.inspect(db.engine)
            tables = inspector.get_table_names()
            print(f"📊 Created tables: {', '.join(tables)}")

    except Exception as e:
        print(f'❌ Error: MySQL Database Exception: {str(e)}')
        print("🔄 Attempting fallback to SQLite...")

        # fallback to SQLite
        BASE_DIR = os.path.abspath(os.path.dirname(__file__))
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'db.sqlite3')
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {}

        print('⚠️  Fallback to SQLite database')
        with app.app_context():
            try:
                db.create_all()
                print("✅ SQLite database tables created successfully!")
            except Exception as sqlite_error:
                print(f"❌ SQLite fallback also failed: {str(sqlite_error)}")
                raise sqlite_error


# Call initialization function
initialize_database()


# Enhanced before_request for MySQL connection management
@app.before_request
def check_database():
    """Ensure database connection is healthy before each request"""
    try:
        # This is a lightweight check for MySQL connection health
        if 'mysql' in app.config.get('SQLALCHEMY_DATABASE_URI', ''):
            # For MySQL, we can use a simple ping
            db.engine.execute('SELECT 1')
    except Exception as e:
        print(f'⚠️  Database connection issue detected: {str(e)}')
        # Let the application handle the error naturally
        pass


"""
   Custom responses
"""


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