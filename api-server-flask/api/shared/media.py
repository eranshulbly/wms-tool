# -*- encoding: utf-8 -*-
"""
Persistent storage for uploaded media (order photos).

Distinct from api/shared/upload_utils.py, which writes a *temporary* file, parses
it and deletes it. Files written here are kept and served back later.

Bytes live on disk under MEDIA_ROOT; only the relative path is stored in the
database. They are served by an authenticated endpoint rather than a public
static path — an order photo should not sit on a guessable URL.
"""

import os
import uuid

from werkzeug.utils import secure_filename

# /app is the container's working dir (the repo is bind-mounted there in dev), so
# media/ persists on the host across container restarts.
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', os.path.join(os.getcwd(), 'media'))

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


def save_order_photo(file_storage, order_id):
    """Persist an uploaded photo and return (relative_path, mime_type, size_bytes).

    The returned path is relative to MEDIA_ROOT so the database never holds an
    absolute path that would break if the deployment layout changes.
    """
    if file_storage is None or not file_storage.filename:
        raise MediaError("a photo file is required")

    ext = _ext_for(file_storage)

    # Size is only known after reading; seek back so save() writes the whole file.
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size == 0:
        raise MediaError("the uploaded photo is empty")
    if size > MAX_IMAGE_BYTES:
        raise MediaError(f"photo is too large (max {MAX_IMAGE_BYTES // (1024 * 1024)}MB)")

    rel_dir = os.path.join('orders', str(order_id))
    abs_dir = os.path.join(MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    name = f"{uuid.uuid4().hex}{ext}"
    file_storage.save(os.path.join(abs_dir, name))
    return os.path.join(rel_dir, name), (file_storage.mimetype or 'image/jpeg'), size


def absolute_path(relative_path):
    """Resolve a stored relative path, refusing anything that escapes MEDIA_ROOT."""
    root = os.path.abspath(MEDIA_ROOT)
    full = os.path.abspath(os.path.join(root, relative_path))
    if not full.startswith(root + os.sep):
        raise MediaError("invalid media path")
    return full
