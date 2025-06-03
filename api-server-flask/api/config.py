# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

import os, random, string
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

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # MySQL Database Configuration
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

    USE_SQLITE = False
    SQLALCHEMY_DATABASE_URI = None

    # Configure MySQL database
    if DB_ENGINE and DB_NAME and DB_USERNAME:
        try:
            # MySQL database URI with connection parameters
            SQLALCHEMY_DATABASE_URI = '{}://{}:{}@{}:{}/{}?charset={}'.format(
                DB_ENGINE,
                DB_USERNAME,
                DB_PASS,
                DB_HOST,
                DB_PORT,
                DB_NAME,
                MYSQL_CHARSET
            )

            # Additional SQLAlchemy engine options for MySQL
            SQLALCHEMY_ENGINE_OPTIONS = {
                'pool_size': DB_POOL_SIZE,
                'max_overflow': DB_MAX_OVERFLOW,
                'pool_recycle': DB_POOL_RECYCLE,
                'pool_pre_ping': True,  # Verify connections before use
                'connect_args': {
                    'charset': MYSQL_CHARSET,
                    'use_unicode': True,
                    'autocommit': False,
                    'sql_mode': 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO',
                }
            }

            USE_SQLITE = False
            print(f'> Using MySQL Database: {DB_HOST}:{DB_PORT}/{DB_NAME}')

        except Exception as e:
            print('> Error: MySQL Configuration Exception: ' + str(e))
            print('> Falling back to SQLite...')
            USE_SQLITE = True

    # Fallback to SQLite if MySQL configuration fails
    if USE_SQLITE or not SQLALCHEMY_DATABASE_URI:
        print('> Using SQLite Database as fallback')
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'db.sqlite3')
        SQLALCHEMY_ENGINE_OPTIONS = {}