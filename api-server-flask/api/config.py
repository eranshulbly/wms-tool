# -*- encoding: utf-8 -*-
"""
WMS Tool - Environment-specific Flask Configuration
Environments: development | staging | production
Loaded by APP_ENV environment variable in __init__.py
"""

import os
import random
import string
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.realpath(__file__))

APP_VERSION = os.getenv('APP_VERSION', '1.0.0')


class BaseConfig():
    SECRET_KEY = os.getenv('SECRET_KEY', None)
    if not SECRET_KEY:
        SECRET_KEY = ''.join(random.choice(string.ascii_lowercase) for i in range(32))

    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', None)
    if not JWT_SECRET_KEY:
        JWT_SECRET_KEY = ''.join(random.choice(string.ascii_lowercase) for i in range(32))

    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)

    # App metadata
    APP_VERSION = os.getenv('APP_VERSION', '1.0.0')
    APP_ENV = os.getenv('APP_ENV', 'production')

    # MySQL Database Configuration (REQUIRED)
    DB_ENGINE   = os.getenv('DB_ENGINE',   'mysql+pymysql')
    DB_USERNAME = os.getenv('DB_USERNAME', 'root')
    DB_PASS     = os.getenv('DB_PASS',     'root-pw')
    DB_HOST     = os.getenv('DB_HOST',     'localhost')
    DB_PORT     = os.getenv('DB_PORT',     '3306')
    DB_NAME     = os.getenv('DB_NAME',     'warehouse_management')

    # MySQL Connection Pool Settings
    DB_POOL_SIZE    = int(os.getenv('DB_POOL_SIZE',    '10'))
    DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '20'))
    DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', '3600'))

    # MySQL specific settings
    MYSQL_CHARSET   = os.getenv('MYSQL_CHARSET',   'utf8mb4')
    MYSQL_COLLATION = os.getenv('MYSQL_COLLATION', 'utf8mb4_unicode_ci')

    if not all([DB_USERNAME, DB_PASS, DB_HOST, DB_PORT, DB_NAME]):
        raise ValueError(
            "MySQL configuration incomplete. Set: DB_USERNAME, DB_PASS, DB_HOST, DB_PORT, DB_NAME"
        )

    print(f'> Environment  : {APP_ENV}')
    print(f'> Version      : {APP_VERSION}')
    print(f'> MySQL        : {DB_HOST}:{DB_PORT}/{DB_NAME}')
    print(f'> Pool         : size={DB_POOL_SIZE}, overflow={DB_MAX_OVERFLOW}')


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)   # longer expiry for dev convenience
    DB_POOL_SIZE    = int(os.getenv('DB_POOL_SIZE',    '3'))
    DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '5'))


class StagingConfig(BaseConfig):
    DEBUG = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=4)
    DB_POOL_SIZE    = int(os.getenv('DB_POOL_SIZE',    '5'))
    DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '10'))


class ProductionConfig(BaseConfig):
    DEBUG = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    DB_POOL_SIZE    = int(os.getenv('DB_POOL_SIZE',    '10'))
    DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '20'))


# Map APP_ENV value → config class
config_map = {
    'development': DevelopmentConfig,
    'staging':     StagingConfig,
    'production':  ProductionConfig,
}

def get_config():
    env = os.getenv('APP_ENV', 'production').lower()
    cfg = config_map.get(env, ProductionConfig)
    return cfg
