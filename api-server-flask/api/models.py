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
    id = db.Column(db.Integer(), primary_key=True)
    username = db.Column(db.String(32), nullable=False)
    email = db.Column(db.String(64), nullable=True)
    password = db.Column(db.Text())
    jwt_auth_active = db.Column(db.Boolean())
    date_joined = db.Column(db.DateTime(), default=datetime.utcnow)

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
    id = db.Column(db.Integer(), primary_key=True)
    jwt_token = db.Column(db.String(), nullable=False)
    created_at = db.Column(db.DateTime(), nullable=False)

    def __repr__(self):
        return f"Expired Token: {self.jwt_token}"

    def save(self):
        db.session.add(self)
        db.session.commit()


class Warehouse(db.Model):
    __tablename__ = 'warehouse'

    warehouse_id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255))
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

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


class Company(db.Model):
    __tablename__ = 'company'

    company_id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

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

    dealer_id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

    def __repr__(self):
        return f"Company {self.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, company_id):
        return cls.query.get_or_404(company_id)

    def to_dict(self):
        return {'company_id': self.dealer_id, 'name': self.name}


class Box(db.Model):
    __tablename__ = 'box'

    box_id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

    def __repr__(self):
        return f"Company {self.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, company_id):
        return cls.query.get_or_404(company_id)

    def to_dict(self):
        return {'company_id': self.box_id, 'name': self.name}


class Product(db.Model):
    __tablename__ = 'product'

    product_id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text())
    price = db.Column(db.Numeric(10, 2))
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

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


class OrderRequest(db.Model):
    __tablename__ = 'order_request'

    order_request_id = db.Column(db.Integer(), primary_key=True)
    original_order_id = db.Column(db.Integer(), unique=True, nullable=False)  # original order id coming from upload
    warehouse_id = db.Column(db.Integer(), db.ForeignKey('warehouse.warehouse_id'))
    company_id = db.Column(db.Integer(), db.ForeignKey('company.company_id'))
    dealer_id = db.Column(db.Integer(), db.ForeignKey('dealer.dealer_id'))
    order_date = db.Column(db.DateTime(), default=datetime.now())
    requested_by = db.Column(db.Integer())  # User ID who created the order request
    status = db.Column(db.String(50), default='Open')  # E.g., 'Open', 'Picking', 'Packing'
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

    warehouse = db.relationship('Warehouse', backref=db.backref('orders', lazy=True))
    company = db.relationship('Company', backref=db.backref('orders', lazy=True))

    def __repr__(self):
        return f"OrderRequest {self.order_request_id} - {self.status}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, order_request_id):
        return cls.query.get_or_404(order_request_id)

    def to_dict(self):
        return {
            'order_request_id': self.order_request_id,
            'warehouse_id': self.warehouse_id,
            'company_id': self.company_id,
            'order_date': self.order_date,
            'status': self.status
        }


class OrderRequestProduct(db.Model):
    __tablename__ = 'order_request_product'

    order_request_product_id = db.Column(db.Integer(), primary_key=True)
    order_request_id = db.Column(db.Integer(), db.ForeignKey('order_request.order_request_id'))
    product_id = db.Column(db.Integer(), db.ForeignKey('product.product_id'))
    quantity = db.Column(db.Integer(), nullable=False)
    mrp = db.Column(db.Numeric(10, 2))  # Maximum Retail Price of the product
    total_price = db.Column(db.Numeric(10, 2))  # Total price = quantity * mrp
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

    order_request = db.relationship('OrderRequest', backref=db.backref('products', lazy=True))
    product = db.relationship('Product', backref=db.backref('order_requests', lazy=True))

    def __repr__(self):
        return f"OrderRequestProduct {self.order_request_product_id} - {self.product.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, order_request_product_id):
        return cls.query.get_or_404(order_request_product_id)

    def to_dict(self):
        return {
            'order_request_product_id': self.order_request_product_id,
            'order_request_id': self.order_request_id,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'mrp': str(self.mrp),
            'total_price': str(self.total_price)
        }


class Order(db.Model):
    __tablename__ = 'order'

    order_id = db.Column(db.Integer(), primary_key=True)
    order_request_id = db.Column(db.Integer(), db.ForeignKey('order_request.order_request_id'))
    order_number = db.Column(db.String(255), unique=True, nullable=False)
    dispatched_date = db.Column(db.DateTime())
    delivery_date = db.Column(db.DateTime())
    status = db.Column(db.String(50), default='In Transit')  # E.g., 'In Transit', 'Delivered', 'Returned'
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

    order_request = db.relationship('OrderRequest', backref=db.backref('final_order', lazy=True))

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
            'order_request_id': self.order_request_id,
            'order_number': self.order_number,
            'dispatched_date': self.dispatched_date,
            'delivery_date': self.delivery_date,
            'status': self.status
        }


class OrderBox(db.Model):
    __tablename__ = 'order_box'

    order_id = db.Column(db.Integer(), db.ForeignKey('order.order_id'))
    box_id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

    def __repr__(self):
        return f"OrderBox {self.order_product_id} - {self.product.name}"

    def save(self):
        db.session.add(self)
        db.session.commit()

    @classmethod
    def get_by_id(cls, company_id):
        return cls.query.get_or_404(company_id)

    def to_dict(self):
        return {
            'order_id': self.order_id,
            'box_id': self.box_id,
            'name': self.name
        }


class OrderProduct(db.Model):
    __tablename__ = 'order_product'

    order_product_id = db.Column(db.Integer(), primary_key=True)
    order_id = db.Column(db.Integer(), db.ForeignKey('order.order_id'))
    product_id = db.Column(db.Integer(), db.ForeignKey('product.product_id'))
    quantity = db.Column(db.Integer(), nullable=False)
    mrp = db.Column(db.Numeric(10, 2))  # Price when the order was placed
    total_price = db.Column(db.Numeric(10, 2))  # Total price = quantity * mrp
    created_at = db.Column(db.DateTime(), default=datetime.now())
    updated_at = db.Column(db.DateTime(), default=datetime.now(), onupdate=datetime.now())

    order = db.relationship('Order', backref=db.backref('products', lazy=True))
    product = db.relationship('Product', backref=db.backref('orders', lazy=True))

    def __repr__(self):
        return f"OrderProduct {self.order_product_id} - {self.product.name}"

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

    state_id = db.Column(db.Integer(), primary_key=True)
    state_name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text())

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

    order_state_history_id = db.Column(db.Integer(), primary_key=True)
    order_request_id = db.Column(db.Integer(), db.ForeignKey('order_request.order_request_id'))
    state_id = db.Column(db.Integer(), db.ForeignKey('order_state.state_id'))
    changed_by = db.Column(db.Integer())  # User who changed the state
    changed_at = db.Column(db.DateTime(), default=datetime.now())

    order_request = db.relationship('OrderRequest', backref=db.backref('state_history', lazy=True))
    order_state = db.relationship('OrderState', backref=db.backref('state_history', lazy=True))

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
            'order_request_id': self.order_request_id,
            'state_id': self.state_id,
            'changed_by': self.changed_by,
            'changed_at': self.changed_at
        }

