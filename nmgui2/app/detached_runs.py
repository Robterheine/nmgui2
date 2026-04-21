"""
Detached run management for NMGUI2.

Handles starting, tracking, and reconciling PsN/NONMEM runs that must
survive NMGUI2 closure — for example when NMGUI2 is used over SSH/MobaXterm.

Design:
  - Each detached run writes a <run_id>.nmgui.pid file to the project folder.
  - stdout/stderr are redirected to a <run_id>.nmgui.log file in the same folder.
  - NMGUI2 uses the PID file to check liveness; the log file is tailed for output.
  - On next NMGUI2 startup (reconcile()), finished runs are detected and their
    run records are finalised without relying on any shutdown hooks.
"""

import json
import logging
import os
import shlex
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .constants import IS_WIN, APP_VERSION

_log = logging.getLogger(__name__)

IS_POSIX = not IS_WIN


# ── File path helpers ──────────────────────────────────────────────────────────

def pid_file_path(project_dir: str, run_id: str) -> Path:
    return Path(project_dir) / f'{run_id}.nmgui.pid'


def log_file_path(project_dir: str, run_id: str) -> Path:
    return Path(project_dir) / f'{run_id}.nmgui.log'


# ── Start ──────────────────────────────────────────────────────────────────────

def start_detached(cmd: str, cwd: str, stem: str, tool: str, model_path: str) -> dict:
    """Launch cmd fully detached from NMGUI2's process lifetime.

    Returns a descriptor dict for tracking the run.
    Raises RuntimeError on Windows or on launch failure.
    """
    from .tools import get_login_env
    from .run_records import create_run_record, load_run_records, save_run_records

    if IS_WIN:
        raise RuntimeError('Detached runs are not supported on Windows.')

    run_id = f'{stem}_{int(time.time())}'
    log_path = log_file_path(cwd, run_id)
    pid_path = pid_file_path(cwd, run_id)

    # Redirect stdout+stderr to the log file; nohup ignores SIGHUP.
    # start_new_session=True also calls setsid() — belt-and-suspenders.
    wrapped = f'nohup {cmd} > {shlex.quote(str(log_path))} 2>&1'

    proc = subprocess.Popen(
        wrapped,
        shell=True,
        cwd=cwd,
        env=get_login_env(),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    pid = proc.pid
    started_epoch = int(time.time())

    pid_data = {
        'pid':           pid,
        'started_epoch': started_epoch,
        'stem':          stem,
        'tool':          tool,
        'log_file':      str(log_path),
        'run_id':        run_id,
        'model_path':    model_path,
        'command':       cmd,
    }
    try:
        pid_path.write_text(json.dumps(pid_data, indent=2))
    except Exception as e:
        _log.warning('Could not write PID file %s: %s', pid_path, e)

    # Create and persist a run record immediately
    record = create_run_record(model_path, cmd, tool)
    record['run_id']   = run_id
    record['status']   = 'detached'
    record['log_file'] = str(log_path)
    records = load_run_records(cwd)
    records.insert(0, record)
    save_run_records(cwd, records[:500])

    descriptor = {
        'run_id':        run_id,
        'stem':          stem,
        'tool':          tool,
        'pid':           pid,
        'started_epoch': started_epoch,
        'log_file':      str(log_path),
        'pid_file':      str(pid_path),
        'cwd':           cwd,
        'model_path':    model_path,
        'command':       cmd,
    }
    _log.info('Started detached run %s: PID %d  log %s', run_id, pid, log_path)
    return descriptor


# ── Liveness ───────────────────────────────────────────────────────────────────

def is_alive(pid: int, started_epoch: int | None = None) -> bool:
    """Return True if the process with this PID is still running.

    On Linux, also verifies the start time to guard against PID reuse.
    """
    if not IS_POSIX or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours — treat as alive

    # Linux: cross-check start time via /proc to guard against PID reuse
    if started_epoch is not None:
        proc_stat = Path(f'/proc/{pid}/stat')
        if proc_stat.exists():
            try:
                fields = proc_stat.read_text().split()
                clk_tck = os.sysconf('SC_CLK_TCK')
                boot_time = _boot_time()
                if boot_time is not None:
                    proc_epoch = int(boot_time + int(fields[21]) / clk_tck)
                    if abs(proc_epoch - started_epoch) > 5:
                        return False  # different process reusing the PID
            except Exception:
                pass
    return True


def _boot_time() -> 'float | None':
    """Return system boot time as Unix epoch (Linux only). Returns None on failure."""
    try:
        for line in Path('/proc/stat').read_text().splitlines():
            if line.startswith('btime '):
                return float(line.split()[1])
    except Exception:
        pass
    return None


# ── Kill ───────────────────────────────────────────────────────────────────────

def kill_detached(pid: int) -> bool:
    """Send SIGTERM to a detached run's process group. Returns True if sent."""
    if not IS_POSIX or pid <= 0:
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except Exception as e:
            _log.warning('Could not kill PID %d: %s', pid, e)
            return False


# ── Reconcile ─────────────────────────────────────────────────────────────────

def reconcile(project_dir: str) -> tuple[list, list]:
    """Reconcile detached run records in project_dir against live PIDs.

    For runs that have finished, finalises their run record (status, timestamps,
    OFV) and removes the PID file.  Completed timestamp is taken from the log
    file's mtime — not from NMGUI2's clock — so it is accurate regardless of
    when NMGUI2 is reopened.

    Returns (still_running: list[dict], just_finished: list[dict]).
    """
    from .run_records import load_run_records, save_run_records, finalize_run_record

    records = load_run_records(project_dir)
    changed = False
    still_running: list[dict] = []
    just_finished: list[dict] = []

    for i, rec in enumerate(records):
        if rec.get('status') not in ('detached', 'running'):
            continue

        run_id   = rec.get('run_id', '')
        pid_path = pid_file_path(project_dir, run_id)

        if not pid_path.exists():
            # Interrupted monitored run (no PID file) — mark as interrupted
            if rec.get('status') == 'running':
                records[i]['status'] = 'interrupted'
                changed = True
            continue

        try:
            pid_data = json.loads(pid_path.read_text())
        except Exception:
            continue

        pid           = pid_data.get('pid', 0)
        started_epoch = pid_data.get('started_epoch')

        if is_alive(pid, started_epoch):
            still_running.append(pid_data)
            continue

        # Process has ended — determine outcome and finalise record
        log_path   = Path(pid_data.get('log_file', ''))
        model_path = rec.get('model_path', '')
        exit_code  = _infer_exit_code(log_path, model_path)

        records[i] = finalize_run_record(rec, model_path, exit_code)

        # Override completed timestamp with log-file mtime for accuracy
        if log_path.exists():
            records[i]['completed'] = datetime.fromtimestamp(
                log_path.stat().st_mtime
            ).isoformat()
            # Recalculate duration using accurate completed time
            try:
                started   = datetime.fromisoformat(rec.get('started', ''))
                completed = datetime.fromisoformat(records[i]['completed'])
                records[i]['duration_seconds'] = int((completed - started).total_seconds())
            except Exception:
                pass

        try:
            pid_path.unlink(missing_ok=True)
        except Exception:
            pass

        changed = True
        just_finished.append(pid_data)
        _log.info('Reconciled detached run %s: %s', run_id, records[i]['status'])

    if changed:
        save_run_records(project_dir, records)

    return still_running, just_finished


def _infer_exit_code(log_path: Path, model_path: str) -> int:
    """Infer whether a run succeeded from .lst content and log tail."""
    _success = (
        'MINIMIZATION SUCCESSFUL', 'STATISTICAL PORTION WAS COMPLETED',
        'IMPORTANCE SAMPLING', 'BAYES ESTIMATION', 'NUTS ESTIMATION',
        'ITERATIVE TWO STAGE',
    )
    if model_path:
        p = Path(model_path)
        for lst in [p.parent / p.stem / f'{p.stem}.lst', p.parent / f'{p.stem}.lst']:
            if lst.exists():
                try:
                    tail = lst.read_text('utf-8', errors='replace')[-2000:]
                    if any(ph in tail for ph in _success):
                        return 0
                except Exception:
                    pass
    if log_path.exists():
        try:
            tail = log_path.read_text('utf-8', errors='replace')[-1000:]
            if any(ph in tail for ph in _success):
                return 0
        except Exception:
            pass
    return 1  # conservative: assume failure when uncertain


# ── Load live descriptors from PID files ──────────────────────────────────────

def load_live_descriptors(project_dir: str) -> list[dict]:
    """Scan project_dir for .nmgui.pid files; return descriptors for still-alive runs."""
    result = []
    for pid_file in sorted(Path(project_dir).glob('*.nmgui.pid')):
        try:
            data = json.loads(pid_file.read_text())
        except Exception as e:
            _log.debug('Could not read PID file %s: %s', pid_file, e)
            continue
        pid     = data.get('pid', 0)
        started = data.get('started_epoch')
        if is_alive(pid, started):
            data['pid_file'] = str(pid_file)
            result.append(data)
        else:
            # Stale PID file from a previous session — clean up silently
            try:
                pid_file.unlink(missing_ok=True)
            except Exception:
                pass
    return result
