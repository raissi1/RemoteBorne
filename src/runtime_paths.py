"""Shared portable export paths and non-destructive legacy-folder migration."""
import os
from pathlib import Path
from datetime import datetime
import uuid


def export_directory(runtime_root):
    return os.path.join(os.path.abspath(runtime_root), 'export')


def normalize_export_folder(value, runtime_root):
    root = os.path.abspath(runtime_root)
    raw = (value or '').strip()
    if not raw:
        return export_directory(root)
    candidate = os.path.normpath(os.path.expanduser(raw))
    if not os.path.isabs(candidate):
        candidate = os.path.join(root, candidate)
    if os.path.isfile(candidate) or (not os.path.isdir(candidate) and
            os.path.splitext(candidate)[1].lower() in {'.properties', '.ini', '.txt', '.csv', '.json'}):
        candidate = os.path.dirname(candidate)
    candidate = os.path.abspath(candidate)
    legacy = Path(root) / 'exports'
    try:
        relative = Path(candidate).relative_to(legacy)
    except ValueError:
        return candidate  # Keep explicitly selected external folders unchanged.
    return str(Path(export_directory(root)) / relative)


def consolidate_export_folders(runtime_root):
    """Retain the entire legacy tree; never merge over existing export files.

    If both roots exist, place the old tree in a unique dated child of export.
    Rename is on the same volume. On failure the old tree remains intact and a
    diagnostic is returned, allowing a retry after closing an older RBM instance.
    """
    legacy = Path(runtime_root) / 'exports'
    target = Path(export_directory(runtime_root))
    if not legacy.exists():
        return None
    if legacy.is_symlink() or target.is_symlink() or not legacy.is_dir():
        return 'Legacy exports was not moved because it is not a regular directory.'
    try:
        if not target.exists():
            legacy.rename(target)
        else:
            archive = target / ('legacy_exports_' + datetime.now().strftime('%Y-%m-%d_%H-%M-%S_') + uuid.uuid4().hex[:8])
            legacy.rename(archive)
    except OSError as exc:
        return f'Unable to consolidate exports into export; original files retained: {exc}'
    return None
