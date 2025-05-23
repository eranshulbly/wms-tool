# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

import os, json

from flask import Flask
from flask_cors import CORS

from .routes import rest_api
from .models import db
# Import dashboard routes to register them with rest_api
from . import dashboard_routes

app = Flask(__name__)

app.config.from_object('api.config.BaseConfig')

db.init_app(app)
rest_api.init_app(app)
CORS(app)

# Setup database
@app.before_request
def initialize_database():
    try:
        db.create_all()
    except Exception as e:

        print('> Error: DBMS Exception: ' + str(e) )

        # fallback to SQLite
        BASE_DIR = os.path.abspath(os.path.dirname(__file__))
        app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'db.sqlite3')

        print('> Fallback to SQLite ')
        db.create_all()

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