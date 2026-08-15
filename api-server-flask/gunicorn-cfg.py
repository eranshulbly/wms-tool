import os

bind = '0.0.0.0:5000'

# One process, four threads.
#
# The box is shared and memory-constrained, so a second worker process is not an
# option — but `sync` served exactly one request at a time for the whole fleet,
# which meant every rep's catalog fetch queued behind whoever was slowest. A
# threaded worker keeps the single-process footprint and serves four concurrently.
#
# Safe against the DB layer: MySQLManager hands out one connection per caller from
# a lock-protected pool (api/shared/db_manager.py), so threads never share a
# connection. Four threads draw at most four of the pool's ten, well inside RDS's
# 60-connection ceiling.
#
# Tunable without a redeploy, so the thread count can be walked up while watching
# DB connection count and memory.
workers = 1
worker_class = 'gthread'
threads = int(os.environ.get('GUNICORN_THREADS', '4'))

preload_app = True          # load app once, share memory across workers
max_requests = 500          # recycle worker periodically to prevent memory leaks
max_requests_jitter = 50

# Ceiling on a single request. Uploads reach Flask only after nginx has buffered
# the whole body, so this bounds server-side work, not the client's link speed.
timeout = 120

# Applies to the nginx -> gunicorn hop. Worth setting only alongside `keepalive 32`
# in nginx's upstream block plus `proxy_set_header Connection ""`; without those
# nginx opens a fresh upstream connection per request and this is inert. The
# phone -> nginx side is governed by nginx's own keepalive_timeout.
# gthread parks idle connections in a poller rather than on a thread, so this does
# not consume one of the four.
keepalive = 65

accesslog = '-'
loglevel = 'warning'        # was 'debug' — saves significant I/O and memory
capture_output = True
enable_stdio_inheritance = True
