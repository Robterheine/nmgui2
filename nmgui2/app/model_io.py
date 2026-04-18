import re, logging
from pathlib import Path

_log = logging.getLogger(__name__)


def _parse_param_names_from_mod(mod_path: str) -> dict:
    """
    Re-parse the .mod file to produce correctly-aligned omega/sigma/theta name lists.
    Returns dict with keys: theta_names, omega_names, sigma_names.

    The parser.py can return misaligned omega_names when BLOCK(n) SAME blocks are
    present, because SAME blocks contribute values (positions) but no comments.
    This function reads the block structure directly and builds the correct mapping.
    """
    try:
        text = Path(mod_path).read_text('utf-8', errors='replace')
    except Exception:
        return {}

    def _extract_comment(token: str) -> str:
        m = re.search(r';([^\n]*)', token)
        return m.group(1).strip() if m else ''

    def _parse_block(raw: str, block_name: str):
        """Parse one $THETA/$OMEGA/$SIGMA block, return list of (value, name) pairs."""
        results = []
        # SAME block: repeat the size of the previous block, no new names
        if re.search(r'\bSAME\b', raw, re.IGNORECASE):
            return None  # sentinel meaning "SAME as previous"

        is_block = re.search(r'BLOCK\s*\(\s*(\d+)\s*\)', raw, re.IGNORECASE)
        if is_block:
            dim = int(is_block.group(1))
            # Lower-triangular: dim*(dim+1)/2 elements
            # We only want the diagonal (dim elements) for display
            # Find all numeric tokens with optional comment
            tokens = re.findall(r'([\d\.Ee\+\-]+(?:\s*FIX)?)\s*(?:;([^\n]*))?', raw)
            n_lower = dim*(dim+1)//2
            diag_indices = []  # 0-based positions of diagonal elements in lower triangle
            pos = 0
            for row in range(dim):
                for col in range(row+1):
                    if col == row:
                        diag_indices.append(pos)
                    pos += 1
            for idx, tok_idx in enumerate(diag_indices):
                if tok_idx < len(tokens):
                    nm = tokens[tok_idx][1].strip() if tokens[tok_idx][1] else ''
                    results.append(nm)
                else:
                    results.append('')
            return results

        # Simple diagonal: each value on its own line with optional comment
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith('$') or line.startswith(';'): continue
            if re.match(r'[\d\.Ee\+\-\(]', line):
                nm = _extract_comment(line)
                results.append(nm)
        return results

    def _parse_all_blocks(keyword: str):
        """Collect all $KEYWORD blocks and build a flat name list."""
        pattern = re.compile(
            r'\$' + keyword + r'\b(.*?)(?=\$[A-Z]|\Z)',
            re.DOTALL | re.IGNORECASE)
        names = []
        last_block_names = []
        for m in pattern.finditer(text):
            raw = m.group(1)
            result = _parse_block(raw, keyword)
            if result is None:
                # SAME — repeat last block structure with empty names
                names.extend([''] * len(last_block_names))
            else:
                names.extend(result)
                last_block_names = result
        return names

    return {
        'theta_names': _parse_all_blocks('THETA'),
        'omega_names': _parse_all_blocks('OMEGA'),
        'sigma_names': _parse_all_blocks('SIGMA'),
    }


def _align_param_names(model: dict) -> dict:
    """
    Return a copy of model with omega/sigma/theta names correctly aligned
    to their values. Reads the .mod file if name lists are misaligned.
    """
    mod_path = model.get('path', '')
    if not mod_path or not Path(mod_path).is_file():
        return model

    needs_fix = False
    for block, val_key, name_key in [
        ('theta', 'thetas', 'theta_names'),
        ('omega', 'omegas', 'omega_names'),
        ('sigma', 'sigmas', 'sigma_names'),
    ]:
        vals  = model.get(val_key, [])
        names = model.get(name_key, [])
        if vals and len(names) != len(vals):
            needs_fix = True; break

    if not needs_fix:
        return model

    fresh = _parse_param_names_from_mod(mod_path)
    if not fresh:
        return model

    patched = dict(model)
    for val_key, name_key, fresh_key in [
        ('thetas', 'theta_names', 'theta_names'),
        ('omegas', 'omega_names', 'omega_names'),
        ('sigmas', 'sigma_names', 'sigma_names'),
    ]:
        vals       = model.get(val_key, [])
        fresh_list = fresh.get(fresh_key, [])
        if len(fresh_list) >= len(vals):
            patched[name_key] = fresh_list[:len(vals)]
        elif fresh_list:
            # Pad with empty strings
            patched[name_key] = fresh_list + [''] * (len(vals) - len(fresh_list))
    return patched
