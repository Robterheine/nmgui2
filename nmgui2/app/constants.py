import sys, threading
from pathlib import Path

IS_WIN  = sys.platform == 'win32'
IS_MAC  = sys.platform == 'darwin'
HOME    = Path.home()
CONFIG_DIR = HOME / '.nmgui'
try:
    CONFIG_DIR.mkdir(exist_ok=True)
except OSError:
    pass  # read-only home (some HPC setups); app continues, file I/O will fail gracefully
META_FILE      = CONFIG_DIR / 'model_meta.json'
SETTINGS_FILE  = CONFIG_DIR / 'settings.json'
BOOKMARKS_FILE = CONFIG_DIR / 'bookmarks.json'
RUNS_FILE      = CONFIG_DIR / 'runs.json'
APP_VERSION    = '2.6.7'
_cfg_lock      = threading.Lock()

# Bootstrap diagnostic thresholds
BOOT_COMPLETION_PASS = 0.90
BOOT_COMPLETION_WARN = 0.80
BOOT_COMPLETION_FAIL = 0.70
BOOT_BIAS_PASS = 0.10
BOOT_BIAS_WARN = 0.20
BOOT_BIAS_FAIL = 0.50
BOOT_CORR_WARN = 0.90
BOOT_CORR_FAIL = 0.99

# SIR diagnostic thresholds
SIR_KS_PASS = 0.05
SIR_KS_WARN = 0.01
SIR_MEDIAN_PASS = 0.15
SIR_MEDIAN_WARN = 0.30
SIR_ESS_PASS = 0.50
SIR_ESS_WARN = 0.30
SIR_ESS_FAIL = 0.10
SIR_ESS_ABS_WARN = 500
SIR_ESS_ABS_FAIL = 200
