import os, subprocess, shutil, logging
from pathlib import Path
from .constants import IS_WIN, IS_MAC, HOME

_log = logging.getLogger(__name__)


def get_login_env():
    env = os.environ.copy()
    if not IS_WIN:
        try:
            shell = os.environ.get('SHELL', '/bin/sh')
            r = subprocess.run([shell, '-l', '-c', 'echo $PATH'],
                               capture_output=True, text=True, timeout=5)
            if r.stdout.strip(): env['PATH'] = r.stdout.strip()
        except Exception as e: _log.debug(f'Could not get login shell PATH: {e}')
    return env


def find_tool(name):
    import shutil as sh
    t = sh.which(name)
    if t: return t
    if not IS_WIN:
        try:
            shell = os.environ.get('SHELL', '/bin/sh')
            r = subprocess.run([shell, '-l', '-c', f'which {name}'],
                               capture_output=True, text=True, timeout=5)
            found = r.stdout.strip()
            if found and Path(found).is_file(): return found
        except Exception as e: _log.debug(f'Could not find tool {name}: {e}')
    return None


def launch_rstudio(directory: str, rstudio_path: str = '') -> str:
    """Launch RStudio with directory as project. Returns error string or ''."""
    import shutil as _sh
    # Find RStudio
    rs = None
    if rstudio_path and Path(rstudio_path).exists():
        rs = rstudio_path
    if not rs:
        rs = _sh.which('rstudio') or _sh.which('RStudio')
    if not rs and IS_MAC:
        for cand in ['/Applications/RStudio.app',
                     str(HOME / 'Applications/RStudio.app')]:
            if Path(cand).exists(): rs = cand; break
    if not rs and IS_WIN:
        import glob as _gl
        for pat in [r'%LOCALAPPDATA%\Programs\Posit\RStudio\rstudio.exe',
                    r'%PROGRAMFILES%\Posit\RStudio\rstudio.exe',
                    r'%PROGRAMFILES%\RStudio\bin\rstudio.exe']:
            hits = _gl.glob(os.path.expandvars(pat))
            if hits: rs = hits[0]; break
    if not rs:
        return 'RStudio not found. Set the path in Settings → RStudio path.'
    # Create .Rproj if needed
    rproj_files = list(Path(directory).glob('*.Rproj'))
    if rproj_files:
        rproj = str(rproj_files[0])
    else:
        name  = Path(directory).name
        rproj = str(Path(directory) / (name + '.Rproj'))
        try:
            Path(rproj).write_text(
                'Version: 1.0\n\nRestoreWorkspace: Default\n'
                'SaveWorkspace: Default\nAlwaysSaveHistory: Default\n')
        except OSError as e:
            return f'Could not create .Rproj file: {e}'
    try:
        if IS_MAC:
            subprocess.Popen(['open', '-a', rs, rproj])
        else:
            subprocess.Popen([rs, rproj])
        return ''
    except Exception as e:
        return str(e)


def _find_rscript():
    import shutil as sh
    r = sh.which('Rscript')
    if r: return r
    if not IS_WIN:
        try:
            shell = os.environ.get('SHELL', '/bin/sh')
            rv = subprocess.run([shell, '-l', '-c', 'which Rscript'],
                                capture_output=True, text=True, timeout=5)
            found = rv.stdout.strip()
            if found and Path(found).is_file(): return found
        except Exception as e: _log.debug(f'Could not find Rscript: {e}')
    return None


def _sanitize_r(s):
    return s.replace('\\', '/').replace('"', '\\"')


def _check_r_packages():
    rscript = _find_rscript()
    if not rscript: return False, {}
    try:
        _wkw = {'creationflags': subprocess.CREATE_NO_WINDOW} if IS_WIN else {}
        rv = subprocess.run(
            [rscript, '-e',
             'pkgs<-rownames(installed.packages());'
             'cat(paste(c("vpc","xpose","xpose4")[c("vpc","xpose","xpose4")%in%pkgs],collapse=","))'],
            capture_output=True, text=True, timeout=15, env=get_login_env(), **_wkw)
        installed = [p.strip() for p in rv.stdout.strip().split(',') if p.strip()]
        avail = {p: p in installed for p in ('vpc', 'xpose', 'xpose4')}
        return True, avail
    except Exception:
        return False, {}


def _check_psn_tools():
    """Check which PsN tools are available on PATH."""
    import shutil as sh
    available = {}
    for tool in ('bootstrap', 'sir', 'psn'):
        available[tool] = sh.which(tool) is not None
    return available
