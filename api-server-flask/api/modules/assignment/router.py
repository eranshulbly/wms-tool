# -*- encoding: utf-8 -*-
"""
assignment module — HTTP routes.

Only a module-status endpoint for now (the work queue is scaffolded).
"""

from flask_restx import Resource

from api.extensions import rest_api
from api.core.auth import token_required, active_required


@rest_api.route('/api/assignment')
class AssignmentStatus(Resource):
    """Module status (scaffold)."""

    @token_required
    @active_required
    def get(self, _current_user):
        return {
            "module": "assignment",
            "status": "scaffolded",
            "features": {"jobs": "planned", "worker_availability": "planned",
                         "allocation_policies": "planned"},
        }, 200
