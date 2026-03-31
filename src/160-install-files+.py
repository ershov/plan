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


def extract_marker(content):
    """Extract the first ## heading from content."""
    for line in content.splitlines():
        if line.startswith("## "):
            return line
    return ""


def main():
    src_dir = Path(__file__).resolve().parent
    plugin_dir = src_dir / "claude-template" / "plugins" / "claude-plan"
    claude_md_path = src_dir / "CLAUDE.md"
    codex_md_path = src_dir / "CODEX.md"

    # --- Collect plugin files ---
    plugin_files = {
        str(p.relative_to(plugin_dir)): p.read_text()
        for p in sorted(plugin_dir.rglob("*"))
        if p.is_file()
    }

    # --- Read CLAUDE.md ---
    claude_md_content = claude_md_path.read_text()
    claude_marker = extract_marker(claude_md_content)

    # --- Read CODEX.md ---
    codex_md_content = codex_md_path.read_text()
    codex_marker = extract_marker(codex_md_content)

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
    print(f"_CLAUDE_MD_MARKER = {claude_marker!r}")
    print()

    # _CODEX_MD_SECTION
    print(f"_CODEX_MD_SECTION = {quote(codex_md_content)}")
    print()

    # _CODEX_MD_MARKER
    print(f"_CODEX_MD_MARKER = {codex_marker!r}")
    print()
    print()


if __name__ == "__main__":
    main()
