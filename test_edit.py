#!/usr/bin/env python3
"""Fake editor for stress-testing plan.py's edit command.

Usage: EDITOR='./test_edit.py' plan #N edit

Reads the temp file path from argv[1] (as real editors do), then modifies
it according to environment variables:

  EDIT_MODE     "append" (default), "replace-body", or "prepend-body"
  EDIT_CONTENT  The text to insert.  If unset, appends "Edited by test."

Modes:
  append        Append EDIT_CONTENT after the root ticket's body.
  replace-body  Keep the header and attributes, replace only the root body.
  prepend-body  Keep the header and attributes, prepend to the root body.

All modes preserve child tickets and other structural elements that
follow the root ticket's body (used for both single and recursive edit).
"""

import os
import re
import sys

TICKET_RE = re.compile(r"^(\s*)\*\s+##\s+Ticket:")
COMMENT_RE = re.compile(r"^(\s*)\*\s+##\s+Comments\s+\{")


def _split_parts(text):
    """Split editor content into (header+attrs, root_body, children_tail).

    - header+attrs: the ticket header line, blank lines, attribute lines,
      and trailing blank line after attrs.
    - root_body: body lines belonging to the root ticket only (stops at
      the first child ticket or comments section).
    - children_tail: everything from the first child ticket onward.
    """
    lines = text.split("\n")
    i = 0
    n = len(lines)

    # Skip header line (* ## Ticket: ... or ## Ticket: ...)
    if i < n:
        i += 1

    # Skip blank lines after header
    while i < n and lines[i].strip() == "":
        i += 1

    # Skip attribute lines (indented key: value)
    attr_re = re.compile(r"^\s+\S+:\s")
    while i < n and attr_re.match(lines[i]):
        i += 1

    # Skip blank lines after attrs
    while i < n and lines[i].strip() == "":
        i += 1

    header_end = i

    # Find where root body ends: at the first child ticket or comments
    # A child ticket/comments has deeper indent than the root header
    body_end = i
    while body_end < n:
        line = lines[body_end]
        if TICKET_RE.match(line) or COMMENT_RE.match(line):
            break
        body_end += 1

    header = "\n".join(lines[:header_end])
    body = "\n".join(lines[header_end:body_end])
    tail = "\n".join(lines[body_end:])
    return header, body, tail


def _detect_body_indent(body):
    """Detect indentation of existing body text."""
    for line in body.split("\n"):
        if line.strip():
            return len(line) - len(line.lstrip())
    return 0


def _indent_content(content, indent):
    """Apply indentation to content lines."""
    prefix = " " * indent
    result = []
    for line in content.split("\n"):
        if line.strip():
            result.append(prefix + line)
        else:
            result.append("")
    return "\n".join(result)


def main():
    if len(sys.argv) < 2:
        print("Usage: test_edit.py <file>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    mode = os.environ.get("EDIT_MODE", "append")
    content = os.environ.get("EDIT_CONTENT", "Edited by test.")

    with open(path) as f:
        original = f.read()

    header, body, tail = _split_parts(original)

    # Detect body indentation from existing content or header
    body_indent = _detect_body_indent(body)
    if body_indent == 0:
        # Infer from header: body is at header_indent + 2
        for line in header.split("\n"):
            if line.strip():
                body_indent = len(line) - len(line.lstrip()) + 2
                break

    # Apply indentation to new content
    indented_content = _indent_content(content, body_indent)

    if mode == "replace-body":
        new_body = indented_content
    elif mode == "prepend-body":
        new_body = indented_content + "\n" + body if body.strip() else indented_content
    else:  # append
        new_body = body.rstrip("\n") + "\n" + indented_content if body.strip() else indented_content

    # Reassemble: header + blank + new_body + blank + tail
    parts = [header]
    if new_body.strip():
        parts.append(new_body)
    if tail.strip():
        parts.append(tail)
    # Ensure single newline between parts
    result = "\n".join(parts)
    if not result.endswith("\n"):
        result += "\n"

    with open(path, "w") as f:
        f.write(result)


if __name__ == "__main__":
    main()
