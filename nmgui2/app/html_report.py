from datetime import datetime
from pathlib import Path
from .constants import APP_VERSION
from .format import fmt_num


def generate_html_report(model: dict) -> str:
    """Generate a self-contained HTML run report for a model."""
    from datetime import datetime as _dt
    stem = model.get('stem', '')
    now  = _dt.now().strftime('%Y-%m-%d %H:%M')

    # ── CSS ──────────────────────────────────────────────────────────────────
    css = """
    *{box-sizing:border-box;}
    body{font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:13px;
         color:#1a1a2e;background:#f4f4f8;margin:0;padding:24px 32px;}
    h1{font-size:22px;font-weight:800;margin:0 0 2px;letter-spacing:-.5px;}
    h2{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
       color:#4c8aff;margin:28px 0 10px;padding-left:12px;
       border-left:3px solid #4c8aff;}
    .header{background:#fff;border:1px solid #e0e0ea;border-radius:10px;
            padding:20px 24px;margin-bottom:24px;
            display:flex;align-items:center;gap:20px;
            box-shadow:0 1px 4px rgba(0,0,0,.06);}
    .logo{background:#4c8aff;color:#fff;font-weight:900;font-size:17px;
          width:42px;height:42px;border-radius:10px;
          display:flex;align-items:center;justify-content:center;flex-shrink:0;}
    .meta{color:#7a7d9a;font-size:12px;margin-top:3px;}
    .card{background:#fff;border:1px solid #e0e0ea;border-radius:10px;
          padding:18px 22px;margin-bottom:16px;
          box-shadow:0 1px 4px rgba(0,0,0,.04);}
    .card-scroll{overflow-x:auto;}
    table{border-collapse:collapse;font-size:12px;min-width:100%;}
    thead th{background:#f0f0f8;font-weight:700;text-align:left;padding:7px 12px;
             border-bottom:2px solid #dde;color:#5a5a70;text-transform:uppercase;
             font-size:10.5px;letter-spacing:.4px;white-space:nowrap;}
    td{padding:6px 12px;border-bottom:1px solid #eeeef4;white-space:nowrap;}
    tr:last-child td{border-bottom:none;}
    tr:nth-child(even) td{background:#fafafd;}
    .block-sep td,.block-sep th{border-top:2px solid #4c8aff;padding-top:8px;
                                 font-weight:700;color:#4c8aff;font-size:10px;
                                 text-transform:uppercase;letter-spacing:.5px;}
    .good{color:#16a34a;font-weight:700;}
    .bad{color:#dc2626;font-weight:700;}
    .warn{color:#d97706;font-weight:700;}
    .fix{color:#b0b0c0;font-style:italic;font-size:11px;}
    .num{text-align:right;font-variant-numeric:tabular-nums;font-family:
         ui-monospace,Menlo,Consolas,monospace;}
    .summary-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;}
    .summary-item{background:#f8f8fc;border:1px solid #e8e8f0;border-radius:8px;padding:12px 14px;}
    .summary-label{font-size:10px;color:#9090a0;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;}
    .summary-value{font-size:17px;font-weight:800;letter-spacing:-.3px;}
    .sticky-col{position:sticky;left:0;background:#f0f0f8;z-index:1;font-weight:700;}
    @media print{
      body{background:#fff;padding:16px;}
      .header{box-shadow:none;border:1px solid #ccc;}
      .card{box-shadow:none;page-break-inside:avoid;}
      h2{page-break-after:avoid;}
    }
    """

    # ── Summary values ────────────────────────────────────────────────────────
    ofv   = model.get('ofv')
    status= model.get('minimization_message', '')
    cov   = model.get('covariance_step')
    cn    = model.get('condition_number')
    meth  = model.get('estimation_method', '')
    rt    = model.get('runtime')
    nind  = model.get('n_individuals')
    nobs  = model.get('n_observations')
    npar  = model.get('n_estimated_params')
    aic   = model.get('aic')

    def _cls(v, good_fn, warn_fn=None):
        if v is None: return ''
        if good_fn(v): return 'good'
        if warn_fn and warn_fn(v): return 'warn'
        return 'bad'

    status_cls = 'good' if ('SUCCESSFUL' in status or 'COMPLETED' in status) else 'bad'
    cov_str    = ('OK' if cov else 'FAILED') if cov is not None else '—'
    cov_cls    = 'good' if cov else ('bad' if cov is False else '')
    cn_str     = f'{cn:.1f}' if cn else '—'
    cn_cls     = 'warn' if cn and cn > 1000 else ('good' if cn else '')
    rt_str     = f'{rt:.1f} s' if rt else '—'

    summary_items = [
        ('OFV',                f'{ofv:.4f}' if ofv is not None else '—', ''),
        ('AIC',                f'{aic:.2f}' if aic is not None else '—', ''),
        ('Status',             status[:30] or '—', status_cls),
        ('Covariance',         cov_str, cov_cls),
        ('Condition number',   cn_str, cn_cls),
        ('Method',             meth or '—', ''),
        ('Individuals',        str(nind) if nind else '—', ''),
        ('Observations',       str(nobs) if nobs else '—', ''),
        ('Est. parameters',    str(npar) if npar else '—', ''),
        ('Runtime',            rt_str, ''),
    ]
    summary_html = '<div class="summary-grid">' + ''.join(
        f'<div class="summary-item"><div class="summary-label">{lbl}</div>'
        f'<div class="summary-value {cls}">{val}</div></div>'
        for lbl, val, cls in summary_items) + '</div>'

    # ── Parameter table ───────────────────────────────────────────────────────
    blocks = [
        ('THETA', model.get('thetas', []),  model.get('theta_ses', []),
         model.get('theta_names', []), model.get('theta_units', []), model.get('theta_fixed', [])),
        ('OMEGA', model.get('omegas', []),  model.get('omega_ses', []),
         model.get('omega_names', []), model.get('omega_units', []), model.get('omega_fixed', [])),
        ('SIGMA', model.get('sigmas', []),  model.get('sigma_ses', []),
         model.get('sigma_names', []), model.get('sigma_units', []), model.get('sigma_fixed', [])),
    ]
    param_rows = ''
    current_block = None
    for block, ests, ses, names, units, fixed in blocks:
        if ests:
            if block != current_block:
                current_block = block
                param_rows += (f'<tr class="block-sep">'
                               f'<td colspan="6">{block}</td></tr>')
            for i, est in enumerate(ests):
                se   = ses[i]   if i < len(ses)   else None
                nm   = names[i] if i < len(names) else ''
                un   = units[i] if i < len(units) else ''
                fx   = fixed[i] if i < len(fixed) else False
                rse  = f'{abs(se/est)*100:.1f}%' if se is not None and est and abs(est)>1e-12 else ('...' if se is None else '—')
                lbl  = f'{block}({i+1})'
                fix_badge = ' <span class="fix">FIX</span>' if fx else ''
                rse_cls = ''
                if se is not None and est and abs(est)>1e-12:
                    pct = abs(se/est)*100
                    rse_cls = 'good' if pct<25 else ('warn' if pct<50 else 'bad')
                param_rows += (
                    f'<tr><td>{lbl}{fix_badge}</td><td>{nm}</td>'
                    f'<td class="num">{fmt_num(est)}</td>'
                    f'<td class="num">{fmt_num(se) if se is not None else "..."}</td>'
                    f'<td class="num {rse_cls}">{rse}</td>'
                    f'<td class="num">{un}</td></tr>')

    param_html = f'''<div class="card-scroll">
    <table><thead><tr>
    <th>Parameter</th><th>Name</th><th>Estimate</th><th>SE</th><th>RSE%</th><th>Units</th>
    </tr></thead><tbody>{param_rows}</tbody></table></div>'''

    # ── Correlation matrix ────────────────────────────────────────────────────
    cor_mat  = model.get('correlation_matrix', [])
    cor_lbls = model.get('cor_labels', [])
    cor_html = ''
    if cor_mat and cor_lbls:
        hdr = ''.join(f'<th>{l}</th>' for l in cor_lbls)
        rows_h = ''
        for i, row in enumerate(cor_mat):
            lbl = cor_lbls[i] if i < len(cor_lbls) else str(i)
            cells = ''
            for j, v in enumerate(row):
                if v is None: cells += '<td></td>'
                else:
                    cls = ''
                    if i != j:
                        a = abs(v)
                        cls = 'bad' if a>0.9 else ('warn' if a>0.7 else '')
                    cells += f'<td class="num {cls}">{v:.3f}</td>'
            rows_h += f'<tr><th class="sticky-col">{lbl}</th>{cells}</tr>'
        cor_html = (f'<div class="card-scroll"><table><thead>'
                    f'<tr><th class="sticky-col"></th>{hdr}</tr></thead>'
                    f'<tbody>{rows_h}</tbody></table></div>')
    else:
        cor_html = '<p style="color:#9090a0;margin:0;">Not available (requires successful covariance step)</p>'

    # ── ETABAR ────────────────────────────────────────────────────────────────
    etabar  = model.get('etabar', [])
    etase   = model.get('etabar_se', [])
    etapval = model.get('etabar_pval', [])
    eta_html = ''
    if etabar:
        eta_rows = ''
        for i, eb in enumerate(etabar):
            se_  = etase[i]   if i < len(etase)   else None
            pv   = etapval[i] if i < len(etapval) else None
            pv_cls = 'bad' if pv is not None and pv < 0.05 else ''
            eta_rows += (f'<tr><td>ETA({i+1})</td>'
                         f'<td class="num">{eb:.4f}</td>'
                         f'<td class="num">{fmt_num(se_) if se_ else "—"}</td>'
                         f'<td class="num {pv_cls}">{f"{pv:.4f}" if pv is not None else "—"}</td></tr>')
        eta_html = f'''<table><thead><tr>
        <th>ETA</th><th>ETABAR</th><th>SE</th><th>P-value</th>
        </tr></thead><tbody>{eta_rows}</tbody></table>'''
    else:
        eta_html = '<p style="color:#9090a0;">Not available</p>'

    # ── Shrinkage ─────────────────────────────────────────────────────────────
    eta_shr = model.get('eta_shrinkage', [])
    eps_shr = model.get('eps_shrinkage', [])
    shr_html = ''
    if eta_shr or eps_shr:
        shr_rows = ''
        for i, v in enumerate(eta_shr):
            cls = 'bad' if v > 30 else ('warn' if v > 20 else 'good')
            shr_rows += f'<tr><td>ETA({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
        for i, v in enumerate(eps_shr):
            cls = 'bad' if v > 30 else ('warn' if v > 20 else 'good')
            shr_rows += f'<tr><td>EPS({i+1})</td><td class="num {cls}">{v:.1f}%</td></tr>'
        shr_html = f'<table><thead><tr><th>Parameter</th><th>Shrinkage (SD%)</th></tr></thead><tbody>{shr_rows}</tbody></table>'
    else:
        shr_html = '<p style="color:#9090a0;">Not available</p>'

    # ── Assemble ──────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8">
<title>NMGUI Report — {stem}</title>
<style>{css}</style>
</head><body>
<div class="header">
  <div class="logo">NM</div>
  <div>
    <h1>{stem}</h1>
    <div class="meta">{model.get('problem', '')}</div>
    <div class="meta">Generated by NMGUI v{APP_VERSION} · {now}</div>
  </div>
</div>
<h2>Summary</h2><div class="card">{summary_html}</div>
<h2>Parameter Estimates</h2><div class="card">{param_html}</div>
<h2>Correlation Matrix</h2><div class="card">{cor_html}</div>
<h2>ETABAR</h2><div class="card">{eta_html}</div>
<h2>Shrinkage</h2><div class="card">{shr_html}</div>
</body></html>"""
    return html
