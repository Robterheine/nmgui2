import os, re, signal, subprocess, logging, time
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from .constants import IS_WIN
from .config import get_meta_entry
from .tools import get_login_env

_log = logging.getLogger(__name__)

_RE_PROB   = re.compile(r'\$PROB(?:LEM)?\s+(.*?)(?:\n|\$)', re.IGNORECASE)
_RE_DATA   = re.compile(r'\$DATA\s+(\S+)', re.IGNORECASE)
_RE_BASEDON = re.compile(r'^;;\s*1\.\s*Based on:\s*(\S+)', re.MULTILINE | re.IGNORECASE)

try:
    from ..parser import (
        parse_lst, extract_param_names, extract_table_files,
    )
    HAS_PARSER = True
except Exception:
    HAS_PARSER = False

try:
    from .dataset_check import check_dataset
    HAS_DS_CHECK = True
except Exception:
    HAS_DS_CHECK = False


class ScanWorker(QThread):
    result = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, directory, meta):
        super().__init__()
        self.directory = directory
        self.meta = meta
        self._cancelled = False

    def cancel(self):
        """Request cancellation of the scan."""
        self._cancelled = True

    def run(self):
        if not HAS_PARSER:
            self.error.emit('parser.py not found'); return
        try:
            models = []
            p = Path(self.directory)
            _ds_cache: dict = {}
            for f in sorted(p.iterdir()):
                # Check for cancellation
                if self._cancelled:
                    _log.debug('ScanWorker cancelled')
                    return
                if not f.is_file() or f.suffix.lower() not in ('.mod', '.ctl'):
                    continue
                m = {k: v for k, v in {
                    'name': f.name, 'path': str(f), 'stem': f.stem,
                    'has_run': False, 'lst_path': '', 'stale': False,
                    'ofv': None, 'minimization_successful': None, 'minimization_message': '',
                    'covariance_step': None, 'n_individuals': None, 'n_observations': None,
                    'n_estimated_params': None, 'aic': None, 'bic': None, 'runtime': None,
                    'runtime_total': None, 'subproblems': [],
                    'estimation_method': '', 'thetas': [], 'omegas': [], 'sigmas': [],
                    'theta_ses': [], 'omega_ses': [], 'sigma_ses': [],
                    'omega_se_matrix': [], 'sigma_se_matrix': [],
                    'theta_names': [], 'omega_names': [], 'sigma_names': [],
                    'theta_units': [], 'omega_units': [], 'sigma_units': [],
                    'theta_fixed': [], 'omega_fixed': [], 'sigma_fixed': [],
                    'eta_shrinkage': [], 'eps_shrinkage': [],
                    'condition_number': None, 'boundary': False,
                    'etabar': [], 'etabar_se': [], 'etabar_pval': [],
                    'cov_failure_reason': '', 'correlation_matrix': [], 'cor_labels': [],
                    'table_files': [], 'table_runno': '', 'problem': '', 'data_file': '',
                    'comment': '', 'star': False, 'based_on': None, 'status_tag': '',
                    'notes': '', 'n_thetas': 0, 'n_omegas': 0,
                    'dataset_report': None,
                }.items()}
                mod_mtime = f.stat().st_mtime
                data_mtime = None
                try:
                    content = f.read_text('utf-8', errors='replace')
                    prob = _RE_PROB.search(content)
                    if prob: m['problem'] = prob.group(1).strip()[:120]
                    dat = _RE_DATA.search(content)
                    if dat:
                        m['data_file'] = dat.group(1)
                        dp = p / m['data_file']
                        if dp.is_file(): data_mtime = dp.stat().st_mtime
                    if HAS_DS_CHECK and m['data_file']:
                        try:
                            data_key = m['data_file']
                            if data_key not in _ds_cache:
                                _ds_cache[data_key] = check_dataset(str(f), data_key)
                            m['dataset_report'] = _ds_cache[data_key]
                        except Exception:
                            pass
                    pn = extract_param_names(content)
                    for k in ('theta_names', 'omega_names', 'sigma_names',
                              'theta_units', 'omega_units', 'sigma_units',
                              'theta_fixed', 'omega_fixed', 'sigma_fixed'):
                        m[k] = pn.get(k, [])
                    # Parse parent model from PsN convention: ";; 1. Based on: runXX"
                    based_m = _RE_BASEDON.search(content)
                    if based_m:
                        m['based_on'] = based_m.group(1).strip()
                    tf = extract_table_files(content)
                    m['table_files'] = tf['table_files']
                    m['table_runno'] = tf['runno']
                except Exception:
                    pass
                # Find .lst
                lst_same = p / (f.stem + '.lst'); lst_sub = None
                rd = p / f.stem
                if rd.is_dir():
                    cands = list(rd.glob('*.lst'))
                    if cands: lst_sub = cands[0]
                lst_path = lst_same if lst_same.is_file() else lst_sub
                if lst_path:
                    m['has_run'] = True; m['lst_path'] = str(lst_path)
                    try:
                        r = parse_lst(str(lst_path))
                        for k in ('ofv', 'minimization_successful', 'minimization_message',
                                  'covariance_step', 'n_individuals', 'n_observations',
                                  'n_estimated_params', 'aic', 'bic', 'runtime', 'runtime_total',
                                  'estimation_method', 'thetas', 'omegas', 'sigmas',
                                  'theta_ses', 'omega_ses', 'sigma_ses',
                                  'omega_se_matrix', 'sigma_se_matrix',
                                  'condition_number', 'boundary', 'etabar', 'etabar_se',
                                  'etabar_pval', 'cov_failure_reason', 'eta_shrinkage',
                                  'eps_shrinkage', 'correlation_matrix', 'cor_labels',
                                  'subproblems'):
                            m[k] = r.get(k)
                        m['n_thetas'] = len(r.get('thetas', [])); m['n_omegas'] = len(r.get('omegas', []))
                        lst_mtime = lst_path.stat().st_mtime
                        if mod_mtime > lst_mtime+2: m['stale'] = True
                        elif data_mtime and data_mtime > lst_mtime+2: m['stale'] = True
                    except Exception as e: _log.debug(f'Parse error for {f.name}: {e}')
                meta_e = get_meta_entry(self.meta, f)
                m.update({'comment': meta_e['comment'], 'star': meta_e['star'],
                          'based_on': meta_e['based_on'], 'status_tag': meta_e['status'],
                          'notes': meta_e['notes']})
                models.append(m)
            self.result.emit(models)
        except Exception as e:
            self.error.emit(str(e))


class RunWorker(QThread):
    line_out = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, cmd, cwd):
        super().__init__()
        self.cmd = cmd; self.cwd = cwd
        self._proc = None; self._env = get_login_env()

    def run(self):
        try:
            kw = dict(shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      cwd=self.cwd, text=True, bufsize=1, env=self._env)
            if not IS_WIN: kw['start_new_session'] = True
            else: kw['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            self._proc = subprocess.Popen(self.cmd, **kw)
            for line in iter(self._proc.stdout.readline, ''):
                self.line_out.emit(line.rstrip())
            self._proc.wait()
            self.finished.emit(self._proc.returncode)
        except Exception as e:
            self.line_out.emit(f'[ERROR] {e}'); self.finished.emit(-1)

    def stop(self):
        self._send_signal(signal.SIGTERM if not IS_WIN else None, force=False)

    def stop_hard(self):
        self._send_signal(signal.SIGKILL if not IS_WIN else None, force=True)

    def _send_signal(self, sig, force):
        # Belt-and-suspenders: stop() is connected to a button only enabled after
        # run() has assigned self._proc, but guard explicitly in case of teardown.
        if not self.isRunning() or not self._proc:
            return
        try:
            if IS_WIN:
                subprocess.run(
                    ['taskkill', '/T', '/F', '/PID', str(self._proc.pid)],
                    capture_output=True)
            else:
                os.killpg(os.getpgid(self._proc.pid), sig)
        except Exception as e:
            _log.debug(f'Error stopping process (force={force}): {e}')
