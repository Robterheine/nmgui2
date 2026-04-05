"""
NONMEM .lst file parser.
Extracts key results: OFV, minimization status, parameter estimates,
standard errors, condition number, shrinkage, and runtime.
"""

import re
import os
from pathlib import Path


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
    # SAEM/IMP: #OBJV line
    objv_matches = re.findall(r'#OBJV:\*+\s*([-\d.]+(?:E[+-]?\d+)?)', text)
    # SAEM: LIKELIHOOD line
    ll_matches = re.findall(
        r'-2\s*LOG(?:\s*LIKE\w*)?\s*[:=]\s*([-\d.]+(?:E[+-]?\d+)?)',
        text, re.IGNORECASE
    )
    # IMP/ITS: OBJECTIVE FUNCTION VALUE at final step
    imp_ofv = re.findall(
        r'OBJECTIVE FUNCTION VALUE[^:]*:\s*([-\d.]+(?:E[+-]?\d+)?)',
        text, re.IGNORECASE
    )

    all_ofv = ofv_matches + objv_matches + ll_matches + imp_ofv
    if all_ofv:
        try:
            result['ofv'] = float(all_ofv[-1])
        except ValueError:
            pass

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

    # ETABAR, SE, and P-values
    etabar_match = re.search(
        r'ETABAR:\s+(.*?)\n\s*SE:\s+(.*?)\n.*?P\s*VAL\.?:\s+(.*?)\n',
        text, re.DOTALL
    )
    # Try simpler line-by-line approach
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
            pass

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
    # Count non-fixed THETAs (SE is not None)
    if result['theta_ses']:
        n_est += sum(1 for s in result['theta_ses'] if s is not None)
    elif result['thetas']:
        # No COV: try to detect FIX'd THETAs from echoed control stream
        theta_fix_count = len(re.findall(r'\$THETA[^;$]*?FIX', text, re.IGNORECASE))
        n_est += max(0, len(result['thetas']) - theta_fix_count)

    # Count non-fixed OMEGA elements
    if result['omega_se_matrix']:
        for row in result['omega_se_matrix']:
            n_est += sum(1 for s in row if s is not None)
    elif result['omega_matrix']:
        # Check for $OMEGA ... FIX in echoed control stream
        omega_fix_count = len(re.findall(r'\$OMEGA[^$]*?FIX', text, re.IGNORECASE))
        if omega_fix_count > 0:
            # All omegas likely fixed
            pass
        else:
            for row in result['omega_matrix']:
                n_est += sum(1 for v in row if v is not None and v != 0)

    # Count non-fixed SIGMA elements
    if result['sigma_se_matrix']:
        for row in result['sigma_se_matrix']:
            n_est += sum(1 for s in row if s is not None)
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
    """Read a NONMEM table file or CSV and return column names + data."""
    if not os.path.exists(filepath):
        return None, None

    with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
        lines = f.readlines()

    # Skip NONMEM table headers (TABLE NO. lines)
    data_lines = []
    header = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('TABLE NO') or not stripped:
            continue
        if header is None:
            header = stripped.split()
            continue
        data_lines.append(stripped)
        if len(data_lines) >= max_rows:
            break

    if header is None:
        return None, None

    # Detect delimiter
    if ',' in lines[0] and not lines[0].strip().startswith('TABLE'):
        # CSV file — re-parse
        with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
            import csv
            reader = csv.reader(f)
            header = next(reader, None)
            data_lines = []
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                data_lines.append(row)
            rows = []
            for row in data_lines:
                r = []
                for val in row:
                    try:
                        r.append(float(val))
                    except ValueError:
                        r.append(val)
                rows.append(r)
            return header, rows

    rows = []
    for line in data_lines:
        parts = line.split()
        row = []
        for p in parts:
            try:
                row.append(float(p))
            except ValueError:
                row.append(p)
        if len(row) == len(header):
            rows.append(row)

    return header, rows


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
