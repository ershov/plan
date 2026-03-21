#!/usr/bin/env python3
"""plan-tui: Terminal UI for plan tickets"""

import sys
import os
import select
import signal
import termios
import tty
import subprocess
import shutil
import re
import errno
import threading

# Plan binary discovery: check PATH first, then same directory as this script
PLAN_BIN = shutil.which('plan') or shutil.which('plan.py')
if not PLAN_BIN:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _candidate = os.path.join(_script_dir, 'plan.py')
    if os.path.isfile(_candidate) and os.access(_candidate, os.X_OK):
        PLAN_BIN = _candidate
    else:
        sys.exit('plan-tui requires plan in PATH or same directory')
