# -*- encoding: utf-8 -*-
"""catalog module — data models. This module owns these tables.

Active-record classes over raw SQL (MySQLModel). Boundary rule: other
modules read these through this module's service.py, never by importing
these classes directly.
"""
from datetime import datetime
from api.shared.db_manager import mysql_manager, MySQLModel, partition_filter


class Company(MySQLModel):
    """Company model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.company_id = kwargs.get('company_id')
        self.name = kwargs.get('name')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save company"""
        if self.company_id:
            mysql_manager.execute_query(
                "UPDATE company SET name=%s, updated_at=%s WHERE company_id=%s",
                (self.name, datetime.utcnow(), self.company_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO company (name, created_at, updated_at) VALUES (%s, %s, %s)",
                    (self.name, datetime.utcnow(), datetime.utcnow())
                )
                self.company_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, company_id):
        """Get company by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM company WHERE company_id = %s", (company_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def get_all(cls):
        """Get all companies"""
        results = mysql_manager.execute_query("SELECT * FROM company")
        return [cls(**row) for row in results]


class Dealer(MySQLModel):
    """Dealer model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.dealer_id = kwargs.get('dealer_id')
        self.name = kwargs.get('name')
        self.dealer_code = kwargs.get('dealer_code')
        self.town = kwargs.get('town')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save dealer"""
        if self.dealer_id:
            mysql_manager.execute_query(
                "UPDATE dealer SET name=%s, dealer_code=%s, town=%s, updated_at=%s WHERE dealer_id=%s",
                (self.name, self.dealer_code, self.town, datetime.utcnow(), self.dealer_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO dealer (name, dealer_code, town, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
                    (self.name, self.dealer_code, self.town, datetime.utcnow(), datetime.utcnow())
                )
                self.dealer_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, dealer_id):
        """Get dealer by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM dealer WHERE dealer_id = %s", (dealer_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_name(cls, name):
        """Find dealer by name (case insensitive)"""
        result = mysql_manager.execute_query(
            "SELECT * FROM dealer WHERE LOWER(name) = LOWER(%s)", (name,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_code(cls, dealer_code):
        """Find dealer by eway bill dealer code"""
        result = mysql_manager.execute_query(
            "SELECT * FROM dealer WHERE dealer_code = %s", (dealer_code,)
        )
        if result:
            return cls(**result[0])
        return None


class Product(MySQLModel):
    """Product model"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.product_id = kwargs.get('product_id')
        self.company_id = kwargs.get('company_id')
        self.product_string = kwargs.get('product_string')
        self.name = kwargs.get('name')
        self.description = kwargs.get('description')
        self.nickname = kwargs.get('nickname')
        self.price = kwargs.get('price')
        self.category_id = kwargs.get('category_id')
        self.subcategory = kwargs.get('subcategory')
        self.uom = kwargs.get('uom')
        self.size = kwargs.get('size')
        self.weight = kwargs.get('weight')
        self.barcode = kwargs.get('barcode')
        self.hsn_code = kwargs.get('hsn_code')
        # NOT NULL in the table, so mirror the column default rather than None —
        # a bare Product(...) must still be insertable.
        self.is_active = 1 if kwargs.get('is_active') is None else kwargs.get('is_active')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def save(self):
        """Save product"""
        if self.product_id:
            mysql_manager.execute_query(
                """UPDATE product SET company_id=%s, product_string=%s, name=%s,
                   description=%s, nickname=%s, price=%s, category_id=%s, subcategory=%s,
                   uom=%s, size=%s, weight=%s, barcode=%s, hsn_code=%s, is_active=%s,
                   updated_at=%s WHERE product_id=%s""",
                (self.company_id, self.product_string, self.name, self.description,
                 self.nickname, self.price, self.category_id, self.subcategory,
                 self.uom, self.size, self.weight, self.barcode, self.hsn_code,
                 self.is_active, datetime.utcnow(), self.product_id),
                fetch=False
            )
        else:
            with mysql_manager.get_cursor() as cursor:
                cursor.execute(
                    """INSERT INTO product (company_id, product_string, name, description,
                       nickname, price, category_id, subcategory, uom, size, weight,
                       barcode, hsn_code, is_active, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (self.company_id, self.product_string, self.name, self.description,
                     self.nickname, self.price, self.category_id, self.subcategory,
                     self.uom, self.size, self.weight, self.barcode, self.hsn_code,
                     self.is_active, datetime.utcnow(), datetime.utcnow())
                )
                self.product_id = cursor.lastrowid

    @classmethod
    def get_by_id(cls, product_id):
        """Get product by ID"""
        result = mysql_manager.execute_query(
            "SELECT * FROM product WHERE product_id = %s", (product_id,)
        )
        if result:
            return cls(**result[0])
        return None

    @classmethod
    def find_by_product_string(cls, product_string):
        """Find product by product string (case insensitive)"""
        result = mysql_manager.execute_query(
            "SELECT * FROM product WHERE LOWER(product_string) = LOWER(%s)",
            (product_string,)
        )
        if result:
            return cls(**result[0])
        return None

