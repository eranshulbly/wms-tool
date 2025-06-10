# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from api import app
from api.db_manager import mysql_manager

@app.shell_context_processor
def make_shell_context():

    return {
        "app": app,
        "mysql_manager": mysql_manager,
        "mysql": mysql_manager  # Shorter alias
    }

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0")
