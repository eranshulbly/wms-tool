# -*- encoding: utf-8 -*-
"""
Order Upload API routes
"""

from flask_restx import Resource, Namespace, fields, reqparse, Api
import werkzeug
from flask_restx import Resource
from .models import db, Warehouse, Company

from .services import order_service
from .routes import token_required, rest_api

@rest_api.route('/test')
def test_route():
    return {
                'success': True,
                'companies': "Test Endpoint Worked."
            }, 200