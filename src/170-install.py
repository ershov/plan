# ---------------------------------------------------------------------------
# Install / Uninstall
# ---------------------------------------------------------------------------

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

    if shutil.which("plan"):
        print(f"Binary: skipped (plan already on PATH at {shutil.which('plan')})")
    else:
        os.makedirs(os.path.dirname(bin_path) or ".", exist_ok=True)
        shutil.copy2(script_path, bin_path)
        os.chmod(bin_path, 0o755)
        print(f"Binary: installed {bin_path}")

    # --- Plugin ---
    if scope == "local":
        plugin_dir = os.path.join(os.getcwd(), ".claude", "plugins", "claude-plan")
        plugin_ref = ".claude/plugins/claude-plan"
        settings_path = os.path.join(os.getcwd(), ".claude", "settings.json")
    else:
        plugin_dir = os.path.expanduser("~/.claude/plugins/claude-plan")
        plugin_ref = plugin_dir
        settings_path = os.path.expanduser("~/.claude/settings.json")

    for rel_path, content in _PLUGIN_FILES.items():
        full_path = os.path.join(plugin_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        if rel_path.endswith(".sh"):
            os.chmod(full_path, 0o755)

    # Register in settings.json
    settings = {}
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            try:
                settings = json.load(f)
            except json.JSONDecodeError:
                settings = {}
    plugins = settings.get("plugins", [])
    if plugin_ref not in plugins:
        plugins.append(plugin_ref)
        settings["plugins"] = plugins
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
    print(f"Plugin: installed {plugin_dir}")

    # --- enabledPlugins in user-level settings.json ---
    user_settings_path = os.path.expanduser("~/.claude/settings.json")
    if os.path.exists(user_settings_path):
        with open(user_settings_path) as f:
            try:
                user_settings = json.load(f)
            except json.JSONDecodeError:
                user_settings = {}
        if "enabledPlugins" in user_settings:
            if not user_settings["enabledPlugins"].get("claude-plan"):
                user_settings["enabledPlugins"]["claude-plan"] = True
                with open(user_settings_path, "w") as f:
                    json.dump(user_settings, f, indent=2)
                    f.write("\n")
                print("enabledPlugins: added claude-plan to user settings")
            else:
                print("enabledPlugins: claude-plan already enabled")

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
        print(f"CLAUDE.md: skipped (task tracking section already present)")
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
        plugin_dir = os.path.join(os.getcwd(), ".claude", "plugins", "claude-plan")
        plugin_ref = ".claude/plugins/claude-plan"
        settings_path = os.path.join(os.getcwd(), ".claude", "settings.json")
    else:
        plugin_dir = os.path.expanduser("~/.claude/plugins/claude-plan")
        plugin_ref = plugin_dir
        settings_path = os.path.expanduser("~/.claude/settings.json")

    if os.path.isdir(plugin_dir):
        shutil.rmtree(plugin_dir)
        print(f"Plugin: removed {plugin_dir}")

        # Clean up empty parent dirs
        plugins_dir = os.path.dirname(plugin_dir)
        if os.path.isdir(plugins_dir) and not os.listdir(plugins_dir):
            os.rmdir(plugins_dir)
    else:
        print(f"Plugin: not found at {plugin_dir}")

    # Unregister from settings.json
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            try:
                settings = json.load(f)
            except json.JSONDecodeError:
                settings = {}
        plugins = settings.get("plugins", [])
        if plugin_ref in plugins:
            plugins.remove(plugin_ref)
            if plugins:
                settings["plugins"] = plugins
            else:
                del settings["plugins"]
            if settings:
                with open(settings_path, "w") as f:
                    json.dump(settings, f, indent=2)
                    f.write("\n")
            else:
                os.remove(settings_path)
                # Clean up empty .claude dir
                claude_dir = os.path.dirname(settings_path)
                if os.path.isdir(claude_dir) and not os.listdir(claude_dir):
                    os.rmdir(claude_dir)

    # --- enabledPlugins in user-level settings.json ---
    # NOTE: Don't do it for now because it will disable all local plugins.
    #user_settings_path = os.path.expanduser("~/.claude/settings.json")
    #if os.path.exists(user_settings_path):
    #    with open(user_settings_path) as f:
    #        try:
    #            user_settings = json.load(f)
    #        except json.JSONDecodeError:
    #            user_settings = {}
    #    if "enabledPlugins" in user_settings and "claude-plan" in user_settings["enabledPlugins"]:
    #        del user_settings["enabledPlugins"]["claude-plan"]
    #        with open(user_settings_path, "w") as f:
    #            json.dump(user_settings, f, indent=2)
    #            f.write("\n")
    #        print("enabledPlugins: removed claude-plan from user settings")

    # --- CLAUDE.md ---
    if scope == "local":
        claude_md_path = os.path.join(os.getcwd(), "CLAUDE.md")
    else:
        claude_md_path = os.path.expanduser("~/.claude/CLAUDE.md")

    if os.path.exists(claude_md_path):
        with open(claude_md_path) as f:
            content = f.read()

        if _CLAUDE_MD_MARKER in content:
            # Remove the task tracking section
            idx = content.index(_CLAUDE_MD_MARKER)
            # Find preceding newlines to trim
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
            new_content = before
            if remaining.strip():
                new_content = new_content.rstrip("\n") + "\n\n" + remaining

            new_content = new_content.rstrip("\n")
            if new_content.strip():
                with open(claude_md_path, "w") as f:
                    f.write(new_content + "\n")
                print(f"CLAUDE.md: removed task tracking section from {claude_md_path}")
            else:
                os.remove(claude_md_path)
                print(f"CLAUDE.md: removed {claude_md_path} (was empty)")
        else:
            print(f"CLAUDE.md: no task tracking section found")
    else:
        print(f"CLAUDE.md: not found at {claude_md_path}")

    print("Done.")

