import math
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextBrowser, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCharFormat, QColor

from ..app.constants import APP_VERSION
from ..app.theme import T, C, THEMES, _active_theme
from ..app.format import fmt_num, fmt_rse, fmt_ofv

_log = logging.getLogger(__name__)


def render_lst_html(model: dict, raw_text: str, embed: bool = False) -> str:
    """Render a NONMEM .lst file as a structured, readable HTML document."""
    import re as _re

    stem = model.get('stem', 'model')
    t = THEMES[_active_theme]
    is_dark = _active_theme == 'dark'

    # ── Colour palette ────────────────────────────────────────────────────────
    bg       = '#1a1a22' if is_dark else '#f8f8fc'
    bg2      = '#22222e' if is_dark else '#ffffff'
    bg3      = '#2a2a38' if is_dark else '#f0f0f8'
    border   = '#3a3a50' if is_dark else '#dde0f0'
    fg       = '#dde0ee' if is_dark else '#1a1a2e'
    fg2      = '#7a7d9a' if is_dark else '#5a5a70'
    accent   = '#4c8aff'
    green    = '#3ec97a' if is_dark else '#16a34a'
    red      = '#e85555' if is_dark else '#dc2626'
    orange   = '#e89540' if is_dark else '#d97706'
    amber_bg = '#2a1f00' if is_dark else '#fffbeb'
    amber_bd = '#8a6000' if is_dark else '#f59e0b'
    mono     = '"Menlo","Consolas","Courier New",monospace'

    # ── CSS ───────────────────────────────────────────────────────────────────
    css = f"""
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:-apple-system,system-ui,sans-serif;font-size:13px;
          color:{fg};background:{bg};padding:20px 24px 40px;line-height:1.5;}}
    h1{{font-size:20px;font-weight:800;letter-spacing:-.5px;margin-bottom:2px;}}
    h2{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
        color:{accent};margin:28px 0 10px;padding-left:12px;
        border-left:3px solid {accent};}}
    .card{{background:{bg2};border:1px solid {border};border-radius:10px;
           padding:16px 20px;margin-bottom:16px;}}
    .summary-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:12px;}}
    .summary-item{{background:{bg3};border:1px solid {border};border-radius:8px;padding:10px 14px;}}
    .summary-label{{font-size:10px;color:{fg2};text-transform:uppercase;letter-spacing:.5px;}}
    .summary-value{{font-size:16px;font-weight:800;margin-top:3px;}}
    .ok{{color:{green};}} .bad{{color:{red};}} .warn{{color:{orange};}}
    .warn-block{{background:{amber_bg};border:1px solid {amber_bd};border-radius:8px;
                 padding:14px 16px;margin-bottom:12px;}}
    .warn-block h3{{font-size:12px;font-weight:700;color:{orange};margin-bottom:6px;}}
    .warn-block pre{{font-size:11px;font-family:{mono};white-space:pre-wrap;
                     color:{fg};background:transparent;border:none;padding:0;}}
    table{{border-collapse:collapse;width:100%;font-size:12px;}}
    thead th{{background:{bg3};font-weight:700;text-align:left;padding:6px 10px;
              border-bottom:2px solid {border};color:{fg2};text-transform:uppercase;
              font-size:10.5px;letter-spacing:.4px;white-space:nowrap;}}
    td{{padding:5px 10px;border-bottom:1px solid {border};white-space:nowrap;}}
    tr:last-child td{{border-bottom:none;}}
    tr:nth-child(even) td{{background:{bg3};}}
    .num{{text-align:right;font-family:{mono};}}
    .fix{{color:{fg2};font-style:italic;font-size:11px;}}
    .block-sep td{{border-top:2px solid {accent};color:{accent};font-weight:700;
                   font-size:10px;text-transform:uppercase;padding-top:8px;}}
    .good{{color:{green};font-weight:700;}}
    .red{{color:{red};font-weight:700;}}
    .or{{color:{orange};font-weight:700;}}
    .scroll-x{{overflow-x:auto;}}
    details summary{{cursor:pointer;font-size:12px;font-weight:600;
                     color:{fg2};padding:6px 0;list-style:none;}}
    details summary::-webkit-details-marker{{display:none;}}
    details summary::before{{content:'▶ ';font-size:10px;}}
    details[open] summary::before{{content:'▼ ';}}
    pre.raw{{font-family:{mono};font-size:11px;background:{bg3};
             border:1px solid {border};border-radius:6px;padding:12px;
             white-space:pre;overflow-x:auto;color:{fg};line-height:1.4;}}
    .tag{{display:inline-block;font-size:10px;font-weight:700;padding:2px 8px;
          border-radius:10px;margin-left:8px;vertical-align:middle;}}
    .tag-ok{{background:{green}22;color:{green};}}
    .tag-bad{{background:{red}22;color:{red};}}
    .iter-table td,.iter-table th{{padding:4px 10px;}}
    .nav{{position:fixed;right:20px;top:80px;width:140px;font-size:11px;
          background:{bg2};border:1px solid {border};border-radius:8px;
          padding:10px 12px;}}
    .nav a{{display:block;color:{fg2};text-decoration:none;padding:3px 0;}}
    .nav a:hover{{color:{accent};}}
    @media(max-width:900px){{.nav{{display:none;}}}}
    @media print{{.nav{{display:none;}}body{{padding:16px;}}}}
    """

    # ── Helper: parse raw sections ─────────────────────────────────────────
    def between(text, start_pat, end_pat):
        m = _re.search(start_pat, text, _re.IGNORECASE)
        if not m: return ''
        start = m.end()
        m2 = _re.search(end_pat, text[start:], _re.IGNORECASE)
        return text[start:start+m2.start()].strip() if m2 else text[start:start+2000].strip()

    def find_all(text, pat, flags=0):
        return _re.findall(pat, text, flags)

    # ── 1. NM-TRAN warnings ────────────────────────────────────────────────
    nmtran_block = between(raw_text, r'NM-TRAN MESSAGES', r'Note:|License Registered')
    warning_texts = _re.findall(r'\(WARNING\s+\d+\).*?(?=\(WARNING\s+\d+\)|\Z)',
                                nmtran_block, _re.DOTALL)
    warnings_html = ''
    for w in warning_texts:
        w = w.strip()
        if w:
            warnings_html += f'<div class="warn-block"><pre>{w}</pre></div>'

    # ── 2. Summary ─────────────────────────────────────────────────────────
    ofv    = model.get('ofv')
    status = model.get('minimization_message','').strip()
    successful = 'SUCCESSFUL' in status or 'COMPLETED' in status
    status_cls  = 'ok' if successful else 'bad'
    status_tag  = f'<span class="tag {"tag-ok" if successful else "tag-bad"}">' \
                  f'{"✓" if successful else "✗"} {status[:30]}</span>'

    # sig digits
    sigdig_m = _re.search(r'NO\. OF SIG\. DIGITS IN FINAL EST\.\:\s*([\d\.]+)', raw_text)
    sigdig = sigdig_m.group(1) if sigdig_m else '—'

    # n function evals
    nevals_m = _re.search(r'NO\. OF FUNCTION EVALUATIONS USED\:\s*(\d+)', raw_text)
    nevals = nevals_m.group(1) if nevals_m else '—'

    # timing
    timing = {}
    for kind in ('estimation','covariance','postprocess'):
        m = _re.search(fr'Elapsed {kind}\s+time in seconds:\s*([\d\.]+)', raw_text, _re.IGNORECASE)
        if m: timing[kind] = float(m.group(1))
    total_time = sum(timing.values()) if timing else None

    cov  = model.get('covariance_step')
    cn   = model.get('condition_number')
    nind = model.get('n_individuals')
    nobs = model.get('n_observations')
    meth = model.get('estimation_method','')
    aic  = model.get('aic')

    summary_items = [
        ('OFV',             f'{ofv:.4f}' if ofv is not None else '—', ''),
        ('AIC',             f'{aic:.2f}' if aic is not None else '—', ''),
        ('Method',          meth or '—', ''),
        ('Covariance',      ('✓ Successful' if cov else '✗ Failed') if cov is not None else '—',
                            'ok' if cov else 'bad' if cov is False else ''),
        ('Sig. digits',     sigdig, ''),
        ('Func. evals',     nevals, ''),
        ('Individuals',     str(nind) if nind else '—', ''),
        ('Observations',    str(nobs) if nobs else '—', ''),
        ('CN',              f'{cn:.1f}' if cn else '—',
                            'or' if cn and cn > 1000 else ''),
        ('Runtime',         f'{total_time:.1f} s' if total_time else '—', ''),
    ]
    summary_cards = ''.join(
        f'<div class="summary-item">'
        f'<div class="summary-label">{lbl}</div>'
        f'<div class="summary-value {cls}">{val}</div></div>'
        for lbl,val,cls in summary_items)

    # ── 3. Control stream (everything before NM-TRAN MESSAGES) ────────────
    ctrl_end = raw_text.find('NM-TRAN MESSAGES')
    ctrl_stream = raw_text[:ctrl_end].strip() if ctrl_end > 0 else ''
    # Syntax-highlight $RECORDS in the control stream for HTML
    def hl_ctrl(s):
        s = s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        s = _re.sub(r'(\$[A-Z]+)', r'<span style="color:#4c8aff;font-weight:700;">\1</span>', s)
        s = _re.sub(r'(;[^\n]*)', r'<span style="color:#6a9955;font-style:italic;">\1</span>', s)
        return s

    # ── 4. Iteration trace ─────────────────────────────────────────────────
    iter_blocks = _re.findall(
        r'ITERATION NO\.\:\s+(\d+)\s+OBJECTIVE VALUE\:\s+([\d\.\-\+E]+)',
        raw_text)
    iter_rows = ''
    prev_ofv = None
    for it, ov in iter_blocks:
        ov_f = float(ov)
        delta = f'{ov_f-prev_ofv:+.3f}' if prev_ofv is not None else '—'
        dcls  = 'ok' if prev_ofv and ov_f < prev_ofv else ''
        iter_rows += (f'<tr><td class="num">{it}</td>'
                      f'<td class="num">{ov_f:.4f}</td>'
                      f'<td class="num {dcls}">{delta}</td></tr>')
        prev_ofv = ov_f
    iter_html = (f'<table class="iter-table"><thead><tr>'
                 f'<th>Iteration</th><th>OFV</th><th>ΔOFV</th></tr></thead>'
                 f'<tbody>{iter_rows}</tbody></table>') if iter_rows else '<p>Not found</p>'

    # ── 5. ETABAR ──────────────────────────────────────────────────────────
    etabar_v = model.get('etabar',[])
    etabar_se = model.get('etabar_se',[])
    etabar_pv = model.get('etabar_pval',[])
    # Fallback: parse from raw
    if not etabar_v:
        eb_m = _re.search(r'ETABAR:\s+([\d\.\-\+E\s]+)\n', raw_text)
        if eb_m:
            etabar_v = [float(x) for x in eb_m.group(1).split()]
        pv_m = _re.search(r'P VAL\.:\s+([\d\.\-\+E\s]+)\n', raw_text)
        if pv_m:
            etabar_pv = [float(x) for x in pv_m.group(1).split()]
    etabar_rows = ''
    for i, eb in enumerate(etabar_v):
        pv = etabar_pv[i] if i < len(etabar_pv) else None
        se_ = etabar_se[i] if i < len(etabar_se) else None
        pv_cls = 'red' if pv is not None and pv < 0.05 else ''
        etabar_rows += (f'<tr><td>ETA({i+1})</td>'
                        f'<td class="num">{eb:.4f}</td>'
                        f'<td class="num">{fmt_num(se_) if se_ else "—"}</td>'
                        f'<td class="num {pv_cls}">{f"{pv:.4f}" if pv else "—"}</td></tr>')
    etabar_html = (f'<table><thead><tr><th>ETA</th><th>ETABAR</th>'
                   f'<th>SE</th><th>P-value</th></tr></thead>'
                   f'<tbody>{etabar_rows}</tbody></table>') if etabar_rows else \
                  '<p style="color:#888;">Not available</p>'

    # ── 6. Shrinkage ───────────────────────────────────────────────────────
    eta_shr = model.get('eta_shrinkage',[])
    eps_shr = model.get('eps_shrinkage',[])
    shr_rows = ''
    for i, v in enumerate(eta_shr):
        cls = 'red' if v > 30 else 'or' if v > 20 else 'ok'
        shr_rows += f'<tr><td>ETA({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
    for i, v in enumerate(eps_shr):
        cls = 'red' if v > 30 else 'or' if v > 20 else 'ok'
        shr_rows += f'<tr><td>EPS({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
    shr_html = (f'<table><thead><tr><th>Parameter</th>'
                f'<th>Shrinkage SD%</th></tr></thead>'
                f'<tbody>{shr_rows}</tbody></table>') if shr_rows else \
               '<p style="color:#888;">Not available</p>'

    # ── Helper: parse NONMEM matrix ──────────────────────────────────────────
    def parse_nonmem_matrix(block):
        """
        Parse a NONMEM matrix block (triangular or full).
        Handles both spaced labels 'TH 1', 'TH 2' and compact 'OM11', 'SG11'.
        Returns (labels, n×n matrix) where matrix[i][j] = float or None.
        """
        lines = block.splitlines()
        label_re = _re.compile(r'(?:TH|OM|SG|ETA|EPS)\s*\d+', _re.IGNORECASE)

        # Header lines contain ONLY parameter tokens and whitespace
        labels = []
        for line in lines:
            stripped = line.strip()
            if not stripped: continue
            # Remove all tokens — if anything non-whitespace remains it's not a header
            cleaned = label_re.sub('', stripped)
            if cleaned.strip(): continue
            for lbl in label_re.findall(stripped):
                compact = lbl.replace(' ', '')
                if compact not in labels:
                    labels.append(compact)

        if not labels: return [], []
        n = len(labels)
        mat = [[None]*n for _ in range(n)]

        row_lbl_re = _re.compile(
            r'^\s+((?:TH|OM|SG|ETA|EPS)\s*\d+)\s*$', _re.IGNORECASE)
        val_re = _re.compile(r'^\+(.*)')

        i = 0
        while i < len(lines):
            lm = row_lbl_re.match(lines[i])
            if lm:
                raw_lbl = lm.group(1).replace(' ', '')
                if raw_lbl in labels:
                    ri = labels.index(raw_lbl)
                    j = i + 1
                    while j < len(lines) and not lines[j].strip(): j += 1
                    if j < len(lines):
                        vm = val_re.match(lines[j])
                        if vm:
                            parts = vm.group(1).split()
                            for ci, p in enumerate(parts):
                                if ci >= n: break
                                if _re.match(r'^\.*$', p):
                                    mat[ri][ci] = None
                                else:
                                    try: mat[ri][ci] = float(p)
                                    except ValueError: mat[ri][ci] = None
                    i = j
            i += 1
        return labels, mat

    def render_matrix_html(labels, mat, is_correlation=False):
        """Render a list-of-lists matrix as a bordered HTML table."""
        if not labels: return ''
        hdr = ''.join(
            f'<th style="padding:5px 10px;white-space:nowrap;background:{bg3};">{l}</th>'
            for l in labels)
        crows = ''
        for i in range(len(labels)):
            cells = ''
            for j in range(len(labels)):
                v = mat[i][j] if i < len(mat) and j < len(mat[i]) else None
                if v is None:
                    cells += f'<td class="num" style="color:{fg2};">·</td>'
                else:
                    cls = ''
                    if is_correlation and i != j:
                        a = abs(v)
                        cls = 'red' if a > 0.95 else ('or' if a > 0.7 else '')
                    cells += f'<td class="num {cls}">{v:.4g}</td>'
            crows += (f'<tr><th style="text-align:left;font-weight:700;'
                      f'padding:5px 10px;white-space:nowrap;background:{bg3};">'
                      f'{labels[i]}</th>{cells}</tr>')
        return (f'<div class="scroll-x"><table style="border-collapse:collapse;">'
                f'<thead><tr><th style="background:{bg3};padding:5px 10px;"></th>{hdr}</tr></thead>'
                f'<tbody>{crows}</tbody></table></div>')

    # ── Find the FINAL PARAMETER ESTIMATE section block ───────────────────────
    # This comes after the rows of stars with "FINAL PARAMETER ESTIMATE"
    final_m = _re.search(
        r'FINAL PARAMETER ESTIMATE.*?\n[\*\s]+\n(.*?)(?=\n[\*\s]{60,}\n|\Z)',
        raw_text, _re.DOTALL | _re.IGNORECASE)
    final_block = final_m.group(1) if final_m else ''

    se_m = _re.search(
        r'STANDARD ERROR OF ESTIMATE.*?\n[\*\s]+\n(.*?)(?=\n[\*\s]{60,}\n|\Z)',
        raw_text, _re.DOTALL | _re.IGNORECASE)
    se_block = se_m.group(1) if se_m else ''

    cor_raw_m = _re.search(
        r'CORRELATION MATRIX OF ESTIMATE.*?\n[\*\s]+\n(.*?)(?=\n[\*\s]{60,}\n|\Z)',
        raw_text, _re.DOTALL | _re.IGNORECASE)
    cor_raw_block = cor_raw_m.group(1) if cor_raw_m else ''

    cov_raw_m = _re.search(
        r'COVARIANCE MATRIX OF ESTIMATE.*?\n[\*\s]+\n(.*?)(?=\n[\*\s]{60,}\n|\Z)',
        raw_text, _re.DOTALL | _re.IGNORECASE)
    cov_raw_block = cov_raw_m.group(1) if cov_raw_m else ''

    # ── Parse theta/omega/sigma from raw if not in model dict ─────────────────
    def parse_theta_from_block(block):
        """Extract THETA values from final parameter block."""
        th_m = _re.search(r'THETA.*?VECTOR.*?\n\s+(.*?)\n\s+(.*?)\n', block, _re.DOTALL)
        if not th_m: return [], []
        labels = th_m.group(1).split()
        vals_str = th_m.group(2).split()
        vals = []
        for v in vals_str:
            try: vals.append(float(v))
            except ValueError: vals.append(None)
        return labels, vals

    def parse_omega_sigma_from_block(blk, name):
        """Extract OMEGA or SIGMA lower triangular from block."""
        m = _re.search(name + r'.*?MATRIX.*?\n(.*?)(?=\n\s*\n\s*(?:SIGMA|OMEGA|1\n|\Z))',
                       blk, _re.DOTALL | _re.IGNORECASE)
        if not m: return [], []
        section = m.group(1)
        labels_m = _re.search(r'^\s+((?:ETA\d+\s+|EPS\d+\s+)+)', section, _re.MULTILINE)
        if not labels_m: return [], []
        labels = labels_m.group(0).split()
        vals = []
        for row_m in _re.finditer(r'\+?\s*((?:[\d\.\-\+E]+|\.{9})\s*)+', section):
            row_vals = []
            for v in row_m.group(0).split():
                try: row_vals.append(float(v))
                except ValueError: row_vals.append(None)
            if row_vals: vals.append(row_vals)
        return labels, vals

    # ── 7. Parameters ──────────────────────────────────────────────────────────
    param_rows = ''
    blocks = [
        ('THETA','thetas','theta_ses','theta_names','theta_units','theta_fixed'),
        ('OMEGA','omegas','omega_ses','omega_names','omega_units','omega_fixed'),
        ('SIGMA','sigmas','sigma_ses','sigma_names','sigma_units','sigma_fixed'),
    ]
    import math as _math

    for block, ek, sk, nk, uk, fk in blocks:
        ests = model.get(ek,[]); ses = model.get(sk,[])
        names = model.get(nk,[]); units = model.get(uk,[])
        fixed = model.get(fk,[])
        if not ests: continue
        param_rows += f'<tr class="block-sep"><td colspan="8">{block}</td></tr>'
        for i, est in enumerate(ests):
            se   = ses[i]   if i < len(ses)   else None
            nm   = names[i] if i < len(names) else ''
            un   = units[i] if i < len(units) else ''
            fx   = fixed[i] if i < len(fixed) else False
            rse_v = abs(se/est)*100 if se and est and abs(est)>1e-12 else None
            rse_s = f'{rse_v:.1f}%' if rse_v is not None else ('...' if se is None and not fx else '—')
            rse_cls = ('red' if rse_v and rse_v>=50 else 'or' if rse_v and rse_v>=25 else 'ok') if rse_v else ''
            ci_lo = f'{est - 1.96*se:.4g}' if se else '—'
            ci_hi = f'{est + 1.96*se:.4g}' if se else '—'
            sd_s = f'{_math.sqrt(max(est,0)):.4g}' if block in ('OMEGA','SIGMA') and est is not None and est >= 0 else ''
            lbl = f'{block}({i+1})'
            fix_tag = ' <span class="fix">FIX</span>' if fx else ''
            param_rows += (
                f'<tr><td>{lbl}{fix_tag}</td><td>{nm}</td>'
                f'<td class="num">{fmt_num(est)}</td>'
                f'<td class="num">{sd_s}</td>'
                f'<td class="num">{fmt_num(se) if se is not None else ("..." if not fx else "—")}</td>'
                f'<td class="num {rse_cls}">{rse_s}</td>'
                f'<td class="num">[{ci_lo}, {ci_hi}]</td>'
                f'<td>{un}</td></tr>')

    param_html = (f'<div class="scroll-x"><table>'
                  f'<thead><tr><th>Parameter</th><th>Name</th><th>Estimate</th>'
                  f'<th>SD</th><th>SE</th><th>RSE%</th><th>95% CI</th><th>Units</th>'
                  f'</tr></thead><tbody>{param_rows}</tbody></table></div>'
                  if param_rows else
                  '<p style="color:#888;">Parameters not available — .lst may not have run successfully</p>')

    # ── 8. Covariance matrix ───────────────────────────────────────────────────
    cov_html = ''
    if cov_raw_block:
        lbls, mat = parse_nonmem_matrix(cov_raw_block)
        if lbls:
            cov_html = render_matrix_html(lbls, mat, is_correlation=False)
    if not cov_html:
        cov_html = '<p style="color:#888;">Not available (requires successful covariance step)</p>'

    # ── 9. Correlation matrix ──────────────────────────────────────────────────
    cor_html = ''
    # Try model dict first, then raw text
    cor_mat  = model.get('correlation_matrix',[])
    cor_lbls = model.get('cor_labels',[])
    if cor_mat and cor_lbls:
        cor_html = render_matrix_html(cor_lbls, cor_mat, is_correlation=True)
    elif cor_raw_block:
        lbls, mat = parse_nonmem_matrix(cor_raw_block)
        if lbls:
            cor_html = render_matrix_html(lbls, mat, is_correlation=True)
    if not cor_html:
        cor_html = '<p style="color:#888;">Not available (requires successful covariance step with PRINT=E)</p>'

    # ── 9. Eigenvalues ─────────────────────────────────────────────────────
    eig_m = _re.search(r'EIGENVALUES OF COR MATRIX.*?\n([\s\d\.E\+\-]+)\n', raw_text, _re.DOTALL)
    eig_html = ''
    if eig_m:
        vals = [float(x) for x in eig_m.group(1).split() if x.replace('.','').replace('-','').replace('+','').replace('E','').isdigit() or _re.match(r'[\d\.E\+\-]+', x)]
        if vals:
            mn, mx = min(vals), max(vals)
            cn_calc = mx/mn if mn > 0 else float('inf')
            cn_cls = 'red' if cn_calc > 1000 else 'or' if cn_calc > 100 else 'ok'
            eig_vals = '  '.join(f'{v:.3E}' for v in vals)
            eig_html = (f'<p style="font-family:{mono};font-size:12px;margin-bottom:8px;">{eig_vals}</p>'
                        f'<p>Min: <b>{mn:.3E}</b>  ·  Max: <b>{mx:.3E}</b>  ·  '
                        f'Condition number: <b class="{cn_cls}">{cn_calc:.1f}</b>'
                        f'{"  ⚠ CN > 1000: near-collinearity" if cn_calc > 1000 else ""}</p>')
    if not eig_html:
        if cn:
            cn_cls = 'red' if cn > 1000 else 'or' if cn > 100 else 'ok'
            eig_html = f'<p>Condition number: <b class="{cn_cls}">{cn:.1f}</b></p>'
        else:
            eig_html = '<p style="color:#888;">Not available</p>'

    # ── 10. Nav ────────────────────────────────────────────────────────────
    nav = f'''<div class="nav">
      <div style="font-size:10px;font-weight:700;color:{fg2};text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:8px;">Jump to</div>
      <a href="#summary">📊 Summary</a>
      {"<a href='#est-steps'>⏱ Steps</a>" if len(model.get('subproblems') or []) >= 2 else ""}
      {"<a href='#warnings'>⚠ Warnings</a>" if warnings_html else ""}
      <a href="#convergence">↻ Convergence</a>
      <a href="#parameters">θ Parameters</a>
      <a href="#etabar">η ETABAR</a>
      <a href="#correlation">ρ Correlation</a>
      <a href="#covariance">Σ Covariance</a>
      <a href="#eigenvalues">λ Eigenvalues</a>
      {"" if embed else "<a href='#raw'>⌨ Raw</a>"}
    </div>'''

    # ── 11. Estimation steps (only rendered if 2+ subproblems) ─────────────
    subs = model.get('subproblems') or []
    steps_block = ''
    if len(subs) >= 2:
        rows = ''
        prev_ofv = None
        for s in subs:
            ofv_v = s.get('ofv')
            ofv_cell = f'{ofv_v:.4f}' if ofv_v is not None else '—'
            if ofv_v is not None and prev_ofv is not None:
                d = ofv_v - prev_ofv
                dcls = 'ok' if d < 0 else ('red' if d > 0 else '')
                dOFV_cell = f'<span class="{dcls}">{d:+.3f}</span>'
            else:
                dOFV_cell = '—'
            rt = s.get('runtime')
            rt_cell = f'{rt:.2f} s' if rt is not None else '—'
            sig = s.get('sig_digits')
            sig_cell = f'{sig:.1f}' if sig is not None else '—'
            ms = s.get('minimization_successful')
            msg = s.get('minimization_message','')
            if ms is True:
                status_cell = f'<span class="good">{msg or "OK"}</span>'
            elif ms is False:
                status_cell = f'<span class="red">{msg or "FAILED"}</span>'
            else:
                status_cell = msg or '—'
            method = s.get('method_label') or s.get('method') or ''
            rows += (f'<tr>'
                     f'<td class="num">{s.get("step","")}</td>'
                     f'<td>{method}</td>'
                     f'<td class="num">{ofv_cell}</td>'
                     f'<td class="num">{dOFV_cell}</td>'
                     f'<td class="num">{rt_cell}</td>'
                     f'<td class="num">{sig_cell}</td>'
                     f'<td>{status_cell}</td>'
                     f'</tr>')
            if ofv_v is not None:
                prev_ofv = ofv_v
        total_rt = model.get('runtime_total')
        total_row = ''
        if total_rt:
            total_row = (f'<tr style="font-weight:700;border-top:2px solid {accent};">'
                         f'<td></td><td>Total</td><td></td><td></td>'
                         f'<td class="num">{total_rt:.2f} s</td>'
                         f'<td></td><td></td></tr>')
        steps_block = (
            f'<h2 id="est-steps">Estimation Steps</h2>'
            f'<div class="card">'
            f'<table><thead><tr>'
            f'<th>Step</th><th>Method</th><th>OFV</th><th>ΔOFV</th>'
            f'<th>Runtime</th><th>Sig. digits</th><th>Status</th>'
            f'</tr></thead><tbody>{rows}{total_row}</tbody></table>'
            f'</div>')

    # ── Assemble ───────────────────────────────────────────────────────────
    from datetime import datetime as _dt
    now = _dt.now().strftime('%Y-%m-%d %H:%M')

    html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<title>{stem}.lst — NMGUI</title>
<style>{css}</style>
</head><body>
{nav}
<h1 id="summary">{stem}.lst {status_tag}</h1>
<p style="color:{fg2};font-size:12px;margin-bottom:16px;">
  {model.get('problem','')}  ·  Rendered by NMGUI v{APP_VERSION}  ·  {now}
</p>
<div class="card"><div class="summary-grid">{summary_cards}</div></div>

{steps_block}

{"<h2 id='warnings'>⚠ NM-TRAN Warnings</h2>" + warnings_html if warnings_html else ""}

<h2 id="convergence">Convergence</h2>
<div class="card">{iter_html}</div>

<h2 id="parameters">Parameter Estimates</h2>
<div class="card">{param_html}</div>

<h2 id="etabar">ETABAR &amp; Shrinkage</h2>
<div class="card" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
  <div><h3 style="font-size:11px;font-weight:700;color:{fg2};margin-bottom:8px;
       text-transform:uppercase;letter-spacing:.5px;">ETABAR</h3>{etabar_html}</div>
  <div><h3 style="font-size:11px;font-weight:700;color:{fg2};margin-bottom:8px;
       text-transform:uppercase;letter-spacing:.5px;">Shrinkage</h3>{shr_html}</div>
</div>

<h2 id="correlation">Correlation Matrix</h2>
<div class="card">{cor_html}</div>

<h2 id="covariance">Covariance Matrix</h2>
<div class="card">{cov_html}</div>

<h2 id="eigenvalues">Eigenvalues &amp; Condition Number</h2>
<div class="card">{eig_html}</div>

{"" if embed else f'''
<details style="margin-top:24px;">
<summary id="raw">Control stream</summary>
<pre class="raw" style="margin-top:8px;">{hl_ctrl(ctrl_stream)}</pre>
</details>

<details style="margin-top:12px;">
<summary>Raw .lst output</summary>
<pre class="raw" style="margin-top:8px;">{raw_text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}</pre>
</details>
'''}

</body></html>"""
    return html


class LstOutputWidget(QWidget):
    """Rendered .lst viewer — embedded QTextBrowser + Open in browser button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None; self._raw_text = ''
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        # Toolbar
        tb = QWidget(); tb.setFixedHeight(36)
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(8,4,8,4); tbl.setSpacing(8)
        self._status_lbl = QLabel('No model selected')
        self._status_lbl.setObjectName('muted')
        tbl.addWidget(self._status_lbl, 1)
        self._browser_btn = QPushButton('Open in browser')
        self._browser_btn.setFixedHeight(26)
        self._browser_btn.setEnabled(False)
        self._browser_btn.clicked.connect(self._open_browser)
        tbl.addWidget(self._browser_btn)
        v.addWidget(tb)

        sep = QWidget(); sep.setFixedHeight(1)
        sep.setObjectName('hairlineSep')
        v.addWidget(sep)

        # QTextBrowser renders basic HTML tables and CSS
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setPlaceholderText('Select a model with a .lst file to render output.')
        v.addWidget(self._browser, 1)

    def load_model(self, model):
        self._model = model
        lst_path = model.get('lst_path','')
        if not lst_path or not Path(lst_path).is_file():
            self._status_lbl.setText(f'{model.get("stem","")} — no .lst file')
            self._browser_btn.setEnabled(False)
            self._browser.setPlainText('No .lst file found for this model.')
            return
        try:
            self._raw_text = Path(lst_path).read_text('utf-8', errors='replace')
        except Exception as e:
            self._browser.setPlainText(f'Could not read .lst file:\n{e}'); return
        self._status_lbl.setText(f'{model.get("stem","")} — {Path(lst_path).name}')
        self._browser_btn.setEnabled(True)
        html = render_lst_html(model, self._raw_text, embed=True)
        self._browser.setHtml(html)

    def _open_browser(self):
        if not self._model: return
        import tempfile, webbrowser
        html = render_lst_html(self._model, self._raw_text, embed=False)
        tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False,
                                          mode='w', encoding='utf-8')
        tmp.write(html); tmp.flush(); tmp_name = tmp.name; tmp.close()
        webbrowser.open(f'file://{tmp_name}')
        QTimer.singleShot(30000, lambda: Path(tmp_name).unlink(missing_ok=True))
