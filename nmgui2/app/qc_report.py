"""
Automated model QC report.

run_qc_checks(model) -> list[QCResult]
generate_qc_html(model) -> str   (self-contained HTML)
open_in_browser(html)            (writes temp file and opens system browser)
"""
from dataclasses import dataclass
from pathlib import Path
from .constants import APP_VERSION
from .format import fmt_num

PASS = 'pass'
WARN = 'warn'
FAIL = 'fail'
INFO = 'info'


@dataclass
class QCResult:
    category: str
    name: str
    status: str      # PASS | WARN | FAIL | INFO
    value: str       # human-readable measured value
    detail: str = ''


def run_qc_checks(model: dict) -> list:
    checks = []

    # ── 1. Termination ────────────────────────────────────────────────────────
    msg = model.get('minimization_message', '') or ''
    if 'SUCCESSFUL' in msg or 'COMPLETED' in msg:
        checks.append(QCResult('Termination', 'Minimization status',
                               PASS, msg[:60]))
    else:
        val = msg[:60] if msg else 'No status'
        checks.append(QCResult('Termination', 'Minimization status',
                               FAIL, val, 'Minimization did not terminate successfully'))

    # ── 2. Covariance step ────────────────────────────────────────────────────
    cov = model.get('covariance_step')
    if cov is True:
        checks.append(QCResult('Termination', 'Covariance step', PASS, 'Successful'))
    elif cov is False:
        checks.append(QCResult('Termination', 'Covariance step', FAIL, 'Failed',
                               'SE and %RSE not reliable; condition number unavailable'))
    else:
        checks.append(QCResult('Termination', 'Covariance step', INFO, 'Not run',
                               'Run $COV step to get SEs and condition number'))

    # ── 3. Condition number ───────────────────────────────────────────────────
    cn = model.get('condition_number')
    if cn is None:
        checks.append(QCResult('Precision', 'Condition number', INFO, '—',
                               'Requires successful covariance step with PRINT=E'))
    elif cn > 10000:
        checks.append(QCResult('Precision', 'Condition number', FAIL, f'{cn:.1f}',
                               'Near-collinearity — model may be poorly identified'))
    elif cn > 1000:
        checks.append(QCResult('Precision', 'Condition number', WARN, f'{cn:.1f}',
                               'Moderate collinearity — check parameter correlations'))
    else:
        checks.append(QCResult('Precision', 'Condition number', PASS, f'{cn:.1f}'))

    # ── 4. %RSE per estimated parameter ──────────────────────────────────────
    rse_results = _check_rse(model)
    checks.extend(rse_results)

    # ── 5. Parameter correlation ──────────────────────────────────────────────
    checks.extend(_check_correlation(model))

    # ── 6. ETA shrinkage ──────────────────────────────────────────────────────
    for i, v in enumerate(model.get('eta_shrinkage', [])):
        if v > 50:
            st, det = FAIL, 'Very high shrinkage — ETA estimates unreliable'
        elif v > 30:
            st, det = WARN, 'High shrinkage — parameter poorly informed by data'
        else:
            st, det = PASS, ''
        checks.append(QCResult('Shrinkage', f'ETA({i+1}) shrinkage', st, f'{v:.1f}%', det))

    for i, v in enumerate(model.get('eps_shrinkage', [])):
        if v > 50:
            st, det = FAIL, 'Very high epsilon shrinkage'
        elif v > 30:
            st, det = WARN, 'High epsilon shrinkage'
        else:
            st, det = PASS, ''
        checks.append(QCResult('Shrinkage', f'EPS({i+1}) shrinkage', st, f'{v:.1f}%', det))

    # ── 7. ETABAR significance ────────────────────────────────────────────────
    etapval = model.get('etabar_pval', [])
    for i, pv in enumerate(etapval):
        if pv is None:
            continue
        if pv < 0.05:
            checks.append(QCResult('ETABAR', f'ETA({i+1}) p-value', WARN,
                                   f'{pv:.4f}',
                                   'ETABAR significantly different from 0 (p < 0.05)'))
        else:
            checks.append(QCResult('ETABAR', f'ETA({i+1}) p-value', PASS, f'{pv:.4f}'))

    if not etapval:
        checks.append(QCResult('ETABAR', 'ETABAR test', INFO, '—', 'Not available'))

    # ── 8. Omega near boundary ────────────────────────────────────────────────
    checks.extend(_check_omega_boundary(model))

    return checks


def _check_rse(model: dict) -> list:
    results = []
    blocks = [
        ('THETA', model.get('thetas', []), model.get('theta_ses', []),
         model.get('theta_fixed', [])),
        ('OMEGA', model.get('omegas', []), model.get('omega_ses', []),
         model.get('omega_fixed', [])),
        ('SIGMA', model.get('sigmas', []), model.get('sigma_ses', []),
         model.get('sigma_fixed', [])),
    ]
    for block, ests, ses, fixed in blocks:
        for i, est in enumerate(ests):
            fx = fixed[i] if i < len(fixed) else False
            if fx:
                continue
            se = ses[i] if i < len(ses) else None
            if se is None:
                results.append(QCResult('Precision', f'{block}({i+1}) %RSE', INFO, '—',
                                        'SE not available'))
                continue
            if est is None or abs(est) < 1e-12:
                continue
            pct = abs(se / est) * 100
            label = f'{block}({i+1}) %RSE'
            val = f'{pct:.1f}%'
            if pct >= 50:
                results.append(QCResult('Precision', label, WARN, val,
                                        'Very imprecise estimate'))
            elif pct >= 25:
                results.append(QCResult('Precision', label, WARN, val,
                                        'Moderate imprecision'))
            else:
                results.append(QCResult('Precision', label, PASS, val))
    return results


def _check_correlation(model: dict) -> list:
    cor_mat  = model.get('correlation_matrix', [])
    cor_lbls = model.get('cor_labels', [])
    if not cor_mat or not cor_lbls:
        return [QCResult('Precision', 'Parameter correlations', INFO, '—',
                         'Requires successful covariance step')]
    worst_r = 0.0
    worst_pair = ('', '')
    n = len(cor_lbls)
    for i in range(n):
        row = cor_mat[i] if i < len(cor_mat) else []
        for j in range(n):
            if i == j:
                continue
            v = row[j] if j < len(row) else None
            if v is not None and abs(v) > abs(worst_r):
                worst_r = v
                worst_pair = (cor_lbls[i], cor_lbls[j])
    awr = abs(worst_r)
    val = f'{worst_r:.3f}  ({worst_pair[0]} vs {worst_pair[1]})' if worst_pair[0] else '—'
    if awr >= 0.95:
        return [QCResult('Precision', 'Highest parameter correlation', FAIL, val,
                         'Near-perfect correlation — consider reparameterisation')]
    elif awr >= 0.9:
        return [QCResult('Precision', 'Highest parameter correlation', WARN, val,
                         'High correlation — model may be over-parameterised')]
    else:
        return [QCResult('Precision', 'Highest parameter correlation', PASS, val)]


def _check_omega_boundary(model: dict) -> list:
    results = []
    omegas = model.get('omegas', [])
    fixed  = model.get('omega_fixed', [])
    for i, v in enumerate(omegas):
        fx = fixed[i] if i < len(fixed) else False
        if fx or v is None:
            continue
        if abs(v) < 1e-6:
            results.append(QCResult('Termination', f'OMEGA({i+1}) near zero', WARN,
                                    fmt_num(v),
                                    'May be at boundary — consider fixing to zero'))
    return results


# ── HTML generation ───────────────────────────────────────────────────────────

_STATUS_COLOR = {PASS: '#16a34a', WARN: '#d97706', FAIL: '#dc2626', INFO: '#6b7280'}
_STATUS_BG    = {PASS: '#f0fdf4', WARN: '#fffbeb', FAIL: '#fef2f2', INFO: '#f9fafb'}
_STATUS_LABEL = {PASS: 'PASS', WARN: 'WARN', FAIL: 'FAIL', INFO: 'INFO'}


def generate_qc_html(model: dict) -> str:
    from datetime import datetime as _dt
    stem  = model.get('stem', 'model')
    now   = _dt.now().strftime('%Y-%m-%d %H:%M')
    checks = run_qc_checks(model)

    n_pass = sum(1 for c in checks if c.status == PASS)
    n_warn = sum(1 for c in checks if c.status == WARN)
    n_fail = sum(1 for c in checks if c.status == FAIL)
    n_info = sum(1 for c in checks if c.status == INFO)

    if n_fail > 0:
        overall_st, overall_col = FAIL, _STATUS_COLOR[FAIL]
        overall_lbl = 'FAIL'
    elif n_warn > 0:
        overall_st, overall_col = WARN, _STATUS_COLOR[WARN]
        overall_lbl = 'WARN'
    else:
        overall_st, overall_col = PASS, _STATUS_COLOR[PASS]
        overall_lbl = 'PASS'

    css = """
*{box-sizing:border-box;}
body{font-family:-apple-system,"Segoe UI",Arial,sans-serif;font-size:13px;
     color:#1a1a2e;background:#f4f4f8;margin:0;padding:24px 32px;}
h1{font-size:22px;font-weight:800;margin:0 0 2px;letter-spacing:-.5px;}
h2{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
   color:#4c8aff;margin:28px 0 10px;padding-left:12px;
   border-left:3px solid #4c8aff;}
.header{background:#fff;border:1px solid #e0e0ea;border-radius:10px;
        padding:20px 24px;margin-bottom:20px;
        display:flex;align-items:center;gap:20px;
        box-shadow:0 1px 4px rgba(0,0,0,.06);}
.logo{background:#4c8aff;color:#fff;font-weight:900;font-size:17px;
      width:42px;height:42px;border-radius:10px;
      display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.meta{color:#7a7d9a;font-size:12px;margin-top:3px;}
.scorecard{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap;}
.score-box{background:#fff;border:1px solid #e0e0ea;border-radius:10px;
           padding:14px 20px;flex:1;min-width:120px;text-align:center;
           box-shadow:0 1px 4px rgba(0,0,0,.04);}
.score-num{font-size:32px;font-weight:900;line-height:1;}
.score-lbl{font-size:11px;color:#9090a0;margin-top:4px;text-transform:uppercase;letter-spacing:.5px;}
.verdict{background:#fff;border:2px solid;border-radius:10px;padding:14px 20px;
         flex:1;min-width:160px;display:flex;align-items:center;gap:12px;
         box-shadow:0 1px 4px rgba(0,0,0,.06);}
.verdict-badge{font-size:18px;font-weight:900;letter-spacing:1px;}
.verdict-sub{font-size:12px;color:#7a7d9a;margin-top:2px;}
.card{background:#fff;border:1px solid #e0e0ea;border-radius:10px;
      padding:18px 22px;margin-bottom:16px;
      box-shadow:0 1px 4px rgba(0,0,0,.04);}
.card-scroll{overflow-x:auto;}
table{border-collapse:collapse;font-size:12px;width:100%;}
thead th{background:#f0f0f8;font-weight:700;text-align:left;padding:7px 12px;
         border-bottom:2px solid #dde;color:#5a5a70;text-transform:uppercase;
         font-size:10.5px;letter-spacing:.4px;white-space:nowrap;}
td{padding:7px 12px;border-bottom:1px solid #eeeef4;vertical-align:top;}
tr:last-child td{border-bottom:none;}
.pill{display:inline-block;padding:2px 9px;border-radius:20px;
      font-size:11px;font-weight:700;letter-spacing:.5px;}
.cat-header td{background:#f8f8fc;font-weight:700;font-size:10.5px;
               color:#5a5a7a;text-transform:uppercase;letter-spacing:.5px;
               padding:5px 12px;border-top:1px solid #e0e0ea;}
.detail{font-size:11px;color:#7a7d9a;margin-top:2px;}
.num{font-family:ui-monospace,Menlo,Consolas,monospace;white-space:nowrap;}
.block-sep td{border-top:2px solid #4c8aff;padding-top:8px;
              font-weight:700;color:#4c8aff;font-size:10px;
              text-transform:uppercase;letter-spacing:.5px;}
.good{color:#16a34a;font-weight:700;}
.bad{color:#dc2626;font-weight:700;}
.warn-col{color:#d97706;font-weight:700;}
.fix{color:#b0b0c0;font-style:italic;font-size:11px;}
@media print{body{background:#fff;padding:16px;}
  .header,.verdict,.card{box-shadow:none;border:1px solid #ccc;}
  .card{page-break-inside:avoid;} h2{page-break-after:avoid;}}
"""

    # Scorecard
    scorecard = f'''
<div class="scorecard">
  <div class="verdict" style="border-color:{overall_col}">
    <div>
      <div class="verdict-badge" style="color:{overall_col}">Overall: {overall_lbl}</div>
      <div class="verdict-sub">{n_pass} pass · {n_warn} warn · {n_fail} fail · {n_info} info</div>
    </div>
  </div>
  <div class="score-box"><div class="score-num" style="color:{_STATUS_COLOR[PASS]}">{n_pass}</div>
    <div class="score-lbl">Pass</div></div>
  <div class="score-box"><div class="score-num" style="color:{_STATUS_COLOR[WARN]}">{n_warn}</div>
    <div class="score-lbl">Warn</div></div>
  <div class="score-box"><div class="score-num" style="color:{_STATUS_COLOR[FAIL]}">{n_fail}</div>
    <div class="score-lbl">Fail</div></div>
</div>
'''

    # QC check table grouped by category
    rows = ''
    current_cat = None
    for c in checks:
        if c.category != current_cat:
            current_cat = c.category
            rows += f'<tr class="cat-header"><td colspan="3">{c.category}</td></tr>'
        col  = _STATUS_COLOR[c.status]
        bg   = _STATUS_BG[c.status]
        lbl  = _STATUS_LABEL[c.status]
        det  = f'<div class="detail">{c.detail}</div>' if c.detail else ''
        rows += (f'<tr style="background:{bg}">'
                 f'<td><div>{c.name}</div>{det}</td>'
                 f'<td class="num">{c.value}</td>'
                 f'<td><span class="pill" style="background:{col}22;color:{col}">{lbl}</span></td>'
                 f'</tr>')

    checks_html = f'''<div class="card-scroll">
<table><thead><tr>
<th>Check</th><th>Value</th><th>Status</th>
</tr></thead><tbody>{rows}</tbody></table></div>'''

    # ── Parameter table ───────────────────────────────────────────────────────
    blocks_p = [
        ('THETA', model.get('thetas',[]),  model.get('theta_ses',[]),
         model.get('theta_names',[]), model.get('theta_units',[]), model.get('theta_fixed',[])),
        ('OMEGA', model.get('omegas',[]),  model.get('omega_ses',[]),
         model.get('omega_names',[]), model.get('omega_units',[]), model.get('omega_fixed',[])),
        ('SIGMA', model.get('sigmas',[]),  model.get('sigma_ses',[]),
         model.get('sigma_names',[]), model.get('sigma_units',[]), model.get('sigma_fixed',[])),
    ]
    param_rows = ''
    cur_block = None
    for block, ests, ses, names, units, fixed in blocks_p:
        if not ests:
            continue
        if block != cur_block:
            cur_block = block
            param_rows += f'<tr class="block-sep"><td colspan="6">{block}</td></tr>'
        for i, est in enumerate(ests):
            se  = ses[i]   if i < len(ses)   else None
            nm  = names[i] if i < len(names) else ''
            un  = units[i] if i < len(units) else ''
            fx  = fixed[i] if i < len(fixed) else False
            fix_badge = ' <span class="fix">FIX</span>' if fx else ''
            if se is not None and est and abs(est) > 1e-12 and not fx:
                pct = abs(se/est)*100
                rse_str = f'{pct:.1f}%'
                rse_cls = 'good' if pct < 25 else ('warn-col' if pct < 50 else 'bad')
            else:
                rse_str = '—' if (fx or se == 0) else ('...' if se is None else '—')
                rse_cls = ''
            param_rows += (
                f'<tr><td>{block}({i+1}){fix_badge}</td><td>{nm}</td>'
                f'<td class="num">{fmt_num(est)}</td>'
                f'<td class="num">{fmt_num(se) if se is not None else "..."}</td>'
                f'<td class="num {rse_cls}">{rse_str}</td>'
                f'<td>{un}</td></tr>')

    param_html = f'''<div class="card-scroll">
<table><thead><tr>
<th>Parameter</th><th>Name</th><th>Estimate</th><th>SE</th><th>RSE%</th><th>Units</th>
</tr></thead><tbody>{param_rows}</tbody></table></div>'''

    # ── Correlation matrix ────────────────────────────────────────────────────
    cor_mat  = model.get('correlation_matrix', [])
    cor_lbls = model.get('cor_labels', [])
    if cor_mat and cor_lbls:
        hdr = ''.join(f'<th>{l}</th>' for l in cor_lbls)
        cor_rows = ''
        for i, row in enumerate(cor_mat):
            lbl  = cor_lbls[i] if i < len(cor_lbls) else str(i)
            cells = ''
            for j, v in enumerate(row):
                if v is None:
                    cells += '<td></td>'
                else:
                    cls = ''
                    if i != j:
                        a = abs(v)
                        cls = 'bad' if a > 0.9 else ('warn-col' if a > 0.7 else '')
                    cells += f'<td class="num {cls}">{v:.3f}</td>'
            cor_rows += f'<tr><th style="background:#f0f0f8;font-weight:700;padding:6px 10px;white-space:nowrap;">{lbl}</th>{cells}</tr>'
        cor_html = (f'<div class="card-scroll"><table><thead>'
                    f'<tr><th></th>{hdr}</tr></thead>'
                    f'<tbody>{cor_rows}</tbody></table></div>')
    else:
        cor_html = '<p style="color:#9090a0;margin:0;">Not available (requires successful covariance step)</p>'

    # ── Shrinkage ─────────────────────────────────────────────────────────────
    eta_shr = model.get('eta_shrinkage', [])
    eps_shr = model.get('eps_shrinkage', [])
    if eta_shr or eps_shr:
        shr_rows = ''
        for i, v in enumerate(eta_shr):
            cls = 'bad' if v > 50 else ('warn-col' if v > 30 else 'good')
            shr_rows += f'<tr><td>ETA({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
        for i, v in enumerate(eps_shr):
            cls = 'bad' if v > 50 else ('warn-col' if v > 30 else 'good')
            shr_rows += f'<tr><td>EPS({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
        shr_html = (f'<table><thead><tr><th>Parameter</th><th>Shrinkage (SD%)</th>'
                    f'</tr></thead><tbody>{shr_rows}</tbody></table>')
    else:
        shr_html = '<p style="color:#9090a0;margin:0;">Not available</p>'

    # ── Summary grid ──────────────────────────────────────────────────────────
    ofv   = model.get('ofv')
    aic   = model.get('aic')
    cov   = model.get('covariance_step')
    cn    = model.get('condition_number')
    meth  = model.get('estimation_method', '') or ''
    rt    = model.get('runtime')
    nind  = model.get('n_individuals')
    nobs  = model.get('n_observations')
    npar  = model.get('n_estimated_params')
    status_msg = model.get('minimization_message', '') or ''

    status_cls = ('good' if ('SUCCESSFUL' in status_msg or 'COMPLETED' in status_msg) else 'bad')
    cov_str = ('OK' if cov else 'FAILED') if cov is not None else '—'
    cov_cls = 'good' if cov else ('bad' if cov is False else '')
    cn_str  = f'{cn:.1f}' if cn else '—'
    cn_cls  = 'warn-col' if cn and cn > 1000 else ('good' if cn else '')
    rt_str  = f'{rt:.1f} s' if rt else '—'

    summary_items = [
        ('OFV',               f'{ofv:.4f}' if ofv is not None else '—', ''),
        ('AIC',               f'{aic:.2f}' if aic is not None else '—', ''),
        ('Status',            status_msg[:30] or '—', status_cls),
        ('Covariance',        cov_str, cov_cls),
        ('Condition number',  cn_str, cn_cls),
        ('Method',            meth or '—', ''),
        ('Individuals',       str(nind) if nind else '—', ''),
        ('Observations',      str(nobs) if nobs else '—', ''),
        ('Est. parameters',   str(npar) if npar else '—', ''),
        ('Runtime',           rt_str, ''),
    ]
    summary_html = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;">'
        + ''.join(
            f'<div style="background:#f8f8fc;border:1px solid #e8e8f0;border-radius:8px;padding:12px 14px;">'
            f'<div style="font-size:10px;color:#9090a0;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;">{lbl}</div>'
            f'<div style="font-size:17px;font-weight:800;letter-spacing:-.3px;" class="{cls}">{val}</div></div>'
            for lbl, val, cls in summary_items)
        + '</div>')

    html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<title>QC Report — {stem}</title>
<style>{css}</style>
</head><body>
<div class="header">
  <div class="logo">NM</div>
  <div>
    <h1>QC Report: {stem}</h1>
    <div class="meta">{model.get('problem', '')}</div>
    <div class="meta">Generated by NMGUI v{APP_VERSION} · {now}</div>
  </div>
</div>
{scorecard}
<h2>QC Checklist</h2>
<div class="card">{checks_html}</div>
<h2>Summary</h2>
<div class="card">{summary_html}</div>
<h2>Parameter Estimates</h2>
<div class="card">{param_html}</div>
<h2>Correlation Matrix</h2>
<div class="card">{cor_html}</div>
<h2>Shrinkage</h2>
<div class="card">{shr_html}</div>
</body></html>"""
    return html


def open_report_in_browser(html: str, stem: str = 'model', prefix: str = 'nmgui_report') -> None:
    import tempfile, webbrowser, os
    suffix = f'_{stem}.html' if stem else '.html'
    with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', suffix=suffix,
            prefix=prefix + '_', delete=False) as f:
        f.write(html)
        path = f.name
    webbrowser.open(f'file://{path}')
