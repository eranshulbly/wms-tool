# -*- encoding: utf-8 -*-
"""
assignment module — public service API (scaffold).

The auto-assignment engine (match a pending job to a free, eligible worker via
RBAC + warehouse access + availability, weighted by allocation policy) is not
implemented yet. Signatures are stubs to define the eventual boundary.
"""


def enqueue_job(job_type, source_type, source_id, warehouse_id, priority=0):
    raise NotImplementedError("assignment engine is scaffolded, not yet implemented")


def next_job_for_worker(user_id, warehouse_id):
    raise NotImplementedError("assignment engine is scaffolded, not yet implemented")
