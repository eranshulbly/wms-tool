# -*- encoding: utf-8 -*-
"""
Flask extension instances.

Instantiated here (without an app) so any module can import them
without triggering circular imports. Bound to the app via init_app()
inside create_app() in __init__.py.
"""

from flask_restx import Api
from flask_cors import CORS

rest_api = Api(version="1.0", title="MySQL Warehouse Management API")
cors = CORS()
