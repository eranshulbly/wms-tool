# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from datetime import datetime, timezone, timedelta

import werkzeug

from .models import db, Warehouse, Company
from .services import order_service

from functools import wraps

from flask import request
from flask_restx import Api, Resource, fields,reqparse
import jwt

from .models import db, Users, JWTTokenBlocklist
from .config import BaseConfig
import requests

rest_api = Api(version="1.0", title="Users API")


"""
    Flask-Restx models for api request and response data
"""

signup_model = rest_api.model('SignUpModel', {"username": fields.String(required=True, min_length=2, max_length=32),
                                              "email": fields.String(required=True, min_length=4, max_length=64),
                                              "password": fields.String(required=True, min_length=4, max_length=16)
                                              })

login_model = rest_api.model('LoginModel', {"email": fields.String(required=True, min_length=4, max_length=64),
                                            "password": fields.String(required=True, min_length=4, max_length=16)
                                            })

user_edit_model = rest_api.model('UserEditModel', {"userID": fields.String(required=True, min_length=1, max_length=32),
                                                   "username": fields.String(required=True, min_length=2, max_length=32),
                                                   "email": fields.String(required=True, min_length=4, max_length=64)
                                                   })


"""
   Helper function for JWT token required
"""

def token_required(f):

    @wraps(f)
    def decorator(*args, **kwargs):

        token = None

        if "authorization" in request.headers:
            token = request.headers["authorization"]

        if not token:
            return {"success": False, "msg": "Valid JWT token is missing"}, 400

        try:
            data = jwt.decode(token, BaseConfig.SECRET_KEY, algorithms=["HS256"])
            current_user = Users.get_by_email(data["email"])

            if not current_user:
                return {"success": False,
                        "msg": "Sorry. Wrong auth token. This user does not exist."}, 400

            token_expired = db.session.query(JWTTokenBlocklist.id).filter_by(jwt_token=token).scalar()

            if token_expired is not None:
                return {"success": False, "msg": "Token revoked."}, 400

            if not current_user.check_jwt_auth_active():
                return {"success": False, "msg": "Token expired."}, 400

        except:
            return {"success": False, "msg": "Token is invalid"}, 400

        return f(current_user, *args, **kwargs)

    return decorator


"""
    Flask-Restx routes
"""


@rest_api.route('/api/users/register')
class Register(Resource):
    """
       Creates a new user by taking 'signup_model' input
    """

    @rest_api.expect(signup_model, validate=True)
    def post(self):

        req_data = request.get_json()

        _username = req_data.get("username")
        _email = req_data.get("email")
        _password = req_data.get("password")

        user_exists = Users.get_by_email(_email)
        if user_exists:
            return {"success": False,
                    "msg": "Email already taken"}, 400

        new_user = Users(username=_username, email=_email)

        new_user.set_password(_password)
        new_user.save()

        return {"success": True,
                "userID": new_user.id,
                "msg": "The user was successfully registered"}, 200


@rest_api.route('/api/users/login')
class Login(Resource):
    """
       Login user by taking 'login_model' input and return JWT token
    """

    @rest_api.expect(login_model, validate=True)
    def post(self):

        req_data = request.get_json()

        _email = req_data.get("email")
        _password = req_data.get("password")

        user_exists = Users.get_by_email(_email)

        # if not user_exists:
        #     return {"success": False,
        #             "msg": "This email does not exist."}, 400

        # if not user_exists.check_password(_password):
        #     return {"success": False,
        #             "msg": "Wrong credentials."}, 400

        # create access token uwing JWT
        # token = jwt.encode({'email': _email, 'exp': datetime.utcnow() + timedelta(minutes=30)}, BaseConfig.SECRET_KEY)
        token = "eyJhbGciOiAiSFMyNTYiLCJraWQiOiAiYXBpY2VydC1rZXkiLCAidHlwIjogIkpXVCJ9.eyJleHBpcnkiOiAiMjAyNS0wMS0wNVQxMjozMjo1Ni4wMDBaIiwibmFtZSI6ICJqb2huZG9lIiwic3ViIjogIjEyMzQ1Njc4OSIsImlhdCI6IDE2MjcwNTkzMDAwMDB9.Ojw8sFv84H4t7Z54lJtneEEHLy8MhG8g8Xy0jHk7uhtTYq0EFU0OOf_mDQ5yM6yyjrQPSGcBQwLX5hqp36-PmHjyfg"

        user_exists.set_jwt_auth_active(True)
        user_exists.save()

        return {"success": True,
                "token": token,
                "user": user_exists.toJSON()}, 200


@rest_api.route('/api/users/edit')
class EditUser(Resource):
    """
       Edits User's username or password or both using 'user_edit_model' input
    """

    @rest_api.expect(user_edit_model)
    @token_required
    def post(self, current_user):

        req_data = request.get_json()

        _new_username = req_data.get("username")
        _new_email = req_data.get("email")

        if _new_username:
            self.update_username(_new_username)

        if _new_email:
            self.update_email(_new_email)

        self.save()

        return {"success": True}, 200


@rest_api.route('/api/users/logout')
class LogoutUser(Resource):
    """
       Logs out User using 'logout_model' input
    """

    @token_required
    def post(self, current_user):

        _jwt_token = request.headers["authorization"]

        jwt_block = JWTTokenBlocklist(jwt_token=_jwt_token, created_at=datetime.now(timezone.utc))
        jwt_block.save()

        self.set_jwt_auth_active(False)
        self.save()

        return {"success": True}, 200


@rest_api.route('/api/warehouses')
class WarehouseList(Resource):
    """
    Endpoint for retrieving all warehouses
    """

    def get(self):
        """
        Get list of all warehouses
        """
        try:
            warehouses = Warehouse.query.all()
            warehouse_list = []

            for warehouse in warehouses:
                warehouse_list.append({
                    'id': warehouse.warehouse_id,
                    'name': warehouse.name,
                    'location': warehouse.location
                })

            return {
                'success': True,
                'warehouses': warehouse_list
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving warehouses: {str(e)}'
            }, 400

@rest_api.route('/api/companies')
class CompanyList(Resource):
    """
    Endpoint for retrieving all companies
    """

    def get(self):
        """
        Get list of all companies
        """
        try:
            companies = Company.query.all()
            company_list = []

            for company in companies:
                company_list.append({
                    'id': company.company_id,
                    'name': company.name
                })

            return {
                'success': True,
                'companies': company_list
            }, 200

        except Exception as e:
            return {
                'success': False,
                'msg': f'Error retrieving companies: {str(e)}'
            }, 400

# Define the request parser for file upload
upload_parser = reqparse.RequestParser()
upload_parser.add_argument('file',
                           type=werkzeug.datastructures.FileStorage,
                           location='files',
                           required=True,
                           help='Excel/CSV file with order data')
upload_parser.add_argument('warehouse_id',
                           type=int,
                           location='form',  # Add this line
                           required=True,
                           help='Warehouse ID must be provided')
upload_parser.add_argument('company_id',
                           type=int,
                           location='form',  # Add this line
                           required=True,
                           help='Company ID must be provided')

# Response model for order upload
order_upload_response = rest_api.model('OrderUploadResponse', {
    'success': fields.Boolean(description='Success status of upload'),
    'msg': fields.String(description='Message describing the result'),
    'orders_processed': fields.Integer(description='Number of orders processed'),
    'products_processed': fields.Integer(description='Number of products processed'),
    'errors': fields.List(fields.String, description='List of errors encountered')
})

@rest_api.route('/api/orders/upload')
class OrderUpload(Resource):
    """
    Handles the upload of Excel/CSV files containing order data
    """

    @rest_api.expect(upload_parser)
    @rest_api.response(200, 'Success', order_upload_response)
    @rest_api.response(400, 'Bad Request', order_upload_response)
    def post(self):
        # Parse the request arguments
        args = upload_parser.parse_args()
        uploaded_file = args['file']
        warehouse_id = args['warehouse_id']
        company_id = args['company_id']

        # Call the service layer to process the upload
        result, status_code = order_service.process_order_upload(
            uploaded_file,
            warehouse_id,
            company_id,
            123
        )

        return result, status_code