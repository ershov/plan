#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Generate embedded plugin file definitions from source files.
#
# Reads files from claude-template/plugins/claude-plan/ and CLAUDE.md to produce
# the _PLUGIN_FILES dict, _CLAUDE_MD_SECTION, and _CLAUDE_MD_MARKER
# used by `plan install`.
# ---------------------------------------------------------------------------

from pathlib import Path


def quote(s):
    """Format a string as a raw triple-quoted Python string literal."""
    return "r'''" + s.replace("'''", "'''+" + '"' + "'''" + '"' + "+r'''") + "'''"


def main():
    src_dir = Path(__file__).resolve().parent
    plugin_dir = src_dir / "claude-template" / "plugins" / "claude-plan"
    claude_md_path = src_dir / "CLAUDE.md"

    # --- Collect plugin files ---
    plugin_files = {
        str(p.relative_to(plugin_dir)): p.read_text()
        for p in sorted(plugin_dir.rglob("*"))
        if p.is_file()
    }

    # --- Read CLAUDE.md ---
    claude_md_content = claude_md_path.read_text()

    # Extract marker (first ## heading)
    marker = ""
    for line in claude_md_content.splitlines():
        if line.startswith("## "):
            marker = line
            break

    # --- Generate output ---
    print("# ---------------------------------------------------------------------------")
    print("# Claude Code Plugin (embedded)")
    print("# ---------------------------------------------------------------------------")
    print("# `plan install` writes these files to create a Claude Code plugin.")
    print("# This dict is the single source of truth for plugin content.")
    print("#")
    print("# Embedded files:")
    for rel_path in plugin_files:
        print(f"#   {rel_path}")
    print("# ---------------------------------------------------------------------------")
    print()

    # _PLUGIN_FILES dict
    print("_PLUGIN_FILES = {")
    for rel_path, content in plugin_files.items():
        print(f"    {rel_path!r}: {quote(content)},")
    print("}")
    print()

    # _CLAUDE_MD_SECTION
    print(f"_CLAUDE_MD_SECTION = {quote(claude_md_content)}")
    print()

    # _CLAUDE_MD_MARKER
    print(f"_CLAUDE_MD_MARKER = {marker!r}")
    print()
    print()


if __name__ == "__main__":
    main()
