# -*- encoding: utf-8 -*-
"""user_auth module — data models. This module owns these tables.

Active-record classes over raw SQL (MySQLModel). Boundary rule: other
modules read these through this module's service.py, never by importing
these classes directly.
"""
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from api.shared.db_manager import mysql_manager, MySQLModel, partition_filter


class Users(MySQLModel):
    """User model with direct MySQL queries"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = kwargs.get('id')
        # The column is `name`; `username` is still accepted so callers built from the
        # older key keep working. Falling back to None here is what previously let
        # save() write a NULL over a loaded row.
        self.name = kwargs.get('name', kwargs.get('username'))
        self.email = kwargs.get('email')
        self.password = kwargs.get('password')
        self.jwt_auth_active = kwargs.get('jwt_auth_active', False)
        self.date_joined = kwargs.get('date_joined')
        self.status = kwargs.get('status', 'pending')   # pending | active | blocked
        self.role = kwargs.get('role', 'viewer')         # admin | manager | warehouse_staff | dispatcher | viewer

    def save(self):
        """Save user to database"""
        if self.id:
            mysql_manager.execute_query(
                """UPDATE users SET name=%s, email=%s, password=%s,
                   jwt_auth_active=%s, status=%s, role=%s WHERE id=%s""",
                (self.name, self.email, self.password,
                 self.jwt_auth_active, self.status, self.role, self.id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO users (name, email, password, jwt_auth_active,
                       date_joined, status, role)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (self.name, self.email, self.password, self.jwt_auth_active,
                     self.date_joined or datetime.utcnow(), self.status, self.role)
                )
                self.id = cursor.lastrowid

    def set_password(self, password):
        """Hash and set password"""
        self.password = generate_password_hash(password)

    def check_password(self, password):
        """Check password against hash"""
        return check_password_hash(self.password, password)

    def update_email(self, new_email):
        """Update email"""
        self.email = new_email

    @property
    def username(self):
        """Legacy alias for `name`, kept so existing callers and JSON keys still work."""
        return self.name

    def update_username(self, new_username):
        """Update the display name."""
        self.name = new_username

    def check_jwt_auth_active(self):
        """Check if JWT auth is active"""
        return self.jwt_auth_active

    def set_jwt_auth_active(self, set_status):
        """Set JWT auth status"""
        self.jwt_auth_active = set_status

    @classmethod
    def get_by_id(cls, user_id):
        """Get user by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM users WHERE id = %s", (user_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_by_email(cls, email):
        """Get user by email"""
        result = mysql_manager.execute_query(
            "SELECT * FROM users WHERE email = %s", (email,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_by_username(cls, username):
        """Get user by username"""
        result = mysql_manager.execute_query(
            "SELECT * FROM users WHERE name = %s", (username,)
        )
        if result:
            return cls(**result[0])
        return None

    def toJSON(self):
        """Convert to JSON"""
        return {
            '_id': self.id,
            'username': self.name,
            'email': self.email
        }


class JWTTokenBlocklist(MySQLModel):
    """JWT Token Blocklist model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = kwargs.get('id')
        self.jwt_token = kwargs.get('jwt_token')
        self.created_at = kwargs.get('created_at')

    def save(self):
        """Save blocked token"""
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                "INSERT INTO jwt_token_blocklist (jwt_token, created_at) VALUES (%s, %s)",
                (self.jwt_token, self.created_at or datetime.utcnow())
            )
            self.id = cursor.lastrowid


class UserWarehouseCompany(MySQLModel):
    """Maps users to allowed warehouse+company pairs"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.warehouse_id = kwargs.get('warehouse_id')
        self.company_id = kwargs.get('company_id')

    def save(self):
        with mysql_manager.get_cursor() as cursor:
            cursor.execute(
                """INSERT IGNORE INTO user_warehouse_company (user_id, warehouse_id, company_id)
                   VALUES (%s, %s, %s)""",
                (self.user_id, self.warehouse_id, self.company_id)
            )
            self.id = cursor.lastrowid

    @classmethod
    def get_for_user(cls, user_id):
        """Return list of {warehouse_id, company_id} pairs for a user"""
        return mysql_manager.execute_query(
            """SELECT uwc.warehouse_id, uwc.company_id,
                      w.name as warehouse_name, c.name as company_name
               FROM user_warehouse_company uwc
               JOIN warehouse w ON uwc.warehouse_id = w.warehouse_id
               JOIN company c ON uwc.company_id = c.company_id
               WHERE uwc.user_id = %s""",
            (user_id,)
        )

    @classmethod
    def delete_for_user(cls, user_id):
        mysql_manager.execute_query(
            "DELETE FROM user_warehouse_company WHERE user_id = %s",
            (user_id,), fetch=False
        )

    @classmethod
    def user_can_access(cls, user_id, warehouse_id, company_id):
        """Check if user has access to a specific warehouse+company pair"""
        result = mysql_manager.execute_query(
            """SELECT id FROM user_warehouse_company
               WHERE user_id=%s AND warehouse_id=%s AND company_id=%s""",
            (user_id, warehouse_id, company_id)
        )
        return bool(result)


# E-Way Bill Automation Models

