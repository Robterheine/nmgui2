try:
    import numpy as np
    HAS_NP = True
except ImportError:
    HAS_NP = False


def fmt_ofv(v):
    return '' if v is None else f'{v:.3f}'


def fmt_num(v, d=4):
    if v is None: return ''
    return f'{v:.{d}g}' if isinstance(v, float) else str(v)


def fmt_rse(est, se):
    if est is None or se is None or abs(est) < 1e-12: return ''
    return f'{abs(se/est)*100:.1f}%'


def loess(x, y, frac=0.4, n_out=80):
    if not HAS_NP: return None, None
    try:
        x = np.asarray(x, float); y = np.asarray(y, float)
        ok = np.isfinite(x) & np.isfinite(y)
        x, y = x[ok], y[ok]
        if len(x) < 6: return None, None
        order = np.argsort(x); xs, ys = x[order], y[order]
        k = max(5, int(frac * len(xs)))
        xo = np.linspace(xs[0], xs[-1], n_out); yo = np.empty(n_out)
        for i, xi in enumerate(xo):
            d = np.abs(xs - xi); idx = np.argsort(d)[:k]
            h = d[idx[-1]] or 1e-10
            w = np.clip(1-(d[idx]/h)**3, 0, None)**3
            A = np.column_stack([np.ones(k), xs[idx]])
            try:
                W = np.diag(w)
                b = np.linalg.lstsq(W @ A, W @ ys[idx], rcond=None)[0]
                yo[i] = b[0] + b[1]*xi
            except Exception:
                yo[i] = np.average(ys[idx], weights=w+1e-12)
        return xo, yo
    except Exception:
        return None, None
