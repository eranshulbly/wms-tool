# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from datetime import datetime

import json

from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Users(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    username = db.Column(db.String(32), nullable=False, index=True)
    email = db.Column(db.String(64), nullable=True, unique=True, index=True)
    password = db.Column(db.Text())
    jwt_auth_active = db.Column(db.Boolean(), default=False)
    date_joined = db.Column(db.DateTime(), default=datetime.utcnow)

    # MySQL specific indexes
    __table_args__ = (
        db.Index('idx_users_username', 'username'),
        db.Index('idx_users_email', 'email'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"User {self.username}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def update_email(self, new_email):
        self.email = new_email

    def update_username(self, new_username):
        self.username = new_username

    def check_jwt_auth_active(self):
        return self.jwt_auth_active

    def set_jwt_auth_active(self, set_status):
        self.jwt_auth_active = set_status

    @classmethod
    def get_by_id(cls, id):
        return cls.query.get_or_404(id)

    @classmethod
    def get_by_email(cls, email):
        return cls.query.filter_by(email=email).first()

    @classmethod
    def get_by_username(cls, username):
        return cls.query.filter_by(username=username).first()

    def toDICT(self):
        cls_dict = {}
        cls_dict['_id'] = self.id
        cls_dict['username'] = self.username
        cls_dict['email'] = self.email

        return cls_dict

    def toJSON(self):
        return self.toDICT()


class JWTTokenBlocklist(db.Model):
    __tablename__ = 'jwt_token_blocklist'

    id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    jwt_token = db.Column(db.Text(), nullable=False)
    created_at = db.Column(db.DateTime(), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_jwt_token_created', 'created_at'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"Expired Token: {self.jwt_token[:20]}..."

    def save(self):
        db.session.add(self)
        db.session.commit()


class Warehouse(db.Model):
    __tablename__ = 'warehouse'

    warehouse_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    location = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_warehouse_name', 'name'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"Warehouse {self.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, warehouse_id):
        return cls.query.get_or_404(warehouse_id)

    def to_dict(self):
        return {'warehouse_id': self.warehouse_id, 'name': self.name, 'location': self.location}

    @classmethod
    def all(cls):
        def format_date(value):
            if isinstance(value, int):
                try:
                    return datetime.utcfromtimestamp(value).isoformat()
                except:
                    return None
            elif isinstance(value, datetime):
                return value.isoformat()
            return None

        warehouses = cls.query.all()
        return [
            {
                'warehouse_id': w.warehouse_id,
                'name': w.name,
                'location': w.location,
                'created_at': format_date(w.created_at),
                'updated_at': format_date(w.updated_at),
            }
            for w in warehouses
        ]


class Company(db.Model):
    __tablename__ = 'company'

    company_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_company_name', 'name'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"Company {self.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, company_id):
        return cls.query.get_or_404(company_id)

    def to_dict(self):
        return {'company_id': self.company_id, 'name': self.name}


class Dealer(db.Model):
    __tablename__ = 'dealer'

    dealer_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_dealer_name', 'name'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"Dealer {self.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, dealer_id):
        return cls.query.get_or_404(dealer_id)

    def to_dict(self):
        return {'dealer_id': self.dealer_id, 'name': self.name}


class Box(db.Model):
    __tablename__ = 'box'

    box_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_box_name', 'name'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"Box {self.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, box_id):
        return cls.query.get_or_404(box_id)

    def to_dict(self):
        return {'box_id': self.box_id, 'name': self.name}


class Product(db.Model):
    __tablename__ = 'product'

    product_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    product_string = db.Column(db.String(100), index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text())
    price = db.Column(db.DECIMAL(10, 2))
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_product_string', 'product_string'),
        db.Index('idx_product_name', 'name'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"Product {self.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, product_id):
        return cls.query.get_or_404(product_id)

    def to_dict(self):
        return {'product_id': self.product_id, 'name': self.name, 'description': self.description,
                'price': str(self.price)}


class PotentialOrder(db.Model):
    __tablename__ = 'potential_order'

    potential_order_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    original_order_id = db.Column(db.String(100), nullable=False, index=True)  # Changed from unique=True for MySQL
    warehouse_id = db.Column(db.Integer(), db.ForeignKey('warehouse.warehouse_id'), index=True)
    company_id = db.Column(db.Integer(), db.ForeignKey('company.company_id'), index=True)
    dealer_id = db.Column(db.Integer(), db.ForeignKey('dealer.dealer_id'), index=True)
    order_date = db.Column(db.DateTime(), default=datetime.utcnow)
    requested_by = db.Column(db.Integer(), index=True)  # User ID who created the order request
    status = db.Column(db.String(50), default='Open', index=True)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    warehouse = db.relationship('Warehouse', backref=db.backref('orders', lazy=True))
    company = db.relationship('Company', backref=db.backref('orders', lazy=True))
    dealer = db.relationship('Dealer', backref=db.backref('orders', lazy=True))

    __table_args__ = (
        db.Index('idx_potential_order_status', 'status'),
        db.Index('idx_potential_order_date', 'order_date'),
        db.Index('idx_potential_order_composite', 'warehouse_id', 'company_id', 'status'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"PotentialOrder {self.potential_order_id} - {self.status}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, potential_order_id):
        return cls.query.get_or_404(potential_order_id)

    def to_dict(self):
        return {
            'potential_order_id': self.potential_order_id,
            'warehouse_id': self.warehouse_id,
            'company_id': self.company_id,
            'order_date': self.order_date,
            'status': self.status
        }


class PotentialOrderProduct(db.Model):
    __tablename__ = 'potential_order_product'

    potential_order_product_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    potential_order_id = db.Column(db.Integer(), db.ForeignKey('potential_order.potential_order_id'), index=True)
    product_id = db.Column(db.Integer(), db.ForeignKey('product.product_id'), index=True)
    quantity = db.Column(db.Integer(), nullable=False)
    quantity_packed = db.Column(db.Integer(), default=0)
    quantity_remaining = db.Column(db.Integer())
    mrp = db.Column(db.DECIMAL(10, 2))
    total_price = db.Column(db.DECIMAL(10, 2))
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    potential_order = db.relationship('PotentialOrder', backref=db.backref('products', lazy=True))
    product = db.relationship('Product', backref=db.backref('potential_orders', lazy=True))

    __table_args__ = (
        db.Index('idx_pop_order_product', 'potential_order_id', 'product_id'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"PotentialOrderProduct {self.potential_order_product_id} - {self.product.name if self.product else 'Unknown'}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, potential_order_product_id):
        return cls.query.get_or_404(potential_order_product_id)

    @property
    def calculated_quantity_remaining(self):
        """Calculate remaining quantity"""
        return self.quantity - (self.quantity_packed or 0)

    def to_dict(self):
        return {
            'potential_order_product_id': self.potential_order_product_id,
            'potential_order_id': self.potential_order_id,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'quantity_packed': self.quantity_packed or 0,
            'quantity_remaining': self.calculated_quantity_remaining,
            'mrp': str(self.mrp) if self.mrp else None,
            'total_price': str(self.total_price) if self.total_price else None
        }


class Order(db.Model):
    __tablename__ = 'order'

    order_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    potential_order_id = db.Column(db.Integer(), db.ForeignKey('potential_order.potential_order_id'), index=True)
    order_number = db.Column(db.String(255), nullable=False, index=True)
    dispatched_date = db.Column(db.DateTime())
    delivery_date = db.Column(db.DateTime())
    status = db.Column(db.String(50), default='In Transit', index=True)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    potential_order = db.relationship('PotentialOrder', backref=db.backref('final_order', lazy=True))

    __table_args__ = (
        db.Index('idx_order_number', 'order_number'),
        db.Index('idx_order_status', 'status'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"Order {self.order_number} - {self.status}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, order_id):
        return cls.query.get_or_404(order_id)

    def to_dict(self):
        return {
            'order_id': self.order_id,
            'potential_order_id': self.potential_order_id,
            'order_number': self.order_number,
            'dispatched_date': self.dispatched_date,
            'delivery_date': self.delivery_date,
            'status': self.status
        }


class OrderBox(db.Model):
    __tablename__ = 'order_box'

    box_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    order_id = db.Column(db.Integer(), db.ForeignKey('order.order_id'), index=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    order = db.relationship('Order', backref=db.backref('boxes', lazy=True))

    __table_args__ = (
        db.Index('idx_order_box_order', 'order_id'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"OrderBox {self.box_id} - {self.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, box_id):
        return cls.query.get_or_404(box_id)

    def to_dict(self):
        return {
            'order_id': self.order_id,
            'box_id': self.box_id,
            'name': self.name
        }


class OrderProduct(db.Model):
    __tablename__ = 'order_product'

    order_product_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    order_id = db.Column(db.Integer(), db.ForeignKey('order.order_id'), index=True)
    product_id = db.Column(db.Integer(), db.ForeignKey('product.product_id'), index=True)
    quantity = db.Column(db.Integer(), nullable=False)
    mrp = db.Column(db.DECIMAL(10, 2))
    total_price = db.Column(db.DECIMAL(10, 2))
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    order = db.relationship('Order', backref=db.backref('products', lazy=True))
    product = db.relationship('Product', backref=db.backref('orders', lazy=True))

    __table_args__ = (
        db.Index('idx_order_product_composite', 'order_id', 'product_id'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"OrderProduct {self.order_product_id} - {self.product.name if self.product else 'Unknown'}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, order_product_id):
        return cls.query.get_or_404(order_product_id)

    def to_dict(self):
        return {
            'order_product_id': self.order_product_id,
            'order_id': self.order_id,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'mrp': str(self.mrp),
            'total_price': str(self.total_price)
        }


class OrderState(db.Model):
    __tablename__ = 'order_state'

    state_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    state_name = db.Column(db.String(50), nullable=False, unique=True, index=True)
    description = db.Column(db.Text())

    __table_args__ = (
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"OrderState {self.state_name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, state_id):
        return cls.query.get_or_404(state_id)

    def to_dict(self):
        return {'state_id': self.state_id, 'state_name': self.state_name, 'description': self.description}


class OrderStateHistory(db.Model):
    __tablename__ = 'order_state_history'

    order_state_history_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    potential_order_id = db.Column(db.Integer(), db.ForeignKey('potential_order.potential_order_id'), index=True)
    state_id = db.Column(db.Integer(), db.ForeignKey('order_state.state_id'), index=True)
    changed_by = db.Column(db.Integer(), index=True)  # User who changed the state
    changed_at = db.Column(db.DateTime(), default=datetime.utcnow)

    potential_order = db.relationship('PotentialOrder', backref=db.backref('state_history', lazy=True))
    order_state = db.relationship('OrderState', backref=db.backref('state_history', lazy=True))

    __table_args__ = (
        db.Index('idx_osh_order_state', 'potential_order_id', 'state_id'),
        db.Index('idx_osh_changed_at', 'changed_at'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"OrderStateHistory {self.order_state_history_id}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, order_state_history_id):
        return cls.query.get_or_404(order_state_history_id)

    def to_dict(self):
        return {
            'order_state_history_id': self.order_state_history_id,
            'potential_order_id': self.potential_order_id,
            'state_id': self.state_id,
            'changed_by': self.changed_by,
            'changed_at': self.changed_at
        }


class BoxProduct(db.Model):
    __tablename__ = 'box_product'

    box_product_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    box_id = db.Column(db.Integer(), db.ForeignKey('box.box_id'), index=True)
    product_id = db.Column(db.Integer(), db.ForeignKey('product.product_id'), index=True)
    quantity = db.Column(db.Integer(), nullable=False)
    potential_order_id = db.Column(db.Integer(), db.ForeignKey('potential_order.potential_order_id'), index=True)
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    box = db.relationship('Box', backref=db.backref('box_products', lazy=True))
    product = db.relationship('Product', backref=db.backref('box_assignments', lazy=True))
    potential_order = db.relationship('PotentialOrder', backref=db.backref('box_assignments', lazy=True))

    __table_args__ = (
        db.Index('idx_box_product_composite', 'box_id', 'product_id'),
        db.Index('idx_box_product_order', 'potential_order_id'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"BoxProduct {self.box_product_id} - Box {self.box_id} Product {self.product_id}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, box_product_id):
        return cls.query.get_or_404(box_product_id)

    def to_dict(self):
        return {
            'box_product_id': self.box_product_id,
            'box_id': self.box_id,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'potential_order_id': self.potential_order_id
        }


class Invoice(db.Model):
    __tablename__ = 'invoice'

    invoice_id = db.Column(db.Integer(), primary_key=True, autoincrement=True)

    # Foreign key relationships
    potential_order_id = db.Column(db.Integer(), db.ForeignKey('potential_order.potential_order_id'), index=True)
    warehouse_id = db.Column(db.Integer(), db.ForeignKey('warehouse.warehouse_id'), index=True)
    company_id = db.Column(db.Integer(), db.ForeignKey('company.company_id'), index=True)

    # Invoice identification
    invoice_number = db.Column(db.String(255), nullable=False, index=True)
    dealer_code = db.Column(db.String(100), index=True)
    original_order_id = db.Column(db.String(255), nullable=False, index=True)  # From narration

    # Customer information
    customer_name = db.Column(db.String(500))
    customer_code = db.Column(db.String(100))
    customer_category = db.Column(db.String(100))

    # Invoice details
    invoice_date = db.Column(db.DateTime())
    invoice_status = db.Column(db.String(50))
    invoice_type = db.Column(db.String(50))
    invoice_format = db.Column(db.String(50))

    # Product information
    part_no = db.Column(db.String(255))
    part_name = db.Column(db.String(500))
    uom = db.Column(db.String(50))
    hsn_number = db.Column(db.String(100))
    product_type = db.Column(db.String(100))
    product_category = db.Column(db.String(100))

    # Quantity and pricing
    quantity = db.Column(db.Integer())
    unit_price = db.Column(db.DECIMAL(10, 2))
    line_item_discount_percent = db.Column(db.DECIMAL(5, 2))
    line_item_discount = db.Column(db.DECIMAL(10, 2))
    net_selling_price = db.Column(db.DECIMAL(10, 2))
    assessable_value = db.Column(db.DECIMAL(10, 2))

    # Tax information
    vat_amount = db.Column(db.DECIMAL(10, 2))
    cgst_percent = db.Column(db.DECIMAL(5, 2))
    cgst_amount = db.Column(db.DECIMAL(10, 2))
    sgst_percent = db.Column(db.DECIMAL(5, 2))
    sgst_amount = db.Column(db.DECIMAL(10, 2))
    utgst_percent = db.Column(db.DECIMAL(5, 2))
    utgst_amount = db.Column(db.DECIMAL(10, 2))
    igst_percent = db.Column(db.DECIMAL(5, 2))
    igst_amount = db.Column(db.DECIMAL(10, 2))
    cess_percent = db.Column(db.DECIMAL(5, 2))
    cess_amount = db.Column(db.DECIMAL(10, 2))

    # Additional tax amounts
    additional_tax_amt = db.Column(db.DECIMAL(10, 2))
    additional_tax_amt2 = db.Column(db.DECIMAL(10, 2))
    additional_tax_amt3 = db.Column(db.DECIMAL(10, 2))
    additional_tax_amt4 = db.Column(db.DECIMAL(10, 2))
    additional_tax_amt5 = db.Column(db.DECIMAL(10, 2))

    # Freight and packaging
    freight_amount = db.Column(db.DECIMAL(10, 2))
    packaging_charges = db.Column(db.DECIMAL(10, 2))

    # Freight/Packaging GST
    frt_pkg_cgst_percent = db.Column(db.DECIMAL(5, 2))
    frt_pkg_cgst_amount = db.Column(db.DECIMAL(10, 2))
    frt_pkg_sgst_percent = db.Column(db.DECIMAL(5, 2))
    frt_pkg_sgst_amount = db.Column(db.DECIMAL(10, 2))
    frt_pkg_igst_percent = db.Column(db.DECIMAL(5, 2))
    frt_pkg_igst_amount = db.Column(db.DECIMAL(10, 2))
    frt_pkg_cess_percent = db.Column(db.DECIMAL(5, 2))
    frt_pkg_cess_amount = db.Column(db.DECIMAL(10, 2))

    # Totals and discounts
    total_invoice_amount = db.Column(db.DECIMAL(12, 2))
    additional_discount_percent = db.Column(db.DECIMAL(5, 2))
    cash_discount_percent = db.Column(db.DECIMAL(5, 2))
    credit_days = db.Column(db.Integer())

    # Location and tax details
    location_code = db.Column(db.String(50))
    state = db.Column(db.String(100))
    state_code = db.Column(db.String(10))
    gstin = db.Column(db.String(50))

    # System fields
    record_updated_dt = db.Column(db.DateTime())
    login = db.Column(db.String(100))
    voucher = db.Column(db.String(100))
    type_field = db.Column(db.String(100))  # 'type' is a reserved word
    parent = db.Column(db.String(100))
    sale_return_date = db.Column(db.DateTime())
    narration = db.Column(db.Text())  # Store the full narration
    cancellation_date = db.Column(db.DateTime())
    executive_name = db.Column(db.String(255))

    # Upload tracking
    uploaded_by = db.Column(db.Integer(), index=True)  # User ID who uploaded
    upload_batch_id = db.Column(db.String(100), index=True)  # To group uploads
    created_at = db.Column(db.DateTime(), default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    potential_order = db.relationship('PotentialOrder', backref=db.backref('invoices', lazy=True))
    warehouse = db.relationship('Warehouse', backref=db.backref('invoices', lazy=True))
    company = db.relationship('Company', backref=db.backref('invoices', lazy=True))

    __table_args__ = (
        db.Index('idx_invoice_number', 'invoice_number'),
        db.Index('idx_invoice_original_order', 'original_order_id'),
        db.Index('idx_invoice_batch', 'upload_batch_id'),
        db.Index('idx_invoice_date', 'invoice_date'),
        db.Index('idx_invoice_composite', 'warehouse_id', 'company_id', 'invoice_date'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )

    def __repr__(self):
        return f"Invoice {self.invoice_number} - Order {self.original_order_id}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, invoice_id):
        return cls.query.get_or_404(invoice_id)

    def to_dict(self):
        return {
            'invoice_id': self.invoice_id,
            'invoice_number': self.invoice_number,
            'original_order_id': self.original_order_id,
            'customer_name': self.customer_name,
            'invoice_date': self.invoice_date.isoformat() if self.invoice_date else None,
            'total_invoice_amount': str(self.total_invoice_amount) if self.total_invoice_amount else None,
            'invoice_status': self.invoice_status,
            'part_no': self.part_no,
            'part_name': self.part_name,
            'quantity': self.quantity,
            'unit_price': str(self.unit_price) if self.unit_price else None
        }