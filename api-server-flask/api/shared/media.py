# -*- encoding: utf-8 -*-
"""
Persistent storage for uploaded media (order photos).

Distinct from api/shared/upload_utils.py, which writes a *temporary* file, parses
it and deletes it. Files written here are kept and served back later.

Only the storage KEY ever reaches the database — never the bytes, and never an
absolute path. A key looks like `orders/42/9f3c….jpg`: it means something to
whichever backend is configured and to nothing else, so the same rows work
whether the file sits on local disk or in S3.

Two backends, chosen by MEDIA_BACKEND:

  local (default)  bytes under MEDIA_ROOT on the app server's disk.
  s3               bytes in an S3 bucket; reads are 302s to a short-lived
                   presigned URL, so image bytes never stream back through
                   gunicorn — which runs as a single process here and would
                   otherwise tie up a worker thread for every download.

Photos are never public in either mode: the caller checks permission before
asking for the file, and in S3 mode the presigned URL expires in minutes.
"""

import os
import uuid

from flask import redirect, send_file
from werkzeug.utils import secure_filename

# /app is the container's working dir (the repo is bind-mounted there in dev), so
# media/ persists on the host across container restarts.
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', os.path.join(os.getcwd(), 'media'))

# 'local' | 's3'. Defaults to local so an unconfigured deployment keeps working.
MEDIA_BACKEND = os.environ.get('MEDIA_BACKEND', 'local').strip().lower()

# S3 settings — only read when MEDIA_BACKEND == 's3'.
S3_BUCKET = os.environ.get('MEDIA_S3_BUCKET', '')
S3_REGION = os.environ.get('MEDIA_S3_REGION') or os.environ.get('AWS_REGION') or 'ap-south-1'
# Keeps media under one prefix so a bucket can be shared and lifecycle rules can
# target just this app's objects.
S3_PREFIX = os.environ.get('MEDIA_S3_PREFIX', 'wms/media/').lstrip('/')
# How long a served photo URL stays valid. Short: the client follows the redirect
# immediately, and a leaked URL should die quickly.
S3_URL_TTL = int(os.environ.get('MEDIA_S3_URL_TTL', '300'))

# Phone cameras produce JPEG/HEIC; PNG is allowed for screenshots of a paper order.
ALLOWED_IMAGE_TYPES = {
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/png': '.png',
    'image/heic': '.heic',
    'image/webp': '.webp',
}

MAX_IMAGE_BYTES = 15 * 1024 * 1024  # matches nginx client_max_body_size


class MediaError(Exception):
    """Raised when an upload is rejected (bad type, too large, empty)."""


def using_s3():
    return MEDIA_BACKEND == 's3'


def _s3_client():
    """Lazily build the S3 client.

    Imported inside the function so a local-backend deployment does not need
    boto3 installed at all — which is why boto3 is optional in requirements.txt
    rather than a hard dependency.
    """
    try:
        import boto3
    except ImportError as e:  # pragma: no cover - depends on deployment
        raise MediaError(
            "MEDIA_BACKEND=s3 but boto3 is not installed — pip install boto3"
        ) from e
    if not S3_BUCKET:
        raise MediaError("MEDIA_BACKEND=s3 but MEDIA_S3_BUCKET is not set")
    return boto3.client('s3', region_name=S3_REGION)


def _s3_key(relative_path):
    """Storage key -> full object key, keeping everything under S3_PREFIX."""
    return f"{S3_PREFIX}{relative_path.replace(os.sep, '/')}"


def _ext_for(file_storage):
    mime = (file_storage.mimetype or '').lower()
    if mime in ALLOWED_IMAGE_TYPES:
        return ALLOWED_IMAGE_TYPES[mime]
    # Fall back to the filename when the client sends a vague content type.
    name = secure_filename(file_storage.filename or '')
    ext = os.path.splitext(name)[1].lower()
    if ext in set(ALLOWED_IMAGE_TYPES.values()):
        return ext
    raise MediaError(
        "unsupported image type — use JPEG, PNG, HEIC or WebP"
    )


def _save(file_storage, rel_dir):
    """Validate and store an upload under `rel_dir`; returns (key, mime, size).

    The returned key is relative to the backend's root, so the database never
    holds an absolute path (which would break if the deployment layout changed)
    nor a bucket name (which would break if the bucket were renamed).
    """
    if file_storage is None or not file_storage.filename:
        raise MediaError("a photo file is required")

    ext = _ext_for(file_storage)

    # Size is only known after reading; seek back so the write sends the whole file.
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size == 0:
        raise MediaError("the uploaded photo is empty")
    if size > MAX_IMAGE_BYTES:
        raise MediaError(f"photo is too large (max {MAX_IMAGE_BYTES // (1024 * 1024)}MB)")

    name = f"{uuid.uuid4().hex}{ext}"
    rel_path = os.path.join(rel_dir, name)
    mime = file_storage.mimetype or 'image/jpeg'

    if using_s3():
        # upload_fileobj streams in parts rather than buffering the whole image.
        _s3_client().upload_fileobj(
            file_storage.stream, S3_BUCKET, _s3_key(rel_path),
            ExtraArgs={'ContentType': mime},
        )
    else:
        abs_dir = os.path.join(MEDIA_ROOT, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        file_storage.save(os.path.join(MEDIA_ROOT, rel_path))

    return rel_path, mime, size


def save_order_photo(file_storage, order_id):
    """Persist an uploaded order photo; returns (key, mime, size_bytes)."""
    return _save(file_storage, os.path.join('orders', str(order_id)))


def save_dealer_location_photo(file_storage, dealer_id):
    """Persist a dealer-location proof photo; returns (key, mime, size).

    These are deliberately short-lived: the photo exists only to let an admin
    verify where the rep was standing. Once the submission is approved or
    rejected the coordinates are kept and the image is deleted by
    `delete_media`, so proof photos don't accumulate.
    """
    return _save(file_storage, os.path.join('dealer_locations', str(dealer_id)))


def delete_media(relative_path):
    """Delete a stored file. Missing files are fine — deletion is idempotent, so
    a retried review can't fail on an already-removed photo."""
    if not relative_path:
        return
    if using_s3():
        try:
            _s3_client().delete_object(Bucket=S3_BUCKET, Key=_s3_key(relative_path))
        except MediaError:
            raise
        except Exception:  # pragma: no cover - network / permissions
            pass
        return
    try:
        os.remove(absolute_path(relative_path))
    except (FileNotFoundError, MediaError):
        pass


def exists(relative_path):
    """Whether the stored object is still there — lets a caller 404 a dangling row."""
    if not relative_path:
        return False
    if using_s3():
        try:
            _s3_client().head_object(Bucket=S3_BUCKET, Key=_s3_key(relative_path))
            return True
        except MediaError:
            raise
        except Exception:
            return False
    try:
        return os.path.exists(absolute_path(relative_path))
    except MediaError:
        return False


def send_media(relative_path, mime=None):
    """Return a Flask response delivering the stored file.

    Local: streams from disk. S3: 302 to a presigned URL that expires shortly, so
    the bytes go straight from S3 to the client. Callers must already have checked
    that this requester may see this file.

    Returns None when the object is gone, so the caller can 404 in its own
    vocabulary instead of this layer inventing a response shape.
    """
    mime = mime or 'image/jpeg'
    if using_s3():
        client = _s3_client()
        try:
            client.head_object(Bucket=S3_BUCKET, Key=_s3_key(relative_path))
        except MediaError:
            raise
        except Exception:
            return None
        url = client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET, 'Key': _s3_key(relative_path)},
            ExpiresIn=S3_URL_TTL,
        )
        return redirect(url, code=302)

    path = absolute_path(relative_path)
    if not os.path.exists(path):
        return None
    return send_file(path, mimetype=mime)


def absolute_path(relative_path):
    """Resolve a stored key to a local path, refusing anything that escapes
    MEDIA_ROOT. Local backend only — an S3 key has no filesystem location."""
    if using_s3():
        raise MediaError("no local path exists when MEDIA_BACKEND=s3")
    root = os.path.abspath(MEDIA_ROOT)
    full = os.path.abspath(os.path.join(root, relative_path))
    if not full.startswith(root + os.sep):
        raise MediaError("invalid media path")
    return full
