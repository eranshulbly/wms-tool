# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

import os
import random
import string
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.realpath(__file__))

class BaseConfig():
    SECRET_KEY = os.getenv('SECRET_KEY', None)
    if not SECRET_KEY:
        SECRET_KEY = ''.join(random.choice(string.ascii_lowercase) for i in range(32))

    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', None)
    if not JWT_SECRET_KEY:
        JWT_SECRET_KEY = ''.join(random.choice(string.ascii_lowercase) for i in range(32))

    GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID', None)
    GITHUB_CLIENT_SECRET = os.getenv('GITHUB_SECRET_KEY', None)

    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)

    # MySQL Database Configuration (REQUIRED)
    DB_ENGINE = os.getenv('DB_ENGINE', 'mysql+pymysql')
    DB_USERNAME = os.getenv('DB_USERNAME', 'root')
    DB_PASS = os.getenv('DB_PASS', 'root-pw')
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '3306')
    DB_NAME = os.getenv('DB_NAME', 'warehouse_management')

    # MySQL Connection Pool Settings
    DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '10'))
    DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '20'))
    DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', '3600'))

    # MySQL specific settings
    MYSQL_CHARSET = os.getenv('MYSQL_CHARSET', 'utf8mb4')
    MYSQL_COLLATION = os.getenv('MYSQL_COLLATION', 'utf8mb4_unicode_ci')

    # Validate MySQL configuration
    if not all([DB_USERNAME, DB_PASS, DB_HOST, DB_PORT, DB_NAME]):
        raise ValueError("MySQL configuration incomplete. Please set all required environment variables: "
                        "DB_USERNAME, DB_PASS, DB_HOST, DB_PORT, DB_NAME")

    print(f'> Using MySQL Database: {DB_HOST}:{DB_PORT}/{DB_NAME}')
    print(f'> Connection Pool: {DB_POOL_SIZE} connections, {DB_MAX_OVERFLOW} overflow')
    print(f'> Character Set: {MYSQL_CHARSET}, Collation: {MYSQL_COLLATION}')