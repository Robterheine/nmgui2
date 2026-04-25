import os, re, subprocess, logging, csv, math, statistics
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton,
                              QLabel, QTextEdit, QTableWidget, QTableWidgetItem,
                              QHeaderView, QAbstractItemView, QGroupBox, QComboBox,
                              QFileDialog, QMessageBox, QProgressBar, QCheckBox, QSpinBox,
                              QPlainTextEdit, QStackedWidget, QRadioButton, QButtonGroup,
                              QFormLayout, QDoubleSpinBox, QGridLayout, QLineEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QPalette

from ..app.theme import C, T
from ..app.constants import (IS_WIN, IS_MAC, BOOT_COMPLETION_PASS, BOOT_COMPLETION_WARN,
                              BOOT_COMPLETION_FAIL, BOOT_BIAS_PASS, BOOT_BIAS_WARN,
                              BOOT_BIAS_FAIL, BOOT_CORR_WARN, BOOT_CORR_FAIL,
                              SIR_KS_PASS, SIR_KS_WARN, SIR_MEDIAN_PASS, SIR_MEDIAN_WARN,
                              SIR_ESS_PASS, SIR_ESS_WARN, SIR_ESS_FAIL,
                              SIR_ESS_ABS_WARN, SIR_ESS_ABS_FAIL)
from ..app.tools import _check_psn_tools, get_login_env
from ..app.format import fmt_num

_log = logging.getLogger(__name__)
HOME = Path.home()

try:
    import numpy as np; HAS_NP = True
except ImportError:
    HAS_NP = False

try:
    from scipy import stats; HAS_SCIPY = True
    from scipy.stats import chi2 as scipy_chi2, kstest as scipy_kstest
except ImportError:
    HAS_SCIPY = False
    scipy_chi2 = None
    scipy_kstest = None

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


class BootstrapParser:
    """Parse PsN bootstrap output folder and compute diagnostics."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.raw_df = None
        self.samples_df = None
        self.original = {}
        self.param_cols = []
        self.n_requested = 0
        self.n_successful = 0

    def parse(self) -> dict:
        # Find raw_results file
        raw_files = list(self.folder.glob('raw_results_*.csv'))
        if not raw_files:
            raise FileNotFoundError('No raw_results_*.csv found in bootstrap folder')

        # Read CSV
        with open(raw_files[0], 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            raise ValueError('raw_results file is empty')

        # Identify parameter columns
        all_cols = list(rows[0].keys())
        self.param_cols = [c for c in all_cols
                          if c.startswith(('THETA', 'OMEGA', 'SIGMA'))
                          and not c.endswith(('SE', 'RSE', '_SE'))]

        # Find original model row (usually model==0 or 'original')
        orig_row = None
        for row in rows:
            model_val = row.get('model', '').lower()
            if model_val in ('0', 'original', 'input') or 'original' in model_val:
                orig_row = row
                break
        if not orig_row:
            orig_row = rows[0]  # fallback

        # Extract original estimates
        self.original = {}
        for col in self.param_cols:
            try:
                self.original[col] = float(orig_row.get(col, 'nan'))
            except (ValueError, TypeError):
                self.original[col] = float('nan')

        # Filter to bootstrap samples only
        sample_rows = []
        for row in rows:
            model_val = row.get('model', '').lower()
            if model_val in ('0', 'original', 'input') or 'original' in model_val:
                continue
            sample_rows.append(row)

        self.n_requested = len(sample_rows)

        # Check minimization success and extract parameter values
        successful_samples = []
        for row in sample_rows:
            # Check for successful minimization
            min_ok = row.get('minimization_successful', '1')
            try:
                is_ok = int(float(min_ok)) == 1
            except (ValueError, TypeError):
                is_ok = True  # assume success if not specified

            # Also check if parameters are valid (not NA)
            params_valid = True
            param_vals = {}
            for col in self.param_cols:
                try:
                    val = float(row.get(col, 'nan'))
                    if math.isnan(val) or math.isinf(val):
                        params_valid = False
                        break
                    param_vals[col] = val
                except (ValueError, TypeError):
                    params_valid = False
                    break

            if is_ok and params_valid:
                successful_samples.append(param_vals)

        self.n_successful = len(successful_samples)
        self.samples_df = successful_samples  # list of dicts

        # Compute diagnostics
        diagnostics = self._assess()

        return {
            'method': 'bootstrap',
            'folder': str(self.folder),
            'n_requested': self.n_requested,
            'n_successful': self.n_successful,
            'param_cols': self.param_cols,
            'original': self.original,
            'samples': successful_samples,
            'diagnostics': diagnostics
        }

    def _assess(self) -> dict:
        checks = []

        # 1. Completion rate
        rate = self.n_successful / max(1, self.n_requested)
        if rate >= BOOT_COMPLETION_PASS:
            status = 'pass'
            interp = 'Excellent completion rate.'
        elif rate >= BOOT_COMPLETION_WARN:
            status = 'pass'
            interp = 'Good completion rate.'
        elif rate >= BOOT_COMPLETION_FAIL:
            status = 'warning'
            interp = 'Borderline completion. Results usable but precision may be affected.'
        else:
            status = 'fail'
            interp = 'Too many failures. Results unreliable.'

        checks.append({
            'name': 'Completion rate',
            'status': status,
            'value': f'{rate*100:.1f}% ({self.n_successful}/{self.n_requested})',
            'interpretation': interp
        })

        if not self.samples_df:
            return {'overall': 'FAILED', 'checks': checks}

        # 2. Bias assessment
        biases = {}
        max_bias = 0
        flagged_params = []
        for col in self.param_cols:
            orig_val = self.original.get(col, 0)
            sample_vals = [s[col] for s in self.samples_df if col in s]
            if not sample_vals:
                continue
            sample_vals.sort()
            median_val = statistics.median(sample_vals)

            if abs(orig_val) > 1e-6:
                bias = abs(median_val - orig_val) / abs(orig_val)
            else:
                bias = abs(median_val - orig_val)
            biases[col] = bias
            if bias > max_bias:
                max_bias = bias
            if bias >= BOOT_BIAS_WARN:
                flagged_params.append(col)

        if max_bias < BOOT_BIAS_PASS:
            status = 'pass'
            value = 'All parameters < 10% deviation'
            interp = 'No evidence of bias.'
        elif max_bias < BOOT_BIAS_WARN:
            status = 'pass'
            value = f'{len(flagged_params)} parameter(s) with 10-20% deviation'
            interp = 'Minor deviation, likely sampling noise.'
        elif max_bias < BOOT_BIAS_FAIL:
            status = 'warning'
            value = f'{len(flagged_params)} parameter(s) > 20% deviation: {", ".join(flagged_params[:3])}'
            interp = 'Moderate bias detected. May indicate model instability.'
        else:
            status = 'fail'
            value = f'{len(flagged_params)} parameter(s) > 50% deviation'
            interp = 'Severe bias. Original estimates likely unreliable.'

        checks.append({
            'name': 'Bias assessment',
            'status': status,
            'value': value,
            'interpretation': interp,
            'details': biases
        })

        # 3. Correlation check
        if HAS_NP and len(self.samples_df) >= 10:
            # Build matrix
            data_matrix = []
            for s in self.samples_df:
                row = [s.get(col, float('nan')) for col in self.param_cols]
                data_matrix.append(row)
            data_matrix = np.array(data_matrix)

            # Compute correlation
            try:
                corr_matrix = np.corrcoef(data_matrix, rowvar=False)
                np.fill_diagonal(corr_matrix, 0)
                max_corr = np.nanmax(np.abs(corr_matrix))

                if max_corr < BOOT_CORR_WARN:
                    status = 'pass'
                    interp = 'Parameters adequately distinguished.'
                elif max_corr < BOOT_CORR_FAIL:
                    status = 'warning'
                    interp = 'High correlation may indicate overparameterization.'
                else:
                    status = 'fail'
                    interp = 'Near-perfect correlation. Parameters not independently identifiable.'

                checks.append({
                    'name': 'Parameter correlations',
                    'status': status,
                    'value': f'Max |r| = {max_corr:.2f}',
                    'interpretation': interp
                })
            except Exception:
                pass  # skip correlation check if numpy fails

        # 4. Confidence interval validity
        ci_issues = []
        for col in self.param_cols:
            orig_val = self.original.get(col, 0)
            sample_vals = sorted([s[col] for s in self.samples_df if col in s])
            if len(sample_vals) < 20:
                continue
            lo = sample_vals[int(len(sample_vals) * 0.025)]
            hi = sample_vals[int(len(sample_vals) * 0.975)]
            if not (lo <= orig_val <= hi):
                ci_issues.append(col)

        if not ci_issues:
            status = 'pass'
            value = 'All CIs include point estimate'
            interp = 'Expected behavior.'
        elif len(ci_issues) <= 2:
            status = 'warning'
            value = f'{len(ci_issues)} CI(s) exclude estimate: {", ".join(ci_issues)}'
            interp = 'Unusual but not necessarily wrong. Suggests skewed distribution.'
        else:
            status = 'warning'
            value = f'{len(ci_issues)} CIs exclude point estimate'
            interp = 'Multiple CIs exclude estimate. Check for bias or instability.'

        checks.append({
            'name': 'CI validity',
            'status': status,
            'value': value,
            'interpretation': interp
        })

        # 5. Boundary proximity check (OMEGA parameters near zero)
        boundary_issues = []
        for col in self.param_cols:
            if not col.startswith('OMEGA'):
                continue
            sample_vals = [s[col] for s in self.samples_df if col in s]
            if not sample_vals:
                continue
            # Count samples near zero (< 0.001 or within 1% of zero)
            n_near_zero = sum(1 for v in sample_vals if abs(v) < 0.001)
            frac_at_zero = n_near_zero / len(sample_vals)
            if frac_at_zero > 0.15:  # More than 15% near boundary
                boundary_issues.append(f'{col} ({frac_at_zero*100:.0f}% near zero)')

        if not boundary_issues:
            status = 'pass'
            value = 'No boundary issues'
            interp = 'OMEGA parameters well away from zero boundary.'
        elif len(boundary_issues) <= 2:
            status = 'warning'
            value = f'{len(boundary_issues)} OMEGA(s) cluster near zero: {", ".join(boundary_issues[:2])}'
            interp = 'Percentile CIs may be biased upward. Consider log-transform or different parameterization.'
        else:
            status = 'warning'
            value = f'{len(boundary_issues)} OMEGAs near zero boundary'
            interp = 'Multiple variance parameters hitting zero. CIs unreliable for these parameters.'

        checks.append({
            'name': 'Boundary proximity',
            'status': status,
            'value': value,
            'interpretation': interp
        })

        # Overall assessment
        n_fail = sum(1 for c in checks if c['status'] == 'fail')
        n_warn = sum(1 for c in checks if c['status'] == 'warning')

        if n_fail > 0:
            overall = 'FAILED'
        elif n_warn > 2:
            overall = 'WARNING'
        elif n_warn > 0:
            overall = 'ACCEPTABLE'
        else:
            overall = 'PASSED'

        return {'overall': overall, 'checks': checks, 'biases': biases}

    def get_parameter_table(self) -> list:
        """Return list of dicts with parameter estimates and CIs."""
        if not self.samples_df:
            return []

        table = []
        for col in self.param_cols:
            orig_val = self.original.get(col, float('nan'))
            sample_vals = sorted([s[col] for s in self.samples_df if col in s])
            if not sample_vals:
                continue

            median = statistics.median(sample_vals)
            lo = sample_vals[int(len(sample_vals) * 0.025)]
            hi = sample_vals[int(len(sample_vals) * 0.975)]

            # RSE approximation
            if abs(median) > 1e-10:
                rse = (hi - lo) / (2 * 1.96 * abs(median)) * 100
            else:
                rse = float('nan')

            table.append({
                'parameter': col,
                'estimate': orig_val,
                'median': median,
                'ci_lo': lo,
                'ci_hi': hi,
                'rse': rse
            })
        return table


class SIRParser:
    """Parse PsN SIR output folder and compute diagnostics."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.dofv = []
        self.df = 0
        self.param_cols = []
        self.samples = []
        self.original = {}
        self.n_resamples = 0

    def parse(self) -> dict:
        raw_file = self.folder / 'raw_results_sir.csv'
        if not raw_file.exists():
            raise FileNotFoundError('raw_results_sir.csv not found in SIR folder')

        # Read CSV
        with open(raw_file, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            raise ValueError('raw_results_sir.csv is empty')

        # Identify parameter columns
        all_cols = list(rows[0].keys())
        self.param_cols = [c for c in all_cols
                          if c.startswith(('THETA', 'OMEGA', 'SIGMA'))
                          and not c.endswith(('SE', 'RSE', '_SE'))]

        self.df = len(self.param_cols)

        # Extract dOFV values
        dofv_col = None
        for cand in ('deltaofv', 'dOFV', 'DOFV', 'delta_ofv'):
            if cand in all_cols:
                dofv_col = cand
                break

        self.dofv = []
        for row in rows:
            try:
                if dofv_col:
                    val = float(row.get(dofv_col, 'nan'))
                else:
                    # Compute from OFV if available
                    continue
                if not math.isnan(val) and val >= 0:
                    self.dofv.append(val)
            except (ValueError, TypeError):
                continue

        # Get original estimates (from sir_results.csv header or first row)
        sir_results = self.folder / 'sir_results.csv'
        if sir_results.exists():
            with open(sir_results, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                final_rows = list(reader)
            self.samples = []
            for row in final_rows:
                param_vals = {}
                for col in self.param_cols:
                    try:
                        param_vals[col] = float(row.get(col, 'nan'))
                    except (ValueError, TypeError):
                        param_vals[col] = float('nan')
                self.samples.append(param_vals)
            self.n_resamples = len(self.samples)
        else:
            # Use final iteration from raw_results
            max_iter = 0
            for row in rows:
                try:
                    it = int(row.get('iteration', 0))
                    if it > max_iter:
                        max_iter = it
                except (ValueError, TypeError):
                    pass

            self.samples = []
            for row in rows:
                try:
                    if int(row.get('iteration', 0)) == max_iter:
                        param_vals = {}
                        for col in self.param_cols:
                            param_vals[col] = float(row.get(col, 'nan'))
                        self.samples.append(param_vals)
                except (ValueError, TypeError):
                    continue
            self.n_resamples = len(self.samples)

        # Get original from model with lowest OFV or iteration 0
        for row in rows:
            try:
                if int(row.get('iteration', 1)) == 0:
                    for col in self.param_cols:
                        self.original[col] = float(row.get(col, 'nan'))
                    break
            except (ValueError, TypeError):
                continue

        # If no original found, use median of final iteration
        if not self.original and self.samples:
            for col in self.param_cols:
                vals = sorted([s[col] for s in self.samples if not math.isnan(s.get(col, float('nan')))])
                if vals:
                    self.original[col] = statistics.median(vals)

        diagnostics = self._assess()

        return {
            'method': 'sir',
            'folder': str(self.folder),
            'n_resamples': self.n_resamples,
            'df': self.df,
            'param_cols': self.param_cols,
            'original': self.original,
            'samples': self.samples,
            'dofv': self.dofv,
            'diagnostics': diagnostics
        }

    def _assess(self) -> dict:
        checks = []

        # 1. dOFV K-S test
        if HAS_SCIPY and len(self.dofv) >= 50:
            try:
                stat, pval = scipy_kstest(self.dofv, 'chi2', args=(self.df,))
                if pval > SIR_KS_PASS:
                    status = 'pass'
                    interp = f'dOFV distribution consistent with χ²({self.df}).'
                elif pval > SIR_KS_WARN:
                    status = 'pass'
                    interp = 'Marginally consistent with theoretical distribution.'
                else:
                    status = 'fail'
                    interp = 'Significant deviation from χ². SIR proposal may be inappropriate.'

                checks.append({
                    'name': 'dOFV K-S test',
                    'status': status,
                    'value': f'p = {pval:.3f} (χ² df={self.df})',
                    'interpretation': interp
                })
            except Exception:
                pass

        # 2. dOFV median check
        if self.dofv:
            observed_median = statistics.median(self.dofv)
            # Theoretical median of chi-square ≈ df * (1 - 2/(9*df))^3
            if self.df > 0:
                theoretical_median = self.df * (1 - 2/(9*self.df))**3
            else:
                theoretical_median = self.df

            if theoretical_median > 0:
                deviation = abs(observed_median - theoretical_median) / theoretical_median
            else:
                deviation = 0

            if deviation < SIR_MEDIAN_PASS:
                status = 'pass'
                interp = 'Median close to expected value.'
            elif deviation < SIR_MEDIAN_WARN:
                status = 'warning'
                interp = 'Some shift from expected. May indicate proposal mismatch.'
            else:
                status = 'fail'
                interp = 'Substantial shift. Proposal distribution problematic.'

            checks.append({
                'name': 'dOFV median',
                'status': status,
                'value': f'{observed_median:.1f} vs expected {theoretical_median:.1f} ({deviation*100:+.0f}%)',
                'interpretation': interp
            })

        # 3. Effective sample size (approximation)
        if self.samples:
            # Simple approximation: count unique resampled vectors
            n_unique = len(set(tuple(sorted(s.items())) for s in self.samples))
            ess_ratio = n_unique / max(1, self.n_resamples)

            if ess_ratio > SIR_ESS_PASS:
                status = 'pass'
                interp = 'Excellent resampling efficiency.'
            elif ess_ratio > SIR_ESS_WARN:
                status = 'pass'
                interp = 'Good efficiency.'
            elif ess_ratio > SIR_ESS_FAIL:
                status = 'warning'
                interp = 'Moderate efficiency. Consider increasing samples.'
            else:
                status = 'fail'
                interp = 'Poor efficiency. Results may be dominated by few samples.'

            # Also check absolute ESS
            if n_unique < SIR_ESS_ABS_FAIL:
                status = 'fail'
                interp = f'ESS below minimum threshold ({SIR_ESS_ABS_FAIL}).'
            elif n_unique < SIR_ESS_ABS_WARN and status == 'pass':
                status = 'warning'
                interp = 'ESS somewhat low. Results usable but consider more samples.'

            checks.append({
                'name': 'Effective sample size',
                'status': status,
                'value': f'~{n_unique} unique / {self.n_resamples} ({ess_ratio*100:.0f}%)',
                'interpretation': interp
            })

        # 4. Parameter shift check
        if self.samples and self.original:
            shifts = {}
            max_shift = 0
            for col in self.param_cols:
                orig_val = self.original.get(col, 0)
                sample_vals = [s[col] for s in self.samples if col in s and not math.isnan(s[col])]
                if not sample_vals:
                    continue
                sample_vals.sort()
                median_val = statistics.median(sample_vals)
                if abs(orig_val) > 1e-6:
                    shift = abs(median_val - orig_val) / abs(orig_val)
                else:
                    shift = abs(median_val - orig_val)
                shifts[col] = shift
                if shift > max_shift:
                    max_shift = shift

            if max_shift < 0.10:
                status = 'pass'
                value = 'All parameters < 10% shift'
                interp = 'Well-centered distributions.'
            elif max_shift < 0.25:
                status = 'warning'
                value = f'Max shift {max_shift*100:.0f}%'
                interp = 'Moderate shift. Original estimate may be at edge of uncertainty region.'
            else:
                status = 'warning'
                value = f'Max shift {max_shift*100:.0f}%'
                interp = 'Substantial shift from point estimate.'

            checks.append({
                'name': 'Parameter shift',
                'status': status,
                'value': value,
                'interpretation': interp
            })

        # 5. Boundary pile-up (check if many samples at lower bound 0 for omegas)
        boundary_issues = []
        for col in self.param_cols:
            if not col.startswith('OMEGA'):
                continue
            sample_vals = [s[col] for s in self.samples if col in s and not math.isnan(s[col])]
            if not sample_vals:
                continue
            n_at_zero = sum(1 for v in sample_vals if abs(v) < 1e-8)
            frac_at_zero = n_at_zero / len(sample_vals)
            if frac_at_zero > 0.15:
                boundary_issues.append(f'{col} ({frac_at_zero*100:.0f}%)')
            elif frac_at_zero > 0.05:
                boundary_issues.append(f'{col} ({frac_at_zero*100:.0f}%)')

        if not boundary_issues:
            status = 'pass'
            value = 'No pile-up detected'
            interp = 'No boundary issues.'
        elif any('(' in b and int(b.split('(')[1].rstrip('%)')) > 15 for b in boundary_issues):
            status = 'fail'
            value = f'Pile-up: {", ".join(boundary_issues[:3])}'
            interp = 'Substantial pile-up at bounds. CI may be artificially narrow.'
        else:
            status = 'warning'
            value = f'Minor: {", ".join(boundary_issues[:3])}'
            interp = 'Some truncation at bounds.'

        checks.append({
            'name': 'Boundary check',
            'status': status,
            'value': value,
            'interpretation': interp
        })

        # Overall assessment
        n_fail = sum(1 for c in checks if c['status'] == 'fail')
        n_warn = sum(1 for c in checks if c['status'] == 'warning')

        if n_fail > 0:
            overall = 'FAILED'
        elif n_warn > 2:
            overall = 'WARNING'
        elif n_warn > 0:
            overall = 'ACCEPTABLE'
        else:
            overall = 'PASSED'

        return {'overall': overall, 'checks': checks}

    def get_parameter_table(self) -> list:
        """Return list of dicts with parameter estimates and CIs."""
        if not self.samples:
            return []

        table = []
        for col in self.param_cols:
            orig_val = self.original.get(col, float('nan'))
            sample_vals = sorted([s[col] for s in self.samples
                                  if col in s and not math.isnan(s[col])])
            if not sample_vals:
                continue

            median = statistics.median(sample_vals)
            lo = sample_vals[int(len(sample_vals) * 0.025)]
            hi = sample_vals[int(len(sample_vals) * 0.975)]

            if abs(median) > 1e-10:
                rse = (hi - lo) / (2 * 1.96 * abs(median)) * 100
            else:
                rse = float('nan')

            table.append({
                'parameter': col,
                'estimate': orig_val,
                'median': median,
                'ci_lo': lo,
                'ci_hi': hi,
                'rse': rse
            })
        return table


class PsNWorker(QThread):
    """Worker thread for running PsN bootstrap or sir."""
    line_out = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # success, folder_or_error

    def __init__(self, cmd: list, output_dir: str, env: dict):
        super().__init__()
        self._cmd = cmd
        self._output_dir = output_dir
        self._env = env
        self._process = None
        self._cancelled = False

    def run(self):
        try:
            self.line_out.emit(f'> {" ".join(self._cmd)}\n')
            _pkw = {'creationflags': subprocess.CREATE_NO_WINDOW} if IS_WIN else {'start_new_session': True}
            self._process = subprocess.Popen(
                self._cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._env,
                cwd=str(Path(self._output_dir).parent) if self._output_dir else None,
                **_pkw
            )

            for line in iter(self._process.stdout.readline, ''):
                if self._cancelled:
                    break
                self.line_out.emit(line.rstrip())

            self._process.wait()

            if self._cancelled:
                self.finished.emit(False, 'Cancelled by user')
            elif self._process.returncode == 0:
                self.finished.emit(True, self._output_dir)
            else:
                self.finished.emit(False, f'Process exited with code {self._process.returncode}')

        except Exception as e:
            self.finished.emit(False, str(e))

    def terminate(self):
        self._cancelled = True
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass


class ParameterUncertaintyTab(QWidget):
    """Tab for running and analyzing Bootstrap and SIR results."""
    status_msg = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._worker = None
        self._results = None
        self._psn_available = {}
        self._build_ui()
        QTimer.singleShot(500, self._check_psn)

    def _build_ui(self):
        main_h = QHBoxLayout(self)
        main_h.setContentsMargins(6, 6, 6, 6)
        main_h.setSpacing(8)

        # ── Left panel: method & mode selection ────────────────────────────────
        left_panel = QWidget()
        left_panel.setFixedWidth(180)
        left_v = QVBoxLayout(left_panel)
        left_v.setContentsMargins(8, 8, 8, 8)
        left_v.setSpacing(16)

        # Model info
        self.model_lbl = QLabel('No model selected')
        self.model_lbl.setWordWrap(True)
        self.model_lbl.setObjectName('muted')
        left_v.addWidget(self.model_lbl)

        # Method selection
        method_lbl = QLabel('METHOD')
        method_lbl.setObjectName('section')
        left_v.addWidget(method_lbl)

        self._method_group = QButtonGroup(self)
        self.bootstrap_rb = QRadioButton('Bootstrap')
        self.bootstrap_rb.setChecked(True)
        self.sir_rb = QRadioButton('SIR')
        self._method_group.addButton(self.bootstrap_rb, 0)
        self._method_group.addButton(self.sir_rb, 1)
        self._method_group.buttonClicked.connect(self._on_method_change)
        left_v.addWidget(self.bootstrap_rb)
        left_v.addWidget(self.sir_rb)

        # Spacer
        left_v.addSpacing(8)

        # Mode selection
        mode_lbl = QLabel('MODE')
        mode_lbl.setObjectName('section')
        left_v.addWidget(mode_lbl)

        self._mode_group = QButtonGroup(self)
        self.run_new_rb = QRadioButton('Run new')
        self.run_new_rb.setChecked(True)
        self.load_existing_rb = QRadioButton('Load existing')
        self._mode_group.addButton(self.run_new_rb, 0)
        self._mode_group.addButton(self.load_existing_rb, 1)
        self._mode_group.buttonClicked.connect(self._on_mode_change)
        left_v.addWidget(self.run_new_rb)
        left_v.addWidget(self.load_existing_rb)

        # Detected results (for load mode)
        left_v.addSpacing(8)
        self.detected_lbl = QLabel('FOUND RESULTS')
        self.detected_lbl.setObjectName('section')
        self.detected_lbl.hide()
        left_v.addWidget(self.detected_lbl)

        self.results_combo = QComboBox()
        self.results_combo.addItem('(none found)')
        self.results_combo.hide()
        left_v.addWidget(self.results_combo)

        browse_btn = QPushButton('Browse other…')
        browse_btn.setFixedHeight(28)
        browse_btn.clicked.connect(self._browse_folder)
        browse_btn.hide()
        self._browse_btn = browse_btn
        left_v.addWidget(browse_btn)

        # PSN status
        left_v.addSpacing(12)
        self.psn_lbl = QLabel('Checking PsN…')
        self.psn_lbl.setWordWrap(True)
        self.psn_lbl.setObjectName('mutedSmall')
        left_v.addWidget(self.psn_lbl)

        left_v.addStretch()
        main_h.addWidget(left_panel)

        # Separator
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setObjectName('hairlineSep')
        main_h.addWidget(sep)

        # ── Right panel: config + results ──────────────────────────────────────
        right_v = QVBoxLayout()
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(8)

        # Config stack (switches between bootstrap/sir and run/load)
        self._config_stack = QStackedWidget()

        # Page 0: Bootstrap run config
        self._bootstrap_config = self._build_bootstrap_config()
        self._config_stack.addWidget(self._bootstrap_config)

        # Page 1: SIR run config
        self._sir_config = self._build_sir_config()
        self._config_stack.addWidget(self._sir_config)

        # Page 2: Load existing (minimal)
        self._load_config = self._build_load_config()
        self._config_stack.addWidget(self._load_config)

        right_v.addWidget(self._config_stack)

        # Run/Load buttons
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton('Run Bootstrap')
        self.run_btn.setFixedHeight(32)
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setFixedHeight(32)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        self.load_btn = QPushButton('Load Results')
        self.load_btn.setFixedHeight(32)
        self.load_btn.clicked.connect(self._load_results)
        self.load_btn.hide()
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.load_btn)
        btn_row.addStretch()
        right_v.addLayout(btn_row)

        # Results tabs
        results_tabs_row = QHBoxLayout()
        self._results_btns = []
        for i, label in enumerate(['Console', 'Assessment', 'Parameters', 'Plots']):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _, idx=i: self._switch_results_tab(idx))
            results_tabs_row.addWidget(btn)
            self._results_btns.append(btn)
        results_tabs_row.addStretch()
        right_v.addLayout(results_tabs_row)

        # Results stack
        self._results_stack = QStackedWidget()

        # Console
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont('Menlo' if IS_MAC else 'Consolas', 10))
        _pal = QPalette()
        _pal.setColor(QPalette.ColorRole.Base, QColor(T('bg2')))
        _pal.setColor(QPalette.ColorRole.Text, QColor(T('fg')))
        _pal.setColor(QPalette.ColorRole.Window, QColor(T('bg2')))
        self.console.setPalette(_pal)
        self._results_stack.addWidget(self.console)

        # Assessment panel
        self.assessment_panel = QWidget()
        ap_v = QVBoxLayout(self.assessment_panel)
        ap_v.setContentsMargins(8, 8, 8, 8)
        self.assessment_lbl = QLabel('No results loaded')
        self.assessment_lbl.setWordWrap(True)
        self.assessment_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.assessment_lbl.setTextFormat(Qt.TextFormat.RichText)
        ap_v.addWidget(self.assessment_lbl)
        ap_v.addStretch()
        self._results_stack.addWidget(self.assessment_panel)

        # Parameters table
        self.param_table = QTableWidget()
        self.param_table.setColumnCount(6)
        self.param_table.setHorizontalHeaderLabels(['Parameter', 'Estimate', 'Median', '2.5%', '97.5%', 'RSE (%)'])
        self.param_table.horizontalHeader().setStretchLastSection(True)
        self.param_table.setAlternatingRowColors(True)
        self.param_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_stack.addWidget(self.param_table)

        # Plots panel
        self.plots_panel = QWidget()
        plots_v = QVBoxLayout(self.plots_panel)
        plots_v.setContentsMargins(0, 0, 0, 0)
        if HAS_MPL:
            self._figure = Figure(figsize=(8, 6), dpi=100)
            self._canvas = FigureCanvasQTAgg(self._figure)
            plots_v.addWidget(self._canvas)
        else:
            plots_v.addWidget(QLabel('Matplotlib not available'))
        self._results_stack.addWidget(self.plots_panel)

        right_v.addWidget(self._results_stack, 1)

        main_h.addLayout(right_v, 1)

        self._on_mode_change()

    def _build_bootstrap_config(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.boot_samples_spin = QDoubleSpinBox()
        self.boot_samples_spin.setRange(100, 10000)
        self.boot_samples_spin.setValue(1000)
        self.boot_samples_spin.setDecimals(0)
        form.addRow('Samples:', self.boot_samples_spin)

        self.boot_threads_spin = QDoubleSpinBox()
        self.boot_threads_spin.setRange(1, 64)
        self.boot_threads_spin.setValue(4)
        self.boot_threads_spin.setDecimals(0)
        form.addRow('Threads:', self.boot_threads_spin)

        self.boot_stratify_edit = QLineEdit()
        self.boot_stratify_edit.setPlaceholderText('Column name (optional)')
        form.addRow('Stratify by:', self.boot_stratify_edit)

        self.boot_skip_cov_cb = QCheckBox('Skip covariance step (faster)')
        self.boot_skip_cov_cb.setChecked(True)
        form.addRow('', self.boot_skip_cov_cb)

        # Output directory
        dir_row = QHBoxLayout()
        self.boot_dir_edit = QLineEdit()
        self.boot_dir_edit.setPlaceholderText('Output directory')
        dir_row.addWidget(self.boot_dir_edit)
        dir_browse = QPushButton('…')
        dir_browse.setFixedWidth(30)
        dir_browse.clicked.connect(lambda: self._browse_output_dir(self.boot_dir_edit))
        dir_row.addWidget(dir_browse)
        form.addRow('Output dir:', dir_row)

        # Cluster options - collapsible
        self.boot_cluster_cb = QCheckBox('Submit to cluster')
        self.boot_cluster_cb.setChecked(False)
        form.addRow('', self.boot_cluster_cb)

        # Cluster options container (hidden by default)
        self._boot_cluster_container = QWidget()
        cluster_layout = QFormLayout(self._boot_cluster_container)
        cluster_layout.setContentsMargins(20, 0, 0, 0)
        cluster_layout.setSpacing(6)

        self.boot_cluster_type = QComboBox()
        self.boot_cluster_type.addItems(['slurm', 'sge', 'torque', 'lsf'])
        cluster_layout.addRow('Scheduler:', self.boot_cluster_type)

        self.boot_cluster_opts = QLineEdit()
        self.boot_cluster_opts.setPlaceholderText('e.g., -p short --mem=4G')
        cluster_layout.addRow('Options:', self.boot_cluster_opts)

        self._boot_cluster_container.hide()
        form.addRow('', self._boot_cluster_container)

        # Connect checkbox to show/hide cluster options
        self.boot_cluster_cb.toggled.connect(self._boot_cluster_container.setVisible)

        return w

    def _build_sir_config(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self.sir_samples_spin = QDoubleSpinBox()
        self.sir_samples_spin.setRange(100, 50000)
        self.sir_samples_spin.setValue(1000)
        self.sir_samples_spin.setDecimals(0)
        form.addRow('Samples:', self.sir_samples_spin)

        self.sir_resamples_spin = QDoubleSpinBox()
        self.sir_resamples_spin.setRange(100, 50000)
        self.sir_resamples_spin.setValue(1000)
        self.sir_resamples_spin.setDecimals(0)
        form.addRow('Resamples:', self.sir_resamples_spin)

        self.sir_threads_spin = QDoubleSpinBox()
        self.sir_threads_spin.setRange(1, 64)
        self.sir_threads_spin.setValue(4)
        self.sir_threads_spin.setDecimals(0)
        form.addRow('Threads:', self.sir_threads_spin)

        # Output directory
        dir_row = QHBoxLayout()
        self.sir_dir_edit = QLineEdit()
        self.sir_dir_edit.setPlaceholderText('Output directory')
        dir_row.addWidget(self.sir_dir_edit)
        dir_browse = QPushButton('…')
        dir_browse.setFixedWidth(30)
        dir_browse.clicked.connect(lambda: self._browse_output_dir(self.sir_dir_edit))
        dir_row.addWidget(dir_browse)
        form.addRow('Output dir:', dir_row)

        # Cluster options - collapsible
        self.sir_cluster_cb = QCheckBox('Submit to cluster')
        self.sir_cluster_cb.setChecked(False)
        form.addRow('', self.sir_cluster_cb)

        # Cluster options container (hidden by default)
        self._sir_cluster_container = QWidget()
        cluster_layout = QFormLayout(self._sir_cluster_container)
        cluster_layout.setContentsMargins(20, 0, 0, 0)
        cluster_layout.setSpacing(6)

        self.sir_cluster_type = QComboBox()
        self.sir_cluster_type.addItems(['slurm', 'sge', 'torque', 'lsf'])
        cluster_layout.addRow('Scheduler:', self.sir_cluster_type)

        self.sir_cluster_opts = QLineEdit()
        self.sir_cluster_opts.setPlaceholderText('e.g., -p short --mem=4G')
        cluster_layout.addRow('Options:', self.sir_cluster_opts)

        self._sir_cluster_container.hide()
        form.addRow('', self._sir_cluster_container)

        # Connect checkbox to show/hide cluster options
        self.sir_cluster_cb.toggled.connect(self._sir_cluster_container.setVisible)

        return w

    def _build_load_config(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel('Select a results folder from the dropdown on the left,\nor browse for a folder.')
        lbl.setWordWrap(True)
        lbl.setObjectName('muted')
        v.addWidget(lbl)
        v.addStretch()
        return w

    def _check_psn(self):
        self._psn_available = _check_psn_tools()
        parts = []
        for tool in ('bootstrap', 'sir'):
            if self._psn_available.get(tool):
                parts.append(f'✓ {tool}')
            else:
                parts.append(f'✗ {tool}')
        self.psn_lbl.setText('PsN tools:\n' + ', '.join(parts))

        if not self._psn_available.get('bootstrap') and not self._psn_available.get('sir'):
            self.run_btn.setEnabled(False)
            self.psn_lbl.setObjectName('error')
            self.psn_lbl.style().unpolish(self.psn_lbl)
            self.psn_lbl.style().polish(self.psn_lbl)

    def _on_method_change(self, *args):
        if self.run_new_rb.isChecked():
            if self.bootstrap_rb.isChecked():
                self._config_stack.setCurrentIndex(0)
                self.run_btn.setText('Run Bootstrap')
            else:
                self._config_stack.setCurrentIndex(1)
                self.run_btn.setText('Run SIR')
        self._detect_existing_results()

    def _on_mode_change(self, *args):
        if self.run_new_rb.isChecked():
            self.detected_lbl.hide()
            self.results_combo.hide()
            self._browse_btn.hide()
            self.run_btn.show()
            self.stop_btn.show()
            self.load_btn.hide()
            self._on_method_change()
        else:
            self.detected_lbl.show()
            self.results_combo.show()
            self._browse_btn.show()
            self.run_btn.hide()
            self.stop_btn.hide()
            self.load_btn.show()
            self._config_stack.setCurrentIndex(2)
            self._detect_existing_results()

    def _detect_existing_results(self):
        """Scan model directory for existing bootstrap/SIR folders."""
        self.results_combo.clear()
        if not self._model or not self._model.get('lst_path'):
            self.results_combo.addItem('(no model selected)')
            return

        model_dir = Path(self._model['lst_path']).parent
        method = 'bootstrap' if self.bootstrap_rb.isChecked() else 'sir'

        # Find matching folders
        patterns = [f'{method}_*', f'{method.upper()}_*']
        found = []
        for pat in patterns:
            found.extend(model_dir.glob(pat))

        # Also look for folders containing the method name and model stem
        stem = self._model.get('stem', '')
        if stem:
            found.extend(model_dir.glob(f'*{method}*{stem}*'))
            found.extend(model_dir.glob(f'*{stem}*{method}*'))

        # Deduplicate and sort by modification time
        found = list(set(found))
        found = [f for f in found if f.is_dir()]
        found.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if found:
            for folder in found[:10]:  # limit to 10 most recent
                # Get modification date
                try:
                    mtime = datetime.fromtimestamp(folder.stat().st_mtime)
                    date_str = mtime.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    date_str = ''
                self.results_combo.addItem(f'{folder.name} ({date_str})', str(folder))
        else:
            self.results_combo.addItem('(none found)')

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select results folder',
            str(Path(self._model['lst_path']).parent) if self._model and self._model.get('lst_path') else str(HOME))
        if folder:
            # Add to combo and select it
            self.results_combo.insertItem(0, Path(folder).name, folder)
            self.results_combo.setCurrentIndex(0)

    def _browse_output_dir(self, edit: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, 'Select output directory',
            edit.text() or str(HOME))
        if folder:
            edit.setText(folder)

    def load_model(self, model: dict):
        self._model = model
        if model:
            stem = model.get('stem', 'model')
            self.model_lbl.setText(f'Model: {stem}')

            # Set default output directories
            if model.get('lst_path'):
                model_dir = Path(model['lst_path']).parent
                self.boot_dir_edit.setText(str(model_dir / f'bootstrap_{stem}'))
                self.sir_dir_edit.setText(str(model_dir / f'sir_{stem}'))

            self._detect_existing_results()
        else:
            self.model_lbl.setText('No model selected')

    def _build_bootstrap_cmd(self) -> list:
        if not self._model or not self._model.get('path'):
            return []

        cmd = ['bootstrap', self._model['path']]
        cmd.append(f'-samples={int(self.boot_samples_spin.value())}')
        cmd.append(f'-threads={int(self.boot_threads_spin.value())}')

        strat = self.boot_stratify_edit.text().strip()
        if strat:
            cmd.append(f'-stratify_on={strat}')

        if self.boot_skip_cov_cb.isChecked():
            cmd.append('-skip_covariance_step')

        if self.boot_cluster_cb.isChecked():
            cluster_type = self.boot_cluster_type.currentText()
            cmd.append(f'-run_on_{cluster_type}')
            opts = self.boot_cluster_opts.text().strip()
            if opts:
                cmd.append(f'-{cluster_type}_options={opts}')

        out_dir = self.boot_dir_edit.text().strip()
        if out_dir:
            cmd.append(f'-directory={out_dir}')

        return cmd

    def _build_sir_cmd(self) -> list:
        if not self._model or not self._model.get('path'):
            return []

        cmd = ['sir', self._model['path']]
        cmd.append(f'-samples={int(self.sir_samples_spin.value())}')
        cmd.append(f'-resamples={int(self.sir_resamples_spin.value())}')
        cmd.append(f'-threads={int(self.sir_threads_spin.value())}')

        if self.sir_cluster_cb.isChecked():
            cluster_type = self.sir_cluster_type.currentText()
            cmd.append(f'-run_on_{cluster_type}')
            opts = self.sir_cluster_opts.text().strip()
            if opts:
                cmd.append(f'-{cluster_type}_options={opts}')

        out_dir = self.sir_dir_edit.text().strip()
        if out_dir:
            cmd.append(f'-directory={out_dir}')

        return cmd

    def _run(self):
        if not self._model:
            QMessageBox.warning(self, 'No model', 'Select a model first.')
            return

        method = 'bootstrap' if self.bootstrap_rb.isChecked() else 'sir'

        if not self._psn_available.get(method):
            QMessageBox.warning(self, 'PsN not available',
                f'The PsN {method} tool is not found on PATH.')
            return

        if method == 'bootstrap':
            cmd = self._build_bootstrap_cmd()
            out_dir = self.boot_dir_edit.text().strip()
        else:
            cmd = self._build_sir_cmd()
            out_dir = self.sir_dir_edit.text().strip()

        if not cmd:
            QMessageBox.warning(self, 'Error', 'Could not build command.')
            return

        self.console.clear()
        self.console.appendPlainText(f'Starting {method}…\n')
        self._switch_results_tab(0)

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._worker = PsNWorker(cmd, out_dir, get_login_env())
        self._worker.line_out.connect(self._on_line)
        self._worker.finished.connect(self._on_run_done)
        self._worker.start()

    def _stop(self):
        if self._worker:
            self._worker.terminate()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.console.appendPlainText('\n[Cancelled]')

    def _on_line(self, line: str):
        self.console.appendPlainText(line)
        # Auto-scroll
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_run_done(self, success: bool, folder_or_err: str):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if success:
            self.console.appendPlainText(f'\n[Completed] Output: {folder_or_err}')
            self.status_msg.emit('Run completed successfully')
            # Auto-load results
            self._parse_and_display(Path(folder_or_err))
        else:
            self.console.appendPlainText(f'\n[Failed] {folder_or_err}')
            self.status_msg.emit(f'Run failed: {folder_or_err}')

    def _load_results(self):
        """Load existing results from selected folder."""
        idx = self.results_combo.currentIndex()
        folder = self.results_combo.itemData(idx)
        if not folder:
            QMessageBox.warning(self, 'No folder', 'Select a results folder first.')
            return

        self._parse_and_display(Path(folder))

    def _parse_and_display(self, folder: Path):
        """Parse results folder and display diagnostics."""
        self.console.appendPlainText(f'\nParsing results from: {folder}\n')

        # Detect method from folder contents
        if (folder / 'raw_results_sir.csv').exists():
            method = 'sir'
        elif list(folder.glob('raw_results_*.csv')):
            method = 'bootstrap'
        else:
            QMessageBox.warning(self, 'Not found',
                'Could not find raw_results_*.csv or raw_results_sir.csv in this folder.')
            return

        try:
            if method == 'bootstrap':
                parser = BootstrapParser(folder)
                self._results = parser.parse()
            else:
                parser = SIRParser(folder)
                self._results = parser.parse()

            self.console.appendPlainText(f'Parsed {method} results successfully.\n')
            self._display_assessment()
            self._display_parameters()
            self._generate_plots()
            self._switch_results_tab(1)  # Switch to assessment
            self.status_msg.emit(f'Loaded {method} results from {folder.name}')

        except Exception as e:
            self.console.appendPlainText(f'Error parsing results: {e}\n')
            QMessageBox.critical(self, 'Parse error', str(e))

    def _display_assessment(self):
        """Display diagnostic assessment panel."""
        if not self._results:
            return

        method = self._results['method'].upper()
        diag = self._results['diagnostics']
        overall = diag['overall']

        # Color-code overall status
        if overall == 'PASSED':
            color = T('green')
            icon = '●'
        elif overall == 'ACCEPTABLE':
            color = T('accent')
            icon = '●'
        elif overall == 'WARNING':
            color = T('orange')
            icon = '●'
        else:
            color = T('red')
            icon = '●'

        html = f'''
        <div style="font-family: system-ui; color: {T('fg')};">
            <h3 style="margin: 0 0 12px 0;">{method} Assessment</h3>
            <p style="font-size: 16px; margin: 0 0 16px 0;">
                Overall: <span style="color: {color}; font-weight: bold;">{icon} {overall}</span>
            </p>
            <table style="border-collapse: collapse; width: 100%;">
        '''

        for check in diag['checks']:
            status = check['status']
            if status == 'pass':
                s_icon = '✓'
                s_color = T('green')
            elif status == 'warning':
                s_icon = '⚠'
                s_color = T('orange')
            else:
                s_icon = '✗'
                s_color = T('red')

            html += f'''
                <tr style="border-bottom: 1px solid {T('border')};">
                    <td style="padding: 8px 4px; color: {s_color}; width: 24px;">{s_icon}</td>
                    <td style="padding: 8px 4px; font-weight: 500;">{check['name']}</td>
                    <td style="padding: 8px 4px; color: {T('fg2')};">{check['value']}</td>
                </tr>
                <tr>
                    <td></td>
                    <td colspan="2" style="padding: 4px 4px 12px 4px; color: {T('fg2')}; font-size: 12px;">
                        {check.get('interpretation', '')}
                    </td>
                </tr>
            '''

        html += '</table></div>'
        self.assessment_lbl.setText(html)

    def _display_parameters(self):
        """Display parameter uncertainty table."""
        if not self._results:
            return

        method = self._results['method']
        if method == 'bootstrap':
            parser = BootstrapParser(Path(self._results['folder']))
            parser.param_cols = self._results['param_cols']
            parser.original = self._results['original']
            parser.samples_df = self._results['samples']
            table_data = parser.get_parameter_table()
        else:
            parser = SIRParser(Path(self._results['folder']))
            parser.param_cols = self._results['param_cols']
            parser.original = self._results['original']
            parser.samples = self._results['samples']
            table_data = parser.get_parameter_table()

        self.param_table.setRowCount(len(table_data))
        for i, row in enumerate(table_data):
            self.param_table.setItem(i, 0, QTableWidgetItem(row['parameter']))
            self.param_table.setItem(i, 1, QTableWidgetItem(f"{row['estimate']:.4g}"))
            self.param_table.setItem(i, 2, QTableWidgetItem(f"{row['median']:.4g}"))
            self.param_table.setItem(i, 3, QTableWidgetItem(f"{row['ci_lo']:.4g}"))
            self.param_table.setItem(i, 4, QTableWidgetItem(f"{row['ci_hi']:.4g}"))
            rse_str = f"{row['rse']:.1f}" if not math.isnan(row['rse']) else '—'
            self.param_table.setItem(i, 5, QTableWidgetItem(rse_str))

        self.param_table.resizeColumnsToContents()

    def _generate_plots(self):
        """Generate diagnostic plots."""
        if not HAS_MPL or not self._results:
            return

        self._figure.clear()
        method = self._results['method']

        if method == 'bootstrap':
            self._plot_bootstrap()
        else:
            self._plot_sir()

        self._canvas.draw()

    def _plot_bootstrap(self):
        """Generate bootstrap diagnostic plots."""
        samples = self._results['samples']
        param_cols = self._results['param_cols'][:6]  # max 6 params
        original = self._results['original']

        if not samples or not param_cols:
            return

        n_params = len(param_cols)
        n_cols = min(3, n_params)
        n_rows = (n_params + n_cols - 1) // n_cols

        for i, col in enumerate(param_cols):
            ax = self._figure.add_subplot(n_rows, n_cols, i + 1)
            vals = [s[col] for s in samples if col in s]
            if not vals:
                continue

            ax.hist(vals, bins=30, alpha=0.7, color='#4c8aff', edgecolor='none')
            orig = original.get(col, None)
            if orig is not None:
                ax.axvline(orig, color='#e85555', linestyle='--', linewidth=1.5, label='Estimate')
            median = statistics.median(vals)
            ax.axvline(median, color='#3ec97a', linestyle='-', linewidth=1.5, label='Median')
            ax.set_title(col, fontsize=9)
            ax.tick_params(labelsize=8)
            if i == 0:
                ax.legend(fontsize=7)

        self._figure.tight_layout()

    def _plot_sir(self):
        """Generate SIR diagnostic plots."""
        dofv = self._results.get('dofv', [])
        df = self._results.get('df', 8)

        if not dofv:
            return

        # Plot 1: dOFV distribution
        ax1 = self._figure.add_subplot(1, 2, 1)
        ax1.hist(dofv, bins=50, density=True, alpha=0.7, color='#4c8aff', edgecolor='none')

        # Chi-square overlay
        if HAS_SCIPY and HAS_NP:
            x = np.linspace(0, max(dofv), 200)
            ax1.plot(x, scipy_chi2.pdf(x, df), color='#e85555', linewidth=2,
                    label=f'χ²(df={df})')
            ax1.legend(fontsize=8)

        ax1.set_xlabel('dOFV', fontsize=9)
        ax1.set_ylabel('Density', fontsize=9)
        ax1.set_title('dOFV Distribution', fontsize=10)
        ax1.tick_params(labelsize=8)

        # Plot 2: Parameter distributions (first 3)
        samples = self._results.get('samples', [])
        param_cols = self._results.get('param_cols', [])[:3]

        if samples and param_cols:
            ax2 = self._figure.add_subplot(1, 2, 2)
            for j, col in enumerate(param_cols):
                vals = [s[col] for s in samples if col in s and not math.isnan(s[col])]
                if vals:
                    ax2.hist(vals, bins=30, alpha=0.5, label=col)
            ax2.legend(fontsize=8)
            ax2.set_title('Parameter Distributions', fontsize=10)
            ax2.tick_params(labelsize=8)

        self._figure.tight_layout()

    def _switch_results_tab(self, index: int):
        self._results_stack.setCurrentIndex(index)
        for i, btn in enumerate(self._results_btns):
            btn.setChecked(i == index)
