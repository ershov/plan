#!/usr/bin/env python3
"""plan — Markdown Ticket Tracker CLI.

A single-file CLI tool that manages tickets in a structured markdown file.
Uses only Python standard library modules.

Sections:
    Constants / Utility .............. data model, parsing helpers
    Parser / Serializer .............. .PLAN.md read/write
    DSL Sandbox ...................... filter, format, mod expressions
    Ranking .......................... ticket ordering
    Link Interlinking ................ blocked/blocking/related
    CLI Parser ....................... argv parsing
    File Discovery ................... .PLAN.md location
    Command Handlers ................. create, list, status, close, ...
    Command Dispatch ................. route parsed request to handler
    Claude Code Plugin (embedded) .... _PLUGIN_FILES dict — skills, hooks, scripts
    Install / Uninstall .............. plan install local|user, plan uninstall
    Main ............................. entry point
"""

import copy
import datetime
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import textwrap

try:
    import fcntl
    _has_flock = True
except ImportError:
    _has_flock = False
