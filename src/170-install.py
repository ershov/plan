# ---------------------------------------------------------------------------
# Install / Uninstall
# ---------------------------------------------------------------------------

_PLUGIN_NAME = "claude-plan"
_PLUGIN_MARKETPLACE = "plan-tools"
_PLUGIN_ID = f"{_PLUGIN_NAME}@{_PLUGIN_MARKETPLACE}"


def _read_json(path):
    """Read a JSON file, returning empty dict on missing/corrupt files."""
    if os.path.exists(path):
        with open(path) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {}


def _write_json(path, data):
    """Write data as JSON to path, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _get_plugin_version():
    """Extract version from embedded plugin.json."""
    plugin_json = _PLUGIN_FILES.get(".claude-plugin/plugin.json", "{}")
    try:
        return json.loads(plugin_json).get("version", "1.0.0")
    except json.JSONDecodeError:
        return "1.0.0"


def _remove_claude_md_section(content):
    """Remove the task tracking section from CLAUDE.md content.

    Returns the remaining content (may be empty string).
    """
    if _CLAUDE_MD_MARKER not in content:
        return content
    idx = content.index(_CLAUDE_MD_MARKER)
    # Trim preceding newlines
    while idx > 0 and content[idx - 1] == "\n":
        idx -= 1
    before = content[:idx]
    after_section = content[content.index(_CLAUDE_MD_MARKER):]
    # Find end of our section: next ## heading or end of file
    lines = after_section.split("\n")
    end = len(lines)
    for i, line in enumerate(lines):
        if i > 0 and line.startswith("## ") and line != _CLAUDE_MD_MARKER:
            end = i
            break
    remaining = "\n".join(lines[end:])
    result = before
    if remaining.strip():
        result = result.rstrip("\n") + "\n\n" + remaining
    result = result.rstrip("\n")
    if result.strip():
        return result + "\n"
    return ""


def _handle_install(scope):
    """Install plan binary, Claude Code plugin, and CLAUDE.md instructions.

    scope: 'local' (current directory) or 'user' (~/.local/bin + ~/.claude).
    """
    if scope not in ("local", "user"):
        raise SystemExit("Error: install requires 'local' or 'user' argument")

    script_path = os.path.abspath(__file__)

    # --- Binary ---
    if scope == "local":
        bin_path = os.path.join(os.getcwd(), "plan")
    else:
        bin_path = os.path.expanduser("~/.local/bin/plan")

    if os.path.exists(bin_path):
        shutil.copy2(script_path, bin_path)
        os.chmod(bin_path, 0o755)
        print(f"Binary: updated {bin_path}")
    elif shutil.which("plan"):
        print(f"Binary: skipped (plan already on PATH at {shutil.which('plan')})")
    else:
        os.makedirs(os.path.dirname(bin_path) or ".", exist_ok=True)
        shutil.copy2(script_path, bin_path)
        os.chmod(bin_path, 0o755)
        print(f"Binary: installed {bin_path}")

    # --- Plugin ---
    if scope == "local":
        plugin_dir = os.path.join(os.getcwd(), ".claude", "plugins", _PLUGIN_NAME)
        plugin_ref = f".claude/plugins/{_PLUGIN_NAME}"
        settings_path = os.path.join(os.getcwd(), ".claude", "settings.json")
    else:
        version = _get_plugin_version()
        plugin_dir = os.path.expanduser(
            f"~/.claude/plugins/cache/{_PLUGIN_MARKETPLACE}/{_PLUGIN_NAME}/{version}"
        )

    for rel_path, content in _PLUGIN_FILES.items():
        full_path = os.path.join(plugin_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        if rel_path.endswith(".sh"):
            os.chmod(full_path, 0o755)

    if scope == "local":
        # Local scope: register via plugins array in project settings.json
        settings = _read_json(settings_path)
        plugins = settings.get("plugins", [])
        if plugin_ref not in plugins:
            plugins.append(plugin_ref)
            settings["plugins"] = plugins
            _write_json(settings_path, settings)
    else:
        # User scope: register in installed_plugins.json (like marketplace install)
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        installed_path = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
        installed = _read_json(installed_path)
        if installed.get("version") != 2:
            installed = {"version": 2, "plugins": installed.get("plugins", {})}
        installed["plugins"][_PLUGIN_ID] = [{
            "scope": "user",
            "installPath": plugin_dir,
            "version": version,
            "installedAt": now,
            "lastUpdated": now,
        }]
        _write_json(installed_path, installed)

    print(f"Plugin: installed {plugin_dir}")

    # --- enabledPlugins in user-level settings.json ---
    user_settings_path = os.path.expanduser("~/.claude/settings.json")
    user_settings = _read_json(user_settings_path)
    enabled = user_settings.get("enabledPlugins", {})
    plugin_key = _PLUGIN_ID if scope == "user" else _PLUGIN_NAME
    if not enabled.get(plugin_key):
        enabled[plugin_key] = True
        user_settings["enabledPlugins"] = enabled
        _write_json(user_settings_path, user_settings)
        print(f"enabledPlugins: added {plugin_key}")
    else:
        print(f"enabledPlugins: {plugin_key} already enabled")

    # --- CLAUDE.md ---
    if scope == "local":
        claude_md_path = os.path.join(os.getcwd(), "CLAUDE.md")
    else:
        claude_md_path = os.path.expanduser("~/.claude/CLAUDE.md")

    existing = ""
    if os.path.exists(claude_md_path):
        with open(claude_md_path) as f:
            existing = f.read()

    if _CLAUDE_MD_MARKER in existing:
        # Replace existing section (handles content changes across versions)
        new_content = _remove_claude_md_section(existing)
        if new_content.strip():
            with open(claude_md_path, "w") as f:
                f.write(new_content + _CLAUDE_MD_SECTION)
        else:
            with open(claude_md_path, "w") as f:
                f.write(_CLAUDE_MD_SECTION)
        print(f"CLAUDE.md: replaced section in {claude_md_path}")
    else:
        with open(claude_md_path, "a") as f:
            f.write(_CLAUDE_MD_SECTION)
        print(f"CLAUDE.md: updated {claude_md_path}")

    print("Done.")


def _handle_uninstall(scope):
    """Uninstall plan binary, Claude Code plugin, and CLAUDE.md instructions.

    scope: 'local' (current directory) or 'user' (~/.local/bin + ~/.claude).
    """
    if scope not in ("local", "user"):
        raise SystemExit("Error: uninstall requires 'local' or 'user' argument")

    # --- Binary ---
    if scope == "local":
        bin_path = os.path.join(os.getcwd(), "plan")
    else:
        bin_path = os.path.expanduser("~/.local/bin/plan")

    if os.path.exists(bin_path):
        os.remove(bin_path)
        print(f"Binary: removed {bin_path}")
    else:
        print(f"Binary: not found at {bin_path}")

    # --- Plugin ---
    if scope == "local":
        plugin_dir = os.path.join(os.getcwd(), ".claude", "plugins", _PLUGIN_NAME)
        plugin_ref = f".claude/plugins/{_PLUGIN_NAME}"
        settings_path = os.path.join(os.getcwd(), ".claude", "settings.json")

        if os.path.isdir(plugin_dir):
            shutil.rmtree(plugin_dir)
            print(f"Plugin: removed {plugin_dir}")
            # Clean up empty parent dirs up to .claude/
            claude_dir = os.path.join(os.getcwd(), ".claude")
            parent = os.path.dirname(plugin_dir)
            while parent.startswith(claude_dir) and parent != claude_dir:
                if os.path.isdir(parent) and not os.listdir(parent):
                    os.rmdir(parent)
                    parent = os.path.dirname(parent)
                else:
                    break
        else:
            print(f"Plugin: not found")
    else:
        # Remove ALL version directories under .../claude-plan/
        plugin_name_dir = os.path.expanduser(
            f"~/.claude/plugins/cache/{_PLUGIN_MARKETPLACE}/{_PLUGIN_NAME}"
        )
        if os.path.isdir(plugin_name_dir):
            shutil.rmtree(plugin_name_dir)
            print(f"Plugin: removed {plugin_name_dir} (all versions)")
            # Clean up empty parent dirs up to cache/
            cache_dir = os.path.expanduser("~/.claude/plugins/cache")
            parent = os.path.dirname(plugin_name_dir)
            while parent != cache_dir and parent.startswith(cache_dir):
                if os.path.isdir(parent) and not os.listdir(parent):
                    os.rmdir(parent)
                    parent = os.path.dirname(parent)
                else:
                    break
        else:
            print(f"Plugin: not found")

    if scope == "local":
        # Remove from plugins array in project settings.json
        settings = _read_json(settings_path)
        plugins = settings.get("plugins", [])
        if plugin_ref in plugins:
            plugins.remove(plugin_ref)
            if plugins:
                settings["plugins"] = plugins
            else:
                del settings["plugins"]
            if settings:
                _write_json(settings_path, settings)
            else:
                os.remove(settings_path)
                claude_dir = os.path.dirname(settings_path)
                if os.path.isdir(claude_dir) and not os.listdir(claude_dir):
                    os.rmdir(claude_dir)
    else:
        # Remove from installed_plugins.json
        installed_path = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
        installed = _read_json(installed_path)
        plugins = installed.get("plugins", {})
        if _PLUGIN_ID in plugins:
            del plugins[_PLUGIN_ID]
            _write_json(installed_path, installed)
            print(f"installed_plugins.json: removed {_PLUGIN_ID}")

    # --- enabledPlugins in user-level settings.json ---
    user_settings_path = os.path.expanduser("~/.claude/settings.json")
    user_settings = _read_json(user_settings_path)
    enabled = user_settings.get("enabledPlugins", {})
    plugin_key = _PLUGIN_ID if scope == "user" else _PLUGIN_NAME
    if plugin_key in enabled:
        del enabled[plugin_key]
        user_settings["enabledPlugins"] = enabled
        _write_json(user_settings_path, user_settings)
        print(f"enabledPlugins: removed {plugin_key}")

    # --- Clean up old-style plugin remnants ---
    if scope == "user":
        old_plugin_dir = os.path.expanduser(f"~/.claude/plugins/{_PLUGIN_NAME}")
        if os.path.isdir(old_plugin_dir):
            shutil.rmtree(old_plugin_dir)
            print(f"Legacy plugin: removed {old_plugin_dir}")
        # Clean up old plugins array reference
        user_settings = _read_json(user_settings_path)
        plugins = user_settings.get("plugins", [])
        old_ref = old_plugin_dir
        if old_ref in plugins:
            plugins.remove(old_ref)
            if plugins:
                user_settings["plugins"] = plugins
            else:
                if "plugins" in user_settings:
                    del user_settings["plugins"]
            _write_json(user_settings_path, user_settings)
            print(f"Legacy plugins array: removed old reference")
        # Clean up old enabledPlugins key (without marketplace suffix)
        enabled = user_settings.get("enabledPlugins", {})
        if _PLUGIN_NAME in enabled:
            del enabled[_PLUGIN_NAME]
            user_settings["enabledPlugins"] = enabled
            _write_json(user_settings_path, user_settings)
            print(f"Legacy enabledPlugins: removed {_PLUGIN_NAME}")

    # --- CLAUDE.md ---
    if scope == "local":
        claude_md_path = os.path.join(os.getcwd(), "CLAUDE.md")
    else:
        claude_md_path = os.path.expanduser("~/.claude/CLAUDE.md")

    if os.path.exists(claude_md_path):
        with open(claude_md_path) as f:
            content = f.read()

        if _CLAUDE_MD_MARKER in content:
            new_content = _remove_claude_md_section(content)
            if new_content.strip():
                with open(claude_md_path, "w") as f:
                    f.write(new_content)
                print(f"CLAUDE.md: removed task tracking section from {claude_md_path}")
            else:
                os.remove(claude_md_path)
                print(f"CLAUDE.md: removed {claude_md_path} (was empty)")
        else:
            print(f"CLAUDE.md: no task tracking section found")
    else:
        print(f"CLAUDE.md: not found at {claude_md_path}")

