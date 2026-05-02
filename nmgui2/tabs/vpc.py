import os, re, subprocess, logging, tempfile, threading, zipfile
from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QTextEdit, QPlainTextEdit, QSplitter, QGroupBox, QCheckBox,
                              QDoubleSpinBox, QSpinBox, QComboBox, QFileDialog, QMessageBox,
                              QLineEdit, QStackedWidget, QSizePolicy)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPixmap, QPalette, QColor

from ..app.theme import C, T
from ..app.constants import IS_WIN, IS_MAC
from ..app.tools import _find_rscript, _sanitize_r, _r_col, _check_r_packages, get_login_env

_log = logging.getLogger(__name__)
HOME = Path.home()


class VPCWorker(QThread):
    line_out  = pyqtSignal(str)
    finished  = pyqtSignal(bool, str)   # success, image_path_or_error

    def __init__(self, script_path, output_png, rscript, env, timeout_sec=1800):
        super().__init__()
        self._script  = script_path
        self._png     = output_png
        self._rs      = rscript
        self._env     = env
        self._timeout = timeout_sec

    def run(self):
        try:
            _pkw = {'creationflags': subprocess.CREATE_NO_WINDOW} if IS_WIN else {'start_new_session': True}
            proc = subprocess.Popen(
                [self._rs, self._script],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=self._env,
                cwd=str(Path(self._script).parent), **_pkw)
            stdout_lines = []
            for line in iter(proc.stdout.readline, ''):
                self.line_out.emit(line.rstrip())
                stdout_lines.append(line)
            try:
                proc.wait(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
                self.finished.emit(False, f'R script timed out after {self._timeout // 60} minutes')
                return
            stdout_all = ''.join(stdout_lines)
            png_ok = Path(self._png).is_file() and Path(self._png).stat().st_size > 1000
            if 'NMGUI_VPC_OK' in stdout_all and png_ok:
                self.finished.emit(True, self._png)
            elif png_ok:
                # Script succeeded but didn't print protocol token (some R setups)
                self.finished.emit(True, self._png)
            else:
                # Extract error
                err = ''
                for line in stdout_lines:
                    if 'NMGUI_VPC_ERROR:' in line:
                        err = line.split('NMGUI_VPC_ERROR:', 1)[1].strip(); break
                if not err: err = 'R script did not produce a valid image'
                self.finished.emit(False, err)
        except Exception as e:
            self.finished.emit(False, str(e))


class VPCTab(QWidget):
    status_msg = pyqtSignal(str)
    _r_check_done = pyqtSignal(bool, dict, str)  # has_r, pkgs, rscript_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model   = None
        self._worker  = None
        self._rscript = None
        self._pkg_avail = {'vpc': False, 'xpose': False}
        self._r_check_done.connect(self._on_r_check_done)
        self._build_ui()
        QTimer.singleShot(500, self._check_r)

    def _build_ui(self):
        v = QVBoxLayout(self); v.setContentsMargins(6, 6, 6, 6); v.setSpacing(6)

        # ── Settings panel ────────────────────────────────────────────────────
        settings_grp = QGroupBox('VPC settings')
        sg = QVBoxLayout(settings_grp); sg.setSpacing(6); sg.setContentsMargins(10, 14, 10, 10)

        hint = QLabel(
            'Workflow: run <code>vpc</code> in PsN first, then select the resulting '
            '<code>vpc_*</code> folder below '
            '(must contain <code>vpctab*</code>, <code>vpc_results.csv</code>, '
            'and either <code>m1/</code> or <code>m1.zip</code> — '
            'a zipped <code>m1</code> is auto-extracted on Run).')
        hint.setWordWrap(True)
        hint.setObjectName('mutedSmall')
        sg.addWidget(hint)

        def _lbl(text):
            l = QLabel(text); l.setFixedWidth(74); return l

        def _spin(lo, hi, val, step, dec, w=86):
            s = QDoubleSpinBox()
            s.setRange(lo, hi); s.setValue(val)
            s.setSingleStep(step); s.setDecimals(dec); s.setFixedWidth(w)
            return s

        # Widget definitions
        self.tool_cb = QComboBox(); self.tool_cb.addItems(['vpc', 'xpose'])
        self.tool_cb.currentTextChanged.connect(self._on_tool_change)
        self.tool_cb.setFixedWidth(100)

        self.use_psn_cb = QCheckBox('Use PsN settings')
        self.use_psn_cb.setToolTip(
            'When checked (recommended), binning, stratification, pred-corr and LLOQ\n'
            'are read directly from the PsN output folder — no manual override.\n'
            'Uncheck to supply your own values for these parameters.')

        self.runno_edit = QLineEdit(); self.runno_edit.setPlaceholderText('e.g. 001')
        self.runno_edit.setFixedWidth(80)

        self.pred_corr_cb = QCheckBox('Prediction-corrected (pcVPC)')
        self.log_y_cb     = QCheckBox('Log Y axis')

        self.vpc_folder_edit = QLineEdit()
        self.vpc_folder_edit.setPlaceholderText('PsN vpc output folder (contains m1/, vpc_results.csv…)')
        vpc_browse = QPushButton('Browse…'); vpc_browse.clicked.connect(self._browse_vpc)

        self.run_dir_edit = QLineEdit()
        self.run_dir_edit.setPlaceholderText('Run directory with sdtab files (xpose only)')
        run_browse = QPushButton('Browse…'); run_browse.clicked.connect(self._browse_run)

        self.stratify_edit = QLineEdit()
        self.stratify_edit.setPlaceholderText('Stratify by column (optional)')
        self.stratify_edit.setFixedWidth(180)
        self.stratify_edit.setToolTip(
            'Column name(s) to stratify on, comma-separated (e.g. SEX, or DOSE).\n'
            'Leave blank if you already used -stratify_on in PsN — '
            'combining both produces incorrect plots.')

        self.pi_lo = _spin(0,   0.5, 0.05, 0.025, 3)
        self.pi_hi = _spin(0.5, 1.0, 0.95, 0.025, 3)
        self.ci_lo = _spin(0,   0.5, 0.05, 0.025, 3)
        self.ci_hi = _spin(0.5, 1.0, 0.95, 0.025, 3)
        self.idv_edit = QLineEdit(); self.idv_edit.setPlaceholderText('Auto (e.g. TIME, TAD)')
        self.idv_edit.setFixedWidth(140)
        self.idv_edit.setToolTip(
            'Independent variable column name (e.g. TIME, TAD, IDV).\n'
            'Auto-detected from PsN meta.yaml / command.txt.\n'
            'Leave blank to use auto-detection; type here to override.\n'
            'Always applied (regardless of "Use PsN settings") because the\n'
            'vpc/xpose backends do not auto-detect IDV from PsN output.')
        self.lloq_edit = QLineEdit(); self.lloq_edit.setPlaceholderText('LLOQ (optional)')
        self.lloq_edit.setFixedWidth(100)
        self.lloq_method_cb = QComboBox()
        self.lloq_method_cb.addItems(['M1', 'M2', 'M3'])
        self.lloq_method_cb.setFixedWidth(60)
        self.lloq_method_cb.setToolTip(
            'LLOQ censoring method passed to vpc::vpc(lloq_method=).\n'
            'M1: BLQ imputed as LLOQ/2 (default)\n'
            'M2: BLQ imputed as 0\n'
            'M3: Kaplan-Meier (requires survival package)')
        self.uloq_edit = QLineEdit(); self.uloq_edit.setPlaceholderText('ULOQ (optional)')
        self.uloq_edit.setFixedWidth(100)
        self.nbins_sb  = _spin(3, 50, 10, 1, 0, w=70)
        self.timeout_sb = QSpinBox()
        self.timeout_sb.setRange(1, 120); self.timeout_sb.setValue(30)
        self.timeout_sb.setSuffix(' min'); self.timeout_sb.setFixedWidth(80)
        self.timeout_sb.setToolTip(
            'Maximum time to wait for the R script.\n'
            'VPCs with 1000+ simulations may need 15–30+ minutes.')

        def _hrow(*widgets, spacing=10):
            h = QHBoxLayout(); h.setContentsMargins(0,0,0,0); h.setSpacing(spacing)
            for w in widgets:
                if w is None:
                    h.addStretch()
                elif isinstance(w, int):
                    h.addSpacing(w)
                else:
                    h.addWidget(w)
            return h

        # Row 1 — Backend / Run no / options
        sg.addLayout(_hrow(
            _lbl('Backend:'), self.tool_cb, 20,
            QLabel('Run no:'), self.runno_edit, None,
            self.pred_corr_cb, 20, self.log_y_cb, 20, self.use_psn_cb))

        # Row 2 — VPC folder
        r2 = QHBoxLayout(); r2.setContentsMargins(0,0,0,0); r2.setSpacing(6)
        r2.addWidget(_lbl('VPC folder:')); r2.addWidget(self.vpc_folder_edit, 1); r2.addWidget(vpc_browse)
        sg.addLayout(r2)

        # Row 3 — Run dir (xpose only, hidden by default)
        self.run_dir_lbl = QLabel('Run dir:'); self.run_dir_lbl.setFixedWidth(74)
        r3 = QHBoxLayout(); r3.setContentsMargins(0,0,0,0); r3.setSpacing(6)
        r3.addWidget(self.run_dir_lbl); r3.addWidget(self.run_dir_edit, 1); r3.addWidget(run_browse)
        self.run_dir_w = QWidget(); self.run_dir_w.setLayout(r3)
        sg.addWidget(self.run_dir_w)

        # Row 3b — Model .lst file (xpose only, hidden by default)
        self.lst_file_edit = QLineEdit()
        self.lst_file_edit.setPlaceholderText(
            'Path to model .lst file (auto-detected from command.txt; fill if auto-detect fails)')
        self.lst_file_edit.setToolTip(
            'xpose needs the original model .lst file to load run metadata.\n'
            'NMGUI2 auto-detects this from the vpc folder\'s command.txt.\n'
            'If auto-detection fails (model was renamed or moved), browse here.')
        self.lst_file_lbl = QLabel('Model .lst:'); self.lst_file_lbl.setFixedWidth(74)
        lst_browse = QPushButton('Browse…'); lst_browse.clicked.connect(self._browse_lst)
        r3b = QHBoxLayout(); r3b.setContentsMargins(0, 0, 0, 0); r3b.setSpacing(6)
        r3b.addWidget(self.lst_file_lbl); r3b.addWidget(self.lst_file_edit, 1); r3b.addWidget(lst_browse)
        self.lst_file_w = QWidget(); self.lst_file_w.setLayout(r3b)
        sg.addWidget(self.lst_file_w)

        # Row 4 — Stratify / PI / CI
        dash1 = QLabel('–'); dash1.setFixedWidth(10)
        dash2 = QLabel('–'); dash2.setFixedWidth(10)
        sg.addLayout(_hrow(
            _lbl('Stratify:'), self.stratify_edit, 20,
            QLabel('PI:'), self.pi_lo, dash1, self.pi_hi, 20,
            QLabel('CI:'), self.ci_lo, dash2, self.ci_hi, None))

        # Row 5 — Column overrides (IDV / LLOQ / ULOQ)
        sg.addLayout(_hrow(
            _lbl('IDV:'), self.idv_edit, 20,
            QLabel('LLOQ:'), self.lloq_edit, self.lloq_method_cb, 10,
            QLabel('ULOQ:'), self.uloq_edit, None))

        # Row 6 — Numerics (Bins / Timeout)
        sg.addLayout(_hrow(
            _lbl('Bins:'), self.nbins_sb, 20,
            QLabel('Timeout:'), self.timeout_sb, None))

        v.addWidget(settings_grp)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.run_btn  = QPushButton('Generate VPC'); self.run_btn.clicked.connect(self._run)
        self.run_btn.setObjectName('success')
        self.stop_btn = QPushButton('Stop'); self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        self.r_status_lbl = QLabel('Checking R…')
        self.r_status_lbl.setObjectName('muted')
        btn_row.addWidget(self.run_btn); btn_row.addWidget(self.stop_btn)
        btn_row.addStretch(); btn_row.addWidget(self.r_status_lbl)
        v.addLayout(btn_row)

        # ── Splitter: image | console+script ─────────────────────────────────
        spl = QSplitter(Qt.Orientation.Horizontal)

        # VPC image panel
        img_w = QWidget(); img_v = QVBoxLayout(img_w); img_v.setContentsMargins(0, 0, 0, 0); img_v.setSpacing(0)

        # Toolbar above image
        img_toolbar = QWidget(); img_toolbar.setFixedHeight(36)
        itl = QHBoxLayout(img_toolbar); itl.setContentsMargins(8, 4, 8, 4); itl.setSpacing(8)
        self.tool_lbl = QLabel('')
        self.tool_lbl.setObjectName('mutedSmall')
        self._open_btn    = QPushButton('Open in viewer')
        self._savepng_btn = QPushButton('Save high-res PNG…')
        self._savepdf_btn = QPushButton('Save PDF…')
        for b in (self._open_btn, self._savepng_btn, self._savepdf_btn):
            b.setEnabled(False)
            b.setFixedHeight(26)
        self._open_btn.clicked.connect(self._open_in_viewer)
        self._savepng_btn.clicked.connect(self._export_hires_png)
        self._savepdf_btn.clicked.connect(self._export_pdf)
        itl.addWidget(self.tool_lbl, 1)
        itl.addWidget(self._open_btn)
        itl.addWidget(self._savepng_btn)
        itl.addWidget(self._savepdf_btn)

        self.img_lbl = QLabel('No VPC generated yet')
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setObjectName('mutedLarge')
        self.img_lbl.setMinimumSize(400, 300)
        self.img_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._last_png = None          # path to most recently generated PNG
        self._last_script_txt = ''     # R script text for re-running at higher res

        img_v.addWidget(img_toolbar); img_v.addWidget(self.img_lbl, 1)
        spl.addWidget(img_w)

        # Right panel: console + R script with pill navigation
        right_panel = QWidget(); rp_v = QVBoxLayout(right_panel); rp_v.setContentsMargins(0, 0, 0, 0); rp_v.setSpacing(0)

        vpc_pill_bar = QWidget(); vpc_pill_bar.setObjectName('pillBar'); vpc_pill_bar.setFixedHeight(36)
        vpl = QHBoxLayout(vpc_pill_bar); vpl.setContentsMargins(8, 4, 8, 4); vpl.setSpacing(4)
        self._vpc_btns = []
        for i, lbl in enumerate(['Console', 'R Script']):
            btn = QPushButton(lbl); btn.setObjectName('pillBtn')
            btn.setCheckable(True); btn.setFixedHeight(26)
            btn.clicked.connect(lambda _, n=i: self._vpc_panel_switch(n))
            vpl.addWidget(btn); self._vpc_btns.append(btn)
        vpl.addStretch()
        rp_v.addWidget(vpc_pill_bar)

        vpc_sep = QWidget(); vpc_sep.setFixedHeight(1); vpc_sep.setObjectName('hairlineSep')
        rp_v.addWidget(vpc_sep)

        self._right_tabs = QStackedWidget()

        self.console = QPlainTextEdit(); self.console.setReadOnly(True)
        self.console.setFont(QFont('Menlo' if IS_MAC else 'Consolas', 11))
        self.console.setMaximumBlockCount(2000)
        self._apply_editor_palette(self.console)
        self._right_tabs.addWidget(self.console)

        # R Script panel — editable, with controls
        rscript_w = QWidget(); rv = QVBoxLayout(rscript_w); rv.setContentsMargins(0, 0, 0, 0); rv.setSpacing(0)
        rscript_ctrl = QWidget(); rscript_ctrl.setFixedHeight(34)
        rcl = QHBoxLayout(rscript_ctrl); rcl.setContentsMargins(8, 4, 8, 4); rcl.setSpacing(8)
        self.custom_script_cb = QCheckBox('Use custom script (edits below)')
        self.custom_script_cb.setToolTip(
            'When checked, the script below is used as-is.\n'
            'When unchecked, the script is rebuilt from settings on each run.')
        reset_btn = QPushButton('Reset from settings')
        reset_btn.setFixedHeight(24)
        reset_btn.setToolTip('Regenerate the R script from the current settings panel')
        reset_btn.clicked.connect(self._reset_r_script)
        rcl.addWidget(self.custom_script_cb); rcl.addStretch(); rcl.addWidget(reset_btn)
        self.r_script_edit = QPlainTextEdit()
        self.r_script_edit.setFont(QFont('Menlo' if IS_MAC else 'Consolas', 11))
        self.r_script_edit.setPlaceholderText('Generate a VPC to see and edit the R script here…')
        self._apply_editor_palette(self.r_script_edit)
        rv.addWidget(rscript_ctrl); rv.addWidget(self.r_script_edit, 1)
        self._right_tabs.addWidget(rscript_w)

        rp_v.addWidget(self._right_tabs, 1)
        spl.addWidget(right_panel)
        spl.setSizes([640, 400])
        v.addWidget(spl, 1)
        self._vpc_panel_switch(0)
        self._on_tool_change(self.tool_cb.currentText())
        self.use_psn_cb.stateChanged.connect(self._on_psn_inherit_change)
        self.use_psn_cb.setChecked(True)  # fires stateChanged → disables override widgets

    def _apply_editor_palette(self, widget):
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Base, QColor(T('bg2')))
        pal.setColor(QPalette.ColorRole.Text, QColor(T('fg')))
        pal.setColor(QPalette.ColorRole.Window, QColor(T('bg2')))
        widget.setPalette(pal)

    def _on_tool_change(self, tool):
        show_run_dir = (tool == 'xpose')
        self.run_dir_lbl.setVisible(show_run_dir)
        self.run_dir_w.setVisible(show_run_dir)
        self.lst_file_lbl.setVisible(show_run_dir)
        self.lst_file_w.setVisible(show_run_dir)

    def _check_r(self):
        def _do():
            has_r, pkgs = _check_r_packages()
            rscript = _find_rscript()
            # Emit signal to update UI from main thread
            self._r_check_done.emit(has_r, pkgs, rscript or '')
        threading.Thread(target=_do, daemon=True).start()

    def _on_r_check_done(self, has_r, pkgs, rscript):
        """Slot called on main thread when R check completes."""
        self._rscript = rscript if rscript else None
        self._pkg_avail = pkgs
        if not has_r:
            self.r_status_lbl.setText('R not found')
            return
        parts = []
        for p in ('vpc', 'xpose'):
            if pkgs.get(p):
                parts.append(f'{p} ✓')
            elif p == 'xpose' and pkgs.get('xpose4'):
                parts.append('xpose ✗ (xpose4 found — run install.packages("xpose"))')
            else:
                parts.append(f'{p} ✗')
        self.r_status_lbl.setText('R: ' + '  '.join(parts))

    def _on_psn_inherit_change(self, _state=None):
        """Enable/disable manual-override widgets based on 'Use PsN settings' checkbox."""
        override = not self.use_psn_cb.isChecked()
        for w in (self.pred_corr_cb, self.stratify_edit, self.lloq_edit, self.lloq_method_cb, self.uloq_edit, self.nbins_sb):
            w.setEnabled(override)

    def _browse_vpc(self):
        d = str(Path(self._model['path']).parent) if self._model else str(HOME)
        folder = QFileDialog.getExistingDirectory(self, 'Select PsN VPC output folder', d)
        if folder: self.vpc_folder_edit.setText(folder)

    def _browse_run(self):
        d = str(Path(self._model['path']).parent) if self._model else str(HOME)
        folder = QFileDialog.getExistingDirectory(self, 'Select run directory', d)
        if folder: self.run_dir_edit.setText(folder)

    def _browse_lst(self):
        d = str(Path(self._model['path']).parent) if self._model else str(HOME)
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select model .lst file', d, 'NONMEM output (*.lst);;All files (*)')
        if path:
            self.lst_file_edit.setText(path)

    def load_model(self, model):
        self._model = model
        # Run number: prefer table_runno from sdtab, fall back to stem digits
        runno = model.get('table_runno', '')
        if not runno:
            # Extract trailing digits from stem e.g. run104 -> 104
            m = re.search(r'(\d+)$', model.get('stem', ''))
            if m: runno = m.group(1)
        if runno:
            self.runno_edit.setText(runno)
        # Auto-populate VPC folder: look for vpc_* subdirs near the model
        if model.get('lst_path'):
            lst_dir = Path(model['lst_path']).parent
            vpc_dirs = sorted(lst_dir.glob('vpc_*'))
            if vpc_dirs: self.vpc_folder_edit.setText(str(vpc_dirs[-1]))
            # Run dir for xpose — use lst directory (where sdtabs live)
            self.run_dir_edit.setText(str(lst_dir))

    def _parse_psn_meta(self, vpc_folder):
        """Parse PsN's meta.yaml (preferred) or command.txt (fallback) to recover
        the actual VPC options used by PsN — most importantly the IDV column.

        Returns dict with keys: idv, dv, predcorr, stratify_on, samples, lloq.
        Missing values are None (or False for predcorr).

        Why: vpc::vpc(psn_folder=...) and xpose::vpc_data(psn_folder=...) do not
        auto-detect the IDV from PsN output, so users who pass `-idv=TAD`
        (or any non-default IDV name) hit a "no idv column" error. PsN itself
        records the IDV in meta.yaml under tool_options.
        """
        opts = {'idv': None, 'dv': None, 'predcorr': False,
                'stratify_on': None, 'samples': None, 'lloq': None,
                'vpc_type': None, 'lnDV': False}
        vpc_path = Path(vpc_folder)

        # Preferred: meta.yaml (PsN ≥4.x). Inline parser to avoid pyyaml dep.
        meta = vpc_path / 'meta.yaml'
        if meta.is_file():
            try:
                in_tool = False
                for raw in meta.read_text('utf-8', errors='replace').splitlines():
                    if raw.rstrip() == 'tool_options:':
                        in_tool = True
                        continue
                    if in_tool:
                        # Block ends when we hit a non-indented line
                        if raw and not raw.startswith(' '):
                            break
                        s = raw.strip()
                        if ':' not in s:
                            continue
                        key, val = s.split(':', 1)
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key == 'idv' and val:
                            opts['idv'] = val
                        elif key == 'dv' and val:
                            opts['dv'] = val
                        elif key == 'predcorr':
                            opts['predcorr'] = (val == '1')
                        elif key == 'stratify_on' and val:
                            opts['stratify_on'] = val
                        elif key == 'samples' and val:
                            try: opts['samples'] = int(val)
                            except ValueError: pass
                        elif key == 'lloq' and val:
                            try: opts['lloq'] = float(val)
                            except ValueError: pass
                        elif key == 'vpc_type' and val:
                            try: opts['vpc_type'] = int(val)
                            except ValueError: pass
                        elif key == 'categorical' and val == '1':
                            opts['vpc_type'] = 2
                        elif key == 'tte' and val == '1':
                            opts['vpc_type'] = 3
                        elif key == 'lnDV':
                            opts['lnDV'] = (val == '1')
            except Exception as e:
                _log.warning(f'Failed to parse meta.yaml: {e}')

        # Fallback: command.txt (older PsN). Only fill what meta.yaml didn't.
        cmd = vpc_path / 'command.txt'
        if cmd.is_file():
            try:
                text = cmd.read_text('utf-8', errors='replace')
                if not opts['idv']:
                    m = re.search(r'-idv[= ](\S+)', text)
                    if m: opts['idv'] = m.group(1)
                m = re.search(r'-dv[= ](\S+)', text)
                if m and not opts['dv']: opts['dv'] = m.group(1)
                if not opts['predcorr'] and re.search(r'-predcorr\b', text):
                    opts['predcorr'] = True
                m = re.search(r'-stratify_on[= ](\S+)', text)
                if m and not opts['stratify_on']: opts['stratify_on'] = m.group(1)
                m = re.search(r'-samples[= ](\d+)', text)
                if m and not opts['samples']: opts['samples'] = int(m.group(1))
                m = re.search(r'-lloq[= ](\S+)', text)
                if m and opts['lloq'] is None:
                    try: opts['lloq'] = float(m.group(1))
                    except ValueError: pass
                if opts['vpc_type'] is None:
                    if re.search(r'-categorical\b', text): opts['vpc_type'] = 2
                    elif re.search(r'-tte\b', text): opts['vpc_type'] = 3
                if not opts['lnDV'] and re.search(r'-lnDV=1\b', text):
                    opts['lnDV'] = True
            except Exception as e:
                _log.warning(f'Failed to parse command.txt: {e}')

        return opts

    def _ensure_m1_extracted(self, vpc_folder):
        """Ensure m1/ is extracted from m1.zip if needed.

        PsN's vpc command zips the m1 directory when -clean>=2, but the R-based
        VPC backends (PsN's vpc.R and xpose) read simulation tables from m1/
        directly, so the zip must be unpacked before they can run.

        Returns (success, error_message). Logs progress to the console widget.
        """
        vpc_path = Path(vpc_folder)
        m1_dir = vpc_path / 'm1'
        m1_zip = vpc_path / 'm1.zip'

        # m1/ exists and has content — check for a newer m1.zip (PsN re-run)
        if m1_dir.is_dir() and any(m1_dir.iterdir()):
            if m1_zip.is_file():
                try:
                    newest_m1 = max(p.stat().st_mtime for p in m1_dir.rglob('*') if p.is_file())
                    if m1_zip.stat().st_mtime > newest_m1:
                        self.console.appendPlainText(
                            'm1.zip is newer than extracted m1/ — re-extracting…')
                        import shutil
                        shutil.rmtree(m1_dir, ignore_errors=True)
                        # Fall through to extract below
                    else:
                        return True, ''
                except Exception:
                    return True, ''   # Can't compare — leave as-is
            else:
                return True, ''

        # No zip and no folder — leave it; downstream will report a clearer
        # error if simulation tables turn out to be needed
        if not m1_zip.is_file():
            return True, ''

        self.console.appendPlainText(f'Extracting {m1_zip.name}…')
        try:
            with zipfile.ZipFile(m1_zip) as zf:
                bad = zf.testzip()
                if bad is not None:
                    return False, f'm1.zip is corrupt: first bad entry is {bad}'
                zf.extractall(vpc_path)
        except zipfile.BadZipFile as e:
            return False, f'm1.zip is not a valid zip file:\n{e}'
        except PermissionError as e:
            return False, f'Cannot write to {vpc_path} (permission denied):\n{e}'
        except OSError as e:
            return False, f'Failed to extract m1.zip:\n{e}'

        # Confirm extraction produced m1/ with content
        if not m1_dir.is_dir() or not any(m1_dir.iterdir()):
            return False, (
                'Extracted m1.zip but m1/ is still missing or empty.\n'
                'The zip may have an unexpected layout.')

        n_files = sum(1 for p in m1_dir.rglob('*') if p.is_file())
        self.console.appendPlainText(f'Extracted {n_files} file(s) into m1/')

        # Also extract m2.zip, m3.zip, … if present (PsN -n_simulation_models > 1)
        extra_zips = sorted(vpc_path.glob('m[2-9]*.zip'))
        for extra_zip in extra_zips:
            extra_dir = vpc_path / extra_zip.stem
            if extra_dir.is_dir() and any(extra_dir.iterdir()):
                continue  # already extracted
            self.console.appendPlainText(f'Extracting {extra_zip.name}…')
            try:
                with zipfile.ZipFile(extra_zip) as zf:
                    bad = zf.testzip()
                    if bad:
                        self.console.appendPlainText(
                            f'[WARNING] {extra_zip.name} is corrupt ({bad}) — skipping')
                        continue
                    zf.extractall(vpc_path)
                n = sum(1 for p in extra_dir.rglob('*') if p.is_file())
                self.console.appendPlainText(f'Extracted {n} file(s) into {extra_dir.name}/')
            except Exception as e:
                self.console.appendPlainText(f'[WARNING] Failed to extract {extra_zip.name}: {e}')

        return True, ''

    def _validate_stratify_column(self, vpc_folder, strat_columns):
        """Validate stratification column(s) exist and have reasonable cardinality."""
        vpc_path = Path(vpc_folder)

        # Parse column names (comma-separated)
        cols = [c.strip() for c in strat_columns.split(',') if c.strip()]
        if not cols:
            return True, ""

        # Try to find data columns from vpctab or vpc_results.csv
        header = None
        data_rows = []

        # Try vpctab files first
        for vpctab in vpc_path.glob('vpctab*'):
            if vpctab.is_file():
                try:
                    lines = vpctab.read_text('utf-8', errors='replace').strip().split('\n')
                    # Skip TABLE lines
                    data_lines = [l for l in lines if not l.startswith('TABLE')]
                    if data_lines:
                        header = data_lines[0].split()
                        data_rows = [l.split() for l in data_lines[1:100]]  # Sample first 100
                        break
                except Exception:
                    continue

        # Fallback to m1/vpc_simulation.1.npctab.dta or similar
        if not header:
            m1_dir = vpc_path / 'm1'
            for f in (m1_dir.glob('*.dta') if m1_dir.is_dir() else []):
                try:
                    lines = f.read_text('utf-8', errors='replace').strip().split('\n')
                    data_lines = [l for l in lines if not l.startswith('TABLE')]
                    if data_lines:
                        header = data_lines[0].split()
                        data_rows = [l.split() for l in data_lines[1:100]]
                        break
                except Exception:
                    continue

        if not header:
            # Can't validate without header - allow it but warn
            _log.warning(f'Could not find VPC data to validate stratification column: {strat_columns}')
            return True, ""

        # Check each column
        for col in cols:
            if col not in header:
                return False, f"Column '{col}' not found in VPC data.\n\nAvailable columns: {', '.join(header[:20])}"

            # Check cardinality
            if data_rows:
                try:
                    idx = header.index(col)
                    unique_vals = set(row[idx] for row in data_rows if len(row) > idx)
                    n_unique = len(unique_vals)

                    if n_unique < 2:
                        return False, f"Column '{col}' has only 1 unique value - cannot stratify."
                    if n_unique > 20:
                        return False, f"Column '{col}' has {n_unique} unique values (sampled from first 100 rows).\n\nStratification with >20 levels is not recommended. Use a categorical column."
                except Exception:
                    pass

        return True, ""

    def _resolve_idv(self, vpc_folder):
        """Compute the IDV column to forward to vpc/xpose, or None for default.

        Resolution order:
          1. Manual override in idv_edit (if non-empty)
          2. PsN's meta.yaml / command.txt (if non-default)
          3. None — let the package fall back to its default ('TIME')
        """
        user = self.idv_edit.text().strip()
        if user:
            return user
        detected = self._parse_psn_meta(vpc_folder).get('idv')
        if detected and detected.upper() not in ('TIME', 'T'):
            return detected
        return None

    def _resolve_xpose_lst(self, vpc_folder):
        """Find the .lst file xpose_data() should load.

        Resolution order:
          1. User override in lst_file_edit
          2. Parse command.txt to get model name -> check {name}.lst in parent dir
          3. UI runno -> check run{runno}.lst in parent dir
          4. None (falls back to runno= form, may fail)

        Returns (path_or_None, warning_str_or_None).
        """
        user_lst = self.lst_file_edit.text().strip()
        if user_lst:
            if Path(user_lst).is_file():
                return user_lst, None
            else:
                return None, f'Specified model .lst file not found:\n{user_lst}'

        vpc_path = Path(vpc_folder)
        parent = vpc_path.parent

        cmd = vpc_path / 'command.txt'
        if cmd.is_file():
            try:
                text = cmd.read_text('utf-8', errors='replace')
                m = re.search(r'(?:^|\s)([^\s-]\S*\.mod)(?:\s|$)', text, re.MULTILINE)
                if m:
                    model_stem = Path(m.group(1).strip()).stem
                    lst_candidate = parent / f'{model_stem}.lst'
                    if lst_candidate.is_file():
                        return str(lst_candidate), None
                    available = sorted(f.name for f in parent.glob('*.lst'))
                    avail_str = ', '.join(available) if available else '(none found)'
                    warn = (
                        f'Auto-detect: model "{model_stem}.lst" not found in parent directory.\n'
                        f'Available .lst files: {avail_str}\n'
                        f'Set the "Model .lst" field in the xpose settings to proceed.')
                    return None, warn
            except Exception as e:
                _log.warning(f'command.txt parse failed: {e}')

        runno = self.runno_edit.text().strip()
        if runno:
            lst_candidate = parent / f'run{runno}.lst'
            if lst_candidate.is_file():
                return str(lst_candidate), None

        return None, None

    def _resolve_dv(self, vpc_folder, psn_opts=None):
        """Resolve DV column name, or None if default ('DV')."""
        if psn_opts is None:
            psn_opts = self._parse_psn_meta(vpc_folder)
        dv = psn_opts.get('dv')
        if dv and dv.upper() not in ('DV',):
            return dv
        return None

    def _build_r_script(self):
        tool       = self.tool_cb.currentText()
        vpc_folder = self.vpc_folder_edit.text().strip()
        run_dir    = self.run_dir_edit.text().strip() or vpc_folder
        runno      = self.runno_edit.text().strip() or '001'
        log_y      = self.log_y_cb.isChecked()
        use_psn    = self.use_psn_cb.isChecked()
        pi_lo      = self.pi_lo.value(); pi_hi = self.pi_hi.value()
        ci_lo      = self.ci_lo.value(); ci_hi = self.ci_hi.value()
        idv        = self._resolve_idv(vpc_folder)   # may be None
        psn_opts   = self._parse_psn_meta(vpc_folder)

        r_vpc = _sanitize_r(vpc_folder)
        r_run = _sanitize_r(run_dir)
        r_out = _sanitize_r(str(Path(vpc_folder) / 'nmgui_vpc.png'))

        if tool == 'vpc':
            args = {'psn_folder': f'"{r_vpc}"'}
            # obs_cols/sim_cols: forward non-default IDV and/or DV
            dv = self._resolve_dv(vpc_folder, psn_opts)
            if dv:
                obs_parts = [f'idv = "{idv}"'] if idv else []
                obs_parts.append(f'dv = "{dv}"')
                sim_parts = obs_parts[:]
                args['obs_cols'] = f'list({", ".join(obs_parts)})'
                args['sim_cols'] = f'list({", ".join(sim_parts)})'
            elif idv:
                args['obs_cols'] = f'list(idv = "{idv}")'
                args['sim_cols'] = f'list(idv = "{idv}")'
            # Auto-inject from PsN meta when using PsN settings
            if use_psn and psn_opts.get('predcorr'):
                args['pred_corr'] = 'TRUE'
            if use_psn and psn_opts.get('stratify_on'):
                args['stratify'] = f'"{psn_opts["stratify_on"]}"'
            if not use_psn:
                lloq_raw = self.lloq_edit.text().strip()
                uloq_raw = self.uloq_edit.text().strip()
                strat    = self.stratify_edit.text().strip()
                args['pred_corr'] = 'TRUE' if self.pred_corr_cb.isChecked() else 'FALSE'
                if lloq_raw:
                    args['lloq'] = lloq_raw
                    args['lloq_method'] = f'"{self.lloq_method_cb.currentText().lower()}"'
                if uloq_raw:
                    args['uloq'] = uloq_raw
                args['bins']   = '"jenks"'
                args['n_bins'] = int(self.nbins_sb.value())
                if strat:
                    vars_ = [_r_col(v.strip()) for v in strat.split(',') if v.strip()]
                    args['stratify'] = (f'"{vars_[0]}"' if len(vars_) == 1
                                        else 'c(' + ','.join(f'"{v}"' for v in vars_) + ')')
            args['pi']   = f'c({pi_lo}, {pi_hi})'
            args['ci']   = f'c({ci_lo}, {ci_hi})'
            args['show'] = ('list(obs_dv=TRUE, obs_ci=FALSE, pi=TRUE, '
                            'pi_as_area=FALSE, pi_ci=TRUE, obs_median=TRUE, sim_median=TRUE)')
            args_str  = ',\n    '.join(f'{k} = {v}' for k, v in args.items())
            log_extra = '\n  vpc_plot <- vpc_plot + ggplot2::scale_y_log10()' if log_y else ''
            script = f'''# NMGUI VPC — tool: vpc (Ron Keizer)
Sys.setlocale("LC_NUMERIC", "C")
library(vpc)
library(ggplot2)

tryCatch({{
  # withCallingHandlers muffles readr "parsing failures" from NONMEM TABLE headers
  vpc_plot <- withCallingHandlers(
    vpc(
      {args_str}
    ),
    warning = function(w) {{
      if (grepl("parsing failure", conditionMessage(w), ignore.case=TRUE))
        invokeRestart("muffleWarning")
    }}
  )
  if (is.null(vpc_plot)) stop("vpc() returned NULL")
  # Handle vpc package v1.x which returns a list with $plot
  if (!inherits(vpc_plot, "gg") && !inherits(vpc_plot, "ggplot")) {{
    if (is.list(vpc_plot) && (inherits(vpc_plot$plot, "gg") || inherits(vpc_plot$plot, "ggplot"))) {{
      vpc_plot <- vpc_plot$plot
    }} else {{
      stop("vpc() returned an unrecognised object type (expected ggplot or vpc list)")
    }}
  }}{log_extra}
  ggsave("{r_out}", vpc_plot, width=8, height=6, dpi=150)
  cat("NMGUI_VPC_OK\\n")
}}, error=function(e) {{
  cat("NMGUI_VPC_ERROR:", conditionMessage(e), "\\n")
}})
'''
        else:  # xpose
            # Resolve .lst file for xpose_data() (GAP 0)
            lst_path, _lst_warn = self._resolve_xpose_lst(vpc_folder)
            if lst_path:
                r_lst = _sanitize_r(lst_path)
                xpdb_line = f'xpdb <- xpose_data(file="{r_lst}")'
            else:
                xpdb_line = f'xpdb <- xpose_data(runno="{runno}", dir="{r_run}/")'
            if use_psn:
                opt_items = []
                if idv:                      opt_items.append(f'idv="{idv}"')
                if psn_opts.get('predcorr'): opt_items.append('pred_corr=pred_corr_val')
                opt_str = f', opt=vpc_opt({", ".join(opt_items)})' if opt_items else ''
                stratify_arg = ''
                if psn_opts.get('stratify_on'):
                    stratify_arg = f', stratify_on=c("{psn_opts["stratify_on"]}")'
                vpc_data_call = f'vpc_data(psn_folder="{r_vpc}", psn_bins=TRUE{opt_str}{stratify_arg})'
            else:
                lloq_raw = self.lloq_edit.text().strip()
                uloq_raw = self.uloq_edit.text().strip()
                strat    = self.stratify_edit.text().strip()
                opt_parts = [f'bins="jenks"', f'n_bins={int(self.nbins_sb.value())}']
                if idv:      opt_parts.append(f'idv="{idv}"')
                if lloq_raw: opt_parts.append(f'lloq={lloq_raw}')
                if uloq_raw: opt_parts.append(f'uloq={uloq_raw}')
                if self.pred_corr_cb.isChecked(): opt_parts.append('pred_corr=TRUE')
                vpc_data_args = [f'opt=vpc_opt({",".join(opt_parts)})',
                                 f'psn_folder="{r_vpc}"']
                if strat:
                    vars_ = [_r_col(v.strip()) for v in strat.split(',') if v.strip()]
                    strat_val = (f'"{vars_[0]}"' if len(vars_) == 1
                                 else 'c(' + ','.join(f'"{v}"' for v in vars_) + ')')
                    vpc_data_args.append(f'stratify={strat_val}')
                vpc_data_call = f'vpc_data({", ".join(vpc_data_args)})'
            vpc_call = 'vpc() + ggplot2::scale_y_log10()' if log_y else 'vpc()'
            script = f'''# NMGUI VPC — tool: xpose
Sys.setlocale("LC_NUMERIC", "C")
library(xpose)
library(ggplot2)

tryCatch({{
  {xpdb_line}
  # xpose version compatibility for pred_corr
  xpose_ver <- tryCatch(as.numeric(utils::packageVersion("xpose")), error=function(e) 0)
  pred_corr_val <- if (xpose_ver >= 0.4) TRUE else 1
  vpc_plot <- xpdb %>%
    {vpc_data_call} %>%
    {vpc_call}
  if (is.null(vpc_plot)) stop("xpose vpc() returned NULL")
  ggsave("{r_out}", vpc_plot, width=8, height=6, dpi=150)
  cat("NMGUI_VPC_OK\\n")
}}, error=function(e) {{
  cat("NMGUI_VPC_ERROR:", conditionMessage(e), "\\n")
  cat("  sdtab files in run dir: ", paste(list.files("{r_run}", pattern="^sdtab"), collapse=", "), "\\n")
  cat("  .lst files in run dir:  ", paste(list.files("{r_run}", pattern=glob2rx("*.lst")), collapse=", "), "\\n")
  cat("  .mod files in run dir:  ", paste(list.files("{r_run}", pattern=glob2rx("*.mod")), collapse=", "), "\\n")
}})
'''
        return script, str(Path(vpc_folder) / 'nmgui_vpc.png')

    def _run(self):
        vpc_folder = self.vpc_folder_edit.text().strip()
        if not vpc_folder or not Path(vpc_folder).is_dir():
            QMessageBox.warning(self, 'Missing folder', 'Select a valid PsN VPC output folder first.')
            return
        if not self._rscript:
            QMessageBox.warning(self, 'R not found', 'Rscript not found. Is R installed and on PATH?')
            return

        # Clear console up front so extraction + run output land in a fresh log
        self.console.clear()

        # PsN with -clean>=2 zips m1/. vpc.R / xpose need the unpacked dir.
        ok, err = self._ensure_m1_extracted(vpc_folder)
        if not ok:
            QMessageBox.warning(self, 'm1.zip extraction failed', err)
            return

        # Warn if vpc_results.csv is absent (PsN -no_results=1 or aborted run)
        if not (Path(vpc_folder) / 'vpc_results.csv').is_file():
            self.console.appendPlainText(
                '[WARNING] vpc_results.csv not found in the VPC folder.\n'
                'PsN may have been run with -no_results=1, or the run did not complete.\n'
                'The R backend may fail or produce an incomplete plot.')

        # Log the PsN options recovered from meta.yaml / command.txt — visibility
        # for users debugging "wrong column" issues.
        psn_opts = self._parse_psn_meta(vpc_folder)
        parts = []
        if psn_opts.get('idv'):         parts.append(f'idv={psn_opts["idv"]}')
        if psn_opts.get('dv'):          parts.append(f'dv={psn_opts["dv"]}')
        if psn_opts.get('predcorr'):    parts.append('predcorr=1')
        if psn_opts.get('stratify_on'): parts.append(f'stratify_on={psn_opts["stratify_on"]}')
        if psn_opts.get('samples'):     parts.append(f'samples={psn_opts["samples"]}')
        if psn_opts.get('lloq') is not None: parts.append(f'lloq={psn_opts["lloq"]}')
        if parts:
            self.console.appendPlainText('Detected PsN options: ' + ', '.join(parts))
        resolved_idv = self._resolve_idv(vpc_folder)
        if resolved_idv:
            self.console.appendPlainText(f'Using IDV column: {resolved_idv}')

        # vpc_type pre-check: abort for unsupported VPC types (GAP 4)
        vpc_type = psn_opts.get('vpc_type')
        if vpc_type in (2, 3):
            type_name = 'categorical' if vpc_type == 2 else 'time-to-event (TTE)'
            QMessageBox.warning(self, 'VPC type not supported',
                f'PsN was run with a {type_name} VPC (-vpc_type={vpc_type}).\n\n'
                f'NMGUI2 currently supports only continuous VPCs. '
                f'For {type_name} VPCs, please run the R script manually '
                f'using vpc_cat() or vpc_tte() from the vpc package.\n\n'
                f'The R script tab will show the generated script as a starting point.')
            return

        # Auto-enable log Y axis when lnDV detected (GAP 5)
        if self.use_psn_cb.isChecked() and psn_opts.get('lnDV'):
            self.log_y_cb.setChecked(True)
            self.console.appendPlainText('Auto-enabling log Y axis (PsN -lnDV=1 detected)')

        # xpose: pre-check model .lst file resolution (GAP 0)
        if self.tool_cb.currentText() == 'xpose':
            _lst_path, _lst_warn = self._resolve_xpose_lst(vpc_folder)
            if _lst_warn:
                self.console.appendPlainText(f'[WARNING] {_lst_warn}')
            elif _lst_path:
                self.console.appendPlainText(f'xpose model file: {Path(_lst_path).name}')

        # Log auto-injected stratification (GAP 2)
        if psn_opts.get('stratify_on') and self.use_psn_cb.isChecked():
            self.console.appendPlainText(f'Auto-stratifying on: {psn_opts["stratify_on"]}')

        # Validate stratification column if specified
        strat = self.stratify_edit.text().strip()
        if strat and not self.use_psn_cb.isChecked():
            valid, msg = self._validate_stratify_column(vpc_folder, strat)
            if not valid:
                QMessageBox.warning(self, 'Stratification error', msg)
                return

        _, output_png = self._build_r_script()   # always need output_png

        if self.custom_script_cb.isChecked():
            # Use whatever is in the editor — user may have tweaked it
            script_txt = self.r_script_edit.toPlainText().strip()
            if not script_txt:
                QMessageBox.warning(self, 'Empty script',
                    'Custom script is empty. Uncheck "Use custom script" to rebuild from settings.')
                return
        else:
            # Rebuild from settings
            script_txt, output_png = self._build_r_script()
            self._last_script_txt = script_txt
            self.r_script_edit.setPlainText(script_txt)

        script_path = str(Path(vpc_folder) / 'nmgui_vpc_script.R')
        # Delete stale PNG
        if Path(output_png).is_file():
            try: Path(output_png).unlink()
            except Exception: pass  # File may be locked
        try:
            Path(script_path).write_text(script_txt, 'utf-8')
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Cannot write R script:\n{e}'); return
        # Console was already cleared at the top of _run() before extraction.
        self.console.appendPlainText(
            f'Running {self.tool_cb.currentText()} VPC'
            f'{"  [custom script]" if self.custom_script_cb.isChecked() else ""}…\n')
        self.run_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self.tool_lbl.setText(f'Backend: {self.tool_cb.currentText()}')
        if self._worker:
            try: self._worker.line_out.disconnect()
            except Exception: pass  # Signal may not be connected
            try: self._worker.finished.disconnect()
            except Exception: pass  # Signal may not be connected
        self._worker = VPCWorker(script_path, output_png, self._rscript, get_login_env(),
                                  timeout_sec=self.timeout_sb.value() * 60)
        self._worker.line_out.connect(self._on_line)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _reset_r_script(self):
        """Rebuild the R script from current settings and populate the editor."""
        vpc_folder = self.vpc_folder_edit.text().strip()
        if not vpc_folder or not Path(vpc_folder).is_dir():
            QMessageBox.warning(self, 'Missing folder', 'Set the VPC folder first.'); return
        script_txt, _ = self._build_r_script()
        self._last_script_txt = script_txt
        self.r_script_edit.setPlainText(script_txt)
        self._vpc_panel_switch(1)   # switch to R Script tab
        self.status_msg.emit('R script reset from settings')

    def _vpc_panel_switch(self, index):
        self._right_tabs.setCurrentIndex(index)
        for i, btn in enumerate(self._vpc_btns):
            btn.setChecked(i == index)

    def _on_line(self, line):
        self.console.appendPlainText(line)
        if 'NMGUI_VPC_ERROR' in line:
            self._vpc_panel_switch(0)

    def _on_done(self, success, path_or_err):
        self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        if success:
            self._last_png = path_or_err
            self._load_image(path_or_err)
            for b in (self._open_btn, self._savepng_btn, self._savepdf_btn):
                b.setEnabled(True)
            self.status_msg.emit('VPC generated successfully')
        else:
            self.console.appendPlainText(f'\n[FAILED] {path_or_err}')
            self.img_lbl.setText(f'VPC failed.\nSee Console tab for details.\n\n{path_or_err}')
            self._vpc_panel_switch(0)
            self.status_msg.emit('VPC failed — see console')

    def _load_image(self, path):
        try:
            self._orig_px = QPixmap(path)   # keep original for resize
            if self._orig_px.isNull(): raise ValueError('QPixmap could not load image')
            self._scale_image()
        except Exception as e:
            self.img_lbl.setText(f'Image load error: {e}')
            self._orig_px = None

    def _scale_image(self):
        if not hasattr(self, '_orig_px') or self._orig_px is None: return
        scaled = self._orig_px.scaled(
            self.img_lbl.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.img_lbl.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_image()

    # ── Export methods ────────────────────────────────────────────────────────

    def _open_in_viewer(self):
        """Open the generated PNG in the OS default image viewer."""
        if not self._last_png or not Path(self._last_png).is_file():
            QMessageBox.warning(self, 'No image', 'No VPC image available.'); return
        try:
            if IS_WIN:
                os.startfile(self._last_png)
            elif IS_MAC:
                subprocess.Popen(['open', self._last_png])
            else:
                subprocess.Popen(['xdg-open', self._last_png])
        except Exception as e:
            QMessageBox.warning(self, 'Error', f'Could not open viewer:\n{e}')

    def _export_hires_png(self):
        """Re-run the VPC R script at 300 DPI and save to a user-chosen path."""
        if not self._last_script_txt or not self._rscript:
            QMessageBox.warning(self, 'Not available', 'No VPC script available. Generate a VPC first.'); return
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save high-res PNG', str(HOME / 'vpc_hires.png'),
            'PNG images (*.png)')
        if not dst: return
        # Patch the script: replace dpi=150 with dpi=300 and the output path
        r_dst = _sanitize_r(dst)
        script = self._last_script_txt
        script = re.sub(r'dpi\s*=\s*\d+', 'dpi=300', script)
        script = re.sub(r'res\s*=\s*\d+',  'res=300', script)
        # Replace output path in ggsave / png()
        if self._last_png:
            r_orig = _sanitize_r(self._last_png)
            script = script.replace(f'"{r_orig}"', f'"{r_dst}"')
        # Write temp script and run
        tmp = Path(dst).parent / '_nmgui_vpc_hires_tmp.R'
        try:
            tmp.write_text(script, 'utf-8')
            self.console.appendPlainText(f'\nExporting 300 DPI PNG to {dst}…')
            self.run_btn.setEnabled(False)
            worker = VPCWorker(str(tmp), dst, self._rscript, get_login_env())
            worker.line_out.connect(self.console.appendPlainText)
            worker.finished.connect(lambda ok, p: self._on_export_done(ok, p, 'PNG', dst, tmp))
            self._export_worker = worker
            worker.start()
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    def _export_pdf(self):
        """Re-run the VPC R script saving as a vector PDF."""
        if not self._last_script_txt or not self._rscript:
            QMessageBox.warning(self, 'Not available', 'No VPC script available. Generate a VPC first.'); return
        dst, _ = QFileDialog.getSaveFileName(
            self, 'Save PDF', str(HOME / 'vpc.pdf'),
            'PDF files (*.pdf)')
        if not dst: return
        r_dst = _sanitize_r(dst)
        script = self._last_script_txt
        # ggsave with pdf device (both vpc and xpose backends use ggsave)
        if self._last_png:
            r_orig = _sanitize_r(self._last_png)
            script = script.replace(f'ggsave("{r_orig}"', f'ggsave("{r_dst}"')
        script = re.sub(r',\s*dpi\s*=\s*\d+', '', script)
        tmp = Path(dst).parent / '_nmgui_vpc_pdf_tmp.R'
        try:
            tmp.write_text(script, 'utf-8')
            self.console.appendPlainText(f'\nExporting PDF to {dst}…')
            self.run_btn.setEnabled(False)
            worker = VPCWorker(str(tmp), dst, self._rscript, get_login_env())
            worker.line_out.connect(self.console.appendPlainText)
            worker.finished.connect(lambda ok, p: self._on_export_done(ok, p, 'PDF', dst, tmp))
            self._export_worker = worker
            worker.start()
        except Exception as e:
            QMessageBox.critical(self, 'Error', str(e))

    def _on_export_done(self, success, path_or_err, kind, dst, tmp):
        self.run_btn.setEnabled(True)
        try: tmp.unlink()
        except Exception: pass  # Temp file cleanup is non-critical
        if success and Path(dst).is_file():
            self.console.appendPlainText(f'[OK] {kind} saved to {dst}')
            self.status_msg.emit(f'{kind} exported: {Path(dst).name}')
            if QMessageBox.question(self, f'{kind} saved',
                f'{kind} saved to:\n{dst}\n\nOpen now?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                self._open_file(dst)
        else:
            self.console.appendPlainText(f'[FAILED] {kind} export: {path_or_err}')
            self.status_msg.emit(f'{kind} export failed')

    def _open_file(self, path):
        try:
            if IS_WIN:   os.startfile(path)
            elif IS_MAC: subprocess.Popen(['open', path])
            else:        subprocess.Popen(['xdg-open', path])
        except Exception as e: _log.debug(f'Could not open file {path}: {e}')

    def _stop(self):
        if self._worker: self._worker.terminate()
        self.run_btn.setEnabled(True); self.stop_btn.setEnabled(False)
