# -*- encoding: utf-8 -*-
"""
Fixed Authentication Routes for Flask API
"""

from datetime import datetime, timezone
from functools import wraps
from flask import request, jsonify
from flask_restx import Api, Resource, fields
import jwt
from .config import BaseConfig
from .models import Users, JWTTokenBlocklist, mysql_manager
from .db_manager import partition_filter

# Create a separate auth API namespace
auth_api = Api(version="1.0", title="Authentication API")

# Models for request/response validation
signup_model = auth_api.model('SignUpModel', {
    "username": fields.String(required=True, min_length=2, max_length=32),
    "email": fields.String(required=True, min_length=4, max_length=64),
    "password": fields.String(required=True, min_length=4, max_length=16)
})

login_model = auth_api.model('LoginModel', {
    "email": fields.String(required=True, min_length=4, max_length=64),
    "password": fields.String(required=True, min_length=4, max_length=16)
})

# Response models
auth_response = auth_api.model('AuthResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg': fields.String(description='Response message'),
    'token': fields.String(description='JWT token'),
    'user': fields.Raw(description='User information')
})

error_response = auth_api.model('ErrorResponse', {
    'success': fields.Boolean(description='Success status'),
    'msg': fields.String(description='Error message')
})


def token_required(f):
    """Enhanced JWT token validation decorator"""

    @wraps(f)
    def decorator(*args, **kwargs):
        token = None

        # Get token from Authorization header
        if "authorization" in request.headers:
            auth_header = request.headers["authorization"]
            try:
                # Handle "Bearer <token>" format
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
                else:
                    token = auth_header
            except IndexError:
                return {"success": False, "msg": "Invalid token format"}, 400

        if not token:
            return {"success": False, "msg": "Valid JWT token is missing"}, 401

        try:
            # Decode the token
            data = jwt.decode(token, BaseConfig.JWT_SECRET_KEY, algorithms=["HS256"])

            # Get user from database
            current_user = Users.get_by_email(data["email"])
            if not current_user:
                return {"success": False, "msg": "User not found"}, 401

            # Check if token is blocklisted
            pf_sql, pf_params = partition_filter('jwt_token_blocklist')
            blocked_token = mysql_manager.execute_query(
                f"SELECT id FROM jwt_token_blocklist WHERE jwt_token = %s AND {pf_sql}",
                (token, *pf_params)
            )
            if blocked_token:
                return {"success": False, "msg": "Token has been revoked"}, 401

            # Check if user's JWT auth is still active
            if not current_user.check_jwt_auth_active():
                return {"success": False, "msg": "Token expired"}, 401

        except jwt.ExpiredSignatureError:
            return {"success": False, "msg": "Token has expired"}, 401
        except jwt.InvalidTokenError:
            return {"success": False, "msg": "Token is invalid"}, 401
        except Exception as e:
            return {"success": False, "msg": f"Token validation failed: {str(e)}"}, 401

        return f(current_user, *args, **kwargs)

    return decorator


@auth_api.route('/api/auth/register')
class Register(Resource):
    """User registration endpoint"""

    @auth_api.expect(signup_model, validate=True)
    @auth_api.response(200, 'Success', auth_response)
    @auth_api.response(400, 'Bad Request', error_response)
    def post(self):
        """Register a new user"""
        try:
            req_data = request.get_json()

            _username = req_data.get("username", "").strip()
            _email = req_data.get("email", "").strip().lower()
            _password = req_data.get("password", "")

            # Validate input
            if not _username or not _email or not _password:
                return {
                    "success": False,
                    "msg": "Username, email, and password are required"
                }, 400

            if len(_username) < 2:
                return {
                    "success": False,
                    "msg": "Username must be at least 2 characters long"
                }, 400

            if len(_password) < 4:
                return {
                    "success": False,
                    "msg": "Password must be at least 4 characters long"
                }, 400

            # Check if user already exists
            existing_user = Users.get_by_email(_email)
            if existing_user:
                return {
                    "success": False,
                    "msg": "Email already registered"
                }, 400

            # Check if username exists
            existing_username = Users.get_by_username(_username)
            if existing_username:
                return {
                    "success": False,
                    "msg": "Username already taken"
                }, 400

            # Create new user
            new_user = Users(
                username=_username,
                email=_email,
                date_joined=datetime.utcnow()
            )
            new_user.set_password(_password)
            new_user.save()

            return {
                "success": True,
                "msg": "User registered successfully",
                "user": {
                    "id": new_user.id,
                    "username": new_user.username,
                    "email": new_user.email
                }
            }, 200

        except Exception as e:
            return {
                "success": False,
                "msg": f"Registration failed: {str(e)}"
            }, 400


@auth_api.route('/api/auth/login')
class Login(Resource):
    """User login endpoint"""

    @auth_api.expect(login_model, validate=True)
    @auth_api.response(200, 'Success', auth_response)
    @auth_api.response(400, 'Bad Request', error_response)
    def post(self):
        """Authenticate user and return JWT token"""
        try:
            req_data = request.get_json()

            _email = req_data.get("email", "").strip().lower()
            _password = req_data.get("password", "")

            # Validate input
            if not _email or not _password:
                return {
                    "success": False,
                    "msg": "Email and password are required"
                }, 400

            # Find user by email
            user = Users.get_by_email(_email)
            if not user:
                return {
                    "success": False,
                    "msg": "Invalid email or password"
                }, 400

            # Check password
            if not user.check_password(_password):
                return {
                    "success": False,
                    "msg": "Invalid email or password"
                }, 400

            # Create JWT token
            token_payload = {
                'email': user.email,
                'user_id': user.id,
                'username': user.username,
                'exp': datetime.utcnow() + BaseConfig.JWT_ACCESS_TOKEN_EXPIRES,
                'iat': datetime.utcnow()
            }

            token = jwt.encode(token_payload, BaseConfig.JWT_SECRET_KEY, algorithm='HS256')

            # Activate JWT auth for user
            user.set_jwt_auth_active(True)
            user.save()

            return {
                "success": True,
                "msg": "Login successful",
                "token": token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email
                }
            }, 200

        except Exception as e:
            return {
                "success": False,
                "msg": f"Login failed: {str(e)}"
            }, 400


@auth_api.route('/api/auth/logout')
class Logout(Resource):
    """User logout endpoint"""

    @auth_api.response(200, 'Success')
    @auth_api.response(401, 'Unauthorized', error_response)
    @token_required
    def post(self, current_user):
        """Logout user and invalidate token"""
        try:
            # Bug 45 fix: use the same stripping logic as token_required so the
            # stored token exactly matches what blocklist checks look for.
            auth_header = request.headers.get("authorization", "")
            token = auth_header[7:] if auth_header.lower().startswith("bearer ") else auth_header

            # Add token to blocklist
            jwt_block = JWTTokenBlocklist(
                jwt_token=token,
                created_at=datetime.now(timezone.utc)
            )
            jwt_block.save()

            # Deactivate JWT auth for user
            current_user.set_jwt_auth_active(False)
            current_user.save()

            return {
                "success": True,
                "msg": "Logged out successfully"
            }, 200

        except Exception as e:
            return {
                "success": False,
                "msg": f"Logout failed: {str(e)}"
            }, 400


@auth_api.route('/api/auth/profile')
class Profile(Resource):
    """Get user profile endpoint"""

    @auth_api.response(200, 'Success')
    @auth_api.response(401, 'Unauthorized', error_response)
    @token_required
    def get(self, current_user):
        """Get current user profile"""
        try:
            return {
                "success": True,
                "user": {
                    "id": current_user.id,
                    "username": current_user.username,
                    "email": current_user.email,
                    "date_joined": current_user.date_joined.isoformat() if current_user.date_joined else None,
                    "jwt_auth_active": current_user.jwt_auth_active
                }
            }, 200
        except Exception as e:
            return {
                "success": False,
                "msg": f"Failed to get profile: {str(e)}"
            }, 400


@auth_api.route('/api/auth/verify')
class VerifyToken(Resource):
    """Verify JWT token endpoint"""

    @auth_api.response(200, 'Success')
    @auth_api.response(401, 'Unauthorized', error_response)
    @token_required
    def get(self, current_user):
        """Verify if token is valid"""
        return {
            "success": True,
            "msg": "Token is valid",
            "user": {
                "id": current_user.id,
                "username": current_user.username,
                "email": current_user.email
            }
        }, 200