"""
NONMEM .lst file parser.
Extracts key results: OFV, minimization status, parameter estimates,
standard errors, condition number, shrinkage, and runtime.
"""

import re
import os
import logging
from pathlib import Path

_log = logging.getLogger(__name__)


def _method_label(raw_method):
    """Convert a raw '#METH:' description into a short label for UI display.

    Examples:
      'First Order with Interaction'                      -> 'FO-I'
      'First Order Conditional Estimation with Interact.' -> 'FOCE-I'
      'Laplacian Conditional Estimation'                  -> 'LAPLACE'
      'Stochastic Approximation Expectation-Maximization' -> 'SAEM'
      'Objective Function Evaluation by Importance Sampl.'-> 'IMP'
      'Iterative Two Stage'                               -> 'ITS'
      'Markov Chain Monte Carlo Bayesian Analysis'        -> 'BAYES'
    """
    if not raw_method:
        return ''
    m = raw_method.strip()
    low = m.lower()
    has_inter = 'interaction' in low or 'interact' in low
    if 'laplacian' in low or 'laplace' in low:
        return 'LAPLACE-I' if has_inter else 'LAPLACE'
    if 'stochastic approximation' in low or 'saem' in low:
        return 'SAEM'
    if 'markov' in low or 'bayes' in low or 'nuts' in low:
        return 'BAYES'
    if 'importance sampling' in low:
        return 'IMP-I' if has_inter else 'IMP'
    if 'iterative two stage' in low or low.startswith('its'):
        return 'ITS'
    if 'first order conditional' in low:
        return 'FOCE-I' if has_inter else 'FOCE'
    if 'first order' in low:
        return 'FO-I' if has_inter else 'FO'
    # Unknown: uppercase the first word as a best-effort label
    return m.split()[0].upper() if m.split() else m.upper()


def _extract_subproblems(text):
    """Split a chained-$EST .lst into per-estimation-step records.

    Each NONMEM estimation step is bounded by a '#TBLN: N' marker line.
    The last step's slice runs from its '#TBLN:' to EOF (inclusive of any
    trailing STANDARD ERROR / COVARIANCE / EIGENVALUE sections which
    belong to that final step globally).

    Returns a list of dicts in estimation order (step 1 first). Each dict
    has the keys documented below. An empty list is returned if no
    '#TBLN:' markers are found (a single-$EST run — the caller should
    synthesize a single subproblem from the top-level parse_lst fields).
    """
    # Locate all #TBLN: markers with their line offsets.
    tbln_positions = [m.start() for m in re.finditer(r'^\s*#TBLN:\s*\d+', text, re.MULTILINE)]
    if not tbln_positions:
        return []

    # Define slice boundaries. Last slice extends to EOF.
    boundaries = tbln_positions + [len(text)]
    subs = []
    for i in range(len(tbln_positions)):
        slice_text = text[boundaries[i]:boundaries[i + 1]]
        sub = {
            'step': i + 1,
            'method': '',
            'method_label': '',
            'ofv': None,
            'minimization_successful': None,
            'minimization_message': '',
            'runtime': None,
            'sig_digits': None,
            'covariance_step': None,
            'etabar': [],
            'etabar_se': [],
            'etabar_pval': [],
            'eta_shrinkage': [],
            'eps_shrinkage': [],
            'thetas': [],
            'omegas': [],
            'sigmas': [],
            'omega_matrix': [],
            'sigma_matrix': [],
            'theta_ses': [],
            'omega_ses': [],
            'sigma_ses': [],
            'omega_se_matrix': [],
            'sigma_se_matrix': [],
            'boundary': False,
        }

        # Method name from '#METH:' line.
        m = re.search(r'^\s*#METH:\s*(.+?)\s*$', slice_text, re.MULTILINE)
        if m:
            sub['method'] = m.group(1).strip()
            sub['method_label'] = _method_label(sub['method'])

        # OFV from '#OBJV:' line (canonical, works across all methods).
        m = re.search(r'#OBJV:\*+\s*([-\d.]+(?:E[+-]?\d+)?)', slice_text)
        if m:
            try:
                sub['ofv'] = float(m.group(1))
            except ValueError:
                _log.debug('Step %d: could not parse OFV from #OBJV line: %r', i + 1, m.group(1))

        # Termination block: between '#TERM:' and '#TERE:'.
        term_match = re.search(r'#TERM:(.*?)#TERE:', slice_text, re.DOTALL)
        term_text = term_match.group(1) if term_match else ''

        # Classify termination status per method family.
        if 'MINIMIZATION SUCCESSFUL' in term_text:
            sub['minimization_successful'] = True
            sub['minimization_message'] = 'SUCCESSFUL'
        elif 'MINIMIZATION TERMINATED' in term_text:
            sub['minimization_successful'] = False
            tm = re.search(r'(MINIMIZATION TERMINATED[^\n]*)', term_text)
            sub['minimization_message'] = tm.group(1).strip() if tm else 'TERMINATED'
        elif 'OPTIMIZATION NOT COMPLETED' in term_text:
            sub['minimization_successful'] = False
            sub['minimization_message'] = 'NOT COMPLETED'
        elif re.search(r'STATISTICAL PORTION WAS COMPLETED', term_text, re.IGNORECASE):
            sub['minimization_successful'] = True
            sub['minimization_message'] = 'SAEM COMPLETED'
        elif re.search(r'BURN.?IN.*COMPLETED', term_text, re.IGNORECASE):
            sub['minimization_successful'] = True
            sub['minimization_message'] = 'BURN-IN COMPLETED'
        elif re.search(r'EXPECTATION ONLY PROCESS WAS COMPLETED', term_text, re.IGNORECASE):
            sub['minimization_successful'] = True
            sub['minimization_message'] = 'IMP EVALUATION COMPLETED'
        elif re.search(r'IMPORTANCE SAMPLING.*COMPLETED', term_text, re.IGNORECASE):
            sub['minimization_successful'] = True
            sub['minimization_message'] = 'IMP COMPLETED'
        elif re.search(r'ITERATIVE TWO STAGE.*COMPLETED', term_text, re.IGNORECASE):
            sub['minimization_successful'] = True
            sub['minimization_message'] = 'ITS COMPLETED'
        elif re.search(r'(BAYES|NUTS).*COMPLETED', term_text, re.IGNORECASE):
            sub['minimization_successful'] = True
            sub['minimization_message'] = 'BAYES COMPLETED'

        # Significant digits (inside #TERM: block on FO/FOCE steps).
        m = re.search(r'NO\.\s*OF\s*SIG\.\s*DIGITS\s*IN\s*FINAL\s*EST\.:\s*([\d.]+)',
                      slice_text, re.IGNORECASE)
        if m:
            try:
                sub['sig_digits'] = float(m.group(1))
            except ValueError:
                pass

        # Runtime (Elapsed estimation time, immediately after #TERE:).
        m = re.search(r'Elapsed\s+estimation\s+time\s+in\s+seconds:\s*([\d.]+)',
                      slice_text, re.IGNORECASE)
        if m:
            try:
                sub['runtime'] = float(m.group(1))
            except ValueError:
                pass

        # Boundary warning (per-step).
        if re.search(r'PARAMETER ESTIMATE IS NEAR ITS BOUNDARY', slice_text, re.IGNORECASE):
            sub['boundary'] = True

        # ETABAR, SE, P VAL (only present when EBEs are computed).
        eb = re.search(r'^\s*ETABAR:\s+(.+)$', slice_text, re.MULTILINE)
        se_ln = re.search(r'^\s*SE:\s+(.+)$', slice_text, re.MULTILINE)
        pv = re.search(r'^\s*P\s*VAL\.?:\s+(.+)$', slice_text, re.MULTILINE)
        if eb:
            try:
                sub['etabar'] = [float(x) for x in eb.group(1).split()]
            except ValueError:
                pass
        if se_ln:
            try:
                sub['etabar_se'] = [float(x) for x in se_ln.group(1).split()]
            except ValueError:
                pass
        if pv:
            try:
                sub['etabar_pval'] = [float(x) for x in pv.group(1).split()]
            except ValueError:
                pass

        # Shrinkage (ETA and EPS) — accept ETASHRINKSD/ETAshrinkSD forms.
        eta_shr = re.findall(
            r'(?:ETAShrink(?:a?SD)?|EtaShrinkSD)\s*[\(%]\s*%?\)?\s*:?\s*'
            r'((?:[-+]?\d+\.?\d*(?:E[+-]?\d+)?(?:\s+|$))+)',
            slice_text, re.IGNORECASE | re.MULTILINE
        )
        if eta_shr:
            try:
                sub['eta_shrinkage'] = [float(x) for x in eta_shr[-1].split()]
            except ValueError:
                pass
        eps_shr = re.findall(
            r'(?:EPSShrink(?:a?SD)?|EpsShrinkSD)\s*[\(%]\s*%?\)?\s*:?\s*'
            r'((?:[-+]?\d+\.?\d*(?:E[+-]?\d+)?(?:\s+|$))+)',
            slice_text, re.IGNORECASE | re.MULTILINE
        )
        if eps_shr:
            try:
                sub['eps_shrinkage'] = [float(x) for x in eps_shr[-1].split()]
            except ValueError:
                pass

        # Per-step FINAL PARAMETER ESTIMATE block (thetas/omegas/sigmas).
        # Each step emits one such block; use _extract_block on the slice.
        tb = _extract_block(slice_text, r'THETA - VECTOR OF FIXED EFFECTS PARAMETERS')
        if tb:
            sub['thetas'] = _parse_values(tb)
        ob = _extract_block(slice_text, r'OMEGA - COV MATRIX FOR RANDOM EFFECTS - ETAS')
        if ob:
            sub['omegas'] = _parse_matrix_diag(ob)
            sub['omega_matrix'] = _parse_matrix_full(ob)
        sb = _extract_block(slice_text, r'SIGMA - COV MATRIX FOR RANDOM EFFECTS - EPSILONS')
        if sb:
            sub['sigmas'] = _parse_matrix_diag(sb)
            sub['sigma_matrix'] = _parse_matrix_full(sb)

        # Standard errors (only last step typically; $COV evaluated once).
        se_sections = slice_text.split('STANDARD ERROR OF ESTIMATE')
        if len(se_sections) > 1:
            se_text = se_sections[-1]
            tse = _extract_block(se_text, r'THETA - VECTOR OF FIXED EFFECTS PARAMETERS')
            if tse:
                sub['theta_ses'] = _parse_values(tse, keep_dots=True)
            ose = _extract_block(se_text, r'OMEGA - COV MATRIX FOR RANDOM EFFECTS - ETAS')
            if ose:
                sub['omega_ses'] = _parse_matrix_diag(ose)
                sub['omega_se_matrix'] = _parse_matrix_full(ose)
            sse = _extract_block(se_text, r'SIGMA - COV MATRIX FOR RANDOM EFFECTS - EPSILONS')
            if sse:
                sub['sigma_ses'] = _parse_matrix_diag(sse)
                sub['sigma_se_matrix'] = _parse_matrix_full(sse)
            sub['covariance_step'] = True

        subs.append(sub)

    return subs


def parse_lst(lst_path):
    """Parse a NONMEM .lst file and return structured results."""
    result = {
        'file': str(lst_path),
        'ofv': None,
        'minimization_successful': None,
        'minimization_message': '',
        'covariance_step': None,
        'n_individuals': None,
        'n_observations': None,
        'sig_digits': None,
        'boundary': False,
        'cov_failure_reason': '',
        'etabar': [],
        'etabar_se': [],
        'etabar_pval': [],
        'n_estimated_params': None,
        'aic': None,
        'bic': None,
        'thetas': [],
        'omegas': [],
        'sigmas': [],
        'omega_matrix': [],
        'sigma_matrix': [],
        'theta_ses': [],
        'omega_ses': [],
        'sigma_ses': [],
        'omega_se_matrix': [],
        'sigma_se_matrix': [],
        'correlation_matrix': [],
        'cor_labels': [],
        'condition_number': None,
        'eta_shrinkage': [],
        'eps_shrinkage': [],
        'runtime': None,
        'estimation_method': '',
        'subproblems': [],
        'raw_text': '',
    }

    if not os.path.exists(lst_path):
        return result

    with open(lst_path, 'r', encoding='utf-8-sig', errors='replace') as f:
        text = f.read()

    result['raw_text'] = text

    # Detect estimation method from control stream or output
    est_method = 'FO'  # default
    method_match = re.search(r'\$EST(?:IMATION)?\s[^;]*?METHOD\s*=\s*(\w+)', text, re.IGNORECASE)
    if method_match:
        m_raw = method_match.group(1).upper()
        if m_raw in ('SAEM', '3'):
            est_method = 'SAEM'
        elif m_raw in ('IMP', 'IMPMAP', 'ITS'):
            est_method = m_raw
        elif m_raw in ('BAYES', 'NUTS', 'CHAIN', '4'):
            est_method = 'BAYES'
        elif m_raw in ('COND', 'CONDITIONAL', '1'):
            est_method = 'FOCE'
        elif m_raw in ('0', 'ZERO'):
            est_method = 'FO'
        else:
            est_method = m_raw
    # Check for INTER option
    if re.search(r'\$EST[^;]*INTER', text, re.IGNORECASE) and est_method == 'FOCE':
        est_method = 'FOCE-I'
    # If multiple $EST, take the last method (often IMP after SAEM)
    all_methods = re.findall(r'\$EST(?:IMATION)?\s[^;]*?METHOD\s*=\s*(\w+)', text, re.IGNORECASE)
    if len(all_methods) > 1:
        last = all_methods[-1].upper()
        if last in ('IMP', 'IMPMAP'):
            est_method = 'SAEM\u2192IMP'
        elif last in ('1', 'COND', 'CONDITIONAL'):
            est_method = 'SAEM\u2192FOCE'
    result['estimation_method'] = est_method

    # OFV — multiple formats across estimation methods
    ofv_matches = re.findall(
        r'MINIMUM VALUE OF OBJECTIVE FUNCTION\s*[=:]\s*([-\d.]+(?:E[+-]?\d+)?)',
        text, re.IGNORECASE
    )
    # SAEM/IMP: #OBJV line (canonical final OFV)
    objv_matches = re.findall(r'#OBJV:\*+\s*([-\d.]+(?:E[+-]?\d+)?)', text)
    # SAEM: LIKELIHOOD line
    ll_matches = re.findall(
        r'-2\s*LOG(?:\s*LIKE\w*)?\s*[:=]\s*([-\d.]+(?:E[+-]?\d+)?)',
        text, re.IGNORECASE
    )
    # IMP/ITS: OBJECTIVE FUNCTION VALUE at final step
    # Exclude "WITH CONSTANT" variant — we want "WITHOUT CONSTANT" or plain OFV
    imp_ofv = re.findall(
        r'OBJECTIVE FUNCTION VALUE(?:\s+WITHOUT CONSTANT)?:\s*([-\d.]+(?:E[+-]?\d+)?)',
        text, re.IGNORECASE
    )

    # Priority order: #OBJV (canonical) > MINIMUM VALUE > others
    # Use first match from highest-priority source
    if objv_matches:
        try:
            result['ofv'] = float(objv_matches[-1])
        except ValueError:
            _log.debug('%s: could not parse OFV from #OBJV line: %r', lst_path, objv_matches[-1])
    elif ofv_matches:
        try:
            result['ofv'] = float(ofv_matches[-1])
        except ValueError:
            _log.debug('%s: could not parse OFV from MINIMUM VALUE line: %r', lst_path, ofv_matches[-1])
    else:
        all_ofv = ll_matches + imp_ofv
        if all_ofv:
            try:
                result['ofv'] = float(all_ofv[-1])
            except ValueError:
                _log.debug('%s: could not parse OFV from fallback line: %r', lst_path, all_ofv[-1])

    # Minimization / convergence status — method-aware
    # Classical: FOCE/FO
    if re.search(r'MINIMIZATION SUCCESSFUL', text):
        result['minimization_successful'] = True
        result['minimization_message'] = 'SUCCESSFUL'
    elif re.search(r'MINIMIZATION TERMINATED', text):
        result['minimization_successful'] = False
        term_match = re.search(r'(MINIMIZATION TERMINATED.*?)(?:\n\s*\n|\n0)', text, re.DOTALL)
        if term_match:
            result['minimization_message'] = term_match.group(1).strip()[:200]
        else:
            result['minimization_message'] = 'TERMINATED'
    elif re.search(r'OPTIMIZATION NOT COMPLETED', text):
        result['minimization_successful'] = False
        result['minimization_message'] = 'NOT COMPLETED'
    # SAEM
    elif re.search(r'STATISTICAL PORTION WAS COMPLETED', text, re.IGNORECASE):
        result['minimization_successful'] = True
        if re.search(r'BURN.?IN\s.*NOT\s.*TESTED', text, re.IGNORECASE):
            result['minimization_message'] = 'SAEM (burn-in not tested)'
        else:
            result['minimization_message'] = 'SAEM COMPLETED'
    elif re.search(r'BURN.?IN\s.*COMPLETED', text, re.IGNORECASE):
        result['minimization_successful'] = True
        result['minimization_message'] = 'SAEM COMPLETED'
    # IMP/ITS
    elif re.search(r'IMPORTANCE SAMPLING.*COMPLETED', text, re.IGNORECASE):
        result['minimization_successful'] = True
        result['minimization_message'] = 'IMP COMPLETED'
    elif re.search(r'ITERATIVE TWO STAGE.*COMPLETED', text, re.IGNORECASE):
        result['minimization_successful'] = True
        result['minimization_message'] = 'ITS COMPLETED'
    # BAYES
    elif re.search(r'BAYES ESTIMATION.*COMPLETED', text, re.IGNORECASE):
        result['minimization_successful'] = True
        result['minimization_message'] = 'BAYES COMPLETED'
    elif re.search(r'NUTS ESTIMATION.*COMPLETED', text, re.IGNORECASE):
        result['minimization_successful'] = True
        result['minimization_message'] = 'NUTS COMPLETED'

    # Covariance step
    if re.search(r'Elapsed covariance\s+time', text, re.IGNORECASE):
        result['covariance_step'] = True
    elif re.search(r'STANDARD ERROR OF ESTIMATE', text):
        result['covariance_step'] = True
    elif re.search(r'COVARIANCE STEP ABORTED', text, re.IGNORECASE):
        result['covariance_step'] = False
    elif re.search(r'\$COV', text):
        # $COV was requested but no output found
        result['covariance_step'] = False

    # Number of individuals and observations
    nind_match = re.search(r'TOT\.?\s*NO\.?\s*OF\s*INDIVIDUALS\s*:\s*(\d+)', text, re.IGNORECASE)
    if nind_match:
        result['n_individuals'] = int(nind_match.group(1))
    nobs_match = re.search(r'TOT\.?\s*NO\.?\s*OF\s*OBS\s*RECS\s*:\s*(\d+)', text, re.IGNORECASE)
    if nobs_match:
        result['n_observations'] = int(nobs_match.group(1))

    # Significant digits
    sig_match = re.search(r'NO\.\s*OF\s*SIG\.\s*DIGITS\s*IN\s*FINAL\s*EST\.:\s*([\d.]+)', text)
    if sig_match:
        try:
            result['sig_digits'] = float(sig_match.group(1))
        except ValueError:
            pass

    # Boundary warning
    if re.search(r'PARAMETER ESTIMATE IS NEAR ITS BOUNDARY', text, re.IGNORECASE):
        result['boundary'] = True

    # Covariance step failure reason
    if result['covariance_step'] is False:
        cov_msgs = [
            (r'R MATRIX ALGORITHMICALLY.*?SINGULAR', 'R matrix singular'),
            (r'R MATRIX.*?NOT POSITIVE (SEMI-)?DEFINITE', 'R matrix not positive semi-definite'),
            (r'S MATRIX ALGORITHMICALLY.*?SINGULAR', 'S matrix singular'),
            (r'COVARIANCE STEP ABORTED', 'Covariance step aborted'),
            (r'MATRIX OF SECOND DERIVATIVES.*?SINGULAR', 'Hessian singular'),
        ]
        for pat, msg in cov_msgs:
            if re.search(pat, text, re.IGNORECASE):
                result['cov_failure_reason'] = msg
                break
        if not result['cov_failure_reason']:
            result['cov_failure_reason'] = 'Failed'

    # ETABAR, SE, and P-values (line-by-line extraction)
    eb_line = re.search(r'^\s*ETABAR:\s+(.+)$', text, re.MULTILINE)
    se_line = re.search(r'^\s*SE:\s+(.+)$', text, re.MULTILINE)
    pv_line = re.search(r'^\s*P\s*VAL\.?:\s+(.+)$', text, re.MULTILINE)
    if eb_line:
        try:
            result['etabar'] = [float(x) for x in eb_line.group(1).split()]
        except ValueError:
            pass
    if se_line:
        try:
            result['etabar_se'] = [float(x) for x in se_line.group(1).split()]
        except ValueError:
            pass
    if pv_line:
        try:
            result['etabar_pval'] = [float(x) for x in pv_line.group(1).split()]
        except ValueError:
            pass

    # THETA estimates
    theta_block = _extract_block(text, r'THETA - VECTOR OF FIXED EFFECTS PARAMETERS')
    if theta_block:
        result['thetas'] = _parse_values(theta_block)

    # OMEGA estimates (diagonal + full matrix)
    omega_block = _extract_block(text, r'OMEGA - COV MATRIX FOR RANDOM EFFECTS - ETAS')
    if omega_block:
        result['omegas'] = _parse_matrix_diag(omega_block)
        result['omega_matrix'] = _parse_matrix_full(omega_block)

    # SIGMA estimates (diagonal + full matrix)
    sigma_block = _extract_block(text, r'SIGMA - COV MATRIX FOR RANDOM EFFECTS - EPSILONS')
    if sigma_block:
        result['sigmas'] = _parse_matrix_diag(sigma_block)
        result['sigma_matrix'] = _parse_matrix_full(sigma_block)

    # Standard errors
    se_section = text.split('STANDARD ERROR OF ESTIMATE')
    if len(se_section) > 1:
        se_text = se_section[-1]

        theta_se_block = _extract_block(se_text, r'THETA - VECTOR OF FIXED EFFECTS PARAMETERS')
        if theta_se_block:
            result['theta_ses'] = _parse_values(theta_se_block, keep_dots=True)

        omega_se_block = _extract_block(se_text, r'OMEGA - COV MATRIX FOR RANDOM EFFECTS - ETAS')
        if omega_se_block:
            result['omega_ses'] = _parse_matrix_diag(omega_se_block)
            result['omega_se_matrix'] = _parse_matrix_full(omega_se_block)

        sigma_se_block = _extract_block(se_text, r'SIGMA - COV MATRIX FOR RANDOM EFFECTS - EPSILONS')
        if sigma_se_block:
            result['sigma_ses'] = _parse_matrix_diag(sigma_se_block)
            result['sigma_se_matrix'] = _parse_matrix_full(sigma_se_block)

    # Condition number
    # Strategy 1: Direct "CONDITION NUMBER" output (some NONMEM versions)
    cond_direct = re.search(
        r'CONDITION NUMBER[^:]*?:\s*([\d.]+(?:E[+-]?\d+)?)',
        text, re.IGNORECASE
    )
    if cond_direct:
        try:
            result['condition_number'] = float(cond_direct.group(1))
        except ValueError:
            _log.debug('%s: could not parse condition number: %r', lst_path, cond_direct.group(1))

    # Strategy 2: Compute from eigenvalues of correlation matrix
    if result['condition_number'] is None:
        # Find the EIGENVALUES section — skip ** decoration lines and column headers
        eig_match = re.search(r'EIGENVALUES OF COR MATRIX OF ESTIMATE', text)
        if eig_match:
            eig_after = text[eig_match.end():eig_match.end() + 500]
            eigs = []
            for line in eig_after.split('\n'):
                line = line.strip()
                if not line or line.startswith('*') or line.startswith('#'):
                    continue
                # Skip column number header lines (just integers)
                if re.match(r'^[\d\s]+$', line) and not re.search(r'[.eEdD]', line):
                    continue
                # Extract floating point values
                for val in re.findall(r'([-+]?\d*\.?\d+(?:[eEdD][+-]?\d+)?)', line):
                    try:
                        v = float(val.replace('D', 'E').replace('d', 'e'))
                        if v > 0:
                            eigs.append(v)
                    except ValueError:
                        pass
                if eigs:
                    break  # Eigenvalues are typically on one or two lines
            if len(eigs) >= 2:
                try:
                    result['condition_number'] = max(eigs) / min(eigs)
                except ZeroDivisionError:
                    pass

    # Correlation matrix of estimates
    cor_match = re.search(r'CORRELATION MATRIX OF ESTIMATE', text)
    if cor_match:
        # Find the end: INVERSE COVARIANCE or EIGENVALUES section
        cor_end = re.search(
            r'INVERSE COVARIANCE|EIGENVALUES OF COR MATRIX',
            text[cor_match.end():]
        )
        cor_text = text[cor_match.end():cor_match.end() + (cor_end.start() if cor_end else 2000)]

        labels = []
        labels_done = False
        matrix_rows = []
        for line in cor_text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('*') or (line.startswith('1') and len(line) <= 2):
                continue
            # Value line starts with +
            if line.startswith('+'):
                vals_line = line[1:].strip()
                row_vals = []
                for token in vals_line.split():
                    if token.startswith('.') and '..' in token:
                        row_vals.append(None)
                    else:
                        try:
                            row_vals.append(float(token.replace('D', 'E').replace('d', 'e')))
                        except ValueError:
                            row_vals.append(None)
                if row_vals:
                    matrix_rows.append(row_vals)
                continue
            # Check if this is a column header (many labels on one line) vs row label (single)
            if re.match(r'^(TH|OM|SG)\s', line):
                parts = line.split()
                # Merge "TH 1" → "TH1" etc.
                merged = []
                i = 0
                while i < len(parts):
                    if i + 1 < len(parts) and re.match(r'^(TH|OM|SG)$', parts[i]):
                        merged.append(parts[i] + parts[i + 1])
                        i += 2
                    else:
                        merged.append(parts[i])
                        i += 1
                # Column header: 3+ labels; Row label: 1 label
                if len(merged) >= 3 and not labels_done:
                    labels = merged
                    labels_done = True
                # else: it's a row label, skip it
                continue

        if matrix_rows:
            result['correlation_matrix'] = matrix_rows
            result['cor_labels'] = labels

    # Shrinkage — multiple formats: "ETAShrinkSD(%):  12.5" or "ETAShrinkSD(%)  12.5"
    eta_shr = re.findall(
        r'ETAShrink(?:a?SD)?\s*[\(%]\s*%?\)?\s*:?\s*((?:\d+\.?\d*(?:E[+-]?\d+)?(?:\s+|$))+)',
        text, re.IGNORECASE | re.MULTILINE
    )
    if not eta_shr:
        eta_shr = re.findall(
            r'EtaShrinkSD\s*[\(%]\s*%?\)?\s*:?\s*((?:\d+\.?\d*(?:E[+-]?\d+)?(?:\s+|$))+)',
            text, re.IGNORECASE | re.MULTILINE
        )
    if eta_shr:
        try:
            result['eta_shrinkage'] = [float(x) for x in eta_shr[-1].split()]
        except ValueError:
            pass

    eps_shr = re.findall(
        r'EPSShrink(?:a?SD)?\s*[\(%]\s*%?\)?\s*:?\s*((?:\d+\.?\d*(?:E[+-]?\d+)?(?:\s+|$))+)',
        text, re.IGNORECASE | re.MULTILINE
    )
    if not eps_shr:
        eps_shr = re.findall(
            r'EpsShrinkSD\s*[\(%]\s*%?\)?\s*:?\s*((?:\d+\.?\d*(?:E[+-]?\d+)?(?:\s+|$))+)',
            text, re.IGNORECASE | re.MULTILINE
        )
    if eps_shr:
        try:
            result['eps_shrinkage'] = [float(x) for x in eps_shr[-1].split()]
        except ValueError:
            pass

    # Runtime
    runtime_match = re.search(
        r'Elapsed\s+(?:estimation|total)\s+time\s+in\s+seconds:\s*([\d.]+)',
        text, re.IGNORECASE
    )
    if runtime_match:
        try:
            result['runtime'] = float(runtime_match.group(1))
        except ValueError:
            pass
    else:
        # Try wall clock
        wall_match = re.search(r'Wall Time:\s*([\d.]+)', text)
        if wall_match:
            try:
                result['runtime'] = float(wall_match.group(1))
            except ValueError:
                pass

    # Count estimated parameters and compute AIC/BIC
    n_est = 0
    # Count non-fixed THETAs: SE must be present (not None) and non-zero.
    # NONMEM reports SE=0 for FIX'd parameters when COV step runs.
    if result['theta_ses']:
        n_est += sum(1 for s in result['theta_ses'] if s is not None and s != 0)
    elif result['thetas']:
        # No COV: try to detect FIX'd THETAs from echoed control stream
        theta_fix_count = len(re.findall(r'\$THETA[^;$]*?FIX', text, re.IGNORECASE))
        n_est += max(0, len(result['thetas']) - theta_fix_count)

    # Count non-fixed OMEGA elements (SE=0 means FIXED)
    if result['omega_se_matrix']:
        for row in result['omega_se_matrix']:
            n_est += sum(1 for s in row if s is not None and s != 0)
    elif result['omega_matrix']:
        # Check for $OMEGA ... FIX in echoed control stream
        omega_fix_count = len(re.findall(r'\$OMEGA[^$]*?FIX', text, re.IGNORECASE))
        if omega_fix_count > 0:
            # All omegas likely fixed
            pass
        else:
            for row in result['omega_matrix']:
                n_est += sum(1 for v in row if v is not None and v != 0)

    # Count non-fixed SIGMA elements (SE=0 means FIXED)
    if result['sigma_se_matrix']:
        for row in result['sigma_se_matrix']:
            n_est += sum(1 for s in row if s is not None and s != 0)
    elif result['sigma_matrix']:
        sigma_fix_count = len(re.findall(r'\$SIGMA[^$]*?FIX', text, re.IGNORECASE))
        if sigma_fix_count > 0:
            pass
        else:
            for row in result['sigma_matrix']:
                n_est += sum(1 for v in row if v is not None and v != 0)

    result['n_estimated_params'] = n_est

    if result['ofv'] is not None and n_est > 0:
        import math
        result['aic'] = result['ofv'] + 2 * n_est
        if result['n_observations'] and result['n_observations'] > 0:
            result['bic'] = result['ofv'] + n_est * math.log(result['n_observations'])

    # --- Subproblem extraction for chained $EST runs ---------------------
    # Each NONMEM estimation step is bounded by '#TBLN:' markers. Extract
    # per-step records so the UI can present all estimation steps, while
    # the top-level fields reflect the FINAL step (what users expect).
    subs = _extract_subproblems(text)
    if subs:
        result['subproblems'] = subs
        final = subs[-1]

        # Override top-level 'final-step' values. Only overwrite when the
        # subproblem actually has a value, so partial extraction doesn't
        # wipe out something that the legacy logic found.
        if final.get('ofv') is not None:
            result['ofv'] = final['ofv']
        if final.get('minimization_successful') is not None:
            result['minimization_successful'] = final['minimization_successful']
        if final.get('minimization_message'):
            result['minimization_message'] = final['minimization_message']
        if final.get('runtime') is not None:
            result['runtime'] = final['runtime']
        # sig_digits: use the last step that actually reported one
        # (IMP evaluation-only steps typically don't report sig_digits;
        # fall back to the most recent step that optimized).
        last_sig = None
        for s in subs:
            if s.get('sig_digits') is not None:
                last_sig = s['sig_digits']
        if last_sig is not None:
            result['sig_digits'] = last_sig
        if final.get('etabar'):
            result['etabar'] = final['etabar']
        if final.get('etabar_se'):
            result['etabar_se'] = final['etabar_se']
        if final.get('etabar_pval'):
            result['etabar_pval'] = final['etabar_pval']
        if final.get('eta_shrinkage'):
            result['eta_shrinkage'] = final['eta_shrinkage']
        if final.get('eps_shrinkage'):
            result['eps_shrinkage'] = final['eps_shrinkage']
        # Per-step thetas/omegas/sigmas: use the final step so the
        # Parameters panel shows the correct values for chained runs.
        if final.get('thetas'):
            result['thetas'] = final['thetas']
        if final.get('omegas'):
            result['omegas'] = final['omegas']
            result['omega_matrix'] = final['omega_matrix']
        if final.get('sigmas'):
            result['sigmas'] = final['sigmas']
            result['sigma_matrix'] = final['sigma_matrix']

        # Build an accurate chain label: 'FO-I -> FOCE-I -> IMP'.
        # ASCII-only arrow for X11/MobaXterm compatibility.
        labels = [s['method_label'] for s in subs if s['method_label']]
        if labels:
            if len(labels) == 1:
                result['estimation_method'] = labels[0]
            else:
                result['estimation_method'] = ' -> '.join(labels)

        # Total estimation time summed across all steps.
        total_rt = sum(s['runtime'] for s in subs if s.get('runtime') is not None)
        if total_rt > 0:
            result['runtime_total'] = total_rt

        # Any step flagged a boundary warning -> top-level boundary True.
        if any(s.get('boundary') for s in subs):
            result['boundary'] = True
    else:
        # Single-$EST run with no '#TBLN:' markers (older NONMEM output
        # or simulation-only runs). Synthesize one subproblem from the
        # top-level fields so UI code can uniformly iterate subproblems.
        if result.get('estimation_method') or result.get('ofv') is not None:
            result['subproblems'] = [{
                'step': 1,
                'method': result.get('estimation_method', ''),
                'method_label': result.get('estimation_method', ''),
                'ofv': result.get('ofv'),
                'minimization_successful': result.get('minimization_successful'),
                'minimization_message': result.get('minimization_message', ''),
                'runtime': result.get('runtime'),
                'sig_digits': result.get('sig_digits'),
                'covariance_step': result.get('covariance_step'),
                'etabar': result.get('etabar', []),
                'etabar_se': result.get('etabar_se', []),
                'etabar_pval': result.get('etabar_pval', []),
                'eta_shrinkage': result.get('eta_shrinkage', []),
                'eps_shrinkage': result.get('eps_shrinkage', []),
                'thetas': result.get('thetas', []),
                'omegas': result.get('omegas', []),
                'sigmas': result.get('sigmas', []),
                'omega_matrix': result.get('omega_matrix', []),
                'sigma_matrix': result.get('sigma_matrix', []),
                'theta_ses': result.get('theta_ses', []),
                'omega_ses': result.get('omega_ses', []),
                'sigma_ses': result.get('sigma_ses', []),
                'omega_se_matrix': result.get('omega_se_matrix', []),
                'sigma_se_matrix': result.get('sigma_se_matrix', []),
                'boundary': result.get('boundary', False),
            }]

    return result


def _extract_block(text, header_pattern):
    """Extract a parameter block following a header."""
    match = re.search(header_pattern, text)
    if not match:
        return None
    start = match.end()
    # Find the next major section header or shrinkage output
    end_match = re.search(
        r'\n\s*(?:OMEGA|SIGMA|THETA|STANDARD ERROR|EIGENVALUES|COVARIANCE|'
        r'ETABAR|ETAShrink|EPSShrink|EtaShrink|EpsShrink|'
        r'Elapsed|Stop Time|\$|#OBJV|1NONLINEAR)',
        text[start:], re.IGNORECASE
    )
    if end_match:
        return text[start:start + end_match.start()]
    return text[start:start + 500]


def _parse_values(block, keep_dots=False):
    """Parse a row of numeric values from a parameter block.
    
    If keep_dots=True, ......... entries are returned as None (for SE alignment).
    """
    values = []
    for line in block.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('+') or line.startswith('-' * 5):
            continue
        # Skip header lines like "TH 1  TH 2  TH 3" or "ETA1  ETA2"
        if re.match(r'^(TH|ET|EP|EPS|SE)\s', line):
            continue
        if re.match(r'^\*+$', line):
            continue
        if keep_dots:
            # Parse token by token to preserve alignment with ......... 
            for token in line.split():
                if token.startswith('.') and '..' in token:
                    values.append(None)
                else:
                    try:
                        values.append(float(token.replace('D', 'E').replace('d', 'e')))
                    except ValueError:
                        pass
        else:
            nums = re.findall(r'[-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?', line)
            for n in nums:
                try:
                    values.append(float(n.replace('D', 'E').replace('d', 'e')))
                except ValueError:
                    pass
    return values


def _parse_matrix_diag(block):
    """Parse diagonal elements from a lower-triangular matrix block."""
    values = []
    row_idx = 0
    for line in block.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('*'):
            continue
        if not line.startswith('+'):
            if re.search(r'(ETA|EPS|EP)\d', line, re.IGNORECASE):
                continue
            if not re.search(r'[-+]?\d+\.\d+', line) and '.........' not in line:
                continue
        if line.startswith('+'):
            line = line[1:].strip()
        # Parse tokens, handling ......... as None
        tokens = []
        for token in line.split():
            if token.startswith('.') and '..' in token:
                tokens.append(None)
            else:
                try:
                    tokens.append(float(token.replace('D', 'E').replace('d', 'e')))
                except ValueError:
                    pass
        if tokens:
            row_idx += 1
            if len(tokens) >= row_idx:
                values.append(tokens[row_idx - 1])
            elif tokens:
                values.append(tokens[-1])
    return values


def _parse_matrix_full(block):
    """Parse full lower-triangular matrix from a NONMEM matrix block.
    Returns a list of rows with None for ......... entries.
    """
    rows = []
    for line in block.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('*'):
            continue
        if not line.startswith('+'):
            if re.search(r'(ETA|EPS|EP)\d', line, re.IGNORECASE):
                continue
            if not re.search(r'[-+]?\d+\.\d+', line) and '.........' not in line:
                continue
        if line.startswith('+'):
            line = line[1:].strip()
        tokens = []
        for token in line.split():
            if token.startswith('.') and '..' in token:
                tokens.append(None)
            else:
                try:
                    tokens.append(float(token.replace('D', 'E').replace('d', 'e')))
                except ValueError:
                    pass
        if tokens:
            rows.append(tokens)
    return rows


def find_runs(base_dir):
    """Scan a directory for NONMEM run results (.lst files)."""
    runs = []
    base = Path(base_dir)
    if not base.exists():
        return runs

    seen_lst = set()

    # Strategy 1: .lst files directly in the base directory
    for lst in sorted(base.glob('*.lst')):
        run_info = parse_lst(str(lst))
        run_info['run_name'] = lst.stem
        run_info['directory'] = str(base)
        run_info.pop('raw_text', None)
        runs.append(run_info)
        seen_lst.add(lst.stem)

    # Strategy 2: .lst files in subdirectories (PSN execute style)
    for item in sorted(base.iterdir()):
        if item.is_dir():
            lst_files = list(item.glob('*.lst'))
            if lst_files:
                for lst in lst_files:
                    # Skip if we already found this run name in root
                    if lst.stem in seen_lst:
                        continue
                    run_info = parse_lst(str(lst))
                    run_info['run_name'] = item.name
                    run_info['directory'] = str(item)
                    run_info.pop('raw_text', None)
                    runs.append(run_info)

    return runs


def read_table_file(filepath, max_rows=5000):
    """Read a NONMEM table file or CSV and return (column_names, rows).

    Format detection follows the xpose approach: inspect the first data row
    for a scientific-notation pattern and pick the delimiter accordingly.
    Supports three formats:
      - NONMEM whitespace-delimited table (default)
      - CSV with '.' decimal (English locale)
      - CSV with ',' decimal and ';' delimiter (European/csv2 locale)

    Values matching the column header names are treated as NA (handles
    NONMEM's repeated-header rows in firstonly tables).

    Returns (None, None) on any read or format error.
    """
    if not os.path.exists(filepath):
        return None, None

    try:
        with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            raw_lines = f.readlines()
    except OSError:
        return None, None

    # Locate header and first data line, skipping 'TABLE NO' banners and blanks.
    header_line = None
    header_idx = None
    data_start_idx = None
    for i, line in enumerate(raw_lines):
        s = line.strip()
        if not s:
            continue
        if s.startswith('TABLE NO'):
            continue
        if header_line is None:
            header_line = s
            header_idx = i
            continue
        # First non-header, non-banner line = first data row.
        data_start_idx = i
        break

    if header_line is None:
        return None, None

    # Determine delimiter by inspecting the first data row (xpose approach,
    # relaxed to accept plain decimals — xpose's regex assumes NONMEM
    # scientific notation but real-world files sometimes strip it).
    #   csv2 (European):  ';' delimiter with ',' decimals
    #   csv  (English):   ',' delimiter with '.' decimals
    #   table (default):  whitespace delimiter
    probe = raw_lines[data_start_idx].rstrip('\n') if data_start_idx is not None else ''

    # Scientific-notation-first checks (xpose style, strictest):
    if re.search(r'\d,\d+[eEdD][+-]?\d+\s*;', probe):
        fmt = 'csv2'
    elif re.search(r'\d\.\d+[eEdD][+-]?\d+\s*,', probe):
        fmt = 'csv'
    # Fallback for plain-decimal CSV files:
    elif ';' in probe and re.search(r'\d,\d', probe):
        fmt = 'csv2'
    elif ',' in probe and not re.search(r'\s{2,}', probe):
        fmt = 'csv'
    else:
        fmt = 'table'

    # Split header according to chosen format.
    if fmt == 'csv2':
        header = [h.strip() for h in header_line.split(';')]
    elif fmt == 'csv':
        header = [h.strip() for h in header_line.split(',')]
    else:
        header = header_line.split()

    header = [h for h in header if h]  # drop empties from trailing delimiters
    if not header:
        return None, None

    # Values that should become None (NONMEM's repeated headers in firstonly tables).
    na_tokens = set(header) | {'NA', 'N/A', '.', ''}

    def _to_num(v, allow_comma_decimal=False):
        if v is None:
            return None
        t = v.strip()
        if t in na_tokens:
            return None
        if allow_comma_decimal:
            t = t.replace(',', '.')
        # Fortran D exponent -> E
        t = t.replace('D', 'E').replace('d', 'e')
        try:
            return float(t)
        except ValueError:
            return v  # keep original string if not numeric

    rows = []
    for i in range(data_start_idx, len(raw_lines)):
        if max_rows is not None and len(rows) >= max_rows:
            break
        line = raw_lines[i].rstrip('\n')
        stripped = line.strip()
        if not stripped:
            continue
        # Skip any embedded TABLE NO banner (multi-problem firstonly tables).
        if stripped.startswith('TABLE NO'):
            continue

        if fmt == 'csv2':
            parts = [p.strip() for p in stripped.split(';')]
            row = [_to_num(p, allow_comma_decimal=True) for p in parts]
        elif fmt == 'csv':
            # Use csv reader for this single line (handles quoted fields).
            import csv as _csv
            try:
                parts = next(_csv.reader([stripped]))
            except Exception:
                parts = stripped.split(',')
            row = [_to_num(p, allow_comma_decimal=False) for p in parts]
        else:
            parts = stripped.split()
            row = [_to_num(p, allow_comma_decimal=False) for p in parts]

        # Only accept rows that align with header width and have at least
        # one non-None value (drops repeated headers in firstonly tables).
        if len(row) == len(header) and any(v is not None for v in row):
            rows.append(row)

    return header, rows


def classify_table_columns(header):
    """Classify NONMEM table columns by role. Returns {col_name: type_str}.

    Ports xpose's index_table logic. Types:
      'id'     — subject identifier
      'dv'     — observed dependent variable
      'idv'    — independent variable (time)
      'occ'    — occasion
      'dvid'   — DV indicator (multi-response)
      'amt'    — dose amount
      'mdv'    — missing DV flag
      'evid'   — event identifier
      'ipred'  — individual predictions
      'pred'   — population predictions
      'res'    — residuals (RES/WRES/CWRES/IWRES/EWRES/NPDE)
      'eta'    — empirical Bayes estimates (ETA1, ET1, PHI1)
      'cmt'    — compartment amount (A1, A2, ...)
      'cov'    — everything else (covariate/parameter/unknown)

    Callers can use this to auto-select plot axes, categorical filters, etc.
    """
    result = {}
    for col in header:
        if not col:
            continue
        cu = col.upper().strip()
        if cu == 'ID':
            t = 'id'
        elif cu == 'DV':
            t = 'dv'
        elif cu in ('TIME', 'TAD', 'TAFD'):
            t = 'idv'
        elif cu == 'OCC':
            t = 'occ'
        elif cu == 'DVID':
            t = 'dvid'
        elif cu == 'AMT':
            t = 'amt'
        elif cu == 'MDV':
            t = 'mdv'
        elif cu == 'EVID':
            t = 'evid'
        elif cu in ('IPRED', 'IPRE', 'IPREDI'):
            t = 'ipred'
        elif cu in ('PRED', 'NPRED'):
            t = 'pred'
        elif cu in ('RES', 'WRES', 'CWRES', 'IWRES', 'EWRES', 'NPDE', 'CIWRES'):
            t = 'res'
        elif re.match(r'^(ETA|ET|PHI)\d+$', cu):
            t = 'eta'
        elif re.match(r'^A\d+$', cu):
            t = 'cmt'
        else:
            t = 'cov'
        result[col] = t
    return result


def inject_estimates(control_text, lst_path, jitter=0):
    """Replace initial estimates in a control stream with final estimates from .lst.
    If jitter > 0, perturb non-fixed parameters by ±jitter fraction (e.g. 0.2 = ±20%).
    Only THETAs and diagonal OMEGA/SIGMA are jittered. Off-diagonals and FIX'd params are untouched.
    """
    import random
    result = parse_lst(lst_path)
    if not result['thetas'] and not result['omegas']:
        return control_text

    def _jitter_val(val, low=None, high=None, must_be_positive=False):
        """Apply jitter to a value, respecting bounds."""
        if jitter <= 0 or val == 0:
            return val
        factor = 1.0 + random.uniform(-jitter, jitter)
        new_val = val * factor
        if must_be_positive and new_val <= 0:
            new_val = abs(val) * 0.01  # small positive fallback
        if low is not None:
            try:
                low_f = float(low)
                if new_val <= low_f:
                    new_val = low_f + abs(val) * 0.01
            except (ValueError, TypeError):
                pass
        if high is not None:
            try:
                high_f = float(high)
                if new_val >= high_f:
                    new_val = high_f - abs(val) * 0.01
            except (ValueError, TypeError):
                pass
        return new_val

    modified = control_text

    # Replace THETA values
    if result['thetas']:
        idx = [0]  # mutable counter

        def replace_theta_val(m):
            if idx[0] >= len(result['thetas']):
                return m.group(0)
            val = result['thetas'][idx[0]]
            idx[0] += 1
            full = m.group(0)
            is_fix = bool(re.search(r'FIX', full, re.IGNORECASE))
            fix_str = ' FIX' if is_fix else ''
            # Bracketed with bounds: (low, init) or (low, init, high)
            bracket = re.match(r'\(([^,]+),\s*[^,)]+(?:,\s*([^)]+))?\)', full)
            if bracket:
                low = bracket.group(1).strip()
                high = bracket.group(2)
                if not is_fix and jitter > 0:
                    val = _jitter_val(val, low=low, high=high.strip() if high else None)
                if high:
                    return f'({low}, {val:.6g}, {high.strip()}){fix_str}'
                return f'({low}, {val:.6g}){fix_str}'
            if not is_fix and jitter > 0:
                val = _jitter_val(val)
            return f'{val:.6g}{fix_str}'

        # Find $THETA block(s) and replace values
        def process_theta_block(m):
            block = m.group(0)
            # Replace each value/bracketed init
            processed = re.sub(
                r'\([^)]+\)(?:\s*FIX(?:ED)?)?|(?<=\s)[-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?(?:\s*FIX(?:ED)?)?',
                replace_theta_val, block
            )
            return processed

        modified = re.sub(
            r'\$THETA\b[^\$]*',
            process_theta_block, modified, flags=re.IGNORECASE
        )

    # Replace OMEGA diagonal values
    if result['omegas']:
        oidx = [0]

        def replace_omega_val(m):
            if oidx[0] >= len(result['omegas']):
                return m.group(0)
            val = result['omegas'][oidx[0]]
            oidx[0] += 1
            full = m.group(0)
            is_fix = bool(re.search(r'FIX', full, re.IGNORECASE))
            fix_str = ' FIX' if is_fix else ''
            if not is_fix and jitter > 0:
                val = _jitter_val(val, must_be_positive=True)
            return f'{val:.6g}{fix_str}'

        def process_omega_block(m):
            block = m.group(0)
            lines = block.split('\n')
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith(';'):
                    new_lines.append(line)
                elif re.match(r'^\$(OMEGA)\b', stripped, re.IGNORECASE):
                    # Value might be on the same line as $OMEGA: "$OMEGA 0.09"
                    after_keyword = re.sub(r'^\$OMEGA\b\s*', '', stripped, flags=re.IGNORECASE)
                    if after_keyword and re.search(r'[-+]?\d*\.?\d+', after_keyword):
                        # Has a numeric value — replace it
                        prefix = stripped[:len(stripped) - len(after_keyword)]
                        new_val = re.sub(
                            r'[-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?(?:\s*FIX(?:ED)?)?',
                            replace_omega_val, after_keyword, count=1
                        )
                        new_lines.append(prefix + new_val)
                    else:
                        new_lines.append(line)
                elif re.match(r'^(BLOCK|SAME|DIAGONAL)\b', stripped, re.IGNORECASE):
                    new_lines.append(line)
                else:
                    new_line = re.sub(
                        r'[-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?(?:\s*FIX(?:ED)?)?',
                        replace_omega_val, line, count=1
                    )
                    new_lines.append(new_line)
            return '\n'.join(new_lines)

        modified = re.sub(
            r'\$OMEGA\b[^\$]*',
            process_omega_block, modified, flags=re.IGNORECASE
        )

    # Replace SIGMA diagonal values
    if result['sigmas']:
        sidx = [0]

        def replace_sigma_val(m):
            if sidx[0] >= len(result['sigmas']):
                return m.group(0)
            val = result['sigmas'][sidx[0]]
            sidx[0] += 1
            full = m.group(0)
            is_fix = bool(re.search(r'FIX', full, re.IGNORECASE))
            fix_str = ' FIX' if is_fix else ''
            if not is_fix and jitter > 0:
                val = _jitter_val(val, must_be_positive=True)
            return f'{val:.6g}{fix_str}'

        def process_sigma_block(m):
            block = m.group(0)
            lines = block.split('\n')
            new_lines = []
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith(';'):
                    new_lines.append(line)
                elif re.match(r'^\$(SIGMA)\b', stripped, re.IGNORECASE):
                    after_keyword = re.sub(r'^\$SIGMA\b\s*', '', stripped, flags=re.IGNORECASE)
                    if after_keyword and re.search(r'[-+]?\d*\.?\d+', after_keyword):
                        prefix = stripped[:len(stripped) - len(after_keyword)]
                        new_val = re.sub(
                            r'[-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?(?:\s*FIX(?:ED)?)?',
                            replace_sigma_val, after_keyword, count=1
                        )
                        new_lines.append(prefix + new_val)
                    else:
                        new_lines.append(line)
                elif re.match(r'^(BLOCK|SAME)\b', stripped, re.IGNORECASE):
                    new_lines.append(line)
                else:
                    new_line = re.sub(
                        r'[-+]?\d*\.?\d+(?:[eEdD][-+]?\d+)?(?:\s*FIX(?:ED)?)?',
                        replace_sigma_val, line, count=1
                    )
                    new_lines.append(new_line)
            return '\n'.join(new_lines)

        modified = re.sub(
            r'\$SIGMA\b[^\$]*',
            process_sigma_block, modified, flags=re.IGNORECASE
        )

    return modified


def parse_nmtran_errors(base_dir, stem):
    """Parse NMTRAN errors from FMSG, PRDERR, or .lst file."""
    errors = []

    for search_dir in [os.path.join(base_dir, stem), base_dir]:
        for fname in ['FMSG', 'PRDERR']:
            fpath = os.path.join(search_dir, fname)
            if os.path.isfile(fpath):
                with open(fpath, 'r', encoding='utf-8-sig', errors='replace') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line == '0':
                            continue
                        is_err = bool(re.search(
                            r'ERROR|WARNING|TERMINATED|UNABLE|CANNOT|ILLEGAL',
                            line, re.IGNORECASE
                        ))
                        errors.append({
                            'type': 'error' if is_err else 'info',
                            'message': line
                        })
                if errors:
                    return errors

    # Check .lst for NMTRAN messages
    lst_path = os.path.join(base_dir, stem + '.lst')
    if os.path.isfile(lst_path):
        with open(lst_path, 'r', encoding='utf-8-sig', errors='replace') as f:
            text = f.read()[:5000]
        for line in text.split('\n'):
            if re.search(r'ERROR|WARNING', line, re.IGNORECASE):
                errors.append({'type': 'error', 'message': line.strip()})

    return errors


def extract_param_names(control_text):
    """Extract parameter names and FIX status from control stream.
    
    Returns dict with 'theta_names', 'omega_names', 'sigma_names' (lists of str)
    and 'theta_fixed', 'omega_fixed', 'sigma_fixed' (lists of bool).
    """
    result = {
        'theta_names': [], 'omega_names': [], 'sigma_names': [],
        'theta_units': [], 'omega_units': [], 'sigma_units': [],
        'theta_fixed': [], 'omega_fixed': [], 'sigma_fixed': [],
    }
    
    if not control_text:
        return result
    
    lines = control_text.split('\n')
    current_block = None

    for line in lines:
        stripped = line.strip()
        
        if re.match(r'^\$THETA\b', stripped, re.IGNORECASE):
            current_block = 'theta'
            remainder = re.sub(r'^\$THETA\s*', '', stripped, flags=re.IGNORECASE)
            if remainder and _has_numeric_value(remainder):
                result['theta_names'].append(_extract_comment_name(remainder))
                result['theta_units'].append(_extract_comment_unit(remainder))
                result['theta_fixed'].append(_is_fixed(remainder))
            continue
        elif re.match(r'^\$OMEGA\b', stripped, re.IGNORECASE):
            current_block = 'omega'
            remainder = re.sub(r'^\$OMEGA\s*', '', stripped, flags=re.IGNORECASE)
            if remainder:
                if re.match(r'^BLOCK\b', remainder, re.IGNORECASE):
                    # Check if the BLOCK line itself says FIX
                    if _is_fixed(remainder):
                        # All elements in this block will be fixed — handled per-line below
                        pass
                    continue
                if _has_numeric_value(remainder):
                    result['omega_names'].append(_extract_comment_name(remainder))
                    result['omega_units'].append(_extract_comment_unit(remainder))
                    result['omega_fixed'].append(_is_fixed(remainder))
            continue
        elif re.match(r'^\$SIGMA\b', stripped, re.IGNORECASE):
            current_block = 'sigma'
            remainder = re.sub(r'^\$SIGMA\s*', '', stripped, flags=re.IGNORECASE)
            if remainder:
                if re.match(r'^BLOCK\b', remainder, re.IGNORECASE):
                    continue
                if _has_numeric_value(remainder):
                    result['sigma_names'].append(_extract_comment_name(remainder))
                    result['sigma_units'].append(_extract_comment_unit(remainder))
                    result['sigma_fixed'].append(_is_fixed(remainder))
            continue
        elif re.match(r'^\$', stripped):
            current_block = None
            continue
        
        if current_block and stripped and not stripped.startswith(';'):
            if re.match(r'^(BLOCK|SAME|DIAGONAL|BAND|CHOLESKY)\b', stripped, re.IGNORECASE):
                continue
            
            if _has_numeric_value(stripped):
                result[current_block + '_names'].append(_extract_comment_name(stripped))
                result[current_block + '_units'].append(_extract_comment_unit(stripped))
                result[current_block + '_fixed'].append(_is_fixed(stripped))
    
    return result


def _extract_comment_name(line):
    """Extract parameter name from the comment portion of a line."""
    if ';' not in line:
        return ''
    comment = line.split(';', 1)[1].strip()
    # Remove [unit] bracket if present — we extract it separately
    comment = re.sub(r'\[.*?\]\s*', '', comment).strip()
    comment = comment[:50].strip()
    return comment


def _extract_comment_unit(line):
    """Extract unit from [unit] in comment portion of a line."""
    if ';' not in line:
        return ''
    comment = line.split(';', 1)[1].strip()
    m = re.search(r'\[([^\]]+)\]', comment)
    return m.group(1).strip() if m else ''


def _has_numeric_value(line):
    """Check if a line contains a numeric value (initial estimate)."""
    # Remove comment
    code = line.split(';')[0] if ';' in line else line
    # Look for numbers (possibly in brackets)
    return bool(re.search(r'[-+]?\d*\.?\d+', code))


def _is_fixed(line):
    """Check if a line contains FIX or FIXED keyword (before the comment)."""
    code = line.split(';')[0] if ';' in line else line
    return bool(re.search(r'\bFIX(?:ED)?\b', code, re.IGNORECASE))


def parse_ext_file(ext_path):
    """Parse a NONMEM .ext file for OFV and parameter convergence history."""
    if not os.path.isfile(ext_path):
        return None

    with open(ext_path, 'r', encoding='utf-8-sig', errors='replace') as f:
        lines = f.readlines()

    header = None
    rows = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('TABLE'):
            header = None
            rows = []  # Reset for each estimation step — keep last
            continue
        if header is None:
            header = stripped.split()
            continue
        parts = stripped.split()
        if len(parts) == len(header):
            row = {}
            for h, v in zip(header, parts):
                try:
                    row[h] = float(v)
                except ValueError:
                    row[h] = v
            # Skip final summary lines (ITERATION < 0 except -1000000000)
            it = row.get('ITERATION', 0)
            if isinstance(it, float) and it < -1e8:
                continue
            rows.append(row)

    if not header or not rows:
        return None

    return {
        'columns': header,
        'data': rows,
        'n_iterations': len(rows),
    }


def extract_table_files(control_text):
    """Extract $TABLE FILE= names from a NONMEM control stream.

    Returns dict:
      table_files: list of FILE= values (e.g. ['sdtab001', 'patab001'])
      runno: auto-detected run number from sdtab name (e.g. '001'), or ''
    """
    result = {'table_files': [], 'runno': ''}
    if not control_text:
        return result

    # $TABLE can span multiple lines; collect each $TABLE block
    # Match FILE=name or FILE="name" or FILE='name'
    for m in re.finditer(r'\$TABLE\b(.*?)(?=\$|\Z)', control_text, re.IGNORECASE | re.DOTALL):
        block = m.group(1)
        # Remove comments
        lines = block.split('\n')
        clean = ' '.join(line.split(';')[0] for line in lines)
        # Find FILE= value
        fm = re.search(r'FILE\s*=\s*["\']?([^\s"\']+)', clean, re.IGNORECASE)
        if fm:
            result['table_files'].append(fm.group(1))

    # Auto-detect runno from sdtab file name
    for f in result['table_files']:
        basename = f.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
        sm = re.match(r'sdtab(\d+)', basename, re.IGNORECASE)
        if sm:
            result['runno'] = sm.group(1)
            break

    # If no sdtab, try patab, catab, cotab
    if not result['runno']:
        for f in result['table_files']:
            basename = f.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
            sm = re.match(r'(?:patab|catab|cotab|mutab)(\d+)', basename, re.IGNORECASE)
            if sm:
                result['runno'] = sm.group(1)
                break

    return result


def parse_phi_file(filepath):
    """Parse a NONMEM .phi file containing individual ETAs and OBJ values.

    Returns dict:
      ids: list of subject IDs
      obj: list of individual OBJ contributions
      etas: dict of {eta_name: [values]} for each ETA column
    """
    result = {'ids': [], 'obj': [], 'etas': {}}
    if not os.path.isfile(filepath):
        return result

    try:
        with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            lines = f.readlines()
    except Exception:
        return result

    header = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('TABLE'):
            header = None
            continue
        parts = stripped.split()
        if 'SUBJECT_NO' in stripped.upper():
            header = parts
            continue
        if header and len(parts) >= len(header):
            row = {}
            for i, col in enumerate(header):
                try:
                    row[col.upper()] = float(parts[i])
                except (ValueError, IndexError):
                    row[col.upper()] = parts[i] if i < len(parts) else None

            if 'ID' in row:
                result['ids'].append(row['ID'])
            elif 'SUBJECT_NO' in row:
                result['ids'].append(row['SUBJECT_NO'])

            if 'OBJ' in row:
                result['obj'].append(row['OBJ'])

            for col in header:
                cu = col.upper()
                if cu.startswith('ETA(') or cu.startswith('ETA_'):
                    if cu not in result['etas']:
                        result['etas'][cu] = []
                    result['etas'][cu].append(row.get(cu, None))

    return result
