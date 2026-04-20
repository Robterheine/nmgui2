import re
import time
import shlex
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QWidget, QMenu,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPalette, QColor, QCloseEvent

from ..app.theme import C, T
from ..app.constants import IS_WIN, IS_MAC
from ..app.workers import RunWorker
from ..app.run_records import create_run_record, finalize_run_record, load_run_records, save_run_records
from ..app.config import load_runs, save_runs
from ..app import detached_runs as _dr

_RE_ITER = re.compile(r'ITERATION NO\.\s*:\s*(\d+)\s+OBJECTIVE VALUE\s*:\s*([-\d.]+(?:E[+-]?\d+)?)', re.IGNORECASE)
_RE_PSN  = re.compile(r'(?:run|model)\s+(\d+)\s*/\s*(\d+)', re.IGNORECASE)


class RunPopup(QDialog):
    """Floating output window for a single NONMEM/PsN run."""
    run_completed = pyqtSignal(str, str, int)   # stem, cwd, return_code

    def __init__(self, stem, tool, cmd, cwd, model_path, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.stem = stem
        self.tool = tool
        self.cmd  = cmd
        self.cwd  = cwd
        self.model_path = model_path
        self._worker: RunWorker | None = None
        self._start_ts = datetime.now()
        self._elapsed  = 0
        self._last_ofv: str | None = None   # remembered for completion status line
        self._run_record = None
        self._finished = False

        self.setWindowTitle(f'{stem} — {tool}')
        self.setObjectName('RunPopupDlg')
        self.resize(720, 500)
        self.setMinimumSize(500, 300)

        self._build_ui()
        self._apply_theme()
        self._start_run()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setSpacing(0)
        v.setContentsMargins(0, 0, 0, 0)

        # ── Header bar ────────────────────────────────────────────────────────
        hdr = QWidget(); hdr.setObjectName('runPopupHeader')
        hdr.setFixedHeight(44)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        hl.setSpacing(10)

        title_lbl = QLabel(self.stem)
        title_lbl.setStyleSheet('font-size:15px; font-weight:700;')
        tool_lbl  = QLabel(self.tool.upper())
        tool_lbl.setObjectName('muted')
        started_lbl = QLabel(f'Started {self._start_ts.strftime("%H:%M:%S")}')
        started_lbl.setObjectName('muted')

        hl.addWidget(title_lbl)
        hl.addWidget(tool_lbl)
        hl.addStretch()
        hl.addWidget(started_lbl)
        v.addWidget(hdr)

        # hairline below header (separate widget — no border-bottom on header)
        v.addWidget(self._hairline())

        # ── Status bar ────────────────────────────────────────────────────────
        sb = QWidget(); sb.setObjectName('runPopupStatus')
        sb.setFixedHeight(28)
        sl = QHBoxLayout(sb)
        sl.setContentsMargins(12, 0, 12, 0)
        sl.setSpacing(12)

        self._status_lbl   = QLabel('● Running')
        self._progress_lbl = QLabel('')
        self._progress_lbl.setObjectName('muted')
        self._elapsed_lbl  = QLabel('0:00')
        self._elapsed_lbl.setObjectName('muted')

        sl.addWidget(self._status_lbl)
        sl.addWidget(self._progress_lbl)
        sl.addStretch()
        sl.addWidget(self._elapsed_lbl)
        v.addWidget(sb)

        # hairline below status
        v.addWidget(self._hairline())

        # ── Console ───────────────────────────────────────────────────────────
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(10000)
        self.console.setFont(QFont('Menlo' if IS_MAC else 'Consolas', 11))
        v.addWidget(self.console, 1)

        # ── Button row ────────────────────────────────────────────────────────
        v.addWidget(self._hairline())

        btn_w = QWidget()
        bl = QHBoxLayout(btn_w)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(6)

        self.stop_btn = QPushButton('Stop')
        self.stop_btn.setObjectName('danger')
        self.stop_btn.setFixedWidth(70)
        self.stop_btn.setToolTip('Click to stop the run')
        self.stop_btn.clicked.connect(self._show_stop_menu)

        self.open_dir_btn = QPushButton('Open run dir')
        self.open_dir_btn.clicked.connect(self._open_run_dir)

        self.close_btn = QPushButton('Close')
        self.close_btn.clicked.connect(self.close)

        bl.addWidget(self.stop_btn)
        bl.addSpacing(8)
        bl.addWidget(self.open_dir_btn)
        bl.addStretch()
        bl.addWidget(self.close_btn)
        v.addWidget(btn_w)

        # ── Timers ────────────────────────────────────────────────────────────
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick)
        self._elapsed_timer.start(1000)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse)
        self._pulse_state = True
        self._pulse_timer.start(600)

    @staticmethod
    def _hairline() -> QWidget:
        w = QWidget(); w.setFixedHeight(1); w.setObjectName('hairlineSep')
        return w

    def _apply_theme(self):
        self.console.setPalette(self._make_console_palette())
        # The app-level QSS sets `background: bg` on every QWidget/QLabel globally.
        # Using `QLabel { background: transparent }` in the dialog's OWN stylesheet
        # (no ancestor selector) is the most reliable way to override that rule —
        # a widget's direct stylesheet always beats the application stylesheet.
        # We use a single bg2 for both header and status to get one uniform band.
        self.setStyleSheet(
            f'QLabel {{ background: transparent; }}'
            f'QWidget#runPopupHeader {{ background:{T("bg2")}; }}'
            f'QWidget#runPopupStatus  {{ background:{T("bg2")}; }}'
            f'QPlainTextEdit {{ border:1px solid {T("border")}; }}'
        )

    def _make_console_palette(self):
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Base, QColor(T('bg')))
        pal.setColor(QPalette.ColorRole.Text, QColor(T('fg')))
        return pal

    # ── Run lifecycle ─────────────────────────────────────────────────────────

    def _start_run(self):
        self.console.appendPlainText(f'$ {self.cmd}\n')

        self._run_record = create_run_record(self.model_path, self.cmd, self.tool)
        cwd = self.cwd
        records = load_run_records(cwd)
        records.insert(0, self._run_record)
        save_run_records(cwd, records[:500])

        runs = load_runs()
        self._run_history_id = f"{self.stem}_{int(time.time())}"
        runs.insert(0, {
            'id': self._run_history_id,
            'run_name': self.stem,
            'model': self.model_path,
            'tool': self.tool,
            'command': self.cmd,
            'working_dir': cwd,
            'status': 'running',
            'started': self._start_ts.isoformat(),
            'finished': None,
        })
        save_runs(runs[:200])

        self._worker = RunWorker(self.cmd, self.cwd)
        self._worker.line_out.connect(self._on_line)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_line(self, line: str):
        self.console.appendPlainText(line)
        self._parse_progress(line)

    def _parse_progress(self, line: str):
        m = _RE_ITER.search(line)
        if m:
            ofv_str = f'{float(m.group(2)):.2f}'
            self._last_ofv = ofv_str
            self._progress_lbl.setText(f'iter {int(m.group(1))}  ·  OFV {ofv_str}')
            return
        m = _RE_PSN.search(line)
        if m:
            self._progress_lbl.setText(f'{self.tool} {m.group(1)}/{m.group(2)}')

    def _on_done(self, rc: int):
        self._finished = True
        self._elapsed_timer.stop()
        self._pulse_timer.stop()

        self.stop_btn.setVisible(False)

        if rc == 0:
            text = self.console.toPlainText()
            status_str = self._extract_termination(text)
            # Absorb final OFV into the status label; clear the progress label
            ofv_part = f'  ·  OFV {self._last_ofv}' if self._last_ofv else ''
            self._status_lbl.setText(f'✓  {status_str}{ofv_part}')
            self._status_lbl.setStyleSheet(f'color:{C.green}; font-weight:600;')
            self.setWindowTitle(f'{self.stem} — {status_str}')
        else:
            self._status_lbl.setText(f'✗  Failed (code {rc})')
            self._status_lbl.setStyleSheet(f'color:{C.red}; font-weight:600;')
            self.setWindowTitle(f'{self.stem} — Failed')

        self._progress_lbl.setText('')
        self.console.appendPlainText(f'\n[Process {"finished" if rc == 0 else f"failed (code {rc})"}]')

        if self._run_record:
            self._run_record = finalize_run_record(self._run_record, self.model_path, rc)
            records = load_run_records(self.cwd)
            for i, r in enumerate(records):
                if r.get('run_id') == self._run_record.get('run_id'):
                    records[i] = self._run_record; break
            save_run_records(self.cwd, records)

        runs = load_runs()
        for r in runs:
            if r.get('id') == self._run_history_id:
                r['status']   = 'ok' if rc == 0 else f'failed ({rc})'
                r['finished'] = datetime.now().isoformat()
                r['exit_code'] = rc
                break
        save_runs(runs)

        self.run_completed.emit(self.stem, self.cwd, rc)

    @staticmethod
    def _extract_termination(text: str) -> str:
        for phrase in ('MINIMIZATION SUCCESSFUL', 'MINIMIZATION TERMINATED',
                       'OPTIMIZATION NOT COMPLETED', 'STATISTICAL PORTION WAS COMPLETED',
                       'CONVERGENCE NOT ACHIEVED'):
            if phrase in text:
                return phrase.title()
        return 'Completed'

    # ── Stop ─────────────────────────────────────────────────────────────────

    def _show_stop_menu(self):
        menu = QMenu(self)
        menu.addAction('Gentle stop  (SIGTERM — PsN finishes writing output)', self._gentle_stop)
        menu.addSeparator()
        menu.addAction('Force kill   (SIGKILL — immediate, no output written)', self._force_kill)
        menu.exec(self.stop_btn.mapToGlobal(self.stop_btn.rect().bottomLeft()))

    def _gentle_stop(self):
        if self._worker:
            self._worker.stop()
            self._status_lbl.setText('⏸  Stopping…')
            self._status_lbl.setStyleSheet(f'color:{C.orange};')

    def _force_kill(self):
        if self._worker:
            self._worker.stop_hard()
            self._status_lbl.setText('⏸  Killing…')
            self._status_lbl.setStyleSheet(f'color:{C.red};')

    # ── Timers ────────────────────────────────────────────────────────────────

    def _tick(self):
        self._elapsed += 1
        m, s = divmod(self._elapsed, 60)
        h, m = divmod(m, 60)
        self._elapsed_lbl.setText(f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}')

    def _pulse(self):
        self._pulse_state = not self._pulse_state
        col = T('accent') if self._pulse_state else T('fg2')
        self._status_lbl.setStyleSheet(f'color:{col};')

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _open_run_dir(self):
        import subprocess, sys
        run_dir = Path(self.cwd) / self.stem
        target = str(run_dir) if run_dir.is_dir() else self.cwd
        if sys.platform == 'darwin':
            subprocess.Popen(['open', target])
        elif sys.platform == 'win32':
            subprocess.Popen(['explorer', target])
        else:
            subprocess.Popen(['xdg-open', target])

    def closeEvent(self, event: QCloseEvent):
        if not self._finished and self._worker and self._worker.isRunning():
            from PyQt6.QtWidgets import QMessageBox
            r = QMessageBox.question(
                self, 'Run still active',
                f'{self.stem} is still running.\nClose window anyway? '
                f'(the run will continue in the background)',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r == QMessageBox.StandardButton.No:
                event.ignore(); return
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
# WatchLogPopup — tail a detached run's log file
# ══════════════════════════════════════════════════════════════════════════════

class WatchLogPopup(QDialog):
    """Floating window that tails the log file of a detached (SSH-safe) run."""

    def __init__(self, descriptor: dict, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self._descriptor    = descriptor
        self._log_path      = Path(descriptor['log_file'])
        self._pid           = descriptor['pid']
        self._stem          = descriptor['stem']
        self._tool          = descriptor['tool']
        self._started_epoch = descriptor.get('started_epoch', int(time.time()))
        self._log_pos       = 0    # byte offset into log file
        self._finished      = False

        self.setWindowTitle(f'{self._stem} — detached run (watching log)')
        self.setObjectName('RunPopupDlg')
        self.resize(720, 500)
        self.setMinimumSize(500, 300)

        self._build_ui()
        self._apply_theme()
        self._start_tail()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setSpacing(0); v.setContentsMargins(0, 0, 0, 0)

        # Header
        hdr = QWidget(); hdr.setObjectName('runPopupHeader'); hdr.setFixedHeight(44)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12, 0, 12, 0); hl.setSpacing(10)
        title_lbl = QLabel(self._stem)
        title_lbl.setStyleSheet('font-size:15px; font-weight:700;')
        tool_lbl  = QLabel(self._tool.upper()); tool_lbl.setObjectName('muted')
        det_lbl   = QLabel('DETACHED');         det_lbl.setObjectName('muted')
        started_lbl = QLabel(f'Started {datetime.fromtimestamp(self._started_epoch).strftime("%H:%M:%S")}')
        started_lbl.setObjectName('muted')
        hl.addWidget(title_lbl); hl.addWidget(tool_lbl); hl.addWidget(det_lbl)
        hl.addStretch(); hl.addWidget(started_lbl)
        v.addWidget(hdr); v.addWidget(self._hairline())

        # Status bar
        sb = QWidget(); sb.setObjectName('runPopupStatus'); sb.setFixedHeight(28)
        sl = QHBoxLayout(sb); sl.setContentsMargins(12, 0, 12, 0); sl.setSpacing(12)
        self._status_lbl  = QLabel('◌  Running (detached)')
        self._elapsed_lbl = QLabel('0:00'); self._elapsed_lbl.setObjectName('muted')
        sl.addWidget(self._status_lbl); sl.addStretch(); sl.addWidget(self._elapsed_lbl)
        v.addWidget(sb); v.addWidget(self._hairline())

        # Console
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(10000)
        self.console.setFont(QFont('Menlo' if IS_MAC else 'Consolas', 11))
        v.addWidget(self.console, 1)

        # Note about log file
        note = QLabel(f'Tailing log: {self._log_path.name}  ·  Closing this window does not affect the run.')
        note.setObjectName('muted')
        note.setContentsMargins(12, 4, 12, 0)
        v.addWidget(note)

        # Button row
        v.addWidget(self._hairline())
        btn_w = QWidget(); bl = QHBoxLayout(btn_w)
        bl.setContentsMargins(12, 8, 12, 8); bl.setSpacing(6)

        self._kill_btn = QPushButton('Stop detached run')
        self._kill_btn.setObjectName('danger')
        self._kill_btn.setToolTip('Send SIGTERM to the PsN process tree')
        self._kill_btn.clicked.connect(self._kill_run)

        open_dir_btn = QPushButton('Open run dir')
        open_dir_btn.clicked.connect(self._open_run_dir)

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)

        bl.addWidget(self._kill_btn); bl.addSpacing(8)
        bl.addWidget(open_dir_btn); bl.addStretch(); bl.addWidget(close_btn)
        v.addWidget(btn_w)

        # Timers
        self._elapsed_timer = QTimer(self); self._elapsed_timer.timeout.connect(self._tick)
        self._elapsed_timer.start(1000)
        self._tail_timer = QTimer(self); self._tail_timer.timeout.connect(self._tail_log)
        self._tail_timer.start(1500)
        self._alive_timer = QTimer(self); self._alive_timer.timeout.connect(self._check_alive)
        self._alive_timer.start(10_000)

    @staticmethod
    def _hairline() -> QWidget:
        w = QWidget(); w.setFixedHeight(1); w.setObjectName('hairlineSep')
        return w

    def _apply_theme(self):
        self.console.setPalette(self._make_console_palette())
        self.setStyleSheet(
            f'QLabel {{ background: transparent; }}'
            f'QWidget#runPopupHeader {{ background:{T("bg2")}; }}'
            f'QWidget#runPopupStatus  {{ background:{T("bg2")}; }}'
            f'QPlainTextEdit {{ border:1px solid {T("border")}; }}'
        )

    def _make_console_palette(self):
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Base, QColor(T('bg')))
        pal.setColor(QPalette.ColorRole.Text, QColor(T('fg')))
        return pal

    # ── Tail ─────────────────────────────────────────────────────────────────

    def _start_tail(self):
        """Read whatever is already in the log file on open."""
        self._tail_log()

    def _tail_log(self):
        """Append any new content from the log file to the console."""
        if not self._log_path.exists():
            return
        try:
            with open(self._log_path, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(self._log_pos)
                new_text = f.read()
                self._log_pos = f.tell()
            if new_text:
                self.console.appendPlainText(new_text.rstrip('\n'))
        except Exception:
            pass

    # ── Liveness check ───────────────────────────────────────────────────────

    def _check_alive(self):
        if self._finished:
            return
        if not _dr.is_alive(self._pid, self._started_epoch):
            self._on_process_ended()

    def _on_process_ended(self):
        self._finished = True
        self._tail_timer.stop()
        self._alive_timer.stop()
        self._kill_btn.setVisible(False)
        # Read remaining log content
        self._tail_log()
        # Determine status from log / .lst
        ec = _dr._infer_exit_code(self._log_path, self._descriptor.get('model_path', ''))
        if ec == 0:
            self._status_lbl.setText('✓  Completed (detached)')
            self._status_lbl.setStyleSheet(f'color:{C.green}; font-weight:600;')
            self.setWindowTitle(f'{self._stem} — Completed')
        else:
            self._status_lbl.setText('✗  Failed (detached)')
            self._status_lbl.setStyleSheet(f'color:{C.red}; font-weight:600;')
            self.setWindowTitle(f'{self._stem} — Failed')
        self.console.appendPlainText('\n[Process ended]')

    # ── Stop ─────────────────────────────────────────────────────────────────

    def _kill_run(self):
        from PyQt6.QtWidgets import QMessageBox
        r = QMessageBox.question(
            self, 'Stop detached run',
            f'Send SIGTERM to the {self._tool} process for {self._stem}?\n'
            f'PsN will attempt to finish writing output files.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            _dr.kill_detached(self._pid)
            self._status_lbl.setText('⏸  Stopping…')
            self._status_lbl.setStyleSheet(f'color:{C.orange};')

    # ── Timers ────────────────────────────────────────────────────────────────

    def _tick(self):
        elapsed = int(time.time()) - self._started_epoch
        m, s = divmod(elapsed, 60); h, m = divmod(m, 60)
        self._elapsed_lbl.setText(f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}')

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _open_run_dir(self):
        import subprocess, sys
        cwd = self._descriptor.get('cwd', '')
        run_dir = Path(cwd) / self._stem
        target = str(run_dir) if run_dir.is_dir() else cwd
        if sys.platform == 'darwin':
            subprocess.Popen(['open', target])
        elif sys.platform == 'win32':
            subprocess.Popen(['explorer', target])
        else:
            subprocess.Popen(['xdg-open', target])
