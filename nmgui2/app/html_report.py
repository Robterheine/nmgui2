from datetime import datetime
from pathlib import Path
from .constants import APP_VERSION
from .format import fmt_num


# ── Init→Final visualization (HTML report side) ─────────────────────────────
# Mirrors the QPainter delegate in widgets/parameter_table.py:
#   - FIXED params: small grey diamond, no track
#   - Bounded params: track + initial tick + final marker
#   - Unbounded params: auto-scaled, right segment dashed
#   - Marker color graded by movement magnitude; red wall-line at-bound
# Inline SVG so the HTML report stays a single self-contained file —
# no external assets, no JavaScript, opens correctly in any browser.

_VIZ_WIDTH    = 80   # px
_VIZ_HEIGHT   = 18   # px
_VIZ_PAD_X    = 5
_TRACK_HEIGHT = 4

# Colors chosen to match the report's existing palette (light theme).
_C_TRACK       = '#e0e0ea'
_C_TICK        = '#7a7d9a'
_C_FIXED       = '#b0b0c0'
_C_DASH        = '#9090a0'
_C_BORDER      = '#5a5a70'
_C_MOVE_LOW    = '#7a7d9a'
_C_MOVE_MED    = '#4c8aff'   # accent
_C_MOVE_HIGH   = '#d97706'   # warn
_C_BOUND       = '#dc2626'   # bad


def _init_final_svg(initial, final, lower, upper, fixed):
    """Render the Init→Final cell as an inline SVG fragment.

    Args:
        initial: float or None (initial estimate from .lst echo)
        final:   float or None (final estimate)
        lower, upper: float or None (parameter bounds; None when unbounded
                                     or for FIXED parameters)
        fixed:   bool

    Returns:
        HTML string with an <svg> element, or '' when no data.
    """
    if fixed:
        # Small filled diamond — no track, no movement to show
        cx, cy = _VIZ_WIDTH // 2, _VIZ_HEIGHT // 2
        return (
            f'<svg width="{_VIZ_WIDTH}" height="{_VIZ_HEIGHT}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<polygon points="{cx},{cy-3} {cx+3},{cy} {cx},{cy+3} {cx-3},{cy}" '
            f'fill="{_C_FIXED}"/></svg>'
        )

    if initial is None or final is None:
        return ''   # blank cell — no data

    track_left  = _VIZ_PAD_X
    track_right = _VIZ_WIDTH - _VIZ_PAD_X
    cy          = _VIZ_HEIGHT // 2
    track_top   = cy - _TRACK_HEIGHT // 2

    # Determine scale: bounded if both bounds present and upper > lower
    if (lower is not None and upper is not None and float(upper) > float(lower)):
        scale_lo, scale_hi = float(lower), float(upper)
        extrapolated = False
    else:
        extrapolated = True
        vmin = min(initial, final, 0.0)
        vmax = max(initial, final, 0.0)
        scale_lo = float(lower) if lower is not None else vmin
        scale_hi = float(upper) if upper is not None else max(2.0 * max(abs(initial), abs(final)), 1e-9)
        if scale_hi <= scale_lo:
            scale_hi = scale_lo + max(abs(scale_lo) * 0.5, 1e-9)

    def _map(v):
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return (track_left + track_right) // 2
        if scale_hi == scale_lo:
            return (track_left + track_right) // 2
        x = track_left + (fv - scale_lo) / (scale_hi - scale_lo) * (track_right - track_left)
        return int(round(max(track_left, min(track_right, x))))

    # Marker color from movement magnitude + bound-proximity
    if initial == 0:
        abs_move = 0.0 if final == 0 else float('inf')
    else:
        abs_move = abs(final - initial) / abs(initial)

    at_upper = (
        upper is not None
        and abs(upper) > 1e-12
        and final >= upper - abs(upper) * 0.01
    )
    at_lower = (
        lower is not None
        and abs(lower) > 1e-12
        and final <= lower + abs(lower) * 0.01
    )
    at_bound = at_upper or at_lower

    if at_bound:
        marker_color = _C_BOUND
    elif abs_move >= 0.5:
        marker_color = _C_MOVE_HIGH
    elif abs_move >= 0.1:
        marker_color = _C_MOVE_MED
    else:
        marker_color = _C_MOVE_LOW

    x_init  = _map(initial)
    x_final = _map(final)

    parts = [
        f'<svg width="{_VIZ_WIDTH}" height="{_VIZ_HEIGHT}" '
        f'xmlns="http://www.w3.org/2000/svg">',
        # Track (rounded rect)
        f'<rect x="{track_left}" y="{track_top}" '
        f'width="{track_right - track_left}" height="{_TRACK_HEIGHT}" '
        f'rx="2" ry="2" fill="{_C_TRACK}"/>',
    ]
    if extrapolated:
        mid = track_left + (track_right - track_left) * 2 // 3
        parts.append(
            f'<line x1="{mid}" y1="{cy}" x2="{track_right}" y2="{cy}" '
            f'stroke="{_C_DASH}" stroke-width="1" stroke-dasharray="2,2"/>'
        )
    # Initial tick (short vertical line)
    parts.append(
        f'<line x1="{x_init}" y1="{track_top - 3}" '
        f'x2="{x_init}" y2="{track_top + _TRACK_HEIGHT + 3}" '
        f'stroke="{_C_TICK}" stroke-width="1"/>'
    )
    # Final marker (filled circle)
    parts.append(
        f'<circle cx="{x_final}" cy="{cy}" r="3" fill="{marker_color}"/>'
    )
    # At-bound wall line
    if at_bound:
        bound_x = track_right if at_upper else track_left
        parts.append(
            f'<line x1="{bound_x}" y1="{track_top - 4}" '
            f'x2="{bound_x}" y2="{track_top + _TRACK_HEIGHT + 4}" '
            f'stroke="{_C_BOUND}" stroke-width="1"/>'
        )
    parts.append('</svg>')
    return ''.join(parts)


def _init_final_tooltip(initial, final, lower, upper, fixed):
    """Title attribute for the HTML cell — shown on hover in browsers."""
    if fixed:
        return f'FIXED at {fmt_num(initial)}' if initial is not None else 'FIXED'
    if initial is None or final is None:
        return ''
    try:
        delta_pct = (final - initial) / initial * 100 if initial else 0.0
        delta_str = f'  ({delta_pct:+.1f}%)' if initial else ''
    except (TypeError, ZeroDivisionError):
        delta_str = ''
    if lower is not None and upper is not None:
        bounds = f'[{fmt_num(lower)}, {fmt_num(upper)}]'
    else:
        bounds = '(no upper bound)'
    # HTML title attribute uses literal newlines as spaces; use ' • ' for clarity
    return (
        f'Initial: {fmt_num(initial)} • Final: {fmt_num(final)}{delta_str} • Bounds: {bounds}'
    )


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
    .viz{padding:2px 6px;line-height:0;vertical-align:middle;width:90px;}
    .viz svg{display:block;}
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
    # Each block carries initial estimates and bounds (parsed from the .lst echo)
    # in parallel arrays for the Init→Final visualization column. OMEGA/SIGMA
    # don't have user-specifiable upper bounds — pass empty lists.
    blocks = [
        ('THETA', model.get('thetas', []),  model.get('theta_ses', []),
         model.get('theta_names', []), model.get('theta_units', []), model.get('theta_fixed', []),
         model.get('theta_initials', []), model.get('theta_lowers', []), model.get('theta_uppers', [])),
        ('OMEGA', model.get('omegas', []),  model.get('omega_ses', []),
         model.get('omega_names', []), model.get('omega_units', []), model.get('omega_fixed', []),
         model.get('omega_initials', []), [], []),
        ('SIGMA', model.get('sigmas', []),  model.get('sigma_ses', []),
         model.get('sigma_names', []), model.get('sigma_units', []), model.get('sigma_fixed', []),
         model.get('sigma_initials', []), [], []),
    ]
    param_rows = ''
    current_block = None
    for block, ests, ses, names, units, fixed, inits, lowers, uppers in blocks:
        if ests:
            if block != current_block:
                current_block = block
                param_rows += (f'<tr class="block-sep">'
                               f'<td colspan="7">{block}</td></tr>')
            for i, est in enumerate(ests):
                se   = ses[i]   if i < len(ses)   else None
                nm   = names[i] if i < len(names) else ''
                un   = units[i] if i < len(units) else ''
                fx   = fixed[i] if i < len(fixed) else False
                init  = inits[i]  if i < len(inits)  else None
                lower = lowers[i] if i < len(lowers) else None
                upper = uppers[i] if i < len(uppers) else None
                rse  = f'{abs(se/est)*100:.1f}%' if se is not None and est and abs(est)>1e-12 else ('...' if se is None else '—')
                lbl  = f'{block}({i+1})'
                fix_badge = ' <span class="fix">FIX</span>' if fx else ''
                rse_cls = ''
                if se is not None and est and abs(est)>1e-12:
                    pct = abs(se/est)*100
                    rse_cls = 'good' if pct<25 else ('warn' if pct<50 else 'bad')
                viz_svg  = _init_final_svg(init, est, lower, upper, fx)
                viz_tip  = _init_final_tooltip(init, est, lower, upper, fx)
                viz_cell = f'<td class="viz" title="{viz_tip}">{viz_svg}</td>'
                param_rows += (
                    f'<tr><td>{lbl}{fix_badge}</td><td>{nm}</td>'
                    f'<td class="num">{fmt_num(est)}</td>'
                    f'{viz_cell}'
                    f'<td class="num">{fmt_num(se) if se is not None else "..."}</td>'
                    f'<td class="num {rse_cls}">{rse}</td>'
                    f'<td class="num">{un}</td></tr>')

    param_html = f'''<div class="card-scroll">
    <table><thead><tr>
    <th>Parameter</th><th>Name</th><th>Estimate</th><th>Init&rarr;Final</th><th>SE</th><th>RSE%</th><th>Units</th>
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
