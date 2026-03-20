# ---------------------------------------------------------------------------
# File Discovery
# ---------------------------------------------------------------------------

def discover_file(flags):
    """Discover the plan file path using precedence rules.

    Returns the path even if the file doesn't exist yet (for write operations).

    1. --file / -f flag
    2. PLAN_MD environment variable
    3. .PLAN.md at git repo root
    4. .PLAN.md walking up from cwd
    """
    # 1. Flag
    if "file" in flags:
        return flags["file"]

    # 2. Environment variable
    env_path = os.environ.get("PLAN_MD")
    if env_path:
        return env_path

    # 3. Git root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            root = result.stdout.strip()
            candidate = os.path.join(root, ".PLAN.md")
            if os.path.exists(candidate):
                return candidate
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    # 4. Walk up from cwd
    d = os.path.abspath(os.getcwd())
    while True:
        candidate = os.path.join(d, ".PLAN.md")
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent

    # Fallback: return git root path (for write operations) or error
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            root = result.stdout.strip()
            return os.path.join(root, ".PLAN.md")
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    raise SystemExit("Error: no plan file found. Use --file, set PLAN_MD, or create .PLAN.md in git root.")

