import json, re, subprocess, hashlib, logging, time
from datetime import datetime
from pathlib import Path
from .constants import IS_WIN, APP_VERSION

_log = logging.getLogger(__name__)

RUN_RECORDS_FILE = 'nmgui_run_records.json'


def _file_hash(path):
    """Compute SHA-256 hash of a file."""
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return f'sha256:{h.hexdigest()[:16]}'
    except Exception:
        return None


def _detect_nonmem_version(cwd):
    """Attempt to detect NONMEM version from environment or output."""
    from .tools import get_login_env  # deferred to avoid circular import
    import shutil as sh
    # Check for nmfe script version
    for ver in ['75', '74', '73']:
        if (Path(cwd) / f'nmfe{ver}').exists() or sh.which(f'nmfe{ver}'):
            return f'7.{ver[1]}'
    # Try to get from psn
    try:
        _wkw = {'creationflags': subprocess.CREATE_NO_WINDOW} if IS_WIN else {}
        r = subprocess.run(['psn', '-nm_versions'], capture_output=True, text=True, timeout=5, env=get_login_env(), **_wkw)
        if r.stdout:
            match = re.search(r'default is (\d+\.\d+)', r.stdout)
            if match: return match.group(1)
    except Exception as e: _log.debug(f'Could not detect NONMEM version: {e}')
    return 'unknown'


def _detect_psn_version():
    """Detect PsN version."""
    from .tools import get_login_env  # deferred to avoid circular import
    try:
        _wkw = {'creationflags': subprocess.CREATE_NO_WINDOW} if IS_WIN else {}
        r = subprocess.run(['psn', '-version'], capture_output=True, text=True, timeout=5, env=get_login_env(), **_wkw)
        if r.stdout:
            match = re.search(r'PsN\s+(\d+\.\d+\.\d+)', r.stdout)
            if match: return match.group(1)
    except Exception as e: _log.debug(f'Could not detect PsN version: {e}')
    return 'unknown'


def load_run_records(project_dir):
    """Load run records from project directory."""
    rr_path = Path(project_dir) / RUN_RECORDS_FILE
    if rr_path.exists():
        try: return json.loads(rr_path.read_text('utf-8'))
        except Exception as e: _log.warning(f'Failed to load run records from {rr_path}: {e}')
    return []


def save_run_records(project_dir, records):
    """Save run records to project directory (atomic write)."""
    rr_path = Path(project_dir) / RUN_RECORDS_FILE
    tmp_path = rr_path.with_suffix('.tmp')
    try:
        tmp_path.write_text(json.dumps(records, indent=2, default=str), encoding='utf-8')
        tmp_path.replace(rr_path)  # Atomic on POSIX
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def create_run_record(model_path, cmd, tool):
    """Create a new run record at run start."""
    model_path = Path(model_path)
    cwd = model_path.parent

    # Read control stream
    try:
        control_stream = model_path.read_text('utf-8', errors='replace')
    except Exception:
        control_stream = ''

    # Find data file from control stream
    data_file = None
    data_hash = None
    data_rows = None
    data_subjects = None
    data_match = re.search(r'\$DATA\s+(\S+)', control_stream)
    if data_match:
        data_ref = data_match.group(1)
        # Resolve relative path
        data_path = (cwd / data_ref).resolve() if not Path(data_ref).is_absolute() else Path(data_ref)
        if data_path.exists():
            data_file = str(data_path.name)
            data_hash = _file_hash(data_path)
            # Count rows and subjects
            try:
                lines = data_path.read_text('utf-8', errors='replace').strip().split('\n')
                data_rows = len(lines) - 1  # Exclude header
                # Count unique IDs (first column, skip header)
                if len(lines) > 1:
                    ids = set()
                    for line in lines[1:]:
                        parts = re.split(r'[,\s]+', line.strip())
                        if parts: ids.add(parts[0])
                    data_subjects = len(ids)
            except Exception as e: _log.debug(f'Could not count data rows/subjects: {e}')

    record = {
        'run_id': f"{model_path.stem}_{int(time.time())}",
        'model_path': str(model_path),
        'model_stem': model_path.stem,
        'control_stream_hash': _file_hash(model_path),
        'control_stream_snapshot': control_stream,
        'data_file': data_file,
        'data_file_hash': data_hash,
        'data_n_rows': data_rows,
        'data_n_subjects': data_subjects,
        'tool': tool,
        'command': cmd,
        'nonmem_version': _detect_nonmem_version(str(cwd)),
        'psn_version': _detect_psn_version(),
        'nmgui_version': APP_VERSION,
        'started': datetime.now().isoformat(),
        'completed': None,
        'duration_seconds': None,
        'status': 'running',
        'exit_code': None,
        'ofv': None,
        'minimization_successful': None,
        'covariance_step': None,
        'warnings': [],
        'output_hashes': {},
    }
    return record


def finalize_run_record(record, model_path, exit_code):
    """Finalize run record after completion."""
    try:
        from nmgui2.parser import parse_lst
        HAS_PARSER = True
    except ImportError:
        HAS_PARSER = False

    model_path = Path(model_path)
    cwd = model_path.parent
    stem = model_path.stem

    record['completed'] = datetime.now().isoformat()
    record['exit_code'] = exit_code
    record['status'] = 'completed' if exit_code == 0 else f'failed ({exit_code})'

    # Calculate duration
    try:
        started = datetime.fromisoformat(record['started'])
        completed = datetime.fromisoformat(record['completed'])
        record['duration_seconds'] = int((completed - started).total_seconds())
    except Exception as e: _log.debug(f'Could not calculate run duration: {e}')

    # Parse results if run succeeded
    run_dir = cwd / stem
    lst_path = run_dir / f'{stem}.lst'
    if not lst_path.exists():
        lst_path = cwd / f'{stem}.lst'

    if lst_path.exists() and HAS_PARSER:
        try:
            parsed = parse_lst(str(lst_path))
            record['ofv'] = parsed.get('ofv')
            record['minimization_successful'] = parsed.get('minimization_successful')
            record['covariance_step'] = parsed.get('covariance_step')
            # Extract warnings
            warnings = []
            if parsed.get('boundary'): warnings.append('PARAMETER NEAR BOUNDARY')
            if parsed.get('eta_shrinkage'):
                high_shr = [s for s in parsed['eta_shrinkage'] if s and s > 30]
                if high_shr: warnings.append(f'HIGH ETA SHRINKAGE (>{30}%)')
            record['warnings'] = warnings
        except Exception as e: _log.warning(f'Failed to parse LST for run record: {e}')

    # Hash output files
    output_files = ['lst', 'ext', 'phi', 'cov', 'cor', 'coi']
    for ext in output_files:
        for loc in [run_dir / f'{stem}.{ext}', cwd / f'{stem}.{ext}']:
            if loc.exists():
                record['output_hashes'][ext] = _file_hash(loc)
                break

    return record
