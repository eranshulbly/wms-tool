# -*- encoding: utf-8 -*-
"""
Mobile API — assignment module (/api/v1/assignment).

Only the module-status endpoint exists in wms-v2-backend (the assignment engine
is unbuilt there too), so that is all this ports.
"""

from flask_restx import Resource

from api.extensions import rest_api


@rest_api.route('/api/v1/assignment')
class V1AssignmentStatus(Resource):
    def get(self):
        return {"module": "assignment", "status": "ok"}, 200
