#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# Generate help text constants from src/help/ text files.
#
# Reads:
#   src/help/general.txt       -> HELP_TEXT
#   src/help/dsl.txt           -> DSL_HELP
#   src/help/commands/*.txt    -> COMMAND_HELP[name]
#
# Also emits alias entries and the DSL_HELP.strip() assignment.
# ---------------------------------------------------------------------------

from pathlib import Path


def quote(s):
    """Format a string as a backslash-escaped triple-quoted Python string literal."""
    return '"""\\\n' + s.replace('\\', '\\\\').replace('"""', '\\"\\"\\"') + '"""'


def main():
    src_dir = Path(__file__).resolve().parent
    help_dir = src_dir / "help"

    # --- Header ---
    print("# ---------------------------------------------------------------------------")
    print("# Help Text Constants (generated from src/help/)")
    print("# ---------------------------------------------------------------------------")
    print()

    # --- HELP_TEXT ---
    general = (help_dir / "general.txt").read_text()
    print(f"HELP_TEXT = {quote(general)}")
    print()
    print()

    # --- DSL_HELP ---
    dsl = (help_dir / "dsl.txt").read_text()
    print(f"DSL_HELP = {quote(dsl)}")
    print()

    # --- COMMAND_HELP ---
    commands_dir = help_dir / "commands"
    command_files = sorted(commands_dir.glob("*.txt"))

    print("COMMAND_HELP = {")
    for i, path in enumerate(command_files):
        name = path.stem
        text = path.read_text()
        comma = ","
        print(f"    {name!r}: {quote(text)}{comma}")
        if i < len(command_files) - 1:
            print()
    print("}")
    print()

    # --- DSL alias ---
    print('COMMAND_HELP["dsl"] = DSL_HELP.strip()')
    print()

    # --- Verb/command aliases ---
    print("# Aliases so both verb and command names resolve")
    print('COMMAND_HELP["+"] = COMMAND_HELP["add"]')
    print('COMMAND_HELP["~"] = COMMAND_HELP["mod"]')
    print('COMMAND_HELP["ls"] = COMMAND_HELP["list"]')
    print('COMMAND_HELP["h"] = COMMAND_HELP.get("help", "")')

    print()


if __name__ == "__main__":
    main()
