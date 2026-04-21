import json, logging
from .constants import (
    META_FILE, SETTINGS_FILE, BOOKMARKS_FILE, RUNS_FILE, HOME, _cfg_lock
)

_log = logging.getLogger(__name__)


def load_meta():
    with _cfg_lock:
        if META_FILE.exists():
            try: return json.loads(META_FILE.read_text('utf-8'))
            except Exception as e: _log.warning(f'Failed to load meta: {e}')
    return {}


def save_meta(meta):
    with _cfg_lock:
        tmp_path = META_FILE.with_suffix('.tmp')
        try:
            tmp_path.write_text(json.dumps(meta, indent=2), encoding='utf-8')
            tmp_path.replace(META_FILE)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise


def get_meta_entry(meta, path):
    e = meta.get(str(path), {})
    if isinstance(e, str): e = {'comment': e, 'star': False, 'based_on': None}
    return {
        'comment':     e.get('comment', ''),
        'star':        e.get('star', False),
        'based_on':    e.get('based_on', None),
        'status':      e.get('status', ''),
        'notes':       e.get('notes', ''),
        'decision':    e.get('decision', ''),
        'tags':        e.get('tags', []),
        'param_notes': e.get('param_notes', {}),
    }


def load_settings():
    with _cfg_lock:
        if SETTINGS_FILE.exists():
            try: return json.loads(SETTINGS_FILE.read_text('utf-8'))
            except Exception as e: _log.warning(f'Failed to load settings: {e}')
    return {'working_directory': str(HOME), 'psn_path': '', 'nonmem_path': ''}


def save_settings(s):
    with _cfg_lock:
        tmp = SETTINGS_FILE.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps(s, indent=2), encoding='utf-8')
            tmp.replace(SETTINGS_FILE)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise


def load_bookmarks():
    with _cfg_lock:
        if BOOKMARKS_FILE.exists():
            try: return json.loads(BOOKMARKS_FILE.read_text('utf-8'))
            except Exception as e: _log.warning(f'Failed to load bookmarks: {e}')
    return []


def save_bookmarks(b):
    with _cfg_lock:
        tmp = BOOKMARKS_FILE.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps(b, indent=2), encoding='utf-8')
            tmp.replace(BOOKMARKS_FILE)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise


def load_runs():
    with _cfg_lock:
        if RUNS_FILE.exists():
            try: return json.loads(RUNS_FILE.read_text('utf-8'))
            except Exception as e: _log.warning(f'Failed to load runs: {e}')
    return []


def save_runs(runs):
    with _cfg_lock:
        tmp = RUNS_FILE.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps(runs, indent=2, default=str), encoding='utf-8')
            tmp.replace(RUNS_FILE)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise


def get_all_tags(meta):
    tags = set()
    for entry in meta.values():
        if isinstance(entry, dict):
            for tag in entry.get('tags', []):
                tags.add(tag)
    return sorted(tags)
