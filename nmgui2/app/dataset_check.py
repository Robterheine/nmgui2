"""
Dataset integrity checks for NONMEM input datasets.

check_dataset(mod_path, data_file_str) -> DatasetReport
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

FAIL = 'fail'
WARN = 'warn'
INFO = 'info'
PASS = 'pass'

MAX_ROWS  = 50_000
MAX_BYTES = 50 * 1024 * 1024   # 50 MB — skip detailed checks above this


@dataclass
class DataIssue:
    level:   str   # FAIL | WARN | INFO | PASS
    message: str
    count:   int = 0   # affected rows / items, 0 = not applicable


@dataclass
class DatasetReport:
    found:     bool
    readable:  bool
    path:      str  = ''
    n_rows:    int  = 0
    n_ids:     int  = 0
    n_obs:     int  = 0
    n_doses:   int  = 0
    n_blq:     int  = 0
    columns:   list = field(default_factory=list)
    issues:    list = field(default_factory=list)
    truncated: bool = False

    @property
    def worst_level(self):
        for level in (FAIL, WARN, INFO):
            if any(i.level == level for i in self.issues):
                return level
        return PASS


def check_dataset(mod_path, data_file_str: str) -> DatasetReport:
    """Run integrity checks on the NONMEM input dataset referenced by a control file."""
    if not data_file_str:
        return DatasetReport(found=False, readable=False)

    # Resolve path relative to the model file
    mod_dir = Path(mod_path).parent
    candidates = [
        mod_dir / data_file_str,
        Path(data_file_str),
    ]
    ds_path = None
    for c in candidates:
        try:
            if c.is_file():
                ds_path = c
                break
        except Exception:
            pass

    if ds_path is None:
        return DatasetReport(
            found=False, readable=False, path=data_file_str,
            issues=[DataIssue(FAIL, f'Dataset file not found: {data_file_str}')])

    try:
        size = ds_path.stat().st_size
    except Exception as e:
        return DatasetReport(
            found=True, readable=False, path=str(ds_path),
            issues=[DataIssue(FAIL, f'Cannot stat dataset: {e}')])

    report = DatasetReport(found=True, readable=True, path=str(ds_path))

    if size > MAX_BYTES:
        report.issues.append(DataIssue(INFO,
            f'Dataset is large ({size/1024/1024:.0f} MB) — detailed checks skipped'))
        return report

    # Read raw lines
    try:
        text = ds_path.read_text('utf-8', errors='replace')
    except Exception as e:
        report.readable = False
        report.issues.append(DataIssue(FAIL, f'Cannot read dataset: {e}'))
        return report

    lines = [l for l in text.splitlines() if l.strip() and not l.strip().startswith(';')]
    if not lines:
        report.issues.append(DataIssue(FAIL, 'Dataset file is empty'))
        return report

    # Detect delimiter and parse header
    header_line = lines[0]
    if '\t' in header_line:
        delim = '\t'
    elif ',' in header_line and ';' not in header_line:
        delim = ','
    elif ';' in header_line:
        delim = ';'
    else:
        delim = None   # whitespace

    def split(line):
        if delim:
            return [v.strip() for v in line.split(delim)]
        return line.split()

    header = split(header_line)
    header = [h.upper() for h in header if h.strip()]
    if not header:
        report.issues.append(DataIssue(FAIL, 'Could not parse dataset header'))
        return report
    report.columns = header

    n_cols = len(header)
    col = {name: i for i, name in enumerate(header)}

    def _idx(*names):
        for n in names:
            if n in col:
                return col[n]
        return None

    id_idx   = _idx('ID', 'SUBJ', 'SUBJECT', 'SUB')
    time_idx = _idx('TIME', 'TAD')
    dv_idx   = _idx('DV', 'CONC', 'Y')
    amt_idx  = _idx('AMT', 'DOSE')
    evid_idx = _idx('EVID')
    mdv_idx  = _idx('MDV')

    # Parse data rows
    bad_width  = 0
    rows       = []
    truncated  = False
    data_lines = lines[1:]

    for raw in data_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith(';'):
            continue
        parts = split(stripped)
        if len(parts) != n_cols:
            bad_width += 1
            continue
        rows.append(parts)
        if len(rows) >= MAX_ROWS:
            truncated = True
            break

    report.n_rows    = len(rows)
    report.truncated = truncated

    if bad_width:
        report.issues.append(DataIssue(WARN,
            f'Column count mismatch (expected {n_cols})', bad_width))

    if not rows:
        report.issues.append(DataIssue(FAIL, 'Dataset has no parseable data rows'))
        return report

    # ── Extract columns ───────────────────────────────────────────────────────
    def col_vals(idx):
        if idx is None:
            return None
        out = []
        for r in rows:
            try:
                v = r[idx].replace(',', '.').replace('D', 'E').replace('d', 'e')
                out.append(float(v))
            except Exception:
                out.append(None)
        return out

    ids   = col_vals(id_idx)
    times = col_vals(time_idx)
    dvs   = col_vals(dv_idx)
    amts  = col_vals(amt_idx)
    evids = col_vals(evid_idx)
    mdvs  = col_vals(mdv_idx)

    # ── Subject count ─────────────────────────────────────────────────────────
    if ids is not None:
        report.n_ids = len({v for v in ids if v is not None})

    # ── Observation / dose counts ─────────────────────────────────────────────
    n_obs = n_doses = n_blq = 0
    for i in range(len(rows)):
        evid = evids[i] if evids else None
        mdv  = mdvs[i]  if mdvs  else None
        amt  = amts[i]  if amts  else None
        dv   = dvs[i]   if dvs   else None
        is_obs  = (evid is None or evid == 0) and (mdv is None or mdv == 0)
        is_dose = (evid == 1) or (amt is not None and amt > 0 and evid != 0)
        if is_obs:
            n_obs += 1
        if is_dose:
            n_doses += 1
        if mdv == 1 and (evid is None or evid == 0):
            n_blq += 1
    report.n_obs   = n_obs
    report.n_doses = n_doses
    report.n_blq   = n_blq

    # ── Non-monotonic TIME within ID ──────────────────────────────────────────
    if ids is not None and times is not None:
        prev_time = {}
        nonmono   = 0
        for i, (id_, t) in enumerate(zip(ids, times)):
            if id_ is None or t is None:
                continue
            evid = evids[i] if evids else None
            # EVID 3/4 reset the clock — skip monotonicity check at those rows
            if evid in (3, 4):
                prev_time[id_] = t
                continue
            if id_ in prev_time and t < prev_time[id_] - 1e-9:
                nonmono += 1
            else:
                prev_time[id_] = t
        if nonmono:
            report.issues.append(DataIssue(WARN,
                'Non-monotonic TIME within subject (excluding EVID 3/4 resets)',
                nonmono))

    # ── Duplicate dose records ────────────────────────────────────────────────
    if ids is not None and times is not None and amts is not None:
        dose_keys = {}
        dup_doses = 0
        for i in range(len(rows)):
            evid = evids[i] if evids else None
            amt  = amts[i]
            if amt is None or amt == 0:
                continue
            if evid is not None and evid not in (1, 4):
                continue
            key = (ids[i], times[i], amt)
            if key in dose_keys:
                dup_doses += 1
            else:
                dose_keys[key] = i
        if dup_doses:
            report.issues.append(DataIssue(WARN,
                'Duplicate dose records (same ID + TIME + AMT)', dup_doses))

    # ── Negative DV in observed records ───────────────────────────────────────
    if dvs is not None:
        neg_dv = 0
        for i, dv in enumerate(dvs):
            if dv is None:
                continue
            evid = evids[i] if evids else None
            mdv  = mdvs[i]  if mdvs  else None
            if (evid is None or evid == 0) and (mdv is None or mdv == 0) and dv < 0:
                neg_dv += 1
        if neg_dv:
            report.issues.append(DataIssue(INFO,
                'Negative DV in observed records (check if expected)', neg_dv))

    # ── Sentinel / flag values in DV ──────────────────────────────────────────
    if dvs is not None:
        sentinel_dv = 0
        for i, dv in enumerate(dvs):
            if dv is None:
                continue
            evid = evids[i] if evids else None
            mdv  = mdvs[i]  if mdvs  else None
            if (evid is None or evid == 0) and (mdv is None or mdv == 0):
                if dv in (-99, -999, -9999, -99999, 9999, 99999):
                    sentinel_dv += 1
        if sentinel_dv:
            report.issues.append(DataIssue(WARN,
                'Possible sentinel/flag values in observed DV (e.g. -99, 9999)',
                sentinel_dv))

    # ── BLQ summary ───────────────────────────────────────────────────────────
    if n_blq > 0 and n_obs + n_blq > 0:
        pct = n_blq / (n_obs + n_blq) * 100
        level = WARN if pct > 30 else INFO
        report.issues.append(DataIssue(level,
            f'BLQ records (MDV=1, EVID=0): {pct:.0f}% of DV records', n_blq))

    # ── All good ──────────────────────────────────────────────────────────────
    if not report.issues:
        report.issues.append(DataIssue(PASS, 'No issues detected'))

    return report
