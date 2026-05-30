#!/usr/bin/env python3

# THIS IS A GENERATED FILE - DO NOT EDIT!
# SOURCE START: 010-preambula.py {{{
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
# }}} # SOURCE END: 010-preambula.py

# SOURCE START: 015-version+.sh {{{
VERSION_A = [1, 0, 10]
VERSION_STR = "1.0.10"
VERSION_DATE = "2026-03-31"
# }}} # SOURCE END: 015-version+.sh

# SOURCE START: 020-constants.py {{{
# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAFE_BUILTINS = {
    "len": len, "any": any, "all": all,
    "min": min, "max": max, "sorted": sorted,
    "int": int, "str": str, "float": float,
    "True": True, "False": False, "None": None,
}

LINK_MIRRORS = {
    "blocked": "blocking",
    "blocking": "blocked",
    "related": "related",
    "derived": "derived-from",
    "derived-from": "derived",
    "caused": "caused-by",
    "caused-by": "caused",
}

ACTIVE_STATUSES = {"open", "in-progress", "assigned", "blocked", "reviewing", "testing"}
DEFERRED_STATUSES = {"backlog", "deferred", "future", "someday", "wishlist", "paused", "on-hold"}
OPEN_STATUSES = ACTIVE_STATUSES | DEFERRED_STATUSES
# }}} # SOURCE END: 020-constants.py

# SOURCE START: 030-utils.py {{{
# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

class DefaultNamespace(dict):
    """Dict that returns '' for missing keys instead of raising KeyError."""
    def __missing__(self, key):
        return ""


def _file(path):
    """Read file contents. '-' reads stdin."""
    if path == "-":
        return sys.stdin.read()
    with open(path) as f:
        return f.read()


def _now():
    """Return current UTC timestamp string."""
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def _parse_links(value):
    """Parse a links string into {type: [int_ids]}.

    'blocked:#3 blocking:#5 related:#2' -> {'blocked': [3], 'blocking': [5], 'related': [2]}
    """
    result = {}
    if not value or not value.strip():
        return result
    for token in value.split():
        if ":#" in token:
            parts = token.split(":#", 1)
            link_type = parts[0]
            try:
                target_id = int(parts[1])
            except (ValueError, IndexError):
                continue
            result.setdefault(link_type, []).append(target_id)
    return result


def _serialize_links(links_dict):
    """Serialize links dict to string: {'blocked': [3]} -> 'blocked:#3'."""
    parts = []
    for link_type, ids in links_dict.items():
        for tid in ids:
            parts.append(f"{link_type}:#{tid}")
    return " ".join(parts)


def _indent_of(line):
    """Return number of leading spaces."""
    return len(line) - len(line.lstrip())


def _normalize_indent(lines):
    """Strip common leading whitespace from lines (preserving blank lines)."""
    min_indent = float('inf')
    for l in lines:
        if l.strip():
            min_indent = min(min_indent, _indent_of(l))
    if min_indent > 0 and min_indent != float('inf'):
        lines = [l[min_indent:] if len(l) >= min_indent else l for l in lines]
    return lines


def _make_comment(comment_id, text, indent_level):
    """Create a Comment node from text, handling multi-line body indentation."""
    lines = text.split('\n')
    comment = Comment(comment_id, lines[0])
    comment.indent_level = indent_level
    if len(lines) > 1:
        content_indent = " " * (indent_level + 2)
        comment.body_lines = [
            content_indent + l if l else "" for l in lines[1:]
        ]
    comment.dirty = True
    return comment


def _collect_ancestors(ticket):
    """Walk parent chain and return ancestors list from root to immediate parent."""
    ancestors = []
    p = ticket.parent
    while p is not None and isinstance(p, Ticket):
        ancestors.append(p)
        p = p.parent
    ancestors.reverse()
    return ancestors

# }}} # SOURCE END: 030-utils.py

# SOURCE START: 040-data-model.py {{{
# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

class Node:
    """Base class for all document elements."""

    def __init__(self):
        self.attrs = {}
        self.body_lines = []
        self.raw_lines = []       # original lines for round-trip
        self.indent_level = 0     # leading spaces of the header line
        self.dirty = False
        self.node_id = None

    def set_attr(self, key, value):
        self.attrs[key] = str(value)
        self.dirty = True

    def del_attr(self, key):
        if key in self.attrs:
            del self.attrs[key]
            self.dirty = True

    def get_attr(self, key, default=""):
        return self.attrs.get(key, default)

    def as_namespace(self):
        """Return a dict of attributes for DSL evaluation."""
        ns = {}
        for k, v in self.attrs.items():
            if k == "links":
                ns[k] = _parse_links(v)
            elif k == "id":
                try:
                    ns[k] = int(v)
                except (ValueError, TypeError):
                    ns[k] = v
            else:
                ns[k] = v
        return ns


class Section(Node):
    """A project section (metadata, description, roles, etc.)."""

    def __init__(self, title="", section_id=None):
        super().__init__()
        self.title = title
        self.node_id = section_id


class Comment(Node):
    """A single comment in a thread."""

    def __init__(self, comment_id=None, title=""):
        super().__init__()
        self.node_id = comment_id
        self.title = title
        self.children = []


class Comments(Node):
    """Container for comment threads on a ticket."""

    def __init__(self, comments_id=None):
        super().__init__()
        self.node_id = comments_id
        self.comments = []


class Ticket(Node):
    """A ticket / task / bug / epic."""

    def __init__(self, ticket_id=None, title="", ticket_type="Task"):
        super().__init__()
        self.node_id = ticket_id
        self.title = title
        self.ticket_type = ticket_type
        self.children = []
        self.comments = None      # Comments node
        self.parent = None        # parent Ticket or None for top-level
        self._rank = None

    def as_namespace(self):
        ns = super().as_namespace()
        ns["id"] = self.node_id if self.node_id is not None else ""
        ns["title"] = self.title
        ns["text"] = textwrap.dedent("\n".join(self.body_lines))
        ns["parent"] = self.parent.node_id if self.parent else 0
        ns["children"] = ChildrenAccessor(self.children)
        # Compute depth by walking parent chain
        d = len(_collect_ancestors(self))
        ns["depth"] = d
        ns["indent"] = "  " * d
        if "status" not in ns:
            ns["status"] = ""
        ns["is_open"] = ns["status"] in OPEN_STATUSES or ns["status"] == ""
        ns["is_active"] = ns["status"] in ACTIVE_STATUSES or ns["status"] == ""
        return ns


class ChildrenAccessor(list):
    """List-like wrapper for children, callable for recursive expansion."""

    def __call__(self, recursive=False):
        if not recursive:
            return list(self)
        result = []
        def _collect(tickets):
            for t in tickets:
                result.append(t)
                _collect(t.children)
        _collect(self)
        return result


class Project(Node):
    """Root node — the entire plan file."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.node_id = "project"
        self.sections = {}        # section_name -> Section  (ordered by insertion)
        self.tickets = []         # top-level tickets
        self.id_map = {}          # str(id) -> Node
        self.next_id = 1
        self._trailing_newline = False

    def allocate_id(self):
        nid = self.next_id
        self.next_id += 1
        if "metadata" in self.sections:
            self.sections["metadata"].set_attr("next_id", str(self.next_id))
        return nid

    def register(self, node):
        if node.node_id is not None:
            self.id_map[str(node.node_id)] = node

    def lookup(self, node_id):
        return self.id_map.get(str(node_id))

# }}} # SOURCE END: 040-data-model.py

# SOURCE START: 050-patterns.py {{{
# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

RE_PROJECT = re.compile(r'^#\s+(.+?)\s*\{#project\}\s*$')
RE_SECTION = re.compile(r'^##\s+(.+?)\s*\{#([^}]+)\}\s*$')
_RE_TICKET_CORE = r'(?!Comments\s)(?:Ticket:\s*)?(?:(?P<type>[^:]+?):\s+)?(?P<title>.+?)'
RE_TICKET  = re.compile(
    r'^(?P<bullet>\s*\*\s+)##\s+' + _RE_TICKET_CORE + r'\s*\{#(?P<id>\d+)\}\s*$'
)
RE_TICKET_BULK = re.compile(
    r'^(?P<bullet>\s*\*\s+)##\s+' + _RE_TICKET_CORE + r'\s*(?:\{#(?P<id>[a-zA-Z0-9_-]+)\})?\s*$'
)
RE_TICKET_HEADER = re.compile(
    r'##\s+' + _RE_TICKET_CORE + r'\s*\{#\d+\}\s*$'
)
RE_COMMENTS = re.compile(
    r'^(\s*\*\s+)##\s+Comments\s*\{#([^}]+)\}\s*$'
)
RE_COMMENT = re.compile(
    r'^(\s*\*\s+)(.+?)\s*\{#([^}]+)\}\s*$'
)
RE_ATTR = re.compile(r'^(\s+)(\S+):\s?(.*?)\s*$')
# }}} # SOURCE END: 050-patterns.py

# SOURCE START: 060-parser.py {{{
# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse(text):
    """Parse markdown plan text into a Project."""
    project = Project()
    project._trailing_newline = text.endswith('\n')
    lines = text.split('\n')
    # If text ends with \n, split gives trailing empty string — keep for fidelity
    idx = [0]  # mutable index wrapper

    def peek():
        return lines[idx[0]] if idx[0] < len(lines) else None

    def advance():
        line = lines[idx[0]]
        idx[0] += 1
        return line

    def at_end():
        return idx[0] >= len(lines)

    # --- Pass 1: locate section boundaries ---
    section_starts = []
    for li, line in enumerate(lines):
        if RE_PROJECT.match(line):
            section_starts.append(('project', li))
        elif RE_SECTION.match(line):
            m = RE_SECTION.match(line)
            section_starts.append((m.group(2), li))

    section_starts.append(('_end', len(lines)))

    # --- Pass 2: process each top-level region ---
    for si in range(len(section_starts) - 1):
        sec_id, start = section_starts[si]
        _, end = section_starts[si + 1]
        region = lines[start:end]

        if sec_id == 'project':
            m = RE_PROJECT.match(region[0])
            project.title = m.group(1).strip()
            project.raw_lines = list(region)
            project.register(project)

        elif sec_id == 'tickets':
            sec = Section("Tickets", "tickets")
            sec.raw_lines = list(region)
            project.sections["tickets"] = sec
            project.register(sec)
            _parse_ticket_region(region[1:], project, project.tickets, None, start + 1)

        else:
            m = RE_SECTION.match(region[0])
            title = m.group(1).strip()
            sid = m.group(2).strip()
            sec = Section(title, sid)
            sec.raw_lines = list(region)
            project.sections[sid] = sec
            project.register(sec)
            # parse attrs + body
            _parse_section_attrs_body(region[1:], sec)

    # Extract next_id
    if "metadata" in project.sections:
        meta = project.sections["metadata"]
        try:
            project.next_id = int(meta.get_attr("next_id", "1"))
        except (ValueError, TypeError):
            project.next_id = 1

    _assign_ranks(project)

    return project


def _bootstrap_project(project):
    """Bootstrap a minimal project structure from an empty/missing file.

    Sets up title, metadata section (next_id: 1), and empty tickets section.
    Only called when the parsed project has no title (i.e., was empty).
    """
    project.title = "Project"
    project.raw_lines = ["# Project {#project}", ""]
    project.register(project)

    # Metadata section
    meta = Section("Metadata", "metadata")
    meta.attrs["next_id"] = "1"
    meta.dirty = True
    project.sections["metadata"] = meta
    project.register(meta)
    project.next_id = 1

    # Tickets section
    tickets_sec = Section("Tickets", "tickets")
    tickets_sec.dirty = True
    project.sections["tickets"] = tickets_sec
    project.register(tickets_sec)

    project._trailing_newline = True
    return project


def _parse_section_attrs_body(region_lines, section):
    """Parse attributes and body from a section's lines (after header)."""
    i = 0
    n = len(region_lines)
    found_body = False

    while i < n:
        line = region_lines[i]
        if line.strip() == '':
            i += 1
            continue
        m = RE_ATTR.match(line)
        if m and not found_body:
            section.attrs[m.group(2)] = m.group(3)
            i += 1
            continue
        found_body = True
        section.body_lines.append(line)
        i += 1


def _parse_ticket_region(region_lines, project, parent_list, parent_ticket,
                         global_line_offset):
    """Parse tickets from a region of lines. Populates parent_list."""
    # Find all ticket headers and their positions within region_lines
    ticket_positions = []
    for i, line in enumerate(region_lines):
        m = RE_TICKET.match(line)
        if m:
            ticket_positions.append((i, m, _indent_of(line)))

    if not ticket_positions:
        return

    # Group tickets by indent level — figure out which are direct children
    # Direct children are those at the minimum indent level
    min_indent = min(ind for _, _, ind in ticket_positions)
    direct = [(i, m, ind) for i, m, ind in ticket_positions if ind == min_indent]

    for di in range(len(direct)):
        pos, m, ind = direct[di]
        # Determine end of this ticket's region
        if di + 1 < len(direct):
            next_pos = direct[di + 1][0]
        else:
            next_pos = len(region_lines)

        ticket_region = region_lines[pos:next_pos]
        ticket = _parse_single_ticket(ticket_region, m, project, parent_ticket)
        parent_list.append(ticket)
        project.register(ticket)


def _parse_single_ticket(region_lines, header_match, project, parent_ticket):
    """Parse a single ticket from its region of lines."""
    m = header_match
    bullet_indent = _indent_of(region_lines[0])
    ticket_type = m.group("type").strip() if m.group("type") else "Task"
    title = m.group("title").strip()
    ticket_id = int(m.group("id"))

    ticket = Ticket(ticket_id, title, ticket_type)
    ticket.indent_level = bullet_indent
    ticket.parent = parent_ticket
    ticket.raw_lines = list(region_lines)

    # Content indent: after "* "
    content_indent = bullet_indent + 2
    attr_indent = content_indent + 4

    i = 1  # skip header line
    n = len(region_lines)
    in_attrs = True
    found_body = False

    while i < n:
        line = region_lines[i]

        # Check for comments header
        mc = RE_COMMENTS.match(line)
        if mc:
            comments_end = _find_comments_end(region_lines, i, bullet_indent)
            comments_region = region_lines[i:comments_end]
            comments = _parse_comments_region(comments_region, project)
            ticket.comments = comments
            project.register(comments)
            i = comments_end
            continue

        # Check for child ticket
        mt = RE_TICKET.match(line)
        if mt:
            child_indent = _indent_of(line)
            if child_indent > bullet_indent:
                child_end = _find_ticket_end(region_lines, i, child_indent)
                child_region = region_lines[i:child_end]
                child = _parse_single_ticket(child_region, mt, project, ticket)
                ticket.children.append(child)
                project.register(child)
                i = child_end
                continue

        # Blank line
        if line.strip() == '':
            if found_body:
                ticket.body_lines.append(line)
            i += 1
            continue

        # Attribute line
        ma = RE_ATTR.match(line)
        if ma and in_attrs and _indent_of(line) >= attr_indent:
            if ma.group(3):  # drop blank optional attrs
                ticket.attrs[ma.group(2)] = ma.group(3)
            i += 1
            continue

        # Body line
        in_attrs = False
        found_body = True
        ticket.body_lines.append(line)
        i += 1

    # Strip trailing blank lines from body
    while ticket.body_lines and ticket.body_lines[-1].strip() == '':
        ticket.body_lines.pop()

    return ticket


def _find_ticket_end(lines, start, indent):
    """Find where a ticket at `indent` ends in `lines` starting from `start`."""
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == '':
            i += 1
            continue
        mt = RE_TICKET.match(line)
        if mt and _indent_of(line) <= indent:
            return i
        # Any non-blank line at or before bullet indent means end
        # But only for ticket headers — body lines will be deeper
        i += 1
    return len(lines)


def _find_comments_end(lines, start, ticket_indent):
    """Find end of comments section starting at `start`."""
    # Comments end when we hit a ticket header at same/lesser indent or end of region
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == '':
            i += 1
            continue
        mt = RE_TICKET.match(line)
        if mt and _indent_of(line) <= ticket_indent + 2:
            # A sibling ticket (child of same parent) or a ticket at ticket's level
            return i
        i += 1
    return len(lines)


def _parse_comments_region(region_lines, project):
    """Parse a comments block into Comments + Comment nodes."""
    mc = RE_COMMENTS.match(region_lines[0])
    comments_id = mc.group(2)
    comments = Comments(comments_id)
    comments.indent_level = _indent_of(region_lines[0])
    comments.raw_lines = list(region_lines)

    # Find top-level comments (direct children of comments header)
    i = 1
    n = len(region_lines)
    while i < n:
        line = region_lines[i]
        if line.strip() == '':
            i += 1
            continue
        mco = RE_COMMENT.match(line)
        if mco:
            comment_indent = _indent_of(line)
            # Find end of this comment
            comment_end = _find_comment_end(region_lines, i, comment_indent)
            comment_region = region_lines[i:comment_end]
            comment = _parse_single_comment(comment_region, mco, project)
            comments.comments.append(comment)
            project.register(comment)
            i = comment_end
            continue
        i += 1

    return comments


def _find_comment_end(lines, start, indent):
    """Find where a comment at `indent` ends."""
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == '':
            i += 1
            continue
        # Another comment at same or lesser indent
        mco = RE_COMMENT.match(line)
        if mco and _indent_of(line) <= indent:
            return i
        i += 1
    return len(lines)


def _parse_single_comment(region_lines, header_match, project):
    """Parse a single comment and its replies."""
    m = header_match
    comment_id = m.group(3)
    title = m.group(2).strip()
    comment = Comment(comment_id, title)
    comment.indent_level = _indent_of(region_lines[0])
    comment.raw_lines = list(region_lines)

    i = 1
    n = len(region_lines)
    while i < n:
        line = region_lines[i]
        if line.strip() == '':
            i += 1
            continue

        # Check for child comment (reply)
        mco = RE_COMMENT.match(line)
        if mco and _indent_of(line) > comment.indent_level:
            child_indent = _indent_of(line)
            child_end = _find_comment_end(region_lines, i, child_indent)
            child_region = region_lines[i:child_end]
            child = _parse_single_comment(child_region, mco, project)
            comment.children.append(child)
            project.register(child)
            i = child_end
            continue

        # Body line
        comment.body_lines.append(line)
        i += 1

    return comment


def _assign_ranks(project):
    """Assign _rank to all tickets from file position, handle legacy migration."""
    # Pass 1: assign _rank from file position, stash legacy rank values
    legacy_groups = {}  # id(parent_list) -> [(stored_rank_float, file_pos, ticket)]
    _assign_positional_ranks(project.tickets, project, legacy_groups)

    # Pass 2: legacy migration — re-sort siblings that had stored rank attrs
    for key, group in legacy_groups.items():
        group.sort(key=lambda x: (x[0], x[1]))
        for i, (_, _, ticket) in enumerate(group):
            ticket._rank = float(i)

    # Pass 3: resolve ephemeral 'move' attrs
    _resolve_move_attrs(project.tickets, project)


def _assign_positional_ranks(tickets, project, legacy_groups):
    """Pass 1: assign _rank from file position, stash legacy rank values."""
    has_legacy = False
    parent_key = id(tickets)  # unique key for this sibling group

    for i, ticket in enumerate(tickets):
        ticket._rank = float(i)

        # Check for legacy rank attr
        stored_rank = ticket.attrs.pop("rank", None)
        if stored_rank is not None:
            ticket.dirty = True
            try:
                rank_float = float(stored_rank)
            except (ValueError, TypeError):
                rank_float = float('inf')
            if parent_key not in legacy_groups:
                legacy_groups[parent_key] = []
            legacy_groups[parent_key].append((rank_float, i, ticket))
            has_legacy = True

        # Recurse into children
        _assign_positional_ranks(ticket.children, project, legacy_groups)

    # If some siblings had legacy rank but not all, add the ones without
    if has_legacy and parent_key in legacy_groups:
        ranked_tickets = {id(t) for _, _, t in legacy_groups[parent_key]}
        for i, ticket in enumerate(tickets):
            if id(ticket) not in ranked_tickets:
                legacy_groups[parent_key].append((float('inf'), i, ticket))


def _resolve_move_attrs(tickets, project):
    """Pass 3: resolve ephemeral 'move' attrs on all tickets."""
    for ticket in list(tickets):
        move_val = ticket.attrs.pop("move", None)
        if move_val is not None:
            ticket.dirty = True
            _resolve_move_expr(move_val, ticket, project)
        _resolve_move_attrs(ticket.children, project)
# }}} # SOURCE END: 060-parser.py

# SOURCE START: 070-bulk.py {{{
# ---------------------------------------------------------------------------
# Bulk Ticket Creation
# ---------------------------------------------------------------------------

def _scan_bulk_headers(text):
    """Scan markdown text for ticket headers and return a list of tuples.

    Each tuple is (line_idx, placeholder_or_none, is_new) where:
    - line_idx: the 0-based line index in the text
    - placeholder_or_none: the placeholder name (e.g. "newAuth") or None
    - is_new: True if the ticket needs a new ID (placeholder or missing ID)
    """
    lines = text.split('\n')
    results = []
    seen_placeholders = set()
    for i, line in enumerate(lines):
        m = RE_TICKET_BULK.match(line)
        if not m:
            continue
        raw_id = m.group("id")
        if raw_id is not None and raw_id.isdigit():
            # Existing numeric ID
            results.append((i, None, False))
        else:
            # Placeholder or missing ID — both are "new"
            placeholder = raw_id  # None if missing, string if placeholder
            if placeholder is not None:
                if placeholder in seen_placeholders:
                    raise SystemExit(
                        f"Duplicate placeholder '{{#{placeholder}}}' "
                        f"on line {i + 1}"
                    )
                seen_placeholders.add(placeholder)
            results.append((i, placeholder, True))
    return results


def _allocate_bulk_ids(project, headers, mode="edit"):
    """Allocate IDs for new tickets without mutating project.next_id.

    Args:
        project: Project instance
        headers: list from _scan_bulk_headers() — [(line_idx, placeholder, is_new), ...]
        mode: "create" (error on numeric IDs) or "edit" (allow them)

    Returns:
        (placeholder_map, new_ids, id_for_missing, next_id)
        - placeholder_map: {"#placeholder": "#N", ...} for placeholder substitution
        - new_ids: set of allocated integer IDs
        - id_for_missing: {line_idx: allocated_id} for headers with no ID
        - next_id: what project.next_id should become on commit
    """
    if mode == "create":
        for line_idx, placeholder, is_new in headers:
            if not is_new:
                raise SystemExit(
                    f"In create mode, all tickets must be new; "
                    f"found existing numeric ID on line {line_idx + 1}"
                )

    placeholder_map = {}
    new_ids = set()
    id_for_missing = {}
    counter = project.next_id

    for line_idx, placeholder, is_new in headers:
        if not is_new:
            continue
        allocated = counter
        counter += 1
        new_ids.add(allocated)
        if placeholder is not None:
            placeholder_map[f"#{placeholder}"] = f"#{allocated}"
        else:
            id_for_missing[line_idx] = allocated

    return placeholder_map, new_ids, id_for_missing, counter


def _substitute_bulk_text(text, placeholder_map, id_for_missing):
    """Replace placeholders and insert IDs for missing-ID headers.

    Args:
        text: full input markdown string
        placeholder_map: {"#placeholder": "#N", ...} from _allocate_bulk_ids
        id_for_missing: {line_idx: allocated_id} for headers with no ID at all

    Returns: substituted text with all real IDs.
    Raises SystemExit on undefined placeholder references.
    """
    lines = text.split("\n")

    # Step 1: Insert {#N} into header lines that had no ID
    for line_idx, allocated_id in id_for_missing.items():
        line = lines[line_idx].rstrip("\n")
        lines[line_idx] = f"{line} {{#{allocated_id}}}"

    # Step 2: Rejoin and replace all placeholder references with real IDs.
    # Use word-boundary lookahead to avoid prefix collisions
    # (e.g. #auth must not match inside #auth-svc).
    result = "\n".join(lines)
    for placeholder, real_id in placeholder_map.items():
        result = re.sub(re.escape(placeholder) + r'(?![a-zA-Z0-9_-])',
                        real_id, result)

    return result


def _parse_bulk_markdown(text, project, parent, mode="create"):
    """Parse markdown containing ticket hierarchy, auto-assigning IDs.

    Args:
        text: markdown string with ticket headers
        project: Project instance
        parent: parent Ticket or None for top-level
        mode: "create" (error on numeric IDs) or "edit" (allow them)

    Returns:
        (tickets, new_ids)
        - tickets: list of top-level parsed Ticket objects
        - new_ids: set of newly allocated integer IDs

    Side effects: commits project.next_id on success, registers new tickets.
    """
    # Step 0 — Snapshot
    saved_next_id = project.next_id
    saved_metadata = (project.sections["metadata"].get_attr("next_id")
                      if "metadata" in project.sections else None)

    try:
        # Step 1 — Scan headers
        headers = _scan_bulk_headers(text)
        if mode == "create" and not headers:
            raise SystemExit("No ticket headers found in input.")

        # Step 2 — Allocate IDs
        placeholder_map, new_ids, id_for_missing, next_counter = (
            _allocate_bulk_ids(project, headers, mode)
        )

        # Step 3 — Substitute
        substituted = _substitute_bulk_text(
            text, placeholder_map, id_for_missing
        )

        # Step 4 — Parse
        lines = substituted.split("\n")

        # If parent is specified, re-indent before parsing
        if parent is not None:
            indent_prefix = " " * (parent.indent_level + 2)
            reindented = []
            for line in lines:
                if line.strip():
                    reindented.append(indent_prefix + line)
                else:
                    reindented.append("")
            lines = reindented

        tickets = []
        _parse_ticket_region(lines, project, tickets, parent, 0)

        # Step 5 — Fill defaults for new tickets
        now = _now()

        def _fill_defaults(ticket):
            if ticket.node_id in new_ids:
                if "status" not in ticket.attrs:
                    ticket.attrs["status"] = "open"
                if "created" not in ticket.attrs:
                    ticket.attrs["created"] = now
                if "updated" not in ticket.attrs:
                    ticket.attrs["updated"] = now
                ticket.dirty = True
            for child in ticket.children:
                _fill_defaults(child)

        for t in tickets:
            _fill_defaults(t)

        # Step 6 — Process move expressions and assign ranks in text order
        def _process_moves(ticket):
            if ticket.node_id in new_ids:
                move_val = ticket.attrs.pop("move", None)
                if move_val is not None:
                    ticket.dirty = True
                    _resolve_move_expr(move_val, ticket, project)
                else:
                    siblings = (ticket.parent.children
                                if ticket.parent and
                                isinstance(ticket.parent, Ticket)
                                else project.tickets)
                    ticket._rank = rank_last(siblings)
            for child in ticket.children:
                _process_moves(child)

        for t in tickets:
            _process_moves(t)

        # Step 7 — Commit
        project.next_id = next_counter
        if "metadata" in project.sections:
            project.sections["metadata"].set_attr(
                "next_id", str(project.next_id)
            )

        return tickets, new_ids

    except Exception:
        # Restore on error
        project.next_id = saved_next_id
        if saved_metadata is not None and "metadata" in project.sections:
            project.sections["metadata"].set_attr("next_id", saved_metadata)
        raise

# }}} # SOURCE END: 070-bulk.py

# SOURCE START: 080-serialize.py {{{
# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------

def serialize(project):
    """Serialize a Project back to markdown text."""
    out = []

    # Collect all raw_lines from project header region
    for rl in project.raw_lines:
        out.append(rl)

    # Sections in insertion order
    for sid, section in project.sections.items():
        if sid == "tickets":
            _serialize_tickets_section(section, project, out)
        else:
            _serialize_section(section, out)

    # Collapse runs of multiple blank lines into single blank lines
    collapsed = []
    for line in out:
        if line.strip() == '' and collapsed and collapsed[-1].strip() == '':
            continue
        collapsed.append(line)

    text = "\n".join(collapsed)
    # Handle trailing newline
    if project._trailing_newline and not text.endswith('\n'):
        text += "\n"
    return text


def _serialize_section(section, out):
    """Serialize a non-tickets section."""
    if not section.dirty:
        for rl in section.raw_lines:
            out.append(rl)
    else:
        out.append(f"## {section.title} {{#{section.node_id}}}")
        out.append("")
        for key, value in section.attrs.items():
            out.append(f"    {key}: {value}")
        if section.attrs:
            out.append("")
        for bl in section.body_lines:
            out.append(bl)
        if section.body_lines or not section.attrs:
            out.append("")


def _serialize_tickets_section(section, project, out):
    """Serialize the tickets section."""
    if not section.dirty and not any(t.dirty or _any_dirty(t) for t in project.tickets):
        # Nothing dirty — emit raw
        for rl in section.raw_lines:
            out.append(rl)
        return

    # Regenerate tickets section
    out.append(f"## Tickets {{#tickets}}")
    out.append("")
    for ticket in sort_by_rank(project.tickets):
        _serialize_ticket(ticket, out)
    # Trailing blank line
    out.append("")


def _any_dirty(ticket):
    """Check if ticket or any descendant is dirty."""
    if ticket.dirty:
        return True
    for c in ticket.children:
        if _any_dirty(c):
            return True
    if ticket.comments and ticket.comments.dirty:
        return True
    return False


def _serialize_ticket(ticket, out):
    """Serialize a ticket — raw if clean, regenerated if dirty."""
    if not ticket.dirty and not _any_dirty(ticket):
        for rl in ticket.raw_lines:
            out.append(rl)
    else:
        _regenerate_ticket(ticket, out)


def _ticket_indents(ticket):
    """Return (bullet, content_indent, attr_indent) for a ticket's indent level."""
    indent = " " * ticket.indent_level
    bullet = f"{indent}* "
    content_indent = " " * (ticket.indent_level + 2)
    attr_indent = content_indent + "    "
    return bullet, content_indent, attr_indent


def _regenerate_ticket(ticket, out):
    """Regenerate ticket from structured data."""
    bullet, content_indent, attr_indent = _ticket_indents(ticket)

    out.append(f"{bullet}## Ticket: {ticket.ticket_type}: {ticket.title} {{#{ticket.node_id}}}")
    out.append("")

    # Attributes
    for key, value in ticket.attrs.items():
        if key == "move":
            continue
        out.append(f"{attr_indent}{key}: {value}")

    if ticket.attrs:
        out.append("")

    # Body
    for bl in ticket.body_lines:
        out.append(bl)

    if ticket.body_lines:
        out.append("")

    # Comments
    if ticket.comments:
        _regenerate_comments(ticket.comments, out)
        out.append("")

    # Children
    for child in sort_by_rank(ticket.children):
        _serialize_ticket(child, out)


def _regenerate_ticket_only(ticket, out):
    """Regenerate ticket with comments but without children."""
    bullet, content_indent, attr_indent = _ticket_indents(ticket)

    out.append(f"{bullet}## Ticket: {ticket.ticket_type}: {ticket.title} {{#{ticket.node_id}}}")
    out.append("")

    for key, value in ticket.attrs.items():
        if key == "move":
            continue
        out.append(f"{attr_indent}{key}: {value}")

    if ticket.attrs:
        out.append("")

    for bl in ticket.body_lines:
        out.append(bl)

    if ticket.body_lines:
        out.append("")

    if ticket.comments:
        _regenerate_comments(ticket.comments, out)
        out.append("")


def _regenerate_comments(comments, out):
    """Regenerate comments section."""
    indent = " " * comments.indent_level
    out.append(f"{indent}* ## Comments {{#{comments.node_id}}}")
    out.append("")
    for comment in comments.comments:
        _regenerate_comment(comment, out)


def _regenerate_comment(comment, out):
    """Regenerate a single comment and its children."""
    indent = " " * comment.indent_level
    out.append(f"{indent}* {comment.title} {{#{comment.node_id}}}")
    out.append("")
    for bl in comment.body_lines:
        out.append(bl)
    for child in comment.children:
        _regenerate_comment(child, out)

# }}} # SOURCE END: 080-serialize.py

# SOURCE START: 090-dsl-sandbox.py {{{
# ---------------------------------------------------------------------------
# DSL Sandbox
# ---------------------------------------------------------------------------

DSL_FILTER_NAMES = (set(SAFE_BUILTINS)
                    | {"file", "parent_of", "is_descendant_of", "children_of"}
                    | set(Ticket(0, "").as_namespace())
                    | {"ready"})


def _eval_dsl(expr, ns, context="expression"):
    """Evaluate a DSL expression with nice error messages."""
    try:
        return eval(expr, {"__builtins__": {}}, ns)
    except SyntaxError as e:
        raise SystemExit(f"Error: invalid {context}: {expr}\n  {e.msg}")
    except Exception as e:
        raise SystemExit(f"Error: {context} failed: {expr}\n  {type(e).__name__}: {e}")


def _make_dsl_namespace(ticket):
    """Build DSL namespace for a ticket with project-level functions."""
    ns = DefaultNamespace(SAFE_BUILTINS)
    ns["file"] = _file
    ns.update(ticket.as_namespace())

    def _parent_of(ticket_id):
        """Return parent ticket ID of ticket #N, or 0 if root."""
        ticket_id = int(ticket_id)
        if ticket_id == 0:
            return 0
        node = _project.lookup(str(ticket_id))
        if node is None or not isinstance(node, Ticket):
            return 0
        return node.parent.node_id if node.parent else 0

    def _is_descendant_of(parent_id, child_id=None):
        """Check if child is a descendant of parent.

        parent_id=0 means root (all tickets are descendants).
        If child_id is omitted, checks the current ticket.
        """
        parent_id = int(parent_id)
        if child_id is not None:
            child_id = int(child_id)
            node = _project.lookup(str(child_id))
            if node is None or not isinstance(node, Ticket):
                return False
        else:
            node = ticket
        if parent_id == 0:
            return True
        p = node.parent
        while p is not None:
            if p.node_id == parent_id:
                return True
            p = p.parent
        return False

    def _children_of(ticket_id, recursive=False):
        """Return list of child ticket IDs of ticket #N.

        ticket_id=0 means root (returns top-level ticket IDs).
        If recursive=True, returns all descendant IDs.
        """
        ticket_id = int(ticket_id)
        if ticket_id == 0:
            source = _project.tickets
        else:
            node = _project.lookup(str(ticket_id))
            if node is None or not isinstance(node, Ticket):
                return []
            source = node.children
        if not recursive:
            return [c.node_id for c in source]
        result = []
        def _walk(tickets):
            for t in tickets:
                result.append(t.node_id)
                _walk(t.children)
        _walk(source)
        return result

    ns["parent_of"] = _parent_of
    ns["is_descendant_of"] = _is_descendant_of
    ns["children_of"] = _children_of

    # Compute ready: is_active + no active blockers + no active children
    def _compute_ready():
        if not ns.get("is_active"):
            return False
        links = ns.get("links", {})
        for bid in links.get("blocked", []):
            blocker = _project.lookup(str(bid))
            if blocker and isinstance(blocker, Ticket):
                bstatus = blocker.get_attr("status", "open")
                if bstatus in ACTIVE_STATUSES or bstatus == "":
                    return False
        for child in ticket.children:
            cstatus = child.get_attr("status", "open")
            if cstatus in ACTIVE_STATUSES or cstatus == "":
                return False
        return True

    ns["ready"] = _compute_ready()
    return ns


# Module-level reference to current project for DSL functions
_project = None


def eval_filter(ticket, expr):
    """Evaluate a filter expression against a ticket. Returns truthy/falsy."""
    ns = _make_dsl_namespace(ticket)
    return _eval_dsl(expr, ns, "filter expression")


def eval_format(ticket, expr):
    """Evaluate a format expression against a ticket. Returns str."""
    ns = _make_dsl_namespace(ticket)
    return str(_eval_dsl(expr, ns, "format expression"))


def apply_mod(ticket, project, expr):
    """Apply a modification expression to a ticket."""
    content_indent = " " * (ticket.indent_level + 2)

    def _set(**kw):
        for k, v in kw.items():
            if k == "title":
                ticket.title = v
                ticket.dirty = True
            elif k == "text":
                ticket.body_lines = [
                    content_indent + line if line else ""
                    for line in v.split("\n")
                ] if v else []
                ticket.dirty = True
            elif k == "move":
                ticket.attrs["move"] = v
                _resolve_move_expr(v, ticket, project)
            else:
                ticket.set_attr(k, v)
            if k == "links" and project:
                # Handle interlinking for links set via mod
                pass
        if "updated" not in kw:
            ticket.set_attr("updated", _now())
        return True

    def _add(**kw):
        for k, v in kw.items():
            if k == "text":
                new_lines = [
                    content_indent + line if line else ""
                    for line in str(v).split("\n")
                ]
                if ticket.body_lines:
                    ticket.body_lines.extend(new_lines)
                else:
                    ticket.body_lines = new_lines
                ticket.dirty = True
            elif k == "links":
                # Parse the link and append
                existing = ticket.get_attr("links", "")
                if existing:
                    ticket.set_attr("links", existing + " " + str(v))
                else:
                    ticket.set_attr("links", str(v))
                # Handle interlinking
                if project:
                    parsed = _parse_links(str(v))
                    for ltype, ids in parsed.items():
                        for tid in ids:
                            _add_interlink(project, ticket, ltype, tid)
            elif k == "comment":
                # Create a new comment
                if project:
                    cid = project.allocate_id()
                    _add_comment_to_ticket(ticket, project, cid, str(v))
            else:
                raise ValueError(
                    f"Cannot add to scalar attribute '{k}'. Use set() instead."
                )
        ticket.set_attr("updated", _now())
        return True

    def _delete(*names):
        for name in names:
            ticket.del_attr(name)
        ticket.set_attr("updated", _now())
        return True

    def _link(link_type, target_id):
        add_link(project, ticket, link_type, target_id)
        ticket.set_attr("updated", _now())
        return True

    def _unlink(link_type, target_id):
        remove_link(project, ticket, link_type, target_id)
        ticket.set_attr("updated", _now())
        return True

    ns = _make_dsl_namespace(ticket)
    ns["set"] = _set
    ns["add"] = _add
    ns["delete"] = _delete
    ns["link"] = _link
    ns["unlink"] = _unlink
    _eval_dsl(expr, ns, "mod expression")


def _add_comment_to_ticket(ticket, project, comment_num, text):
    """Add a new comment to a ticket."""
    comment_id = f"{ticket.node_id}:comment:{comment_num}"
    comment = _make_comment(comment_id, text, ticket.indent_level + 4)

    if ticket.comments is None:
        comments_id = f"{ticket.node_id}:comments"
        comments = Comments(comments_id)
        comments.indent_level = ticket.indent_level + 2
        comments.dirty = True
        ticket.comments = comments
        project.register(comments)

    ticket.comments.comments.append(comment)
    ticket.comments.dirty = True
    ticket.dirty = True
    project.register(comment)

# }}} # SOURCE END: 090-dsl-sandbox.py

# SOURCE START: 095-edit-files.py {{{
# ---------------------------------------------------------------------------
# Non-Interactive Edit File Utilities
# ---------------------------------------------------------------------------

import glob
import hashlib


def _edit_content_hash(content):
    """Compute a short hash of content for edit file naming."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:8]


def _edit_file_parts(plan_filename):
    """Split plan filename into (base, ext) for edit file naming.

    E.g. '.PLAN.md' -> ('.PLAN', '.md'), 'MYPLAN' -> ('MYPLAN', '')
    """
    if plan_filename.endswith(".md"):
        return plan_filename[:-3], ".md"
    return plan_filename, ""


def _edit_file_encode(plan_filename, ticket_id, flags, content_hash):
    """Build temp filename from edit parameters.

    plan_filename: basename of plan file, e.g. '.PLAN.md'
    ticket_id: str (digits)
    flags: set of single-letter strings, e.g. {"r"}
    content_hash: str, 8 hex chars
    """
    base, ext = _edit_file_parts(plan_filename)
    parts = ["edit", str(ticket_id)]
    for f in sorted(flags):
        assert len(f) == 1 and f.isalpha()
        parts.append(f)
    parts.append(content_hash[:8])
    return base + "-" + "-".join(parts) + ext


def _edit_file_decode(filename, plan_filename):
    """Parse temp filename -> (ticket_id, flags_set, content_hash) or None.

    Returns None if filename does not match the pattern.
    """
    base, ext = _edit_file_parts(plan_filename)
    prefix = base + "-edit-"
    if not filename.startswith(prefix) or not filename.endswith(ext):
        return None
    stem = filename[len(prefix):]
    if ext:
        stem = stem[:-len(ext)]
    parts = stem.split("-")
    if len(parts) < 2:
        return None
    ticket_id = parts[0]
    if not ticket_id.isdigit():
        return None
    content_hash = parts[-1]
    if len(content_hash) != 8:
        return None
    flags = set(parts[1:-1])
    return ticket_id, flags, content_hash


def _edit_file_glob(plan_dir, plan_filename, ticket_id=None):
    """Find edit files in plan_dir, optionally filtered by ticket_id.

    Returns list of (filename, full_path) tuples.
    """
    base, ext = _edit_file_parts(plan_filename)
    pattern = os.path.join(plan_dir, base + "-edit-*" + ext)
    results = []
    for path in glob.glob(pattern):
        fname = os.path.basename(path)
        decoded = _edit_file_decode(fname, plan_filename)
        if decoded is None:
            continue
        if ticket_id is not None and decoded[0] != str(ticket_id):
            continue
        results.append((fname, path))
    return results


def _edit_list_remaining(plan_dir, plan_filename, output, exclude_path=None):
    """List remaining in-flight edit files (for status messages)."""
    remaining = _edit_file_glob(plan_dir, plan_filename)
    if exclude_path:
        remaining = [(f, p) for f, p in remaining if p != exclude_path]
    if remaining:
        output.append("")
        output.append(f"In-flight edits ({len(remaining)}):")
        for fname, fpath in remaining:
            mtime = os.path.getmtime(fpath)
            age = time.time() - mtime
            if age < 60:
                age_str = f"{int(age)}s ago"
            elif age < 3600:
                age_str = f"{int(age / 60)}m ago"
            else:
                age_str = f"{int(age / 3600)}h ago"
            output.append(f"  {fname} ({age_str})")
# }}} # SOURCE END: 095-edit-files.py

# SOURCE START: 100-rank.py {{{
# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def midpoint_rank(a, b):
    """Calculate midpoint between a and b. Returns raw float (no rounding)."""
    if a == b:
        return a
    return (a + b) / 2.0


def rank_first(siblings):
    """Return a rank that places before all siblings."""
    if not siblings:
        return 0
    ranks = _sorted_ranks(siblings)
    first = ranks[0]
    return int(first) - 1 if first == int(first) else int(math.floor(first)) - 1


def rank_last(siblings):
    """Return a rank that places after all siblings."""
    if not siblings:
        return 0
    ranks = _sorted_ranks(siblings)
    last = ranks[-1]
    return int(last) + 1 if last == int(last) else int(math.ceil(last)) + 1


def rank_before(target, siblings):
    """Return a rank that places just before target among siblings."""
    ranks = _sorted_ranks(siblings)
    target_rank = _get_rank(target)
    try:
        idx = ranks.index(target_rank)
    except ValueError:
        idx = _bisect_left(ranks, target_rank)
    if idx == 0:
        return rank_first(siblings)
    return midpoint_rank(ranks[idx - 1], target_rank)


def rank_after(target, siblings):
    """Return a rank that places just after target among siblings."""
    ranks = _sorted_ranks(siblings)
    target_rank = _get_rank(target)
    try:
        idx = ranks.index(target_rank)
    except ValueError:
        idx = _bisect_left(ranks, target_rank)
    if idx >= len(ranks) - 1:
        return rank_last(siblings)
    return midpoint_rank(target_rank, ranks[idx + 1])


def _bisect_left(a, x):
    """Return leftmost index where x could be inserted in sorted list a."""
    lo, hi = 0, len(a)
    while lo < hi:
        mid = (lo + hi) // 2
        if a[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _get_rank(ticket):
    """Get rank from ticket's internal _rank property."""
    return ticket._rank if ticket._rank is not None else 0.0


def _sorted_ranks(siblings):
    """Get sorted list of ranks from sibling tickets."""
    ranks = [_get_rank(s) for s in siblings]
    ranks.sort()
    return ranks


def sort_by_rank(tickets):
    """Sort tickets by rank, falling back to id for ties."""
    return sorted(tickets, key=lambda t: (_get_rank(t), t.node_id or 0))


def _update_descendant_indent(ticket):
    """Recursively update indent_level of all descendants after reparenting."""
    for child in ticket.children:
        if isinstance(child, Ticket):
            child.indent_level = ticket.indent_level + 2
            child.dirty = True
            _update_descendant_indent(child)


def _reparent_ticket(ticket, new_parent, project):
    """Move ticket under new_parent (None for root). Handles detach + attach."""
    old_parent = ticket.parent if isinstance(ticket.parent, Ticket) else None
    if new_parent is old_parent:
        return
    # Detach
    if old_parent:
        old_parent.children = [c for c in old_parent.children if c is not ticket]
        old_parent.dirty = True
    else:
        project.tickets = [t for t in project.tickets if t is not ticket]
    # Attach
    if new_parent:
        ticket.parent = new_parent
        ticket.indent_level = new_parent.indent_level + 2
        new_parent.children.append(ticket)
        new_parent.dirty = True
    else:
        ticket.parent = None
        ticket.indent_level = 0
        project.tickets.append(ticket)
    ticket.dirty = True
    _update_descendant_indent(ticket)


def _resolve_move_expr(value, ticket, project):
    """Resolve a move expression, updating ticket._rank and possibly reparenting.

    Accepts positional expressions:
      "first" / "last"         — among current siblings
      "first N" / "last N"     — as child of ticket N (0 for root)
      "before N" / "after N"   — as sibling of ticket N

    Returns True if resolved, False if not a valid expression.
    """
    s = str(value).strip()
    if not s or not project:
        return False

    parts = s.split()
    direction = parts[0].lower() if parts else ""
    ref_id_str = parts[1].lstrip('#') if len(parts) >= 2 else None

    if direction not in ("first", "last", "before", "after"):
        return False

    # Resolve reference ticket
    ref = None
    if ref_id_str is not None:
        parsed_id = _parse_id_arg(ref_id_str)
        if parsed_id is None:
            return False
        if parsed_id != "0":
            ref = project.lookup(parsed_id)
            if ref is None or not isinstance(ref, Ticket):
                return False
            if ref is ticket:
                return False

    if direction in ("before", "after"):
        if ref is None:
            return False
        new_parent = ref.parent if isinstance(ref.parent, Ticket) else None
        _reparent_ticket(ticket, new_parent, project)
        siblings = new_parent.children if new_parent else project.tickets
        if direction == "before":
            ticket._rank = rank_before(ref, siblings)
        else:
            ticket._rank = rank_after(ref, siblings)
        return True

    # first / last
    if ref_id_str is not None:
        _reparent_ticket(ticket, ref, project)
        siblings = ref.children if ref else project.tickets
    else:
        if ticket.parent and isinstance(ticket.parent, Ticket):
            siblings = ticket.parent.children
        else:
            siblings = project.tickets

    if direction == "first":
        ticket._rank = rank_first(siblings)
    else:
        ticket._rank = rank_last(siblings)
    return True
# }}} # SOURCE END: 100-rank.py

# SOURCE START: 110-link.py {{{
# ---------------------------------------------------------------------------
# Link Interlinking
# ---------------------------------------------------------------------------

def add_link(project, source, link_type, target_id):
    """Add a link from source to target, and the mirror link on target."""
    # Add to source
    _raw_add_link(source, link_type, target_id)
    # Add mirror
    mirror = LINK_MIRRORS.get(link_type)
    if mirror and project:
        target = project.lookup(target_id)
        if target and isinstance(target, Ticket):
            _raw_add_link(target, mirror, source.node_id)


def remove_link(project, source, link_type, target_id):
    """Remove a link from source to target, and the mirror link on target."""
    _raw_remove_link(source, link_type, target_id)
    mirror = LINK_MIRRORS.get(link_type)
    if mirror and project:
        target = project.lookup(target_id)
        if target and isinstance(target, Ticket):
            _raw_remove_link(target, mirror, source.node_id)


def _raw_add_link(ticket, link_type, target_id):
    """Add a single link entry to a ticket's links attr."""
    links = _parse_links(ticket.get_attr("links", ""))
    ids = links.setdefault(link_type, [])
    tid = int(target_id)
    if tid not in ids:
        ids.append(tid)
    ticket.set_attr("links", _serialize_links(links))


def _raw_remove_link(ticket, link_type, target_id):
    """Remove a single link entry from a ticket's links attr."""
    links = _parse_links(ticket.get_attr("links", ""))
    tid = int(target_id)
    if link_type in links and tid in links[link_type]:
        links[link_type].remove(tid)
        if not links[link_type]:
            del links[link_type]
    result = _serialize_links(links)
    if result:
        ticket.set_attr("links", result)
    else:
        ticket.del_attr("links")


def _add_interlink(project, source, link_type, target_id):
    """Add mirror link only (source already has the link)."""
    mirror = LINK_MIRRORS.get(link_type)
    if mirror and project:
        target = project.lookup(target_id)
        if target and isinstance(target, Ticket):
            _raw_add_link(target, mirror, source.node_id)

# }}} # SOURCE END: 110-link.py

# SOURCE START: 115-merge-engine.py {{{
# ---------------------------------------------------------------------------
# Merge Engine (structure-aware three-way merge)
# ---------------------------------------------------------------------------
#
# Pure engine: no git, no filesystem, no CLI. Operates on in-memory Project
# trees produced by parse(). It is concatenated into plan.py after the data
# model (040), utils (030), bulk (070), serialize (080), rank (100) and link
# (110) modules, so it may freely use the names they define.

import hashlib as _hashlib

# Sentinel: a side that removed (deleted) a node.
DELETED = "<DELETED>"

# Sentinel field name for a whole-node (modify/delete) conflict.
NODE_FIELD = "<node>"

# Auto-maintained timestamp attrs. These are NEVER allowed to conflict: a
# co-edit of any field would otherwise make `updated` diverge and spuriously
# conflict. They are excluded from conflict detection (and from the
# modify-vs-delete "was it edited" test) and merged by rule instead:
#   updated -> latest of base/mine/theirs
#   created -> earliest of base/mine/theirs (normally base)
TIMESTAMP_ATTRS = ("updated", "created")


def normalize_conflict_text(text):
    """Normalize text for checksum/identity comparison.

    - CRLF -> LF
    - strip trailing whitespace on each line
    - strip leading and trailing blank lines
    """
    if text is None:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    start = 0
    end = len(lines)
    while start < end and lines[start] == "":
        start += 1
    while end > start and lines[end - 1] == "":
        end -= 1
    return "\n".join(lines[start:end])


def conflict_sum(text):
    """First 8 hex chars of sha256(normalize_conflict_text(text))."""
    norm = normalize_conflict_text(text)
    return _hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]


class Conflict:
    """A single merge conflict.

    Fields mirror the design's "Conflict model" section.
    """

    def __init__(self, id, node_id, node_kind, field, ctype,
                 base_value, mine_value, theirs_value,
                 mine_lines=None, theirs_lines=None):
        self.id = id
        self.node_id = node_id          # stable id string, e.g. "12" / "7:comment:9"
        self.node_kind = node_kind      # "ticket" | "comment"
        self.field = field              # "title"/"status"/<attr>/"body"/"parent"/NODE_FIELD
        self.ctype = ctype              # "field" | "text" | "modify-delete"
        self.base_value = base_value    # str | None
        self.mine_value = mine_value    # str | None (DELETED sentinel for removal)
        self.theirs_value = theirs_value
        self.mine_lines = mine_lines    # (start, end) | None (advisory)
        self.theirs_lines = theirs_lines

    def key(self):
        """Resolution key: (node_id, field)."""
        return (str(self.node_id), self.field)

    def __repr__(self):
        return (f"Conflict(id={self.id}, node={self.node_id!r}, "
                f"field={self.field!r}, ctype={self.ctype!r})")


class MergeResult:
    """Result of merge_trees()."""

    def __init__(self, project, conflicts, renumber_map):
        self.project = project              # valid merged Project (mine defaults)
        self.conflicts = conflicts          # list[Conflict]
        self.renumber_map = renumber_map    # {old_int_id: new_int_id} on renumbered side


# ---------------------------------------------------------------------------
# Helpers: extracting comparable field values from nodes
# ---------------------------------------------------------------------------

def _ticket_index(project):
    """Map str(id) -> Ticket for every ticket in the project (recursive)."""
    out = {}

    def walk(tickets):
        for t in tickets:
            out[str(t.node_id)] = t
            walk(t.children)

    if project is not None:
        walk(project.tickets)
    return out


def _comment_index(project):
    """Map comment-id -> (Comment, owning Ticket) for all comments (recursive)."""
    out = {}

    def walk_comments(comments, ticket):
        for c in comments:
            out[str(c.node_id)] = (c, ticket)
            walk_comments(c.children, ticket)

    def walk_tickets(tickets):
        for t in tickets:
            if t.comments is not None:
                walk_comments(t.comments.comments, t)
            walk_tickets(t.children)

    if project is not None:
        walk_tickets(project.tickets)
    return out


def _body_text(node):
    """Position-independent body text of a ticket/comment (dedented)."""
    return textwrap.dedent("\n".join(node.body_lines))


def _parent_id_of(ticket):
    """Stable parent id string, or None for a top-level ticket."""
    p = ticket.parent
    if p is not None and isinstance(p, Ticket):
        return str(p.node_id)
    return None


def _ticket_scalar_fields(ticket, include_timestamps=True):
    """Return the comparable scalar field map for a ticket.

    Keys: 'title', 'type' + every attr key. `links` is treated as a normal attr
    (we compare its serialized string field-by-field like any other attr).
    When include_timestamps is False, the auto-maintained timestamp attrs are
    omitted so they never participate in conflict detection.
    """
    fields = {
        "title": ticket.title,
        "type": ticket.ticket_type,
    }
    for k, v in ticket.attrs.items():
        if k == "move":
            continue
        if not include_timestamps and k in TIMESTAMP_ATTRS:
            continue
        fields[k] = v
    return fields


def _merge_timestamp(key, bv, mv, tv):
    """Merge a timestamp attr by rule. Returns the chosen value, or None.

    `updated` -> the latest (max) of the present values; `created` -> the
    earliest (min). Values use the fixed 'YYYY-MM-DD HH:MM:SS TZ' format, which
    sorts chronologically as plain strings.
    """
    present = [v for v in (bv, mv, tv) if v is not None]
    if not present:
        return None
    if key == "updated":
        return max(present)
    # created (or any other timestamp attr) -> earliest
    return min(present)


def _max_used_id(base, mine, theirs):
    """Highest integer ticket id used across the three projects (0 if none)."""
    hi = 0
    for p in (base, mine, theirs):
        if p is None:
            continue
        for tid in _ticket_index(p):
            try:
                hi = max(hi, int(tid))
            except (ValueError, TypeError):
                pass
    return hi


# ---------------------------------------------------------------------------
# Reference rewriting (reuse of the bulk substitution approach)
# ---------------------------------------------------------------------------

def _rewrite_id_mentions(text, id_map):
    """Rewrite '#N' mentions in free text, word-boundary safe.

    Mirrors src/070-bulk.py::_substitute_bulk_text: each old id is replaced by
    its new id only when not followed by another id-character, so '#4' inside
    '#42' is never touched. Replacements happen against the original ids in one
    pass per id using non-overlapping placeholders to avoid chained rewrites
    (e.g. 4->5 then 5->6 must not turn an original #4 into #6).
    """
    if not id_map:
        return text
    # Two-phase substitution with unique sentinels to prevent re-substitution.
    sentinels = {}
    result = text
    for i, (old, new) in enumerate(id_map.items()):
        sentinel = "\x00MERGEID%d\x00" % i
        sentinels[sentinel] = "#%d" % new
        result = re.sub(r'#%d(?![a-zA-Z0-9_-])' % old,
                        sentinel, result)
    for sentinel, real in sentinels.items():
        result = result.replace(sentinel, real)
    return result


def _rewrite_body_lines(node, id_map):
    """Rewrite #N mentions across a node's body_lines in place."""
    if not id_map or not node.body_lines:
        return
    new_lines = []
    changed = False
    for line in node.body_lines:
        rewritten = _rewrite_id_mentions(line, id_map)
        if rewritten != line:
            changed = True
        new_lines.append(rewritten)
    if changed:
        node.body_lines = new_lines
        node.dirty = True


def _rewrite_links_attr(ticket, id_map):
    """Rewrite both-direction link targets in a ticket's links attr."""
    raw = ticket.get_attr("links", "")
    if not raw:
        return
    links = _parse_links(raw)
    changed = False
    for ltype, ids in links.items():
        new_ids = []
        for tid in ids:
            if tid in id_map:
                new_ids.append(id_map[tid])
                changed = True
            else:
                new_ids.append(tid)
        links[ltype] = new_ids
    if changed:
        ticket.set_attr("links", _serialize_links(links))


def _renumber_side(project, id_map):
    """Apply an old->new ticket-id remapping to an entire project in place.

    Rewrites: ticket node_ids, parent nesting (parent ids follow automatically
    via the object graph; only node_id needs changing), comment container and
    comment ids whose ticket was renumbered, links attrs in both directions,
    and #N mentions in body and comment text.
    """
    if not id_map:
        return

    # 1. Rewrite ticket node_ids and their comment subtree ids.
    def renumber_ticket(t):
        old = t.node_id
        if old in id_map:
            new = id_map[old]
            t.node_id = new
            t.dirty = True
            # comment container + comment ids carry the ticket id prefix
            if t.comments is not None:
                _retarget_comment_ids(t.comments, old, new)
        for child in t.children:
            renumber_ticket(child)

    def walk(tickets):
        for t in tickets:
            renumber_ticket(t)

    walk(project.tickets)

    # 2. Rewrite links (both directions) and #N body mentions on EVERY ticket,
    #    because a renumbered ticket may be referenced from anywhere.
    def walk_rewrite(tickets):
        for t in tickets:
            _rewrite_links_attr(t, id_map)
            _rewrite_body_lines(t, id_map)
            if t.comments is not None:
                _rewrite_comment_bodies(t.comments, id_map)
            walk_rewrite(t.children)

    walk_rewrite(project.tickets)

    # 3. Rebuild id_map registration.
    _reindex(project)


def _retarget_comment_ids(comments_node, old_tid, new_tid):
    """When a ticket is renumbered old_tid->new_tid, update its comment ids."""
    old_prefix = "%s:comment:" % old_tid
    new_prefix = "%s:comment:" % new_tid
    if comments_node.node_id == "%s:comments" % old_tid:
        comments_node.node_id = "%s:comments" % new_tid
        comments_node.dirty = True

    def walk(comments):
        for c in comments:
            if isinstance(c.node_id, str) and c.node_id.startswith(old_prefix):
                c.node_id = new_prefix + c.node_id[len(old_prefix):]
                c.dirty = True
            walk(c.children)

    walk(comments_node.comments)


def _rewrite_comment_bodies(comments_node, id_map):
    """Rewrite #N mentions in all comment titles/bodies under a container."""
    def walk(comments):
        for c in comments:
            new_title = _rewrite_id_mentions(c.title, id_map)
            if new_title != c.title:
                c.title = new_title
                c.dirty = True
            _rewrite_body_lines(c, id_map)
            walk(c.children)

    walk(comments_node.comments)


def _reindex(project):
    """Rebuild project.id_map from the current tree."""
    project.id_map = {}
    project.register(project)
    for sid, sec in project.sections.items():
        project.register(sec)

    def walk(tickets):
        for t in tickets:
            project.register(t)
            if t.comments is not None:
                project.register(t.comments)

                def walk_comments(comments):
                    for c in comments:
                        project.register(c)
                        walk_comments(c.children)

                walk_comments(t.comments.comments)
            walk(t.children)

    walk(project.tickets)


# ---------------------------------------------------------------------------
# Collision detection + renumber planning
# ---------------------------------------------------------------------------

def _plan_ticket_renumber(base, mine, theirs, renumber, hi):
    """Decide which colliding new ticket ids on the renumber side get reassigned.

    An independent-creation collision: a ticket id that is ABSENT from base but
    present in BOTH mine and theirs. The renumber side's copy gets a fresh id.

    Returns id_map ({old_int_id: new_int_id}).
    """
    base_idx = _ticket_index(base)
    mine_idx = _ticket_index(mine)
    theirs_idx = _ticket_index(theirs)

    side_idx = theirs_idx if renumber == "theirs" else mine_idx
    other_idx = mine_idx if renumber == "theirs" else theirs_idx

    id_map = {}
    counter = hi + 1
    # Deterministic order: ascending numeric id.
    colliding = []
    for sid in side_idx:
        if sid in base_idx:
            continue
        if sid in other_idx:
            try:
                colliding.append(int(sid))
            except (ValueError, TypeError):
                pass
    for old in sorted(colliding):
        id_map[old] = counter
        counter += 1
    return id_map


def _plan_comment_renumber(base, mine, theirs, renumber):
    """Decide which colliding new comment ids on the renumber side get bumped.

    A comment-id collision: a comment id ABSENT from base but present in BOTH
    sides on the SAME surviving ticket. We renumber the renumber side's comment
    to a fresh per-ticket number above the high-water mark of that ticket's
    comment numbers across both sides (+base).

    Returns {old_comment_id_str: new_comment_id_str}.
    """
    base_c = _comment_index(base)
    mine_c = _comment_index(mine)
    theirs_c = _comment_index(theirs)

    side_c = theirs_c if renumber == "theirs" else mine_c
    other_c = mine_c if renumber == "theirs" else theirs_c

    # Group colliding comment ids by their (original) ticket id.
    def parse_cid(cid):
        # "T:comment:N" -> (T_str, N_int) or None
        m = re.match(r'^(.+):comment:(\d+)$', cid)
        if not m:
            return None
        return m.group(1), int(m.group(2))

    colliding = []  # list of (ticket_str, n_int, old_cid)
    for cid in side_c:
        if cid in base_c:
            continue
        if cid in other_c:
            parsed = parse_cid(cid)
            if parsed:
                colliding.append((parsed[0], parsed[1], cid))

    if not colliding:
        return {}

    # Per-ticket high-water mark of comment numbers across all three trees.
    def hw_for_ticket(tstr):
        hw = 0
        for idx in (base_c, mine_c, theirs_c):
            for cid in idx:
                p = parse_cid(cid)
                if p and p[0] == tstr:
                    hw = max(hw, p[1])
        return hw

    cmap = {}
    counters = {}
    for tstr, n, old_cid in sorted(colliding, key=lambda x: (x[0], x[1])):
        if tstr not in counters:
            counters[tstr] = hw_for_ticket(tstr) + 1
        new_n = counters[tstr]
        counters[tstr] += 1
        cmap[old_cid] = "%s:comment:%d" % (tstr, new_n)
    return cmap


def _apply_comment_renumber(project, comment_id_map):
    """Apply a comment-id remapping (string->string) to a project in place."""
    if not comment_id_map:
        return
    cidx = _comment_index(project)
    for old_cid, new_cid in comment_id_map.items():
        entry = cidx.get(old_cid)
        if entry is not None:
            comment, _ticket = entry
            comment.node_id = new_cid
            comment.dirty = True
    _reindex(project)


# ---------------------------------------------------------------------------
# Three-way field merge
# ---------------------------------------------------------------------------

def _three_way_field(base_val, mine_val, theirs_val):
    """Resolve a single scalar field. Returns ('value', v) or ('conflict',).

    Values are strings or None (absent). Comparison is on normalized text only
    for deciding equality of present values; the returned value is the raw one.
    """
    bn = None if base_val is None else normalize_conflict_text(base_val)
    mn = None if mine_val is None else normalize_conflict_text(mine_val)
    tn = None if theirs_val is None else normalize_conflict_text(theirs_val)

    if mn == tn:
        # Same on both sides (covers identical change and no-change).
        return ("value", mine_val)
    # They differ. Did exactly one side change relative to base?
    mine_changed = (mn != bn)
    theirs_changed = (tn != bn)
    if mine_changed and not theirs_changed:
        return ("value", mine_val)
    if theirs_changed and not mine_changed:
        return ("value", theirs_val)
    # Both changed differently -> conflict.
    return ("conflict",)


# ---------------------------------------------------------------------------
# Building the merged tree
# ---------------------------------------------------------------------------

def _empty_project():
    p = Project()
    _bootstrap_project(p)
    return p


def merge_trees(base, mine, theirs, *, renumber="theirs",
                prefer=None, resolutions=None, two_way=False):
    """Structure-aware three-way merge of three Project trees.

    Returns a MergeResult. The merged project always uses the MINE value at any
    conflict so it serializes to a usable file even before resolution.

    two_way mode (used when reconciling from raw git conflict markers, where
    there is no common ancestor): a shared ID means *the same diverged node*,
    NOT an independent-creation collision. In this mode:
      - collision renumbering is SKIPPED entirely (no `renumber` behavior);
      - the base is empty, so a shared ID is field-merged with an empty base
        and any divergence conflicts (field/text); timestamps still merge by
        rule and never conflict;
      - an ID present on only one side is simply added (taken);
      - there are no modify/delete conflicts (no base to detect deletion).

    None-robustness: any of base/mine/theirs may be None and is treated as an
    empty Project (covers the merge-driver's empty-%A and file-new-on-a-side
    cases without crashing).
    """
    if renumber not in ("mine", "theirs"):
        raise ValueError("renumber must be 'mine' or 'theirs'")
    resolutions = resolutions or {}

    # None-robustness: substitute empty projects for any missing tree.
    if mine is None:
        mine = _empty_project()
    if theirs is None:
        theirs = _empty_project()
    # In two_way mode there is no meaningful base: force an empty one so shared
    # IDs are treated as the same node diverging from nothing.
    if two_way or base is None:
        base = _empty_project()

    # ----- Step 2: plan + apply collision renumbering on the renumber side. ---
    # Skipped entirely in two_way mode (shared IDs are the same node).
    ticket_id_map = {}
    if not two_way:
        hi = _max_used_id(base, mine, theirs)
        side_proj = theirs if renumber == "theirs" else mine

        ticket_id_map = _plan_ticket_renumber(base, mine, theirs, renumber, hi)
        if ticket_id_map:
            _renumber_side(side_proj, ticket_id_map)

        comment_id_map = _plan_comment_renumber(base, mine, theirs, renumber)
        if comment_id_map:
            _apply_comment_renumber(side_proj, comment_id_map)

    # Re-index everything after renumbering.
    base_idx = _ticket_index(base)
    mine_idx = _ticket_index(mine)
    theirs_idx = _ticket_index(theirs)

    conflicts = []
    counter = [1]

    def next_id():
        v = counter[0]
        counter[0] += 1
        return v

    # ----- Build the merged project as a fresh tree. ----------------------
    # We start from mine's structure (we are on mine's branch) and weave in
    # theirs-only nodes. Conflicts default to mine in-tree.
    merged = _build_skeleton(mine)

    # Resolve each ticket and stage its merged field set + presence decision.
    # We mutate the merged tree (copied from mine) in place. New theirs-only
    # tickets get appended.
    merged_idx = _ticket_index(merged)

    def record_field_conflict(node_id, node_kind, field, ctype,
                              base_v, mine_v, theirs_v):
        c = Conflict(next_id(), str(node_id), node_kind, field, ctype,
                     base_v, mine_v, theirs_v)
        conflicts.append(c)
        return c

    # --- Pass A: tickets present in mine (merge fields with base/theirs). ---
    for tid in mine_idx:
        m_t = mine_idx[tid]
        b_t = base_idx.get(tid)
        th_t = theirs_idx.get(tid)
        merged_t = merged_idx[tid]

        if th_t is None:
            # Not on theirs side.
            if b_t is not None:
                # Was in base, theirs deleted it. Did mine edit it?
                if _ticket_changed(b_t, m_t):
                    record_field_conflict(tid, "ticket", NODE_FIELD,
                                          "modify-delete",
                                          _node_repr(b_t), _node_repr(m_t),
                                          DELETED)
                    # Default to mine (keep node) in-tree.
                # else: theirs deleted, mine untouched -> honor delete.
                else:
                    _mark_for_deletion(merged_t)
            # else: mine-only new ticket -> keep as is.
            continue

        # Present on both mine and theirs (maybe base too).
        _merge_ticket_fields(b_t, m_t, th_t, merged_t,
                             record_field_conflict)
        _merge_comments(b_t, m_t, th_t, merged_t,
                        record_field_conflict, next_id)

    # --- Pass B: tickets present in theirs but NOT mine. -----------------
    for tid in theirs_idx:
        if tid in mine_idx:
            continue
        th_t = theirs_idx[tid]
        b_t = base_idx.get(tid)
        if b_t is not None:
            # Was in base, mine deleted it. Did theirs edit it?
            if _ticket_changed(b_t, th_t):
                record_field_conflict(tid, "ticket", NODE_FIELD,
                                      "modify-delete",
                                      _node_repr(b_t), DELETED,
                                      _node_repr(th_t))
                # Default to mine's decision (deletion) in-tree: do not add.
            # else: mine deleted, theirs untouched -> honor delete (skip).
            continue
        # theirs-only NEW ticket -> add it to the merged tree, placed after
        # mine's siblings under the same parent.
        _graft_theirs_ticket(th_t, theirs_idx, merged, merged_idx)

    # Remove tickets marked for deletion.
    _apply_deletions(merged)

    # ----- Apply prefer / resolutions to conflicts. -----------------------
    remaining = _resolve_conflicts(merged, conflicts, prefer, resolutions,
                                   mine_idx, theirs_idx, base_idx)

    # ----- Step 6: ensure tree is serializable; reindex. ------------------
    _finalize_ranks(merged)
    _reindex(merged)

    # ----- Step 7: next_id fixup. -----------------------------------------
    _fix_next_id(merged)

    return MergeResult(merged, remaining, ticket_id_map)


# ---------------------------------------------------------------------------
# Skeleton / cloning
# ---------------------------------------------------------------------------

def _build_skeleton(mine):
    """Deep-copy mine into the merged base tree we will mutate."""
    merged = copy.deepcopy(mine)
    _reindex(merged)
    return merged


def _node_repr(ticket):
    """A human-readable single-string repr of a ticket for modify-delete."""
    out = []
    bullet, content_indent, attr_indent = _ticket_indents(ticket)
    out.append("%s## Ticket: %s: %s {#%s}" %
               (bullet, ticket.ticket_type, ticket.title, ticket.node_id))
    for k, v in ticket.attrs.items():
        if k == "move":
            continue
        out.append("%s%s: %s" % (attr_indent, k, v))
    for bl in ticket.body_lines:
        out.append(bl)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Per-ticket field merge
# ---------------------------------------------------------------------------

def _ticket_changed(a, b):
    """True if any scalar/body/parent field differs between two ticket states.

    Timestamp attrs are excluded: an auto-bumped `updated` must not count as an
    edit for the modify-vs-delete decision.
    """
    fa = _ticket_scalar_fields(a, include_timestamps=False)
    fb = _ticket_scalar_fields(b, include_timestamps=False)
    keys = set(fa) | set(fb)
    for k in keys:
        if normalize_conflict_text(fa.get(k)) != normalize_conflict_text(fb.get(k)):
            return True
    if normalize_conflict_text(_body_text(a)) != normalize_conflict_text(_body_text(b)):
        return True
    if _parent_id_of(a) != _parent_id_of(b):
        return True
    return False


def _merge_ticket_fields(b_t, m_t, th_t, merged_t, record_conflict):
    """Field-by-field three-way merge writing results onto merged_t."""
    b_fields = _ticket_scalar_fields(b_t) if b_t is not None else {}
    m_fields = _ticket_scalar_fields(m_t)
    th_fields = _ticket_scalar_fields(th_t)

    all_keys = set(b_fields) | set(m_fields) | set(th_fields)

    # Decide the final attr set. title/type are stored on the object directly.
    final_attrs = {}
    # Preserve mine's attr ordering, then append theirs-only keys.
    ordered_keys = []
    for k in m_t.attrs:
        if k == "move":
            continue
        if k in ("title", "type"):
            continue
        ordered_keys.append(k)
    for k in th_t.attrs:
        if k == "move":
            continue
        if k in ("title", "type"):
            continue
        if k not in ordered_keys:
            ordered_keys.append(k)
    # base-only keys (deleted on both) won't appear; that's fine.

    for k in all_keys:
        bv = b_fields.get(k)
        mv = m_fields.get(k)
        tv = th_fields.get(k)
        # Timestamp attrs never conflict: merge by rule.
        if k in TIMESTAMP_ATTRS:
            merged_ts = _merge_timestamp(k, bv, mv, tv)
            if merged_ts is not None:
                final_attrs[k] = merged_ts
            continue
        outcome = _three_way_field(bv, mv, tv)
        if k == "title":
            if outcome[0] == "value":
                merged_t.title = outcome[1] if outcome[1] is not None else ""
            else:
                record_conflict(m_t.node_id, "ticket", "title", "field",
                                bv, mv, tv)
                merged_t.title = mv if mv is not None else ""
            continue
        if k == "type":
            if outcome[0] == "value":
                merged_t.ticket_type = outcome[1] if outcome[1] is not None else m_t.ticket_type
            else:
                record_conflict(m_t.node_id, "ticket", "type", "field",
                                bv, mv, tv)
                merged_t.ticket_type = mv if mv is not None else m_t.ticket_type
            continue
        # Regular attr.
        if outcome[0] == "value":
            if outcome[1] is not None:
                final_attrs[k] = outcome[1]
            # None means the attr is deleted on the winning side -> drop it.
        else:
            record_conflict(m_t.node_id, "ticket", k, "field", bv, mv, tv)
            # default to mine; if mine absent, keep absent.
            if mv is not None:
                final_attrs[k] = mv

    # Write attrs back in the chosen order.
    new_attrs = {}
    for k in ordered_keys:
        if k in final_attrs:
            new_attrs[k] = final_attrs[k]
    # Any key present in final_attrs but not ordered (shouldn't happen) appended.
    for k in final_attrs:
        if k not in new_attrs:
            new_attrs[k] = final_attrs[k]
    merged_t.attrs = new_attrs
    merged_t.dirty = True

    # --- body (multiline -> text conflict). ---
    b_body = _body_text(b_t) if b_t is not None else None
    m_body = _body_text(m_t)
    th_body = _body_text(th_t)
    outcome = _three_way_field(b_body, m_body, th_body)
    if outcome[0] == "value":
        _set_body_from_text(merged_t, outcome[1])
    else:
        record_conflict(m_t.node_id, "ticket", "body", "text",
                        b_body, m_body, th_body)
        _set_body_from_text(merged_t, m_body)

    # --- parent (reparent) -> field conflict. ---
    b_par = _parent_id_of(b_t) if b_t is not None else None
    m_par = _parent_id_of(m_t)
    th_par = _parent_id_of(th_t)
    outcome = _three_way_field(b_par, m_par, th_par)
    if outcome[0] == "conflict":
        record_conflict(m_t.node_id, "ticket", "parent", "field",
                        b_par, m_par, th_par)
        # default to mine: merged already mirrors mine's structure.
    # Non-conflict parent moves: merged mirrors mine's structure already; if
    # theirs is the winning change we honor it via reparent below.
    elif outcome[0] == "value":
        winner = outcome[1]
        if winner != m_par:
            _reparent_in_merged(merged_t, winner)


def _set_body_from_text(node, text):
    """Set a node's body_lines from dedented text, re-indenting to its level."""
    if text is None or text == "":
        node.body_lines = []
        node.dirty = True
        return
    indent = " " * (node.indent_level + 2)
    lines = text.split("\n")
    node.body_lines = [(indent + ln) if ln.strip() else "" for ln in lines]
    node.dirty = True


def _reparent_in_merged(merged_t, new_parent_id):
    """Reparent merged_t to new_parent_id (or None) within the merged project."""
    # Find the merged project root via walking up is not available; we rely on
    # the caller having merged_t inside `merged`. We resolve parent by id_map at
    # finalize. For simplicity we re-attach using the existing reparent helper
    # if we can find the project; but merged_t.parent chain gives us access.
    # We attach a pending marker; actual relocation done in _finalize_reparents.
    merged_t._pending_parent = new_parent_id


# ---------------------------------------------------------------------------
# Comments merge (union by id)
# ---------------------------------------------------------------------------

def _merge_comments(b_t, m_t, th_t, merged_t, record_conflict, next_id):
    """Union-by-id comment merge; divergent same-comment body -> field conflict.

    Comments are merged into merged_t.comments (which is mine's copy). Theirs-only
    comments are appended after mine's. Body edits diverging -> conflict.
    """
    b_comments = _flatten_comments(b_t) if b_t is not None else {}
    m_comments = _flatten_comments(m_t)
    th_comments = _flatten_comments(th_t)
    merged_comments = _flatten_comments(merged_t)

    # Merge bodies for comments present on both mine and theirs.
    for cid, (m_c, _mp) in m_comments.items():
        if cid not in th_comments:
            continue
        th_c = th_comments[cid][0]
        b_c = b_comments.get(cid, (None,))[0]
        b_body = _body_text(b_c) if b_c is not None else None
        m_body = _body_text(m_c)
        th_body = _body_text(th_c)
        b_title = b_c.title if b_c is not None else None
        # Title merge.
        t_out = _three_way_field(b_title, m_c.title, th_c.title)
        merged_c = merged_comments.get(cid, (None,))[0]
        if merged_c is None:
            continue
        if t_out[0] == "value":
            merged_c.title = t_out[1] if t_out[1] is not None else merged_c.title
        else:
            record_conflict(cid, "comment", "title", "field",
                            b_title, m_c.title, th_c.title)
            merged_c.title = m_c.title
        # Body merge.
        out = _three_way_field(b_body, m_body, th_body)
        if out[0] == "value":
            _set_body_from_text(merged_c, out[1])
        else:
            record_conflict(cid, "comment", "body", "text",
                            b_body, m_body, th_body)
            _set_body_from_text(merged_c, m_body)

    # Add theirs-only comments (append after mine's at the top level).
    if merged_t.comments is None and th_t.comments is not None:
        # mine had no comments; clone theirs container into merged.
        merged_t.comments = copy.deepcopy(th_t.comments)
        merged_t.comments.dirty = True
        return

    if th_t.comments is None:
        return

    merged_top = merged_t.comments
    existing_ids = set(merged_comments.keys())
    for th_c in th_t.comments.comments:
        if str(th_c.node_id) not in existing_ids:
            clone = copy.deepcopy(th_c)
            _reindent_comment(clone, merged_top.indent_level + 2)
            merged_top.comments.append(clone)
            merged_top.dirty = True
        else:
            # Append theirs-only nested replies under matching comments.
            _merge_nested_comment_children(
                _find_comment(merged_top.comments, str(th_c.node_id)),
                th_c, existing_ids)


def _merge_nested_comment_children(merged_c, th_c, existing_ids):
    """Append theirs-only reply children recursively under a merged comment."""
    if merged_c is None:
        return
    for th_child in th_c.children:
        if str(th_child.node_id) not in existing_ids:
            clone = copy.deepcopy(th_child)
            _reindent_comment(clone, merged_c.indent_level + 2)
            merged_c.children.append(clone)
            merged_c.dirty = True
            existing_ids.add(str(th_child.node_id))
        else:
            child_merged = _find_comment(merged_c.children,
                                         str(th_child.node_id))
            _merge_nested_comment_children(child_merged, th_child, existing_ids)


def _find_comment(comments, cid):
    for c in comments:
        if str(c.node_id) == cid:
            return c
    return None


def _reindent_comment(comment, indent_level):
    """Re-indent a cloned comment subtree to a new base indent level."""
    delta = indent_level - comment.indent_level
    if delta == 0:
        return

    def walk(c, lvl):
        old_body_indent = c.indent_level + 2
        c.indent_level = lvl
        new_body_indent = lvl + 2
        if c.body_lines:
            dedented = textwrap.dedent("\n".join(c.body_lines)).split("\n")
            prefix = " " * new_body_indent
            c.body_lines = [(prefix + ln) if ln.strip() else "" for ln in dedented]
        c.dirty = True
        for child in c.children:
            walk(child, lvl + 2)

    walk(comment, indent_level)


def _flatten_comments(ticket):
    """Map comment-id -> (Comment, parent-Comment-or-None) for a ticket."""
    out = {}
    if ticket is None or ticket.comments is None:
        return out

    def walk(comments, parent):
        for c in comments:
            out[str(c.node_id)] = (c, parent)
            walk(c.children, c)

    walk(ticket.comments.comments, None)
    return out


# ---------------------------------------------------------------------------
# Grafting theirs-only tickets
# ---------------------------------------------------------------------------

def _graft_theirs_ticket(th_t, theirs_idx, merged, merged_idx):
    """Insert a theirs-only ticket subtree into merged, after mine's siblings."""
    # Skip if already grafted (a parent graft pulls children with it).
    if str(th_t.node_id) in merged_idx:
        return
    parent_id = _parent_id_of(th_t)

    clone = copy.deepcopy(th_t)
    # Detach children that are NOT theirs-only-relative-to-merged? No: a
    # theirs-only ticket's whole subtree is theirs-only by construction unless a
    # child id already exists in mine (rare divergent structure). Handle by
    # pruning children that already exist in merged.
    _prune_existing(clone, merged_idx)

    if parent_id is None or parent_id not in merged_idx:
        # Top-level (or parent also theirs-only and not yet present): place at
        # end of top-level list.
        clone.parent = None
        _reindent_ticket(clone, 0)
        clone._rank = _rank_after_all(merged.tickets)
        merged.tickets.append(clone)
    else:
        parent = merged_idx[parent_id]
        clone.parent = parent
        _reindent_ticket(clone, parent.indent_level + 2)
        clone._rank = _rank_after_all(parent.children)
        parent.children.append(clone)
        parent.dirty = True
    clone.dirty = True
    # Register the new subtree in merged_idx.
    _register_subtree(clone, merged_idx)


def _prune_existing(clone, merged_idx):
    """Remove children of clone whose ids already exist in merged."""
    clone.children = [c for c in clone.children
                      if str(c.node_id) not in merged_idx]
    for c in clone.children:
        _prune_existing(c, merged_idx)


def _register_subtree(ticket, merged_idx):
    merged_idx[str(ticket.node_id)] = ticket
    for c in ticket.children:
        _register_subtree(c, merged_idx)


def _reindent_ticket(ticket, indent_level):
    """Re-indent a ticket subtree (and body/comments) to a new base level."""
    old = ticket.indent_level
    if old == indent_level:
        # Still need to recurse in case caller changed nothing but children off.
        pass
    ticket.indent_level = indent_level
    # Re-indent body.
    if ticket.body_lines:
        dedented = textwrap.dedent("\n".join(ticket.body_lines)).split("\n")
        prefix = " " * (indent_level + 2)
        ticket.body_lines = [(prefix + ln) if ln.strip() else "" for ln in dedented]
    # Re-indent comments.
    if ticket.comments is not None:
        _reindent_comment_container(ticket.comments, indent_level + 2)
    ticket.dirty = True
    for child in ticket.children:
        _reindent_ticket(child, indent_level + 2)


def _reindent_comment_container(container, indent_level):
    container.indent_level = indent_level
    container.dirty = True
    for c in container.comments:
        _reindent_comment(c, indent_level + 2)


def _rank_after_all(siblings):
    """Rank that sorts after all current siblings."""
    if not siblings:
        return 0.0
    return max(_get_rank(s) for s in siblings) + 1.0


# ---------------------------------------------------------------------------
# Deletions / reparents finalization
# ---------------------------------------------------------------------------

def _mark_for_deletion(ticket):
    ticket._delete = True


def _apply_deletions(merged):
    """Remove tickets marked with _delete from the merged tree."""
    def filter_list(tickets):
        kept = []
        for t in tickets:
            if getattr(t, "_delete", False):
                continue
            t.children = filter_list(t.children)
            kept.append(t)
        return kept

    merged.tickets = filter_list(merged.tickets)


def _finalize_reparents(merged):
    """Apply pending reparent relocations recorded during field merge."""
    pending = []

    def collect(tickets):
        for t in tickets:
            if hasattr(t, "_pending_parent"):
                pending.append((t, t._pending_parent))
            collect(t.children)

    collect(merged.tickets)
    if not pending:
        return
    idx = _ticket_index(merged)
    for ticket, new_parent_id in pending:
        del ticket._pending_parent
        new_parent = idx.get(new_parent_id) if new_parent_id is not None else None
        if new_parent_id is not None and new_parent is None:
            continue  # target gone; leave in place
        # Avoid cycles: don't reparent under own descendant.
        if new_parent is not None and _is_descendant(new_parent, ticket):
            continue
        _reparent_ticket(ticket, new_parent, merged)


def _is_descendant(candidate, ancestor):
    """True if candidate is ancestor or within ancestor's subtree."""
    if candidate is ancestor:
        return True
    for c in ancestor.children:
        if _is_descendant(candidate, c):
            return True
    return False


def _finalize_ranks(merged):
    """Apply pending reparents, then normalize ranks to positional ints."""
    _finalize_reparents(merged)

    def renorm(tickets):
        ordered = sort_by_rank(tickets)
        for i, t in enumerate(ordered):
            t._rank = float(i)
        # rebuild list in sorted order so serialization is stable
        tickets[:] = ordered
        for t in tickets:
            renorm(t.children)

    renorm(merged.tickets)


# ---------------------------------------------------------------------------
# Conflict resolution (prefer / resolutions)
# ---------------------------------------------------------------------------

def _resolve_conflicts(merged, conflicts, prefer, resolutions,
                       mine_idx, theirs_idx, base_idx):
    """Resolve conflicts via resolutions (per-key) then prefer (fill rest).

    Returns the list of conflicts that remain UNRESOLVED.
    """
    if prefer is None and not resolutions:
        return conflicts

    remaining = []
    for c in conflicts:
        side = None
        rkey = c.key()
        if rkey in resolutions:
            side = resolutions[rkey]
        elif prefer is not None:
            side = prefer
        if side is None:
            remaining.append(c)
            continue
        _apply_resolution(merged, c, side, mine_idx, theirs_idx, base_idx)
    return remaining


def _apply_resolution(merged, c, side, mine_idx, theirs_idx, base_idx):
    """Apply the chosen side for a single conflict onto the merged tree."""
    merged_idx = _ticket_index(merged)

    if c.ctype == "modify-delete":
        # mine_value / theirs_value: one is DELETED, other is node repr.
        mine_deleted = (c.mine_value == DELETED)
        theirs_deleted = (c.theirs_value == DELETED)
        keep = None
        if side == "mine":
            keep = not mine_deleted
        else:
            keep = not theirs_deleted
        merged_t = merged_idx.get(str(c.node_id))
        if keep:
            # Ensure node present with the kept side's content.
            if merged_t is None:
                src_idx = mine_idx if side == "mine" else theirs_idx
                src = src_idx.get(str(c.node_id))
                if src is not None:
                    _graft_theirs_ticket(src, src_idx, merged, merged_idx)
            else:
                # If kept side is theirs, overwrite mine's content with theirs.
                if side == "theirs":
                    src = theirs_idx.get(str(c.node_id))
                    if src is not None:
                        _copy_ticket_content(src, merged_t)
        else:
            if merged_t is not None:
                _mark_for_deletion(merged_t)
                _apply_deletions(merged)
        return

    # Field / text conflict: pick the chosen side's value.
    chosen = c.mine_value if side == "mine" else c.theirs_value

    if c.node_kind == "comment":
        cidx = _comment_index(merged)
        entry = cidx.get(str(c.node_id))
        if entry is None:
            return
        comment = entry[0]
        if c.field == "body":
            _set_body_from_text(comment, chosen)
        elif c.field == "title":
            comment.title = chosen if chosen is not None else comment.title
        return

    merged_t = merged_idx.get(str(c.node_id))
    if merged_t is None:
        return
    if c.field == "title":
        merged_t.title = chosen if chosen is not None else ""
    elif c.field == "type":
        merged_t.ticket_type = chosen if chosen is not None else merged_t.ticket_type
    elif c.field == "body":
        _set_body_from_text(merged_t, chosen)
    elif c.field == "parent":
        if chosen != _parent_id_of(merged_t):
            _reparent_in_merged(merged_t, chosen)
            _finalize_reparents(merged)
    else:
        # attr
        if chosen is None:
            merged_t.del_attr(c.field)
        else:
            merged_t.set_attr(c.field, chosen)
    merged_t.dirty = True


def _copy_ticket_content(src, dst):
    """Copy scalar fields, attrs, body from src ticket onto dst (in place)."""
    dst.title = src.title
    dst.ticket_type = src.ticket_type
    dst.attrs = dict(src.attrs)
    _set_body_from_text(dst, _body_text(src))
    dst.dirty = True


# ---------------------------------------------------------------------------
# next_id fixup
# ---------------------------------------------------------------------------

def _fix_next_id(merged):
    """Set ## Metadata next_id to max(all used ticket ids) + 1."""
    hi = 0
    for tid in _ticket_index(merged):
        try:
            hi = max(hi, int(tid))
        except (ValueError, TypeError):
            pass
    new_next = hi + 1
    merged.next_id = new_next
    if "metadata" in merged.sections:
        merged.sections["metadata"].set_attr("next_id", str(new_next))
# }}} # SOURCE END: 115-merge-engine.py

# SOURCE START: 116-merge-report.py {{{
# ---------------------------------------------------------------------------
# Merge Report (render conflicts -> .reject text; parse edits -> resolutions)
# ---------------------------------------------------------------------------
#
# Pure text: no git, no filesystem, no CLI. Concatenated after the merge engine
# (115), so it may freely use everything defined in 010-115 — in particular
# DELETED, NODE_FIELD, normalize_conflict_text(), conflict_sum() and the
# Conflict / MergeResult classes.
#
# The renderer turns a list[Conflict] into the textual `.reject` file the user
# edits; the parser reads an edited `.reject` back into a resolutions map
# {(node_id, field) -> "mine" | "theirs"} that can be fed straight to
# merge_trees(..., resolutions=...). The contract is "choice only": the user
# selects a side, never edits the content — which the parser enforces via the
# checksums recorded on each conflict header line.
#
# VOCABULARY: the user-facing `.reject` surface speaks `to`/`from` (the side
# merged into / the side merged from); the engine and the resolutions map this
# parser RETURNS keep the historical `mine`/`theirs` names. The `to`<->`mine`,
# `from`<->`theirs` mapping happens entirely inside this file, at render/parse.

import re as _re


class RejectError(Exception):
    """Raised when a `.reject` file is malformed, edited, or unresolved.

    Carries a human-readable message (and, where known, the offending conflict
    id). The CLI layer converts this to a user-facing error + exit code 2.
    """

    def __init__(self, message, conflict_id=None):
        super().__init__(message)
        self.message = message
        self.conflict_id = conflict_id


# Machine-owned line markers. The header/footer and side indicators are not to
# be hand-edited (only chosen between); these constants drive both rendering and
# parsing so the two halves cannot drift.
_REJECT_HEADER_PREFIX = "<<< PLAN-CONFLICT"
_REJECT_FOOTER_PREFIX = ">>> END"
# Precise indicator form, exactly as rendered: '--- to (<branch>) ---' /
# '--- from (<branch>) ---'. We match the rendered shape (not a bare prefix)
# so a side's CONTENT — a body conflict or a node repr that happens to contain a
# markdown rule like '--- topic' — is never mistaken for an indicator. The
# checksums on the header line remain the authoritative arbiter regardless.
# The capture group keeps the engine-internal side name so the rest of the
# parser is unchanged: `to` -> "mine", `from` -> "theirs".
_INDICATOR_RE = _re.compile(r'^--- (to|from) \(.*\) ---\s*$')

# Map the rendered user-facing side word to the engine-internal side name.
_REJECT_SIDE_TO_ENGINE = {"to": "mine", "from": "theirs"}

_HOW_TO_RESOLVE = (
    "# HOW TO RESOLVE\n"
    "#   For each block, keep exactly ONE side (--- to --- or --- from ---)\n"
    "#   and delete the other; or delete a side's indicator line and leave only\n"
    "#   its content. Do NOT edit the content — only choose a side. A side whose\n"
    "#   content is <DELETED> removes the entry. Do not edit the '#' header or\n"
    "#   the <<< / >>> lines.\n"
)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _fmt_lines(lines):
    """Render an advisory (start, end) line range as 'a-b' (default '0-0')."""
    if not lines:
        return "0-0"
    start, end = lines
    return "%s-%s" % (start, end)


def _conflict_node_token(node_id):
    """The 'node=#<id>' token value (without the leading '#').

    Comment ids keep their full form (e.g. '7:comment:9'); ticket ids keep their
    numeric form verbatim. We emit c.node_id as-is after a leading '#'.
    """
    return str(node_id)


def render_reject(conflicts, *, plan_path, base_label, to_label, from_label,
                  to_branch, from_branch, snapshot_dir, plan_version,
                  generated=None):
    """Render conflicts into the textual `.reject` file.

    Arguments (all supplied by the git/CLI layer in Stage 3):
      conflicts     list[Conflict] (the unresolved conflicts from a MergeResult)
      plan_path     path to the plan file, for the '# Plan file' line
      base_label    e.g. 'a1b2c3d' (merge-base short hash)
      to_label      e.g. 'feature-x @ 9f8e7d6' (the `to`/canonical side; engine 'mine')
      from_label    e.g. 'main      @ 1234abc' (the `from` side; engine 'theirs')
      to_branch     branch name shown in the '--- to (<branch>) ---' marker
      from_branch   branch name shown in the '--- from (<branch>) ---' marker
      snapshot_dir  dir holding base/mine/theirs snapshots (advisory line refs)
      plan_version  the plan version string ('vX.Y') for the header
      generated     pre-formatted timestamp string; default 'now' in UTC.

    Returns the full `.reject` text. The `to` side maps to the engine's `mine`
    value (Conflict.mine_value / mine_lines) and `from` to `theirs`.
    """
    if generated is None:
        generated = _now_utc_label()

    out = []
    # --- global '#' header --------------------------------------------------
    out.append("# plan merge — conflict resolution file   "
               "(edit blocks, then: plan merge --resolve | --abort)")
    out.append("#")
    out.append("# Generated : %s · plan %s" % (generated, plan_version))
    out.append("# Plan file : %s" % plan_path)
    out.append("# Base      : %s   (merge-base)" % base_label)
    out.append("# To        : %s   -> written into the plan file "
               "(conflicts default to this side)" % to_label)
    out.append("# From      : %s" % from_label)
    out.append("# Snapshots : %s   (line numbers below refer to to/from)"
               % snapshot_dir)
    out.append("# Conflicts : %d" % len(conflicts))
    out.append("#")
    out.append(_HOW_TO_RESOLVE.rstrip("\n"))
    out.append("")

    # --- one block per conflict --------------------------------------------
    for c in conflicts:
        out.append(_render_block(c, to_branch, from_branch))
        out.append("")

    return "\n".join(out).rstrip("\n") + "\n"


def _render_block(c, to_branch, from_branch):
    """Render a single conflict block (header + both sides + footer).

    `to` is the engine's `mine` side, `from` is `theirs`.
    """
    parts = []
    header = "%s id=%s type=%s node=#%s" % (
        _REJECT_HEADER_PREFIX, c.id, c.ctype, _conflict_node_token(c.node_id))
    # field=<name> is included for field/text; OMITTED for modify-delete (the
    # parser infers field=NODE_FIELD from type=modify-delete).
    if c.ctype != "modify-delete":
        header += " field=%s" % c.field
    header += " to.lines=%s from.lines=%s to.sum=%s from.sum=%s" % (
        _fmt_lines(c.mine_lines), _fmt_lines(c.theirs_lines),
        conflict_sum(c.mine_value), conflict_sum(c.theirs_value))
    parts.append(header)

    parts.append("--- to (%s) ---" % to_branch)
    parts.append(_render_side_value(c.mine_value))
    parts.append("--- from (%s) ---" % from_branch)
    parts.append(_render_side_value(c.theirs_value))
    parts.append("%s id=%s" % (_REJECT_FOOTER_PREFIX, c.id))
    return "\n".join(parts)


def _render_side_value(value):
    """Render a side's value as block content.

    `value` is already a render-ready string (scalar, multiline body, or node
    repr) or the DELETED sentinel. We emit it verbatim; an empty/absent value
    becomes a single empty line so the block shape is preserved.
    """
    if value is None:
        return ""
    return value


def _now_utc_label():
    """'YYYY-MM-DD HH:MM UTC' for the Generated header (best effort)."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------

# Header field extractors. The header line is machine-owned; we read the tokens
# we care about and tolerate the advisory line-range tokens.
_HDR_ID = _re.compile(r'\bid=(\S+)')
_HDR_TYPE = _re.compile(r'\btype=(\S+)')
_HDR_NODE = _re.compile(r'\bnode=#(\S+)')
_HDR_FIELD = _re.compile(r'\bfield=(\S+)')
# The header tokens are user-facing (`to.sum`/`from.sum`); the dict keys below
# stay `mine_sum`/`theirs_sum` (engine-internal) so the resolver is unchanged.
_HDR_TO_SUM = _re.compile(r'\bto\.sum=(\S+)')
_HDR_FROM_SUM = _re.compile(r'\bfrom\.sum=(\S+)')


def _parse_header(line):
    """Parse a '<<< PLAN-CONFLICT ...' header into a dict of fields.

    Returns {'id', 'type', 'node_id', 'field', 'mine_sum', 'theirs_sum'}.
    The header tokens are the user-facing `to.sum`/`from.sum`; the dict keys
    remain engine-internal (`mine_sum` <- to.sum, `theirs_sum` <- from.sum).
    `field` defaults to NODE_FIELD when type=modify-delete (it is omitted from
    the rendered header for that type).
    """
    def need(rx, name):
        m = rx.search(line)
        if not m:
            raise RejectError("malformed conflict header (missing %s): %s"
                              % (name, line.strip()))
        return m.group(1)

    cid = need(_HDR_ID, "id")
    ctype = need(_HDR_TYPE, "type")
    node_id = need(_HDR_NODE, "node")
    mine_sum = need(_HDR_TO_SUM, "to.sum")
    theirs_sum = need(_HDR_FROM_SUM, "from.sum")

    fm = _HDR_FIELD.search(line)
    if fm:
        field = fm.group(1)
    elif ctype == "modify-delete":
        field = NODE_FIELD
    else:
        raise RejectError("malformed conflict header (missing field): %s"
                          % line.strip(), conflict_id=cid)

    return {
        "id": cid,
        "type": ctype,
        "node_id": node_id,
        "field": field,
        "mine_sum": mine_sum,
        "theirs_sum": theirs_sum,
    }


def _footer_id(line):
    """If `line` is a '>>> END id=N' footer, return N (str); else None."""
    if not line.startswith(_REJECT_FOOTER_PREFIX):
        return None
    m = _re.search(r'\bid=(\S+)', line)
    return m.group(1) if m else ""


def _split_blocks(text):
    """Yield (header_dict, body_lines) for each conflict block in `text`.

    body_lines are the raw lines strictly between the '<<<' header and the
    matching '>>> END id=N' footer (markers and content intermixed; not yet
    classified). Lines outside blocks (the '#' header, blank separators) are
    ignored.

    The footer is ANCHORED to the block's own id: only '>>> END id=N' (the same
    N as the opening header) closes the block. A '>>> END id=M' (M != N) or a
    nested '<<< PLAN-CONFLICT ...' that appears while a block is open is treated
    as ordinary body content — a side's content can legitimately contain such
    delimiter-like lines (a body/text conflict, or a node repr quoting git
    output). The header checksums are the final arbiter of correctness.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith(_REJECT_HEADER_PREFIX):
            header = _parse_header(line)
            cid = header["id"]
            body = []
            i += 1
            closed = False
            while i < n:
                fid = _footer_id(lines[i])
                if fid is not None and fid == cid:
                    # Our own terminator.
                    closed = True
                    i += 1
                    break
                # Any other footer (id mismatch) or a stray opening header that
                # appears before our terminator is just content of this block.
                body.append(lines[i])
                i += 1
            if not closed:
                raise RejectError(
                    "unterminated conflict block (missing '>>> END id=%s')" % cid,
                    conflict_id=cid)
            yield header, body
        else:
            i += 1


def _indicator_side(line):
    """If `line` is exactly a rendered side indicator, return 'mine'/'theirs'.

    Recognition is precise (the full '--- to (<branch>) ---' shape), so a
    side's content containing a markdown rule or quoted delimiter is NEVER
    mistaken for an indicator. The rendered word is user-facing (`to`/`from`);
    we translate it to the engine-internal side ('mine'/'theirs') so the rest of
    the parser — and the resolutions map it produces — stays engine-internal.
    """
    m = _INDICATOR_RE.match(line)
    return _REJECT_SIDE_TO_ENGINE[m.group(1)] if m else None


def _has_content(text):
    """True if normalized text is non-empty."""
    return normalize_conflict_text(text) != ""


def _match_side(text, mine_sum, theirs_sum):
    """Return 'mine'/'theirs' if conflict_sum(text) matches a side, else None.

    Returns 'mine' when both sums are equal (the two sides are byte-identical
    after normalization, so the choice is immaterial — mine is the in-tree
    default).
    """
    if not _has_content(text):
        return None
    csum = conflict_sum(text)
    m = (csum == mine_sum)
    t = (csum == theirs_sum)
    if m:                  # also covers m and t (identical sides)
        return "mine"
    if t:
        return "theirs"
    return None


def _indicator_positions(body_lines):
    """Return the indices of body lines that are precise side indicators,
    paired with their side: [(index, 'mine'|'theirs'), ...]."""
    out = []
    for idx, ln in enumerate(body_lines):
        side = _indicator_side(ln)
        if side is not None:
            out.append((idx, side))
    return out


def _resolve_block(header, body_lines):
    """Determine the chosen side ('mine' | 'theirs', engine-internal) for one block.

    Choice-only is enforced by the recorded checksums: the kept content MUST
    `conflict_sum`-match exactly one side. Because a side's CONTENT can itself
    contain delimiter-like lines (a body/text conflict, a node repr quoting git
    output, a markdown rule), we let the checksums — not line scanning — be the
    arbiter:

      1. Build a small set of candidate "kept content" strings and accept the
         first that checksum-matches a side. The candidates cover the two ways a
         user keeps a single side:
           (a) the whole body verbatim       -> "content-only" keep;
           (b) the body minus a single leading indicator line -> "indicator kept".
         The rendered form always places exactly one indicator immediately
         before its content, so (a)/(b) reconstruct the exact side value even if
         that value contains interior delimiter-like lines.
      2. If NO candidate matches, fall back to indicator analysis to choose the
         RIGHT diagnostic:
           - both indicators present, each owning content -> "keep only one side"
           - nothing kept at all                          -> "not resolved"
           - otherwise                                    -> "edited/unrecognized"
    """
    cid = header["id"]
    mine_sum = header["mine_sum"]
    theirs_sum = header["theirs_sum"]

    # --- 1. Checksum-arbitrated candidates. --------------------------------
    candidates = []
    whole = "\n".join(body_lines)
    candidates.append(whole)
    # Strip a single LEADING indicator line (the only place the renderer emits
    # one for a kept side). Skip any blank lines that may precede it.
    j = 0
    while j < len(body_lines) and body_lines[j].strip() == "":
        j += 1
    if j < len(body_lines) and _indicator_side(body_lines[j]) is not None:
        candidates.append("\n".join(body_lines[j + 1:]))
    # Last resort: drop EVERY recognized indicator line. Tried only after the
    # genuine forms above, so a side whose content contains an indicator-shaped
    # line is already resolved verbatim; this only rescues odd layouts (e.g.
    # content left before/around an emptied marker).
    indicators = _indicator_positions(body_lines)
    if indicators:
        ind_idx = {idx for idx, _s in indicators}
        candidates.append(
            "\n".join(ln for i, ln in enumerate(body_lines) if i not in ind_idx))

    for cand in candidates:
        side = _match_side(cand, mine_sum, theirs_sum)
        if side is not None:
            return side

    # --- 2. No checksum match -> choose the right diagnostic. --------------
    # Does a recognized 'mine' indicator AND a 'theirs' indicator each own
    # non-empty trailing content? (Approximate, only for diagnostics.)
    mine_has = _indicator_owns_content(body_lines, indicators, "mine")
    theirs_has = _indicator_owns_content(body_lines, indicators, "theirs")
    if mine_has and theirs_has:
        raise RejectError(
            "keep only one side (conflict #%s)" % cid, conflict_id=cid)

    if not _has_content(whole):
        raise RejectError(
            "conflict #%s not resolved" % cid, conflict_id=cid)

    raise RejectError(
        "unrecognized/edited content; only side selection is allowed "
        "(conflict #%s)" % cid, conflict_id=cid)


def _indicator_owns_content(body_lines, indicators, want_side):
    """True if a `want_side` indicator is followed by any non-blank content
    before the next indicator. Used only to pick the 'keep only one side'
    diagnostic when no checksum candidate matched."""
    for k, (idx, side) in enumerate(indicators):
        if side != want_side:
            continue
        end = indicators[k + 1][0] if k + 1 < len(indicators) else len(body_lines)
        for ln in body_lines[idx + 1:end]:
            if ln.strip() != "":
                return True
    return False


def parse_reject(text):
    """Parse an edited `.reject` file into a resolutions map.

    Returns {(node_id, field) -> "mine" | "theirs"} (engine-internal side
    names; the user-facing `to`/`from` selection is translated here), with keys
    shaped exactly like Conflict.key() so the map can be passed to
    merge_trees(..., resolutions=...).

    Raises RejectError (with the offending conflict id where known) on any
    malformed, edited, ambiguous or unresolved block. All problems are collected
    and reported together where practical.
    """
    resolutions = {}
    errors = []
    for header, body in _split_blocks(text):
        try:
            side = _resolve_block(header, body)
        except RejectError as exc:
            errors.append(exc)
            continue
        key = (str(header["node_id"]), header["field"])
        resolutions[key] = side

    if errors:
        if len(errors) == 1:
            raise errors[0]
        msg = "; ".join(e.message for e in errors)
        raise RejectError(msg, conflict_id=errors[0].conflict_id)

    return resolutions
# }}} # SOURCE END: 116-merge-report.py

# SOURCE START: 117-merge-git.py {{{
# ---------------------------------------------------------------------------
# Merge Git Plumbing (subprocess + filesystem primitives)
# ---------------------------------------------------------------------------
#
# Focused, testable primitives for the porcelain `merge` command (Stage 4) and
# the git merge driver + install config (Stage 5). NO CLI, NO argument parsing.
#
# Concatenated after the report module (116), so it may freely use everything
# defined in 010-116 — in particular parse(), serialize(), the Conflict class,
# render_reject(), and the stdlib imports (os, re, subprocess, ...) from the
# preamble.
#
# ISOLATION CONTRACT: every function that touches git takes an explicit
# `repo_root` (or a path it derives the repo from) and runs git with
# cwd=repo_root. Nothing here relies on the process's current working directory.


# ---------------------------------------------------------------------------
# Git query helpers
# ---------------------------------------------------------------------------

def _git(args, repo_root, check=True, input_text=None, timeout=30):
    """Run `git <args>` with cwd=repo_root and return stdout (text).

    Raises a clear RuntimeError on non-zero exit when `check` is True; otherwise
    returns stdout regardless of exit code (caller inspects). `input_text`, when
    given, is fed to git's stdin.
    """
    proc = subprocess.run(
        ["git"] + list(args),
        cwd=repo_root,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "git %s failed (exit %d): %s"
            % (" ".join(args), proc.returncode,
               (proc.stderr or proc.stdout or "").strip())
        )
    return proc.stdout


def git_repo_root(start=None):
    """Return the repository top-level directory (via rev-parse --show-toplevel).

    `start` is the directory to run git in; defaults to the process cwd. Raises
    RuntimeError when not inside a git work tree.
    """
    cwd = start or os.getcwd()
    out = _git(["rev-parse", "--show-toplevel"], cwd)
    return out.strip()


def git_show(repo_root, ref, rel_path):
    """Return the contents of `<ref>:<rel_path>` or None if absent at that ref.

    Used to read the plan file as it existed at the merge-base / on the other
    branch. None means the file did not exist there (added on only one side).
    """
    proc = subprocess.run(
        ["git", "show", "%s:%s" % (ref, rel_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_merge_base(repo_root, a, b):
    """Return the merge-base sha of two refs, or None if there is none."""
    proc = subprocess.run(
        ["git", "merge-base", a, b],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def git_rev_parse(repo_root, ref):
    """Resolve a ref to its full object sha. Raises if it doesn't resolve."""
    return _git(["rev-parse", "--verify", "%s^{commit}" % ref], repo_root).strip()


def git_short_sha(repo_root, ref):
    """Resolve a ref to its abbreviated (short) object sha."""
    return _git(["rev-parse", "--short", "%s^{commit}" % ref], repo_root).strip()


def git_current_branch(repo_root):
    """Return the current branch name, or None on a detached HEAD."""
    out = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root).strip()
    if out == "HEAD" or out == "":
        return None
    return out


def git_ref_exists(repo_root, ref):
    """True if `ref` resolves to a commit in this repo."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "%s^{commit}" % ref],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# Explicit source resolution (--to / --from / --base)
# ---------------------------------------------------------------------------
#
# A "source spec" names one side of a merge. Three forms:
#   git:<ref>   force a git commit/ref (requires a repo)
#   file:<path> force a filesystem path
#   <bare>      auto: an existing path is a file; else a resolvable git ref;
#               else an error.
# A file source is read directly from disk; a commit source is read as
# `<ref>:<relpath>` (relpath = the plan file's in-repo path). Returns
# (text, label) where text is None when the file/ref-path is absent (so a side
# can legitimately be "added"). The label is human-readable for the .reject
# header / block markers.


class SourceError(Exception):
    """A merge source spec could not be resolved to a file or git ref."""


def _resolve_commit_source(ref, repo_root, relpath, display=None):
    """Resolve a git commit source: read <ref>:<relpath>. Returns (text, label)."""
    if repo_root is None:
        raise SourceError(
            "git source %r requires a git repository" % (display or ref))
    if relpath is None:
        # Without a known canonical plan path we cannot read <ref>:<path>, and
        # guessing would silently read the wrong (likely absent) path. Error
        # instead of producing an empty side.
        raise SourceError(
            "cannot determine the plan file path for commit source %r; "
            "run inside the repo or use --file" % (display or ref))
    if not git_ref_exists(repo_root, ref):
        raise SourceError("git ref %r does not resolve to a commit" % ref)
    text = git_show(repo_root, ref, relpath)
    try:
        label = "%s @ %s" % (ref, git_short_sha(repo_root, ref))
    except RuntimeError:
        label = ref
    return text, label


def _resolve_file_source(path):
    """Resolve a filesystem source. Returns (text|None, label=path)."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read(), path
    return None, path


def resolve_source(spec, repo_root, relpath):
    """Resolve a merge source spec to (text, label).

    spec      a source spec string (git:<ref> | file:<path> | bare).
    repo_root the repository top-level, or None when outside a git repo.
    relpath   the canonical plan file's path relative to repo_root, used for
              commit reads (<ref>:<relpath>). None means "undeterminable"; a
              commit source then raises SourceError rather than guessing.

    Raises SourceError on a spec that is neither a file nor a resolvable ref, or
    on a commit source when relpath is None.
    """
    if spec is None:
        raise SourceError("missing source")
    if spec.startswith("git:"):
        ref = spec[len("git:"):]
        if not ref:
            raise SourceError("empty git ref in %r" % spec)
        return _resolve_commit_source(ref, repo_root, relpath, display=spec)
    if spec.startswith("file:"):
        return _resolve_file_source(spec[len("file:"):])
    # Bare: an existing path wins; else try a git ref; else error.
    if os.path.exists(spec):
        return _resolve_file_source(spec)
    if repo_root is not None and git_ref_exists(repo_root, spec):
        return _resolve_commit_source(spec, repo_root, relpath)
    raise SourceError(
        "%r is not a file or git ref" % spec
        + ("" if repo_root is not None
           else " (and we are not inside a git repository)"))


def source_commit(spec, repo_root):
    """Return the commit ref a source spec points at, or None for a file source.

    Used by base auto-detection (a merge-base needs a commit on each side). A
    `file:` source or an existing path is NOT a commit. A `git:<ref>` or a bare
    name that resolves to a commit (and is not an existing path) is.
    """
    if spec is None:
        return None
    if spec.startswith("git:"):
        ref = spec[len("git:"):]
        return ref or None
    if spec.startswith("file:"):
        return None
    if os.path.exists(spec):
        return None
    if repo_root is not None and git_ref_exists(repo_root, spec):
        return spec
    return None


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------

def _rel_to_repo(repo_root, plan_path):
    """The path of plan_path relative to repo_root, with forward slashes."""
    rel = os.path.relpath(os.path.abspath(plan_path), os.path.abspath(repo_root))
    return rel.replace(os.sep, "/")


# ---------------------------------------------------------------------------
# Snapshots & in-progress state (paths)
# ---------------------------------------------------------------------------

def reject_path(plan_path):
    """Path of the sidecar `.reject` file for plan_path."""
    return plan_path + ".reject"


def snapshot_dir(repo_root):
    """The base directory under which per-merge state dirs live (inside .git).

    Kept for the existing test helpers; concrete merges use
    merge_state_dir(output_path, repo_root), which namespaces a subdirectory of
    this per output so two in-flight merges in one repo don't clobber each other.
    """
    return os.path.join(repo_root, ".git", "plan-merge")


def _output_state_key(output_path):
    """A short, filesystem-safe key identifying a merge by its output path.

    First 12 hex of sha256(abspath(output)). Used to namespace the in-repo state
    dir so concurrent `-o` merges keep separate snapshots/options/.reject state.
    """
    abspath = os.path.abspath(output_path)
    return _hashlib.sha256(abspath.encode("utf-8")).hexdigest()[:12]


def merge_state_dir(output_path, repo_root):
    """Directory holding the snapshots + options for a merge writing `output_path`.

    Inside a repo -> <repo_root>/.git/plan-merge/<key> (hidden in .git, never
    committed), namespaced per output so multiple in-flight merges don't collide.
    Outside a repo -> <dirname(output_path)>/.plan-merge, beside the output file
    so `--resolve`/`--abort` can find it without git (one in-flight merge per
    output directory, which is the natural unit there).
    """
    if repo_root is not None:
        return os.path.join(repo_root, ".git", "plan-merge",
                            _output_state_key(output_path))
    out_dir = os.path.dirname(os.path.abspath(output_path))
    return os.path.join(out_dir, ".plan-merge")


_SNAPSHOT_NAMES = ("base", "mine", "theirs")


def write_snapshots_at(state_dir, base_text, mine_text, theirs_text):
    """Write base/mine/theirs snapshots into an explicit `state_dir`.

    A None side is written as an empty file (so the trio always exists and
    read_snapshots_at round-trips a consistent shape). Returns the state dir.
    """
    os.makedirs(state_dir, exist_ok=True)
    for name, text in zip(_SNAPSHOT_NAMES, (base_text, mine_text, theirs_text)):
        with open(os.path.join(state_dir, name), "w", encoding="utf-8") as f:
            f.write(text if text is not None else "")
    return state_dir


def read_snapshots_at(state_dir):
    """Read the three snapshots from an explicit `state_dir`.

    Returns (base_text, mine_text, theirs_text); a missing file reads as None.
    """
    out = []
    for name in _SNAPSHOT_NAMES:
        path = os.path.join(state_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out.append(f.read())
        else:
            out.append(None)
    return tuple(out)


def clear_merge_state_at(state_dir, reject_file):
    """Remove a `.reject` file and a snapshot/state dir (explicit paths).

    When the state dir is a per-output subdir of `.git/plan-merge`, also remove
    the now-empty parent so no stale empty directory lingers — but ONLY when it
    is empty, so other in-flight merges (their own subdirs) are preserved.
    """
    if reject_file and os.path.exists(reject_file):
        os.remove(reject_file)
    if state_dir and os.path.isdir(state_dir):
        shutil.rmtree(state_dir)
        parent = os.path.dirname(os.path.abspath(state_dir))
        if os.path.basename(parent) == "plan-merge" and os.path.isdir(parent):
            try:
                os.rmdir(parent)  # only succeeds when empty
            except OSError:
                pass


def write_snapshots(repo_root, base_text, mine_text, theirs_text):
    """Write snapshots into <repo_root>/.git/plan-merge/ (in-repo convenience)."""
    return write_snapshots_at(snapshot_dir(repo_root),
                              base_text, mine_text, theirs_text)


def read_snapshots(repo_root):
    """Read snapshots from <repo_root>/.git/plan-merge/ (in-repo convenience)."""
    return read_snapshots_at(snapshot_dir(repo_root))


def clear_merge_state(repo_root, plan_path):
    """Remove the `.reject` file and the `.git/plan-merge/` snapshot dir."""
    clear_merge_state_at(snapshot_dir(repo_root), reject_path(plan_path))


def merge_in_progress(plan_path):
    """True if a merge is in progress (the `.reject` file exists)."""
    return os.path.exists(reject_path(plan_path))


def merge_in_progress_at(reject_file):
    """True if a merge is in progress for an explicit `.reject` path."""
    return os.path.exists(reject_file)


# ---------------------------------------------------------------------------
# Advisory line annotation
# ---------------------------------------------------------------------------

# A node header line, anywhere in serialized plan text: '* ## ... {#<id>}'.
# Group 1 = leading whitespace + bullet (used to gauge nesting depth); group 2
# = the id token inside the braces.
_ANNOTATE_HEADER_RE = re.compile(r'^(\s*\*\s+)##\s+.*\{#([^}]+)\}\s*$')


def _header_lines(text):
    """Yield (line_index_0based, indent_width, id_token) for every node header.

    indent_width is the number of leading whitespace columns before the '*'
    bullet, used to determine nesting depth (a node's span ends at the next
    header at the same-or-shallower indent).
    """
    out = []
    if text is None:
        return out
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = _ANNOTATE_HEADER_RE.match(line)
        if m:
            indent = len(m.group(1)) - len(m.group(1).lstrip(" "))
            out.append((i, indent, m.group(2)))
    return out


def _node_span(text, node_id):
    """Return a 1-based (start_line, end_line) span for node_id in text, or None.

    The span runs from the node's '{#<id>}' header line to the line before the
    next header at the same-or-shallower indent (or EOF). Best-effort only.
    """
    if text is None:
        return None
    headers = _header_lines(text)
    n_lines = len(text.split("\n"))
    target = str(node_id)
    for k, (idx, indent, tok) in enumerate(headers):
        if tok != target:
            continue
        # End = line before the next header at same-or-shallower indent, or EOF.
        end_idx = n_lines - 1
        for (nidx, nindent, _ntok) in headers[k + 1:]:
            if nindent <= indent:
                end_idx = nidx - 1
                break
        # Trim trailing blank lines from the span.
        all_lines = text.split("\n")
        while end_idx > idx and all_lines[end_idx].strip() == "":
            end_idx -= 1
        return (idx + 1, end_idx + 1)
    return None


def annotate_conflict_lines(conflicts, mine_text, theirs_text):
    """Best-effort: set mine_lines/theirs_lines spans on each conflict.

    For each conflict, locate its node in the mine and theirs snapshots and set
    a 1-based (start, end) span pointing at the node's '{#<id>}' header through
    the line before the next same-or-shallower header (or EOF). A node absent on
    a side (e.g. modify-delete) leaves that side's lines as None. This is
    ADVISORY only — it never raises; any difficulty leaves the span None.
    """
    if not conflicts:
        return
    for c in conflicts:
        try:
            c.mine_lines = _node_span(mine_text, c.node_id)
        except Exception:
            c.mine_lines = None
        try:
            c.theirs_lines = _node_span(theirs_text, c.node_id)
        except Exception:
            c.theirs_lines = None


# ---------------------------------------------------------------------------
# Git index / conflict-state management
# ---------------------------------------------------------------------------

def in_merge_or_rebase(repo_root):
    """True if a merge or rebase is currently in progress.

    Consults the real git dir via `git rev-parse --git-path` (robust to worktrees
    and non-default git dirs): checks MERGE_HEAD, rebase-merge/, rebase-apply/.
    """
    for name in ("MERGE_HEAD", "rebase-merge", "rebase-apply"):
        try:
            p = _git(["rev-parse", "--git-path", name], repo_root).strip()
        except RuntimeError:
            continue
        if not os.path.isabs(p):
            p = os.path.join(repo_root, p)
        if os.path.exists(p):
            return True
    return False


def _hash_object(repo_root, text):
    """Write `text` as a blob into the object store; return its sha."""
    return _git(["hash-object", "-w", "--stdin"], repo_root,
                input_text=text if text is not None else "").strip()


def mark_unmerged(repo_root, plan_path, base_text, mine_text, theirs_text):
    """Mark plan_path as 'unmerged' in the index via stages 1/2/3.

    For each non-None side, write a blob (git hash-object -w) and feed an
    index-info line "<mode> <sha> <stage>\\t<rel_path>" (mode 100644) to
    `git update-index --index-info`. Stage 1=base, 2=mine, 3=theirs. Afterwards
    `git status` reports the path unmerged and `git commit` is blocked until a
    `git add`.
    """
    rel = _rel_to_repo(repo_root, plan_path)
    # Clear any existing index entry first so stale stages don't linger.
    _git(["update-index", "--force-remove", "--", rel], repo_root, check=False)

    lines = []
    for stage, text in ((1, base_text), (2, mine_text), (3, theirs_text)):
        if text is None:
            continue
        sha = _hash_object(repo_root, text)
        lines.append("100644 %s %d\t%s" % (sha, stage, rel))
    if not lines:
        return
    payload = "\n".join(lines) + "\n"
    _git(["update-index", "--index-info"], repo_root, input_text=payload)


def mark_resolved(repo_root, plan_path):
    """Clear the unmerged stages by `git add`-ing the path."""
    rel = _rel_to_repo(repo_root, plan_path)
    _git(["add", "--", rel], repo_root)


# ---------------------------------------------------------------------------
# Install-config helpers (driver / .gitattributes / .gitignore)
# ---------------------------------------------------------------------------

_MERGE_DRIVER_NAME = "plan structure-aware merge"
_MERGE_DRIVER_CMD = "plan merge-driver %O %A %B %P"


def _read_lines_file(path):
    """Read a text file into a list of lines (no trailing newlines). [] if absent."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if text == "":
        return []
    lines = text.split("\n")
    # Drop a single trailing empty element produced by a final newline.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _write_lines_file(path, lines):
    """Write a list of lines back, one per line, with a trailing newline.

    An empty list removes the file (idempotent for the remove_* helpers).
    """
    if not lines:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _add_line_idempotent(path, line):
    """Append `line` to the file iff it is not already present (exact match)."""
    lines = _read_lines_file(path)
    if line in lines:
        return
    lines.append(line)
    _write_lines_file(path, lines)


def _remove_line_idempotent(path, line):
    """Remove every exact-match occurrence of `line` from the file."""
    lines = _read_lines_file(path)
    kept = [ln for ln in lines if ln != line]
    if len(kept) != len(lines):
        _write_lines_file(path, kept)


def ensure_gitattributes(repo_root, rel_plan):
    """Idempotently add '<rel_plan> merge=plan' to <repo_root>/.gitattributes."""
    line = "%s merge=plan" % rel_plan
    _add_line_idempotent(os.path.join(repo_root, ".gitattributes"), line)


def remove_gitattributes(repo_root, rel_plan):
    """Idempotently remove the '<rel_plan> merge=plan' .gitattributes line."""
    line = "%s merge=plan" % rel_plan
    _remove_line_idempotent(os.path.join(repo_root, ".gitattributes"), line)


def set_merge_driver(repo_root):
    """Configure the repo-local merge.plan driver in .git/config (idempotent)."""
    _git(["config", "merge.plan.name", _MERGE_DRIVER_NAME], repo_root)
    _git(["config", "merge.plan.driver", _MERGE_DRIVER_CMD], repo_root)


def unset_merge_driver(repo_root):
    """Remove the merge.plan config section. Tolerates an absent section."""
    proc = subprocess.run(
        ["git", "config", "--remove-section", "merge.plan"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Exit 128 == "no such section"; that is fine (idempotent).
    return proc.returncode in (0, 128)


def ensure_gitignore(repo_root, pattern):
    """Idempotently add `pattern` as a line in <repo_root>/.gitignore."""
    _add_line_idempotent(os.path.join(repo_root, ".gitignore"), pattern)


def remove_gitignore(repo_root, pattern):
    """Idempotently remove the `pattern` line from <repo_root>/.gitignore."""
    _remove_line_idempotent(os.path.join(repo_root, ".gitignore"), pattern)
# }}} # SOURCE END: 117-merge-git.py

# SOURCE START: 120-cli.py {{{
# ---------------------------------------------------------------------------
# CLI Parser
# ---------------------------------------------------------------------------

COMMANDS = {"create", "edit",
            "check", "fix", "resolve", "merge", "help", "h"}
SELECTORS = {"comment", "attr", "project", "id"}  # bare ints detected by isdigit()
VERBS = {"get", "list", "ls", "replace", "add", "+", "del", "mod", "~",
         "link", "unlink", "next", "status", "close", "reopen", "move"}

def _parse_id_arg(arg):
    """Parse a ticket ID from a CLI argument.

    Accepts bare integer N only.  Returns the ID string or None.
    """
    if arg.isdigit():
        return arg
    return None


class ParsedRequest:
    """A single parsed request from the command line."""
    def __init__(self):
        self.verb = None           # str or None
        self.command = None        # (name, args_list) or None
        self.selector_type = None  # "comment" | "attr" | "project" | None
        self.selector_args = []    # e.g. ["assignee"] for attr, ["description"] for project
        self.pipeline = []         # ordered steps: ("id",val) | ("q",expr) | ("r",) | ("p",)
        self.flags = {}            # --force, -r, -n, -q, --format, --file, etc.
        self.verb_args = []        # arguments to the verb

    @property
    def targets(self):
        """Extract bare ticket IDs from pipeline (backward compat)."""
        return [s[1] for s in self.pipeline if s[0] == "id"]


def parse_argv(argv):
    """Parse command-line arguments into a list of ParsedRequest.

    --file/-f is a global flag extracted before splitting by ';'.
    """
    # Extract global --file/-f before splitting
    file_path = None
    filtered = []
    i = 0
    n = len(argv)
    while i < n:
        if argv[i] in ("--file", "-f") and i + 1 < n:
            if file_path is not None:
                raise SystemExit("Error: --file/-f specified more than once")
            file_path = argv[i + 1]
            i += 2
        else:
            filtered.append(argv[i])
            i += 1

    groups = _split_on_semicolons(filtered)
    requests = []
    for group in groups:
        req = _parse_single_request(group)
        if file_path is not None:
            req.flags["file"] = file_path
        requests.append(req)
    return requests


def _split_on_semicolons(argv):
    """Split argv list on ';' tokens."""
    groups = []
    current = []
    for arg in argv:
        if arg == ";":
            if current:
                groups.append(current)
            current = []
        else:
            current.append(arg)
    if current:
        groups.append(current)
    return groups if groups else [[]]


def _parse_flag(argv, i, n, req):
    """Try to parse a flag at position i. Returns new i if consumed, else None."""
    arg = argv[i]
    if arg == "--force":
        req.flags["force"] = True
        return i + 1
    if arg in ("-r", "--recursive"):
        req.flags["recursive"] = True
        req.pipeline.append(("r",))
        return i + 1
    if arg in ("-p", "--parent"):
        req.flags["parent"] = True
        return i + 1
    if arg in ("-h", "--help"):
        req.flags["help"] = True
        return i + 1
    if arg == "-n" and i + 1 < n:
        req.flags["n"] = int(argv[i + 1])
        return i + 2
    if arg == "-q" and i + 1 < n:
        req.flags.setdefault("q", []).append(argv[i + 1])
        req.pipeline.append(("q", argv[i + 1]))
        return i + 2
    if arg == "--format" and i + 1 < n:
        req.flags["format"] = argv[i + 1]
        return i + 2
    if arg == "--title" and i + 1 < n:
        req.flags["title"] = argv[i + 1]
        return i + 2
    if arg == "--text" and i + 1 < n:
        req.flags["text"] = argv[i + 1]
        return i + 2
    if arg == "--attr" and i + 1 < n:
        req.flags["attr_filter"] = argv[i + 1]
        return i + 2
    if arg == "--quiet":
        req.flags["quiet"] = True
        return i + 1
    if arg in ("-e", "--edit"):
        req.flags["edit"] = True
        return i + 1
    if arg == "--start":
        req.flags["start"] = True
        return i + 1
    if arg == "--restart":
        req.flags["restart"] = True
        return i + 1
    if arg == "--accept":
        req.flags["accept"] = True
        return i + 1
    if arg == "--abort":
        req.flags["abort"] = True
        return i + 1
    return None


def _parse_single_request(argv):
    """Parse a single request (no semicolons).

    Two paths:
    1. If the first non-flag token is a command → command dispatch.
       Commands must be the first word.
    2. Otherwise → normal scanning for verbs, selectors, pipeline steps.
    """
    req = ParsedRequest()
    i = 0
    n = len(argv)

    # Consume leading flags
    while i < n:
        new_i = _parse_flag(argv, i, n, req)
        if new_i is not None:
            i = new_i
        else:
            break

    # Path 1: First content token is a command
    if i < n and argv[i] in COMMANDS:
        return _parse_command(argv, i, n, req)

    # Path 2: Normal scanning (verbs, selectors, pipeline)
    while i < n:
        arg = argv[i]

        # --- Flags (can appear anywhere) ---
        new_i = _parse_flag(argv, i, n, req)
        if new_i is not None:
            i = new_i
            continue

        # --- Verbs ---
        if arg in VERBS:
            if req.verb is not None:
                raise SystemExit(
                    f"Error: multiple verbs: '{req.verb}' and '{arg}'")
            req.verb = {"+": "add", "~": "mod", "ls": "list"}.get(arg, arg)
            i += 1
            # Consume verb arguments
            if req.verb in ("replace", "add", "mod"):
                if i < n and not _is_keyword(argv[i]):
                    req.verb_args.append(argv[i])
                    i += 1
            elif req.verb == "list":
                if i < n and argv[i] == "order":
                    req.verb_args.append(argv[i])
                    i += 1
            elif req.verb in ("link", "unlink"):
                while i < n and len(req.verb_args) < 2:
                    a = argv[i]
                    if _is_keyword(a) or a.startswith("-"):
                        break
                    req.verb_args.append(a)
                    i += 1
            elif req.verb in ("status", "close"):
                while i < n:
                    a = argv[i]
                    if _is_keyword(a) or a.startswith("-"):
                        break
                    id_val = _parse_id_arg(a)
                    if id_val is not None:
                        req.pipeline.append(("id", id_val))
                        i += 1
                        continue
                    # First non-integer is the status value
                    if not req.verb_args:
                        req.verb_args.append(a)
                        i += 1
                    break
            elif req.verb == "move":
                _MOVE_DIRS = {"first", "last", "before", "after"}
                while i < n:
                    a = argv[i]
                    if a in _MOVE_DIRS:
                        req.verb_args.append(a)
                        i += 1
                        # Read destination (bare int) after direction
                        if i < n:
                            dest_id = _parse_id_arg(argv[i])
                            if dest_id is not None:
                                req.verb_args.append(argv[i])
                                i += 1
                        break
                    dest_id = _parse_id_arg(a)
                    if dest_id is not None:
                        req.pipeline.append(("id", dest_id))
                        i += 1
                        continue
                    if _is_keyword(a) or a.startswith("-"):
                        break
                    break
            continue

        # --- Bare integer (selector: ticket ID) ---
        id_val = _parse_id_arg(arg)
        if id_val is not None:
            if req.selector_type == "project":
                raise SystemExit(
                    "Error: cannot mix ticket IDs with 'project' selector")
            req.pipeline.append(("id", id_val))
            i += 1
            continue

        # --- Named selectors ---
        if arg in SELECTORS:
            if arg == "comment":
                if req.selector_type not in (None, "comment"):
                    raise SystemExit(
                        f"Error: cannot mix selector types: "
                        f"'{req.selector_type}' and 'comment'")
                req.selector_type = "comment"
                i += 1
                continue

            if arg == "attr":
                if req.selector_type not in (None, "attr"):
                    raise SystemExit(
                        f"Error: cannot mix selector types: "
                        f"'{req.selector_type}' and 'attr'")
                req.selector_type = "attr"
                i += 1
                # Consume attr name — any non-flag token (even keywords
                # like "status" can be attribute names)
                if i < n and not argv[i].startswith("-"):
                    req.selector_args.append(argv[i])
                    i += 1
                continue

            if arg == "project":
                if any(s[0] == "id" for s in req.pipeline):
                    raise SystemExit(
                        "Error: cannot mix ticket IDs with 'project' selector")
                if req.selector_type not in (None, "project"):
                    raise SystemExit(
                        f"Error: cannot mix selector types: "
                        f"'{req.selector_type}' and 'project'")
                req.selector_type = "project"
                i += 1
                # Section name — don't consume verbs/selectors/flags
                if i < n and not _is_keyword(argv[i]):
                    req.selector_args.append(argv[i])
                    i += 1
                continue

            if arg == "id":
                if req.selector_type not in (None, "id"):
                    raise SystemExit(
                        f"Error: cannot mix selector types: "
                        f"'{req.selector_type}' and 'id'")
                req.selector_type = "id"
                i += 1
                # Node ID — any non-flag token (keywords like "project"
                # are valid node IDs)
                if i < n and not argv[i].startswith("-"):
                    req.selector_args.append(argv[i])
                    i += 1
                continue

        # --- Verb arg that landed after flags ---
        if req.verb in ("replace", "add", "mod") and not req.verb_args:
            req.verb_args.append(arg)
            i += 1
            continue
        if req.verb in ("link", "unlink") and len(req.verb_args) < 2:
            req.verb_args.append(arg)
            i += 1
            continue
        if req.verb in ("status", "close") and not req.verb_args:
            id_val = _parse_id_arg(arg)
            if id_val is not None:
                req.pipeline.append(("id", id_val))
            else:
                req.verb_args.append(arg)
            i += 1
            continue

        # --- Implicit query ---
        _validate_implicit_q(arg)
        req.flags.setdefault("q", []).append(arg)
        req.pipeline.append(("q", arg))
        i += 1
        continue

    # --- Post-parse ---
    # -h flag converts to help command
    if req.flags.get("help"):
        if req.verb:
            req.command = ("help", [req.verb])
        elif req.selector_type:
            req.command = ("help", [req.selector_type])
        else:
            req.command = ("help", [])
        return req

    # Default verb is 'get' when no command present
    if req.verb is None:
        req.verb = "get"

    # Validation
    if req.verb in ("list", "next") and req.selector_type in ("comment", "attr"):
        raise SystemExit(
            f"Error: '{req.verb}' verb cannot be used with "
            f"'{req.selector_type}' selector")

    return req


def _parse_command(argv, i, n, req):
    """Parse a command starting at position i.

    Commands consume all remaining non-flag tokens as arguments.
    """
    cmd = argv[i]
    i += 1
    cmd_args = []

    if cmd in ("help", "h"):
        # help takes one optional topic
        while i < n:
            new_i = _parse_flag(argv, i, n, req)
            if new_i is not None:
                i = new_i
                continue
            if not cmd_args:
                cmd_args.append(argv[i])
                i += 1
            else:
                break
        req.command = ("help", cmd_args)

    elif cmd in ("check", "fix", "resolve"):
        req.command = (cmd, [])

    elif cmd == "merge":
        return _parse_merge(argv, i, n, req)

    else:
        # create, edit: consume all remaining non-flag tokens
        while i < n:
            new_i = _parse_flag(argv, i, n, req)
            if new_i is not None:
                i = new_i
                continue
            cmd_args.append(argv[i])
            i += 1
        req.command = (cmd, cmd_args)

    # -h flag converts to help about this command
    if req.flags.get("help") and req.command[0] not in ("help", "h"):
        req.command = ("help", [req.command[0]])

    return req


_MERGE_ENUM_FLAGS = {"--prefer": "prefer", "--renumber": "renumber"}
# Value flags taking an arbitrary string argument (source specs / output path).
_MERGE_VALUE_FLAGS = {
    "--to": "merge_to",
    "--from": "merge_from",
    "--base": "merge_base",
    "-o": "merge_output",
    "--output": "merge_output",
}
_MERGE_BOOL_FLAGS = {
    "--resolve": "merge_resolve",
    "--abort": "abort",
    "--check": "merge_check",
    "--stage": "stage",
    "--no-stage": "no_stage",
    "--no-edit": "no_edit",
}


def _parse_merge(argv, i, n, req):
    """Parse the `merge` command: an OPTIONAL <branch> plus merge-specific flags.

    Grammar:
        plan merge [<branch>] [--to SRC] [--from SRC] [--base SRC] [-o|--output OUT]
                   [--renumber to|from] [--prefer to|from]
                   [--stage|--no-stage] [--no-edit] [--check]
        plan merge --resolve [-o OUT]
        plan merge --abort   [-o OUT]

    A positional <branch> is shorthand for `--from <branch>`; supplying both a
    positional branch and an explicit --from is an error. Sources/output land in
    req.flags as merge_to/merge_from/merge_base/merge_output; req.command holds
    the positional branch (or nothing). The merge-specific flags are recognized
    only inside this parser so they cannot leak into the general flag set used by
    other commands.
    """
    branch = None
    while i < n:
        arg = argv[i]
        # Generic flags shared with other commands (e.g. -h/--help) still apply.
        # NOTE: the global _parse_flag also recognizes --abort (used by edit);
        # we let it set req.flags["abort"] which _handle_merge reads.
        new_i = _parse_flag(argv, i, n, req)
        if new_i is not None:
            i = new_i
            continue
        # Value flags: --to / --from / --base / -o|--output take a string arg.
        if arg in _MERGE_VALUE_FLAGS:
            if i + 1 >= n:
                raise SystemExit("Error: %s requires a value" % arg)
            req.flags[_MERGE_VALUE_FLAGS[arg]] = argv[i + 1]
            i += 2
            continue
        # Enum flags: --prefer / --renumber take a validated to|from value.
        if arg in _MERGE_ENUM_FLAGS:
            if i + 1 >= n:
                raise SystemExit("Error: %s requires a value (to|from)" % arg)
            val = argv[i + 1]
            if val not in ("to", "from"):
                raise SystemExit(
                    "Error: %s must be 'to' or 'from', got %r" % (arg, val))
            req.flags[_MERGE_ENUM_FLAGS[arg]] = val
            i += 2
            continue
        # Boolean merge flags.
        if arg in _MERGE_BOOL_FLAGS:
            req.flags[_MERGE_BOOL_FLAGS[arg]] = True
            i += 1
            continue
        if arg.startswith("-"):
            raise SystemExit("Error: unknown flag for merge: %s" % arg)
        # First bare token is the branch (shorthand for --from); a second errors.
        if branch is not None:
            raise SystemExit(
                "Error: merge takes at most one branch, got extra %r" % arg)
        branch = arg
        i += 1

    # A positional branch is shorthand for --from. We record whether BOTH a
    # positional and an explicit --from were supplied so the handler can reject
    # that with the merge exit code (2) rather than a generic parse error (1).
    if branch is not None:
        if "merge_from" in req.flags:
            req.flags["merge_both_from"] = True
        else:
            req.flags["merge_from"] = branch

    # Keep the positional in req.command for back-compat. An empty list means
    # "no positional branch given".
    cmd_args = [branch] if branch is not None else []
    req.command = ("merge", cmd_args)

    # -h flag converts to help about the merge command.
    if req.flags.get("help"):
        req.command = ("help", ["merge"])

    return req


def _validate_implicit_q(arg):
    """Validate an implicit query argument.

    Bare identifiers must be known DSL names; compound expressions must
    reference at least one known DSL name (to catch typos like 'qwe == asd'
    where DefaultNamespace returns '' for both sides).
    """
    known_lower = sorted(n for n in DSL_FILTER_NAMES if n[0].islower())
    if not arg.isidentifier():
        # Compound expression — compile and check referenced names
        try:
            code = compile(arg, "<query>", "eval")
        except SyntaxError as e:
            raise SystemExit(
                f"Error: invalid filter expression: {arg}\n  {e.msg}")
        unknown = [n for n in code.co_names if n not in DSL_FILTER_NAMES]
        if len(unknown) > 1 and not any(
                n in DSL_FILTER_NAMES for n in code.co_names):
            raise SystemExit(
                f"Error: unknown name(s) in filter: {', '.join(unknown)}\n"
                f"  Known: {', '.join(known_lower)}"
            )
        return
    if arg not in DSL_FILTER_NAMES:
        if arg in COMMANDS:
            raise SystemExit(
                f"Error: '{arg}' is a command and must be the first word\n"
                f"  Usage: plan {arg} ..."
            )
        raise SystemExit(
            f"Error: unknown filter name: {arg}\n"
            f"  Known: {', '.join(known_lower)}"
        )


def _is_keyword(arg):
    """Check if arg is a known selector, verb, or flag keyword.

    Commands are not included — they are only valid as the first word.
    """
    return arg in SELECTORS or arg in VERBS or arg in (
        "--force", "-r", "--recursive", "-n", "-q", "--format",
        "--title", "--text", "--attr", "-p", "--parent", "-h", "--help",
        "-e", "--edit", "--quiet",
        "--start", "--restart", "--accept", "--abort",
    )
# }}} # SOURCE END: 120-cli.py

# SOURCE START: 130-file.py {{{
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

# }}} # SOURCE END: 130-file.py

# SOURCE START: 135-help+.py {{{
# ---------------------------------------------------------------------------
# Help Text Constants (generated from src/help/)
# ---------------------------------------------------------------------------

HELP_TEXT = """\
plan — Markdown Ticket Tracker

Usage: plan <command> [args] [flags]
       plan [selectors] [verb] [args] [flags] [; ...]

Global flags:
  -f, --file FILE   Use specific plan file (must appear before ';')
  PLAN_MD env var   Fallback file path
  .PLAN.md          Auto-discovered at git root

Commands (must be the first word):
  create [parent] EXPR | - | -e
                    Create new ticket (title required, - for stdin, -e for editor)
  edit ID [-r]      Edit ticket in $EDITOR (-r includes children)
  check             Validate document
  fix               Auto-repair document
  merge <branch>    Structure-aware three-way merge of the plan file
                    (--resolve | --abort | --check; see 'help merge')
  resolve           Recover a file with raw git conflict markers
  install local|user|git  Install binary/plugin/CLAUDE.md ('git' = merge driver only)
  uninstall local|user|git  Remove binary, plugin, CLAUDE.md ('git' = merge driver only)
  help [TOPIC]      Show help on command/verb/selector
  help dsl          Help on DSL for selectors, filters, expressions

Selectors and filters (left-to-right pipeline):
  N                 Select ticket by ID (bare integer)
  id NAME           Select any node by its #id (section, ticket, comment)
  comment           Narrow to ticket's comments
  attr NAME         Narrow to a specific attribute
  project [SECTION] Select project-level section
  -r, --recursive   Add all descendant tickets to the selection
  -p, --parent      Add all ancestor tickets (up to root) to the result
  -q EXPR           Query expression (usually implicit — non-numeric args
                    are auto-promoted to -q).  bool → filter, list/int → selector

Verbs (at most one per request):
  get               Print content (default)
  list / ls         List titles / children summary
  replace --force   Replace content (text, -, @file)
  add / +           Smart append
  del               Delete target
  mod / ~           Modify via DSL expression
  link [TYPE] ID    Link to ticket (default: related)
  unlink [TYPE|all] ID
                    Remove link (default: all)
  next              Next ticket in execution order (list order -n 1)
  status STATUS     Set ticket status
  close [RESOLUTION]
                    Close ticket (default: done)
  reopen            Reopen ticket (set status to open)
  move          Reorder: first | last | before|after dest
                Reparent: dest | first|last dest

Selectors and verbs can appear in either order:
  plan 5 list
  plan list 5 - both show ticket 5 in list format

Selectors add to the working set; filters narrow it.
If the first step is a selector, the initial set is empty.
If the first step is a filter, the initial set is all tickets.
Order matters: plan 1 -r is_open ≠ plan is_open 1 -r

-p is a flag, not a pipeline step — it always adds ancestors to the
final result regardless of position. plan -p 3 = plan 3 -p.

Multiple tickets:  plan 5 6 7 close
Multiple requests: plan 5 status done ";" 6 status in-progress

Examples:
  plan list                          All tickets
  plan 5                             Show ticket #5
  plan create -e                     Create ticket (opens editor)
  plan create 5 -e                   Create child of #5
  plan edit 5                        Edit in $EDITOR
  plan 5 status in-progress          Set status
  plan 5 close                       Close ticket
  plan 5 comment add "Note"          Add comment
  plan 5 -r list                     Ticket #5 and descendants
  plan 5 move 3                      Move #5 under #3
"""


DSL_HELP = """\

DSL expressions:

  Namespace variables (available in -q, --format, mod):
    id          Ticket number (int)
    title       Ticket title (str)
    text        Body text (str)
    status      Status value (str)
    is_open     True if status is active or deferred (bool)
                  active:   open, in-progress, assigned, blocked,
                            reviewing, testing
                  deferred: backlog, deferred, future, someday,
                            wishlist, paused, on-hold
                  Unset status is open. Any other status is closed.
    is_active   True if status is active (not deferred or closed) (bool)
    ready       True if is_active and no active blockers or children (bool)
    move        Ephemeral attribute for positioning. In set():
                "first [N]", "last [N]", "before N", "after N",
                or bare ticket ID. Not available in filters.
    assignee    Assignee name (str)
    depth       Nesting level, 0 = top-level (int)
    indent      "  " * depth (str)
    parent      Parent ticket ID (int), 0 if root
    children    Child tickets (list)
    links       Link dict, e.g. {"blocked": [3]}
    Any other attribute on the ticket is also available.

  Helper functions:
    parent_of(N)             Parent ticket ID of #N (0 if root; 0 = virtual root)
    is_descendant_of(P)      True if current ticket is a descendant of #P
    is_descendant_of(P, C)   True if #C is a descendant of #P
    children_of(N)           List of child ticket IDs of #N (0 = top-level)
    children_of(N, True)     All descendant IDs recursively
    children()               Returns list of direct children of current ticket
    children(recursive=True) Returns all descendants recursively

  Builtins:
    len, any, all, min, max, sorted, int, str, float,
    True, False, None, file (reads a file path)

  Filter (-q EXPR, usually implicit):
    Evaluated per-ticket. Return truthy to include.
    Example: plan 'status == "open" and assignee == "alice"' list

  Format (--format EXPR):
    Evaluated per-ticket. Result is printed.
    Example: --format 'f"{indent}#{id} [{status}] {title}"'

  Mutator functions (mod / ~ only):
    set(key=val, ...)   Set attributes. Keys: title, text, or any attr.
    add(key=val, ...)   Append to composite attrs:
                          text   — appends a line to body
                          links  — appends link string (e.g. "blocked:#3")
                          comment — creates a new comment with the value
    delete(name, ...)   Remove named attributes.
    link(type, id)      Add a link (with mirror). Types: blocked,
                          blocking, related, derived, derived-from,
                          caused, caused-by.
    unlink(type, id)    Remove a link (with mirror).

  Composition:
    Chain with commas: set(status="done"), add(text="note")

  Filter examples:
    plan 'not parent' list              List top-level tickets only
    plan 'depth == 0' list              Same as above
    plan 'assignee == "alice"' list     Tickets assigned to alice
    plan 'is_descendant_of(5)' list     All descendants of #5
    plan '"auth" in title' list         Tickets with "auth" in title

  Mutator examples:
    plan 5 ~ 'set(status="in-progress", assignee="alice")'
    plan 5 ~ 'set(move="first")'
    plan 5 ~ 'set(move="first 3")'     Move under #3 as first child
    plan 5 ~ 'set(move="after 3")'     Move to be a sibling after #3
    plan 5 ~ 'add(text="Extra detail")'
    plan 5 ~ 'link("blocked", 3)'
    plan 5 ~ 'delete("estimate")'
"""

COMMAND_HELP = {
    'add': """\
plan add — Append content (smart append)

Usage:
  plan N add TEXT
  plan N + TEXT
  plan N add -e                  Open editor to append text
  plan N -r add TEXT             Append to ticket and all descendants

Appends to the ticket body text. '+' is a shorthand for 'add'.
Text can be a literal string, @filepath, - for stdin, or -e for editor.

Flags:
  -e, --edit      Open $EDITOR for text input

Examples:
  plan 5 add "Another paragraph"
  plan 5 + "Quick note"
  plan 1 -r add "Sprint 5 note"
  plan 5 add                     Open editor to append text
  plan 5 add -e                  Same as above
""",

    'attr': """\
plan attr — Get or set ticket attributes (selector)

Usage:
  plan 5 attr NAME                       Get attribute value
  plan 5 attr NAME get                   Same as above
  plan 5 attr NAME add VAL               Append to attribute (links)
  plan 5 attr NAME del                   Delete attribute
  plan 5 attr NAME replace --force VAL   Replace attribute value
  plan 5 -r attr NAME replace --force VAL
                                          Set on ticket and descendants

Selectors and verbs can appear in either order:
  plan 5 attr NAME get    ─┐
  plan get 5 attr NAME    ─┘ equivalent

Attributes are key-value pairs stored under each ticket (status,
assignee, links, estimate, or any custom name).

Examples:
  plan 5 attr assignee
  plan 1 -r attr status replace --force open
""",

    'check': """\
plan check — Validate the plan document

Usage:
  plan check

Checks for structural issues: duplicate IDs, broken links,
orphaned comments, and other inconsistencies. Exits with a
non-zero status if errors are found.
""",

    'close': """\
plan close — Close ticket with a resolution (verb)

Usage:
  plan SELECTOR close [RESOLUTION]
  plan SELECTOR -r close [RESOLUTION]

  Sets status to RESOLUTION (default: done).

Bare integer IDs after 'close' are treated as selectors, not
as the resolution:
  plan close 5 done              Same as: plan 5 close done

Examples:
  plan 5 close
  plan 5 close duplicate
  plan close 1 2 done            Selectors after verb
  plan 1 -r 'status == "open"' close done
  plan is_open close "won't do"
""",

    'comment': """\
plan comment — Access or add comments on a ticket (selector)

Usage:
  plan 5 comment             List comments
  plan 5 comment get         Same as above
  plan 5 comment add TEXT    Add a new comment
  plan 5 comment add -e      Open editor to add comment
  plan add TEXT 5 comment    Same as above (either order)
  plan 5 -r comment add TEXT Add comment to ticket and all descendants

Selectors and verbs can appear in either order.

Examples:
  plan 5 comment
  plan 5 comment add "Needs review"
  plan add "Needs review" 5 comment
  plan 1 -r comment add "Sprint 5"
  plan 5 comment add                 Open editor to add comment
  plan 5 comment add -e              Same as above
""",

    'create': """\
plan create — Create a new ticket (command)

Usage:
  plan create [parent] [--quiet] EXPR
  plan create [parent] [--quiet] -
  plan create [parent] [-e]

  EXPR is a keyword expression: title is required; other attributes
  are optional. Use '-' to read a template or bulk markdown from stdin
  (same format as the editor template). Use '-e' to open $EDITOR with
  a template. Prints the new ticket number on success.

  When input (from stdin or editor) contains * ## headers,
  tickets are created in bulk from the markdown hierarchy. Use
  {#newXXX} placeholders for cross-references between new tickets.
  IDs, timestamps, and status are auto-assigned. Explicit numeric
  IDs are not allowed in create mode.

Arguments:
  parent          Optional parent ticket ID (bare integer) for nesting
  EXPR            Keyword expression (evaluated via set())
  -               Read template or bulk markdown from stdin

Flags:
  -e, --edit      Open $EDITOR for text input
  --quiet         Suppress printing the new ticket number

The move attribute accepts positional expressions that may also
reparent the ticket: "first [N]", "last [N]", "before N", "after N".
"first N" / "last N" place under parent N (0 for root).
"before N" / "after N" place as sibling of N.
A bare ticket ID reparents as last child.

Examples:
  plan create 'title="Fix login bug"'
  plan create 'title="Sub-task", status="open"'
  plan create 5 'title="Child task"'
  plan create 'title="Urgent", move="first"'
  plan create --quiet 'title="Silent create"'
  echo '## My task' | plan create -        Create from template via stdin
  plan create                              Open editor to create ticket
  plan create -e                           Same as above
  plan create 5 -e                         Create child of #5 in editor
  plan create -e 'title="Bug"'            Open editor with title pre-filled

Bulk creation (markdown input — tickets execute in creation order):
  plan create [parent] - <<'EOF'
  * ## Epic: Auth
    Auth system.
    * ## JWT
      JWT middleware.
  * ## Epic: Database
    Schema and migrations.
  EOF

  Use {#placeholder} IDs for cross-branch dependencies:
  * ## Set up DB {#db}
  * ## Build API
        links: blocked:#db

See 'plan help dsl' for DSL expression syntax.
""",

    'del': """\
plan del — Delete content

Usage:
  plan N del                       Delete a ticket (must have no children)
  plan del N                       Same as above
  plan N -r del                    Delete ticket and all descendants
  plan N -r EXPR del               Delete matching descendants only
  plan N attr NAME del             Delete an attribute

Selectors and verbs can appear in either order.
Tickets with child tickets require -r to delete recursively.

Examples:
  plan 5 del
  plan del 5
  plan 1 -r del
  plan 1 -r 'status=="closed"' del
""",

    'edit': """\
plan edit — Edit in external editor (or non-interactively for agents)

Usage:
  plan edit ID                   Edit single ticket
  plan edit ID -r                Edit entire subtree in one editor
  plan edit --start ID           Export ticket to a temp file (non-interactive)
  plan edit --start ID -r        Export ticket + children to a temp file
  plan edit --restart ID         Abort existing edit and start fresh
  plan edit --accept [ID]        Apply edited temp file and clean up
  plan edit --abort [ID]         Delete temp file without applying

Opens the ticket or node content in $EDITOR for interactive editing.
Saves changes back to the plan file on exit. ID can be a ticket
number, section name, or any node identifier.

When editing recursively (-r), you can add new tickets by writing
* ## headers without an ID or with {#newXXX} placeholders.
New ticket IDs, timestamps, and status are auto-assigned.

Non-interactive (agent) workflow:
  --start creates a .PLAN-edit-{ID}-{hash}.md file next to .PLAN.md.
  Edit that file, then run --accept to apply and clean up.
  --accept and --abort accept an optional ID; if omitted and exactly
  one edit file exists, it is used automatically.
  --abort and --restart are idempotent (no error if no edit is in flight).
  A hash mismatch on --accept means the base changed; use --restart.

Flags:
  -r, --recursive    Edit the entire subtree (ticket + children) recursively.
  --start ID         Export ticket content to a temp file for non-interactive editing.
  --restart ID       Abort any existing edit for ID and start a fresh export.
  --accept [ID]      Apply the edited temp file to the plan and delete the temp file.
  --abort [ID]       Delete the temp file without applying any changes.

Examples:
  plan edit 5                    Edit ticket #5 interactively
  plan edit 5 -r                 Edit ticket #5 and all children
  plan edit description          Edit project description section
  plan edit project              Edit the project root node
  plan edit --start 5            Export ticket #5 to a temp file
  plan edit --start 5 -r         Export ticket #5 and children to a temp file
  plan edit --accept             Apply the edit (when only one edit is in flight)
  plan edit --accept 5           Apply the edit for ticket #5
  plan edit --abort 5            Discard the edit for ticket #5
  plan edit --restart 5          Abort existing edit and start fresh for ticket #5
""",

    'fix': """\
plan fix — Auto-repair the plan document

Usage:
  plan fix

Fixes common issues found by 'check': re-assigns duplicate IDs,
removes broken links, and repairs other structural problems.
""",

    'get': """\
plan get — Print content (default verb)

Usage:
  plan N get                     Print ticket content
  plan get N                     Same as above
  plan N -r get                  Print full subtree (markdown tree view)
  plan N -r EXPR get              Print matching descendants individually

'get' is the default verb — if no verb is specified, get is used.
Selectors and verbs can appear in either order.

Examples:
  plan 5
  plan 5 -r get
  plan get 5 -r
  plan 1 -r 'status=="open"' get
""",

    'id': """\
plan id — Select any node by its #id (selector)

Usage:
  plan id NAME                  Get node content (implicit get)
  plan id NAME get              Same as above
  plan id NAME -r               Recursive subtree view
  plan -p id NAME               Show with ancestor chain
  plan id NAME list             List children
  plan id NAME add TEXT          Append text
  plan id NAME replace --force TEXT
                                Replace content

NAME is any #id in the document: section names (description,
metadata), ticket numbers (3), or compound ids (1:comment:2).
For numeric IDs, 'plan id 3' is equivalent to 'plan 3'.

Examples:
  plan id description
  plan id description add "New paragraph"
  plan id 3                     Same as 'plan 3'
  plan id 1:comment:2
  plan id 3 -r get
  plan -p id 3
""",

    'install': """\
plan install — Install plan binary, Claude Code plugin, and instructions

Usage:
  plan install local    Install into current directory / project
  plan install user     Install into ~/.local/bin and ~/.claude
  plan install git       Configure ONLY the git merge driver in this repo

What gets installed:
  Binary     'local': ./plan, 'user': ~/.local/bin/plan
             Skipped if plan is already on PATH.
  Plugin     'local': .claude/plugins/claude-plan/
             'user': ~/.claude/plugins/claude-plan/
             Registered in the corresponding settings.json.
  CLAUDE.md  'local': ./CLAUDE.md
             'user': ~/.claude/CLAUDE.md
             Appends task tracking instructions. Skipped if already present.
  AGENTS.md  'local': ./AGENTS.md (Codex)
             'user': ~/.codex/instructions.md
             Appends task tracking instructions. Skipped if already present.
  Merge      'local' and 'git': configure the .PLAN.md merge driver in the
  driver     current repo — adds '.PLAN.md merge=plan' to .gitattributes, sets
             merge.plan.driver in git config, and ignores '.PLAN.md.reject'.
             'user' does not touch any repo.

The 'git' target installs ONLY the merge driver (no binary, plugin, or
CLAUDE.md/AGENTS.md). It must be run inside a git repository; otherwise it
exits with an error.
""",

    'link': """\
plan link — Link tickets together (verb)

Usage:
  plan ID link TARGET            Link as related (default)
  plan ID link TYPE TARGET       Link with specific type
  plan ID... link TYPE TARGET    Link multiple sources

  TYPE is one of: blocked, blocking, related, derived, derived-from,
  caused, caused-by. Default: related.

  Mirror links are maintained automatically.

Examples:
  plan 5 link 3                  #5 related to #3
  plan 5 link blocked 3          #5 blocked by #3
  plan 1 2 3 link blocked 5      Link #1, #2, #3 as blocked by #5
""",

    'list': """\
plan list — List and query tickets (verb)

Usage:
  plan list                   List all tickets
  plan 5 list                 Show ticket 5 in list format
  plan list 5                 Same as above
  plan 5 -r list              Show ticket 5 and all descendants
  plan list ready              Show only tickets ready for work
  plan list is_active          Show active tickets (excludes deferred)
  plan list order             Show tickets in execution order
  plan [selectors] list [flags]
  plan list [flags] [selectors]

Selectors and verbs can appear in either order.
Output always shows tree-depth indentation.

Flags:
  -r, --recursive   Recursive (include all descendants)
  -q EXPR         Query expression (usually implicit; bool → filter, list/int → selector)
  --format EXPR   Format output with DSL expression
  -n N            Limit to first N results
  --title PAT     Filter by title substring
  --text PAT      Filter by body text substring
  --attr EXPR     Filter by attribute expression
  -p, --parent    Include ancestor path to the target ticket
  order           Verb argument: topological sort by execution order

DSL filter properties:
  is_open         Status is active or deferred (not closed)
  is_active       Status is active (not deferred or closed)
  ready           is_active + no active blockers or children

Examples:
  plan list
  plan 5 list
  plan 5 -r list
  plan -r list
  plan list ready
  plan list is_active
  plan list order
  plan 'status == "open"' list
  plan -p is_open -r list            Filter with tree context
  plan list --format 'f"{indent}#{id} {title}"'

See 'plan help dsl' for DSL expression syntax.
""",

    'merge': """\
plan merge — Structure-aware three-way merge of the plan file

Usage:
  plan merge <branch> [--renumber to|from] [--prefer to|from]
                      [--stage|--no-stage] [--no-edit]
  plan merge <branch> --check
  plan merge [--to SRC] --from SRC [--base SRC] [-o OUT] [flags]
  plan merge --resolve [-o OUT]
  plan merge --abort   [-o OUT]

Merges the plan file from <branch> into the current branch using a
structural three-way merge (base = merge-base, 'to' = current branch,
'from' = <branch>). It merges per ticket/comment and per field by
identity (ID), not by file position, so it reconciles changes that a
line-based merge cannot.

Explicit sources: instead of a positional <branch> (shorthand for
'--from <branch>'), name each side with --to / --from / --base. A SRC is:
  git:<ref>     a git commit/ref (requires a repo)
  file:<path>   a filesystem path
  <bare>        auto: an existing path is a file, else a git ref
'--to' defaults to the working-tree plan file; '--base' is optional —
when omitted, a merge-base is auto-computed if both sides are commits,
otherwise a (lossy) two-way merge is used. With explicit file sources
this works entirely OUTSIDE a git repo. Use -o/--output OUT to write the
result elsewhere (default: the --to file, or the discovered plan file);
the in-progress state then lives in '<OUT>.reject' + '<dir>/.plan-merge',
so '--resolve -o OUT' / '--abort -o OUT' finish it with or without git.

The two sides are 'to' (the side merged INTO — your current branch, kept
canonical) and 'from' (the side merged FROM — <branch>). The auto-merged
result is always written to the plan file and is always valid: at each
unresolved conflict the 'to' (your) side is kept, so the file stays
usable even before you resolve. Tickets/comments created independently
on both sides with the same ID are renumbered (the incoming 'from' side
by default) and every reference (links, parent nesting, #N mentions) is
rewritten.

If genuine conflicts remain, a '<planfile>.reject' sidecar is written
listing the conflicting blocks and the command exits non-zero. Edit the
sidecar (keep one side per block — see below), then run
'plan merge --resolve'.

Modes:
  <branch>          Merge <branch> into the working-tree plan file.
  --check           Dry run: compute the merge, print the conflict
                    count, write nothing. Exits non-zero if conflicts.
  --resolve         Apply the edited '<planfile>.reject' and finish.
  --abort           Discard an in-progress merge (restore the pre-merge
                    plan file) and remove the '.reject'.

Flags:
  --to SRC                 The side merged INTO (default: working-tree
                           plan file). git:<ref> | file:<path> | bare.
  --from SRC               The side merged FROM (required). A positional
                           <branch> is shorthand for --from <branch>.
  --base SRC               Explicit merge base (forces three-way). When
                           omitted: auto merge-base for commit sides,
                           else two-way.
  -o, --output OUT         Write the merged result to OUT (default: the
                           --to file, else the discovered plan file).
  --renumber to|from       Which side's colliding new IDs get reassigned
                           (default: from).
  --prefer to|from         Auto-resolve ALL conflicts to one side; no
                           '.reject' is written.
  --stage / --no-stage     Whether to mark the plan file unmerged in the
                           git index. Standalone default is file-only
                           (index untouched); inside a real git
                           merge/rebase the index is handled
                           automatically. No-op outside a git repo.
  --no-edit                Do not auto-launch $EDITOR on the '.reject'.

Resolving the .reject file:
  Each block shows '--- to (<branch>) ---' and
  '--- from (<branch>) ---'. Keep EXACTLY ONE side: delete the other
  side entirely, or delete a side's indicator line and leave only its
  content. Do NOT edit the content — only choose a side. A side whose
  content is <DELETED> removes the entry. Do not edit the '#' header or
  the '<<<' / '>>>' lines. Then run 'plan merge --resolve' (or
  'plan merge --abort' to discard).

Git merge driver:
  'plan install local' configures a git merge driver for the repo, so a
  plain 'git merge' / 'git rebase' / 'cherry-pick' / 'stash pop'
  reconciles the plan file automatically. On conflict git leaves the
  file unmerged plus a '.reject'; finish with 'plan merge --resolve'
  then 'git add'. ('plan merge-driver' is the internal entry git calls;
  you do not run it directly.)

Exit codes:
  0   merged cleanly, or --resolve succeeded
  1   conflicts need action (.reject written), or --check found conflicts
  2   error (bad branch, parse failure, edited/unresolved blocks, or no
      merge in progress for --resolve / --abort)

Examples:
  plan merge main                    Merge main into the current branch
  plan merge main --check            Report conflicts without writing
  plan merge main --prefer to        Take your side on every conflict
  plan merge --from v1.0:.PLAN.md    Merge a plan as of a tag (git: ref)
  plan merge --to a.md --from b.md -o out.md
                                     Merge two files outside git into out.md
  plan merge --resolve -o out.md     Finish an out.md merge (no git needed)
  plan merge --resolve               Apply edits from the .reject file
  plan merge --abort                 Discard the in-progress merge

See 'plan help resolve' for recovering a file that already contains raw
git conflict markers (a driver-less merge).
""",

    'mod': """\
plan mod — Modify ticket via DSL expression

Usage:
  plan N mod EXPR
  plan N ~ EXPR
  plan N -r mod EXPR             Apply to ticket and all descendants
  plan N -r FILTER mod EXPR      Apply to matching descendants

  '~' is a shorthand for 'mod'. EXPR is evaluated in a sandboxed
  namespace with access to ticket attributes and mutator functions.

Examples:
  plan 5 ~ 'set(assignee="alice")'
  plan 1 -r ~ 'set(status="in-progress")'
  plan 1 -r 'type=="Bug"' ~ 'set(status="open")'

See 'plan help dsl' for DSL expression syntax.
""",

    'move': """\
plan move — Move and/or reorder tickets (verb)

Usage:
  plan SELECTOR move first          Move to first among siblings
  plan SELECTOR move last           Move to last among siblings
  plan SELECTOR move first DEST     Move as first child of DEST
  plan SELECTOR move last DEST      Move as last child of DEST
  plan SELECTOR move before DEST    Move before sibling DEST
  plan SELECTOR move after DEST     Move after sibling DEST

A direction (first, last, before, after) is required.
DEST can be 0 to target the root level.

Selectors can appear before or after 'move', but must come
before the direction keyword:
  plan 5 move after 7          Selector before move
  plan move 5 after 7          Selector after move

Multiple targets are moved in selection order, each placed
sequentially at the requested position.

The same values can be used with the 'move' attribute in
set(move="...") or in the ticket's attributes in the file.

Examples:
  plan 5 move first 3          Move 5 as first child of 3
  plan 5 move last 3           Move 5 as last child of 3
  plan 5 move before 7         Move 5 before sibling 7
  plan 5 move first            Move 5 to first among current siblings
  plan 5 move first 0          Move 5 to first at root
  plan 5 7 9 move first        Place 5, 7, 9 first in order
  plan 5 7 move after 3        Place 5 after 3, then 7 after 5
  plan move 5 after 7          Selector after move keyword
  plan 5 ~ 'set(move="first")' Move via DSL
""",

    'next': """\
plan next — Show next ticket in execution order (verb)

Usage:
  plan next                      Next ticket (list order -n 1)
  plan next -n 3                 Next 3 tickets
  plan next 'assignee==""'       Next unassigned ticket

  Shortcut for 'list order -n 1'. The -n flag overrides the default
  limit of 1. All other list flags work normally.

Examples:
  plan next
  plan next --format 'f"{indent}#{id} {title}"'
  plan next -n 5
""",

    'project': """\
plan project — Access project-level sections (selector)

Usage:
  plan project                 List all project sections
  plan project SECTION         Print a section's content
  plan project SECTION add TXT Append text to a section
  plan project SECTION replace --force TXT
                               Replace section content

Sections are the markdown headings under the project root, such as
Metadata, Description, Roles, etc.

Examples:
  plan project
  plan project description
  plan project metadata get
  plan project description add "New paragraph"
""",

    'reopen': """\
plan reopen — Reopen a closed ticket (verb)

Usage:
  plan SELECTOR reopen
  plan SELECTOR -r reopen

  Sets status to "open".

Examples:
  plan 5 reopen
  plan 5 7 9 reopen
  plan 1 -r reopen
""",

    'replace': """\
plan replace — Replace content

Usage:
  plan N replace --force TEXT
  plan N -r replace --force TEXT   Replace on ticket and all descendants

Replaces the body text of a ticket or section. Requires --force.
Text can be a literal string, @filepath, or - for stdin.

Examples:
  plan 5 replace --force "New body text"
  plan 1 -r replace --force @notes.txt
""",

    'resolve': """\
plan resolve — Recover a plan file with raw git conflict markers

Usage:
  plan resolve

Best-effort recovery for a plan file that already contains raw git
conflict markers ('<<<<<<<', '=======', '>>>>>>>') — i.e. a merge done
WITHOUT the git merge driver. It reconstructs both sides from the
markers and runs a structure-aware merge (three-way if diff3 '|||||||'
base markers are present, otherwise a lossier two-way merge that cannot
distinguish add from delete).

The file is cleaned (markers removed) and the auto-merged result is
written; unresolved conflicts default to your ('to') side. If genuine
conflicts remain, a '<planfile>.reject' is written so you can finish
per-field with 'plan merge --resolve' (or 'plan merge --abort').

This is the degraded cousin of 'plan merge' and is lossier. Prefer
'plan merge <branch>', or install the git merge driver with
'plan install local' so merges reconcile automatically.

Exit codes:
  0   no markers found, or markers reconciled cleanly
  1   reconciled, but field conflicts remain (.reject written; finish
      with 'plan merge --resolve')
  2   a merge is already in progress, or a hard error

See 'plan help merge' for the primary structure-aware merge command.
""",

    'status': """\
plan status — Set ticket status (verb)

Usage:
  plan SELECTOR status STATUS
  plan SELECTOR -r status STATUS

  STATUS is any string (e.g. open, in-progress, done, planned).

Bare integer IDs after 'status' are treated as selectors, not
as the status value:
  plan status 5 in-progress      Same as: plan 5 status in-progress

Examples:
  plan 5 status in-progress
  plan 5 7 9 status planned
  plan status 1 2 in-progress    Selectors after verb
  plan is_open status in-progress
  plan 1 -r 'assignee == "alice"' status in-progress
""",

    'uninstall': """\
plan uninstall — Remove plan binary, plugin, and instruction sections

Usage:
  plan uninstall local    Remove from current directory / project
  plan uninstall user     Remove from ~/.local/bin and ~/.claude
  plan uninstall git       Remove ONLY the git merge driver from this repo

Removes the binary, plugin directory, settings.json registration, and
the task tracking section from CLAUDE.md and AGENTS.md. Empty files
and directories are cleaned up.

'local' and 'git' also remove the .PLAN.md merge driver config from the
current repo (.gitattributes line, merge.plan git config section, and the
'.PLAN.md.reject' .gitignore line). The 'git' target removes ONLY that
driver config and must be run inside a git repository.
""",

    'unlink': """\
plan unlink — Remove links between tickets (verb)

Usage:
  plan ID unlink TARGET          Remove ALL links to TARGET
  plan ID unlink TYPE TARGET     Remove specific link type
  plan ID unlink all TARGET      Explicit: remove all links

  TYPE is one of: blocked, blocking, related, derived, derived-from,
  caused, caused-by, all. Default: all.

Examples:
  plan 5 unlink 3                Remove all links between #5 and #3
  plan 5 unlink blocked 3        Remove only blocked link to #3
""",
}

COMMAND_HELP["dsl"] = DSL_HELP.strip()

# Aliases so both verb and command names resolve
COMMAND_HELP["+"] = COMMAND_HELP["add"]
COMMAND_HELP["~"] = COMMAND_HELP["mod"]
COMMAND_HELP["ls"] = COMMAND_HELP["list"]
COMMAND_HELP["h"] = COMMAND_HELP.get("help", "")

# }}} # SOURCE END: 135-help+.py

# SOURCE START: 140-handlers.py {{{
# ---------------------------------------------------------------------------
# Command Handlers
# ---------------------------------------------------------------------------

def _get_content(node, normalize_indent=True):
    """Get display content of a node, with indentation normalized to 0."""
    if isinstance(node, Ticket):
        lines = []
        lines.append(f"## {node.ticket_type}: {node.title} {{#{node.node_id}}}")
        lines.append("")
        for key, value in node.attrs.items():
            lines.append(f"    {key}: {value}")
        if node.attrs:
            lines.append("")
        # Normalize body indent independently (header is always at 0)
        if normalize_indent and node.body_lines:
            body_text = textwrap.dedent("\n".join(node.body_lines))
            for bl in body_text.split("\n"):
                lines.append(bl)
        else:
            for bl in node.body_lines:
                lines.append(bl)
        if node.comments:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(_get_content(node.comments, normalize_indent))
        return lines
    elif isinstance(node, Section):
        lines = []
        lines.append(f"## {node.title} {{#{node.node_id}}}")
        lines.append("")
        for key, value in node.attrs.items():
            lines.append(f"    {key}: {value}")
        if node.attrs:
            lines.append("")
        for bl in node.body_lines:
            lines.append(bl)
        return lines
    elif isinstance(node, Comments):
        lines = list(node.raw_lines)
        return _normalize_indent(lines) if lines else lines
    elif isinstance(node, Comment):
        lines = list(node.raw_lines)
        return _normalize_indent(lines) if lines else lines
    elif isinstance(node, Project):
        lines = []
        lines.append(f"# {node.title} {{#project}}")
        return lines
    return []


def _handle_get(project, targets, req, output):
    """Handle 'get' verb — print content of targets.

    Display modes:
    - Flat: all content tickets share one parent and level.
      Non-indented sections separated by one empty line.
    - Nested: tickets span multiple levels (via -p or -r) or have
      different parents.  Structural parents (those with children
      also in the target set) show title only; content tickets show
      full content, indented by tree depth.
    """
    tickets = [t for t in targets if isinstance(t, Ticket)]

    if not tickets:
        for node in targets:
            output.extend(_get_content(node))
        return

    # Structural parents: tickets whose children are also in the target set
    target_ids = set(t.node_id for t in tickets)
    parent_ids = set()
    for t in tickets:
        if any(c.node_id in target_ids for c in t.children):
            parent_ids.add(t.node_id)

    content_tickets = [t for t in tickets if t.node_id not in parent_ids]

    # Multi-level when structural parents exist or content tickets
    # belong to different parents
    multi_level = bool(parent_ids)
    if not multi_level and len(content_tickets) > 1:
        parents = set(id(t.parent) for t in content_tickets)
        multi_level = len(parents) > 1

    if multi_level:
        min_depth = min(len(_collect_ancestors(t)) for t in tickets)

    prev_was_content = False
    for node in targets:
        if not isinstance(node, Ticket):
            if prev_was_content:
                output.append("")
            output.extend(_get_content(node))
            prev_was_content = True
            continue

        if not multi_level:
            # Flat: non-indented, one empty line between tickets
            if prev_was_content:
                output.append("")
            output.extend(_get_content(node))
            prev_was_content = True
        elif node.node_id in parent_ids:
            # Structural parent: bulleted header line only (no body/attrs)
            if prev_was_content:
                output.append("")
            depth = len(_collect_ancestors(node)) - min_depth
            output.append(f"{'  ' * depth}* ## {node.ticket_type}: {node.title} {{#{node.node_id}}}")
            prev_was_content = False
        else:
            # Content ticket: bulleted full content, indented by depth
            if prev_was_content:
                output.append("")
            depth = len(_collect_ancestors(node)) - min_depth
            indent = "  " * depth
            content = _get_content(node)
            for i, line in enumerate(content):
                if i == 0:
                    output.append(f"{indent}* {line}")
                elif line.strip():
                    output.append(f"{indent}  {line}")
                else:
                    output.append("")
            prev_was_content = True


def _collect_tickets(project, targets, req):
    """Collect tickets for list verb based on resolved targets.

    - If targets provided: list those tickets directly (tree-walk order).
    - If no targets and no queries: list all tickets (recursive tree-walk).
    - If queries matched nothing: empty.
    """
    bare = False

    if targets:
        for t in targets:
            if not isinstance(t, Ticket):
                raise SystemExit(f"Error: #{t.node_id} is not a ticket")
        tickets = list(targets)
    elif req.pipeline:
        tickets = []  # pipeline produced no results
    else:
        # Bare list: show all tickets by recursing from top-level
        tickets = list(project.tickets)
        bare = True

    order_mode = "order" in req.verb_args

    if order_mode or bare:
        all_tickets = []
        seen = set()
        def _collect_recursive(tlist):
            for t in sort_by_rank(tlist):
                if id(t) not in seen:
                    seen.add(id(t))
                    all_tickets.append(t)
                    _collect_recursive(t.children)
        _collect_recursive(tickets)
        tickets = all_tickets
    else:
        tickets = _topo_order(project, tickets)

    # Apply filters
    title_filter = req.flags.get("title")
    text_filter = req.flags.get("text")
    attr_filter = req.flags.get("attr_filter")

    if title_filter:
        tickets = [t for t in tickets if title_filter.lower() in t.title.lower()]
    if text_filter:
        def _text_match(t):
            body = "\n".join(t.body_lines)
            return (text_filter.lower() in t.title.lower() or
                    text_filter.lower() in body.lower())
        tickets = [t for t in tickets if _text_match(t)]
    if attr_filter:
        tickets = [t for t in tickets if any(
            attr_filter in str(v) for v in t.attrs.values()
        )]

    # Order mode — topological sort by execution order
    if order_mode:
        # Only active tickets are actionable
        tickets = [t for t in tickets
                   if t.get_attr("status", "open") in ACTIVE_STATUSES
                   or t.get_attr("status", "open") == ""]
        ticket_ids = {str(t.node_id) for t in tickets}

        # Compute DFS post-order positions (natural execution order):
        # complete each subtree (children in rank order) before the parent.
        dfs_pos = {}
        pos = [0]
        def _dfs(t):
            for c in sort_by_rank(t.children):
                if str(c.node_id) in ticket_ids:
                    _dfs(c)
            dfs_pos[str(t.node_id)] = pos[0]
            pos[0] += 1
        roots = [t for t in tickets
                 if not t.parent or not isinstance(t.parent, Ticket)
                 or str(t.parent.node_id) not in ticket_ids]
        for r in sort_by_rank(roots):
            _dfs(r)

        # Build dependency graph (Kahn's algorithm)
        in_degree = {str(t.node_id): 0 for t in tickets}
        adj = {str(t.node_id): [] for t in tickets}

        for t in tickets:
            nid = str(t.node_id)
            # blocked-by: blocker must come before this ticket
            links = _parse_links(t.get_attr("links", ""))
            for bid in links.get("blocked", []):
                bid_str = str(bid)
                if bid_str in ticket_ids:
                    adj[bid_str].append(nid)
                    in_degree[nid] += 1
            # parent depends on all children: child before parent
            if t.parent and isinstance(t.parent, Ticket):
                pid = str(t.parent.node_id)
                if pid in ticket_ids:
                    adj[nid].append(pid)
                    in_degree[pid] += 1

        # Kahn's algorithm using DFS position as priority
        ticket_map = {str(t.node_id): t for t in tickets}
        queue = sorted(
            [nid for nid, deg in in_degree.items() if deg == 0],
            key=lambda nid: dfs_pos.get(nid, float('inf')),
        )
        result = []
        while queue:
            current = queue.pop(0)
            result.append(ticket_map[current])
            for neighbor in adj[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
            queue.sort(key=lambda nid: dfs_pos.get(nid, float('inf')))
        # Append any remaining (cycles) at the end
        if len(result) < len(tickets):
            seen = {str(t.node_id) for t in result}
            for t in tickets:
                if str(t.node_id) not in seen:
                    result.append(t)
        tickets = result

    return tickets


def _all_project_tickets(project):
    """Collect all tickets recursively from the project."""
    result = []
    def _walk(tickets):
        for t in tickets:
            result.append(t)
            _walk(t.children)
    _walk(project.tickets)
    return result


def _topo_order(project, tickets):
    """Sort tickets in tree-walk order (depth-first, rank-sorted)."""
    if not tickets:
        return tickets
    wanted = set(id(t) for t in tickets)
    ordered = []
    def _walk(children):
        for node in sort_by_rank(children):
            if id(node) in wanted:
                ordered.append(node)
            if hasattr(node, 'children'):
                _walk(node.children)
    _walk(project.tickets)
    return ordered


def _expand_targets(project, targets, req):
    """Expand targets with -r (add descendants) and -p (add ancestors).

    - If -r is set, each Ticket target expands to include all descendants.
    - If -p is set, each Ticket target expands to include all ancestors
      up to the root.
    - Non-Ticket targets are passed through unchanged.
    - Result is sorted in tree-walk order.
    """
    recursive = req.flags.get("recursive", False)
    parent_flag = req.flags.get("parent", False)

    if not recursive and not parent_flag:
        return list(targets)

    ticket_ids = set()
    non_tickets = []

    for t in targets:
        if isinstance(t, Ticket):
            ticket_ids.add(t.node_id)
        else:
            non_tickets.append(t)

    if recursive:
        def _collect_descendants(ticket):
            for c in ticket.children:
                ticket_ids.add(c.node_id)
                _collect_descendants(c)
        for t in targets:
            if isinstance(t, Ticket):
                _collect_descendants(t)

    if parent_flag:
        for t in targets:
            if isinstance(t, Ticket):
                p = t.parent
                while p is not None and isinstance(p, Ticket):
                    ticket_ids.add(p.node_id)
                    p = p.parent

    # Re-sort in tree-walk order
    ordered = []
    def _walk(children):
        for t in sort_by_rank(children):
            if t.node_id in ticket_ids:
                ordered.append(t)
            _walk(t.children)
    _walk(project.tickets)
    return non_tickets + ordered


def _handle_list(project, targets, req, output):
    """Handle 'list' verb — title-only listing.

    Targets are resolved nodes from dispatch.
    If targets provided, list those tickets directly.
    If no targets, list top-level tickets.
    Always shows tree-depth indentation.
    """
    tickets = _collect_tickets(project, targets, req)

    # Limit
    limit = req.flags.get("n")
    if limit:
        tickets = tickets[:limit]

    # Format
    fmt = req.flags.get("format")
    for t in tickets:
        if fmt:
            output.append(eval_format(t, fmt))
        else:
            depth = 0
            p = t.parent
            while p is not None:
                depth += 1
                p = p.parent
            indent = "  " * depth
            links = t.get_attr("links", "")
            if links:
                links = f" <{links}>"
            output.append(f"{indent}#{t.node_id} [{t.get_attr('status', 'open')}] {t.title}{links}")


def _handle_project(project, cmd_args, req, output):
    """Handle 'project' command."""
    if not cmd_args:
        # Show project info: title + all non-tickets sections
        content = _get_content(project)
        output.extend(content)
        for sid, section in project.sections.items():
            if sid in ("metadata", "tickets"):
                continue
            output.append("")
            output.extend(_get_content(section))
        return

    section_name = cmd_args[0]
    section = project.sections.get(section_name)
    if section is None:
        # Try lookup in id_map
        section = project.lookup(section_name)
    if section is None:
        if req.verb in ("add", "replace"):
            # Auto-create the section
            title = section_name.capitalize()
            section = Section(title, section_name)
            section.dirty = True
            # Insert before tickets section to maintain order
            new_sections = {}
            inserted = False
            for sid, sec in project.sections.items():
                if sid == "tickets" and not inserted:
                    new_sections[section_name] = section
                    inserted = True
                new_sections[sid] = sec
            if not inserted:
                new_sections[section_name] = section
            project.sections = new_sections
            project.register(section)
        else:
            raise SystemExit(f"Error: section '{section_name}' not found")

    if req.verb == "get":
        content = _get_content(section)
        output.extend(content)
    elif req.verb == "add":
        if not req.verb_args:
            raise SystemExit("Error: add requires text argument")
        text = _read_text_arg(req.verb_args[0])
        section.body_lines.append(text)
        section.dirty = True
    elif req.verb == "replace":
        if not req.flags.get("force"):
            raise SystemExit("Error: replace requires --force")
        if not req.verb_args:
            raise SystemExit("Error: replace requires text argument")
        text = _read_text_arg(req.verb_args[0])
        section.body_lines = text.rstrip('\n').split('\n') if text.strip() else []
        section.dirty = True
    else:
        raise SystemExit(f"Error: verb '{req.verb}' not supported for project sections")


def _handle_help(output, command=None):
    """Handle 'help' command, optionally for a specific command."""
    if command:
        # Normalize aliases
        alias = {"h": "help", "+": "add", "~": "mod"}.get(command, command)
        text = COMMAND_HELP.get(alias)
        if text:
            output.append(text.rstrip())
        else:
            output.append(f"Unknown command: {command}")
    else:
        output.append(HELP_TEXT.rstrip())


def _read_text_arg(arg):
    """Read text from argument: literal string, '-' for stdin, '@path' for file."""
    if arg == "-":
        return sys.stdin.read()
    if arg.startswith("@"):
        with open(arg[1:]) as f:
            return f.read()
    return arg


def _handle_replace(project, targets, req):
    """Handle 'replace' verb — replace content."""
    if not req.flags.get("force"):
        raise SystemExit("Error: replace requires --force flag")
    if not req.verb_args:
        raise SystemExit("Error: replace requires text argument")

    text = _read_text_arg(req.verb_args[0])

    for node in targets:
        if isinstance(node, Ticket):
            content_indent = " " * (node.indent_level + 2)
            node.body_lines = [
                content_indent + line if line else ""
                for line in text.rstrip('\n').split('\n')
            ] if text.strip() else []
            node.set_attr("updated", _now())
        elif isinstance(node, Section):
            node.body_lines = text.rstrip('\n').split('\n') if text.strip() else []
            node.dirty = True
        elif isinstance(node, Comment):
            content_indent = " " * (node.indent_level + 2)
            node.body_lines = [
                content_indent + line if line else ""
                for line in text.rstrip('\n').split('\n')
            ] if text.strip() else []
            node.dirty = True


def _handle_add(project, targets, req):
    """Handle 'add' verb — smart append."""
    use_editor = req.flags.get("edit") or not req.verb_args

    if use_editor:
        text = _open_editor("")
        if text is None:
            return  # cancelled
        text = text.strip()
    else:
        text = _read_text_arg(req.verb_args[0])

    for node in targets:
        if isinstance(node, Ticket):
            # Append to body
            content_indent = " " * (node.indent_level + 2)
            for line in text.split("\n"):
                node.body_lines.append(content_indent + line if line else "")
            node.set_attr("updated", _now())
        elif isinstance(node, Section):
            node.body_lines.append(text)
            node.dirty = True
        elif isinstance(node, Comments):
            # Add new comment
            cid = project.allocate_id()
            _add_comment_to_ticket_from_comments(node, project, cid, text)
        elif isinstance(node, Comment):
            # Add reply
            parent_ticket_id = node.node_id.split(":")[0]
            cid = project.allocate_id()
            comment_id = f"{parent_ticket_id}:comment:{cid}"
            reply = _make_comment(comment_id, text, node.indent_level + 2)
            node.children.append(reply)
            node.dirty = True
            project.register(reply)


def _add_comment_to_ticket_from_comments(comments_node, project, comment_num, text):
    """Add a comment to a Comments node."""
    ticket_id = comments_node.node_id.split(":")[0]
    comment_id = f"{ticket_id}:comment:{comment_num}"
    comment = _make_comment(comment_id, text, comments_node.indent_level + 2)
    comments_node.comments.append(comment)
    comments_node.dirty = True
    project.register(comment)


def _handle_del(project, targets, req):
    """Handle 'del' verb — delete target.

    Targets are already resolved and expanded by dispatch.
    """
    q_filter = req.flags.get("q")
    # Sort by depth (deepest first) to avoid parent-before-child issues
    def _depth(t):
        d = 0
        p = t.parent if isinstance(t, Ticket) else None
        while p:
            d += 1
            p = p.parent
        return d
    targets = sorted(targets, key=_depth, reverse=True)
    target_ids = set(t.node_id for t in targets if isinstance(t, Ticket))
    for node in targets:
        if isinstance(node, Ticket):
            orphaned = [c for c in node.children if c.node_id not in target_ids]
            if orphaned and not q_filter:
                raise SystemExit(
                    f"Error: #{node.node_id} has {len(orphaned)} "
                    f"child ticket(s) not in selection. Use -r to include descendants."
                )
            _delete_ticket(project, node)
        elif isinstance(node, Comment):
            _delete_comment(project, node)
        elif isinstance(node, Section):
            # Remove section
            for sid, sec in list(project.sections.items()):
                if sec is node:
                    del project.sections[sid]
                    break
            if str(node.node_id) in project.id_map:
                del project.id_map[str(node.node_id)]


def _delete_ticket(project, ticket):
    """Remove a ticket from its parent and id_map (recursively)."""
    # Remove from parent's children
    if ticket.parent:
        ticket.parent.children = [c for c in ticket.parent.children
                                   if c is not ticket]
        ticket.parent.dirty = True
    else:
        project.tickets = [t for t in project.tickets if t is not ticket]
        if "tickets" in project.sections:
            project.sections["tickets"].dirty = True

    # Recursively remove from id_map
    _unregister_recursive(project, ticket)


def _unregister_recursive(project, node):
    """Remove node and all descendants from id_map."""
    if str(node.node_id) in project.id_map:
        del project.id_map[str(node.node_id)]

    if isinstance(node, Ticket):
        for child in node.children:
            _unregister_recursive(project, child)
        if node.comments:
            _unregister_recursive(project, node.comments)

    if isinstance(node, Comments):
        for comment in node.comments:
            _unregister_recursive(project, comment)

    if isinstance(node, Comment):
        for child in node.children:
            _unregister_recursive(project, child)


def _delete_comment(project, comment):
    """Remove a comment from its parent."""
    # Find parent comments node or parent comment
    cid = str(comment.node_id)
    if cid in project.id_map:
        del project.id_map[cid]

    # Search through all tickets to find the comment
    for tid, node in list(project.id_map.items()):
        if isinstance(node, Comments):
            if comment in node.comments:
                node.comments.remove(comment)
                node.dirty = True
                return
        if isinstance(node, Comment):
            if comment in node.children:
                node.children.remove(comment)
                node.dirty = True
                return


def _parse_edited_content(new_lines, node):
    """Parse edited content back into structured parts of a node.

    The editor content (produced by _get_content) has the format:
      ## [Type: ]Title {#id}           (or ## Title {#id} for sections)
      <blank>
          attr1: value1
          attr2: value2
      <blank>
      body line 1
      body line 2

    This function separates the header, attrs, and body, then updates
    the node accordingly.
    """
    i = 0
    n = len(new_lines)

    if isinstance(node, Ticket):
        # Skip/parse the header line
        if i < n:
            m = RE_TICKET_HEADER.match(new_lines[i].strip())
            if m:
                node.ticket_type = m.group("type").strip() if m.group("type") else node.ticket_type
                node.title = m.group("title").strip() if m.group("title").strip() else node.title
            i += 1
    elif isinstance(node, Section):
        # Skip the section header line
        if i < n and new_lines[i].strip().startswith("## "):
            i += 1

    # Skip blank lines after header
    while i < n and new_lines[i].strip() == '':
        i += 1

    # Parse attribute lines (4-space indent, key: value)
    new_attrs = {}
    while i < n:
        m = RE_ATTR.match(new_lines[i])
        if m and new_lines[i].startswith("    "):
            new_attrs[m.group(2)] = m.group(3)
            i += 1
        else:
            break

    if new_attrs:
        node.attrs = new_attrs

    # Skip blank lines after attrs
    while i < n and new_lines[i].strip() == '':
        i += 1

    # Rest is body — strip existing indent, then re-indent to match the node
    content_indent = " " * (node.indent_level + 2) if isinstance(node, Ticket) else ""
    raw_body = new_lines[i:]
    dedented = textwrap.dedent("\n".join(raw_body)).split("\n")
    body_lines = []
    for line in dedented:
        if line.strip():
            body_lines.append(content_indent + line)
        else:
            body_lines.append("")

    # Strip trailing blank lines
    while body_lines and body_lines[-1].strip() == '':
        body_lines.pop()

    node.body_lines = body_lines


def _open_editor(initial_content, suffix='.md'):
    """Open $EDITOR with initial_content, return edited text.

    Strips comment lines (starting with '# ') that are used for error messages.
    Returns None if the result is empty (user cancelled).
    Raises SystemExit if editor exits non-zero.
    """
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile(mode='w', suffix=suffix,
                                      delete=False) as f:
        f.write(initial_content)
        tmppath = f.name
    try:
        result = subprocess.run(shlex.split(editor) + [tmppath])
        if result.returncode != 0:
            raise SystemExit(f"Error: editor exited with code {result.returncode}")
        with open(tmppath) as f:
            text = f.read()
    finally:
        os.unlink(tmppath)

    # Strip error comment lines from top of file (from validation loop)
    lines = text.split('\n')
    while lines and lines[0].startswith('# '):
        lines.pop(0)
    text = '\n'.join(lines)

    if not text.strip():
        return None
    return text


def _build_create_template(move="", title="", errors=None,
                            body="", extra_attrs=None, bulk=False):
    """Build the editor template for create command.

    Args:
        move: pre-filled move expression or empty
        title: pre-filled title or empty
        errors: list of error strings to show as comments
        body: pre-filled body text
        extra_attrs: dict of additional pre-filled attributes
        bulk: if True, produce bulk markdown format (* ## Title)
    """
    lines = []
    if errors:
        for err in errors:
            lines.append(f"# Error: {err}")
    if bulk:
        lines.append(f"* ## {title}")
        lines.append("")
        attr_prefix = "      "
        body_prefix = "  "
    else:
        lines.append(f"## {title}")
        lines.append("")
        attr_prefix = "    "
        body_prefix = ""
    lines.append(f"{attr_prefix}move: {move}")
    if extra_attrs:
        for key, val in extra_attrs.items():
            if key not in ("move", "assignee", "links"):
                lines.append(f"{attr_prefix}{key}: {val}")
    lines.append(f"{attr_prefix}assignee: {(extra_attrs or {}).get('assignee', '')}")
    lines.append(f"{attr_prefix}links: {(extra_attrs or {}).get('links', '')}")
    lines.append("")
    if body:
        lines.append(f"{body_prefix}{body}" if body_prefix else body)
    else:
        lines.append("")
    return '\n'.join(lines) + '\n'


def _parse_create_template(text):
    """Parse editor template into ticket fields.

    Returns dict with keys: title, attrs, body, errors.
    Returns None if text is empty.
    """
    if not text or not text.strip():
        return None

    lines = text.split('\n')
    result = {"title": "", "attrs": {}, "body": "", "errors": []}

    # First non-empty line is the title
    line_idx = 0
    while line_idx < len(lines) and not lines[line_idx].strip():
        line_idx += 1
    if line_idx >= len(lines):
        return None

    title_line = lines[line_idx].strip()
    if title_line.startswith("## "):
        title_line = title_line[3:]
    elif title_line == "##":
        title_line = ""
    # Parse optional Ticket: and type prefixes
    title_line = title_line.strip()
    ticket_type = "Task"
    if title_line.lower().startswith("ticket:"):
        title_line = title_line[7:].strip()
    type_m = re.match(r'^(\w+):\s+(.+)$', title_line)
    if type_m:
        ticket_type = type_m.group(1)
        title_line = type_m.group(2)
    result["title"] = title_line.strip()
    result["ticket_type"] = ticket_type
    line_idx += 1

    # Skip blank lines between title and attributes
    while line_idx < len(lines) and not lines[line_idx].strip():
        line_idx += 1

    # Parse 4-space indented attributes
    while line_idx < len(lines):
        line = lines[line_idx]
        if line.startswith("    ") and ":" in line:
            key, _, value = line.strip().partition(":")
            key = key.strip()
            value = value.strip()
            if value:  # drop blank optional attrs
                result["attrs"][key] = value
            line_idx += 1
        elif not line.strip():
            # Blank line ends attribute block
            line_idx += 1
            break
        else:
            break

    # Remaining lines are body
    body_lines = []
    while line_idx < len(lines):
        body_lines.append(lines[line_idx])
        line_idx += 1
    body = '\n'.join(body_lines).strip()
    result["body"] = body

    # Validate
    if not result["title"]:
        result["errors"].append("title is required")

    return result


def _edit_export_content(project, ticket, recursive):
    """Export ticket content for editing (shared by interactive and non-interactive).

    Returns the exported text string (indent-normalized to 0).
    """
    out = []
    if recursive:
        _regenerate_ticket(ticket, out)
    else:
        _regenerate_ticket_only(ticket, out)

    # Normalize indent to 0
    min_indent = float('inf')
    for line in out:
        if line.strip():
            min_indent = min(min_indent, _indent_of(line))
    if min_indent > 0 and min_indent != float('inf'):
        out = [line[min_indent:] if len(line) >= min_indent else line
               for line in out]

    return "\n".join(out)


def _edit_export_to_file(project, node_id, req, plan_dir, plan_filename):
    """Export ticket content to a temp file and print path to stdout, help to stderr."""
    node = project.lookup(node_id)
    if node is None:
        raise SystemExit(f"Error: ticket #{node_id} not found")
    if not isinstance(node, Ticket):
        raise SystemExit("Error: non-interactive edit is only supported for tickets")

    recursive = req.flags.get("recursive", False)
    text = _edit_export_content(project, node, recursive)
    content_hash = _edit_content_hash(text)
    flags = set()
    if recursive:
        flags.add("r")
    filename = _edit_file_encode(plan_filename, node_id, flags, content_hash)
    filepath = os.path.join(plan_dir, filename)

    with open(filepath, "w") as f:
        f.write(text)

    file_flag = req.flags.get("file")
    accept_cmd = "plan edit --accept"
    if file_flag:
        accept_cmd = f"plan -f {file_flag} edit --accept"
    print(filepath)
    print(f"Edit {filename} then run \"{accept_cmd}\" when done.", file=sys.stderr)


def _handle_edit_start(project, cmd_args, req, plan_dir, plan_filename):
    """Handle 'edit --start' — export ticket to temp file for non-interactive editing."""
    if not cmd_args:
        raise SystemExit("Error: edit --start requires a ticket ID")
    node_id = cmd_args[0]

    # Check for existing edit file
    existing = _edit_file_glob(plan_dir, plan_filename, ticket_id=node_id)
    if existing:
        raise SystemExit(
            f"Error: edit already in progress for #{node_id}. "
            f"Use --restart {node_id} or --abort {node_id}.")

    _edit_export_to_file(project, node_id, req, plan_dir, plan_filename)


def _handle_edit_restart(project, cmd_args, req, plan_dir, plan_filename):
    """Handle 'edit --restart' — abort existing edit and start fresh."""
    if not cmd_args:
        raise SystemExit("Error: edit --restart requires a ticket ID")
    node_id = cmd_args[0]

    # Delete existing edit files for this ticket (idempotent)
    existing = _edit_file_glob(plan_dir, plan_filename, ticket_id=node_id)
    for _fname, fpath in existing:
        os.unlink(fpath)

    _edit_export_to_file(project, node_id, req, plan_dir, plan_filename)


def _handle_edit_accept(project, cmd_args, req, plan_dir, plan_filename):
    """Handle 'edit --accept' — apply edited temp file."""
    ticket_id = cmd_args[0] if cmd_args else None

    # Find edit files
    edit_files = _edit_file_glob(plan_dir, plan_filename, ticket_id=ticket_id)
    if not edit_files:
        if ticket_id:
            raise SystemExit(f"Error: no edit in flight for #{ticket_id}")
        raise SystemExit("Error: no edit files found")
    if len(edit_files) > 1 and ticket_id is None:
        names = ", ".join(f for f, _ in edit_files)
        raise SystemExit(
            f"Error: multiple edits in flight ({names}). "
            f"Specify a ticket ID: plan edit --accept ID")

    fname, fpath = edit_files[0]
    decoded = _edit_file_decode(fname, plan_filename)
    if decoded is None:
        raise SystemExit(f"Error: cannot parse edit filename: {fname}")
    tid, edit_flags, original_hash = decoded

    # Look up ticket
    node = project.lookup(tid)
    if node is None:
        raise SystemExit(f"Error: ticket #{tid} no longer exists")
    if not isinstance(node, Ticket):
        raise SystemExit(f"Error: #{tid} is not a ticket")

    recursive = "r" in edit_flags

    # Re-export current content and verify hash
    current_text = _edit_export_content(project, node, recursive)
    current_hash = _edit_content_hash(current_text)

    if current_hash != original_hash:
        raise SystemExit(
            f"Error: content of #{tid} has changed since export. "
            f"Run \"plan edit --restart {tid}\" to get fresh content.")

    # Read edited file
    with open(fpath) as f:
        new_text = f.read()

    if not new_text.strip():
        os.unlink(fpath)
        output = []
        _edit_list_remaining(plan_dir, plan_filename, output)
        for line in output:
            print(line)
        return False

    # Apply changes using the same logic as interactive edit
    if isinstance(node, Ticket):
        _apply_edit_to_ticket(project, node, new_text, recursive)

    # Delete temp file on success
    os.unlink(fpath)

    # List remaining edit files
    output = []
    _edit_list_remaining(plan_dir, plan_filename, output)
    for line in output:
        print(line)

    return True


def _handle_edit_abort(cmd_args, plan_dir, plan_filename):
    """Handle 'edit --abort' — delete temp file without applying."""
    ticket_id = cmd_args[0] if cmd_args else None

    edit_files = _edit_file_glob(plan_dir, plan_filename, ticket_id=ticket_id)
    if not edit_files:
        # Idempotent — no error if nothing to abort
        if ticket_id:
            print(f"No edit in flight for #{ticket_id}.")
        else:
            print("No edit files found.")
        return

    if len(edit_files) > 1 and ticket_id is None:
        names = ", ".join(f for f, _ in edit_files)
        raise SystemExit(
            f"Error: multiple edits in flight ({names}). "
            f"Specify a ticket ID: plan edit --abort ID")

    fname, fpath = edit_files[0]
    os.unlink(fpath)
    print(f"Aborted edit: {fname}")

    output = []
    _edit_list_remaining(plan_dir, plan_filename, output, exclude_path=fpath)
    for line in output:
        print(line)


def _apply_edit_to_ticket(project, ticket, new_text, include_children):
    """Apply edited text to a ticket (shared logic for accept flow).

    Reuses the same parsing logic as _handle_edit_recursive.
    """
    # Check for new tickets (bulk creation within edit)
    headers = _scan_bulk_headers(new_text)
    has_new = any(h[2] for h in headers)
    new_ids = set()
    saved_next_id = project.next_id
    saved_metadata = (project.sections["metadata"].get_attr("next_id")
                      if "metadata" in project.sections else None)
    if has_new:
        placeholder_map, new_ids, id_for_missing, next_counter = (
            _allocate_bulk_ids(project, headers, mode="edit")
        )
        new_text = _substitute_bulk_text(
            new_text, placeholder_map, id_for_missing
        )
        project.next_id = next_counter
        if "metadata" in project.sections:
            project.sections["metadata"].set_attr(
                "next_id", str(project.next_id)
            )

    try:
        # Re-indent the edited text to the ticket's original indent level
        edited_lines = new_text.rstrip('\n').split('\n')
        indent_prefix = " " * ticket.indent_level
        reindented = []
        for line in edited_lines:
            if line.strip():
                reindented.append(indent_prefix + line)
            else:
                reindented.append("")

        # Save original children before unregistering (for non-recursive edit)
        saved_children = ticket.children if not include_children else None

        # Unregister the old ticket from id_map
        if include_children:
            _unregister_recursive(project, ticket)
        else:
            if str(ticket.node_id) in project.id_map:
                del project.id_map[str(ticket.node_id)]
            if ticket.comments:
                _unregister_recursive(project, ticket.comments)

        # Re-parse the edited subtree
        new_tickets = []
        _parse_ticket_region(reindented, project, new_tickets, ticket.parent, 0)

        if not new_tickets:
            return

        # The first parsed ticket replaces the original
        new_root = new_tickets[0]
        new_root.indent_level = ticket.indent_level
        new_root.parent = ticket.parent
        new_root._rank = ticket._rank
        new_root.dirty = True

        # Mark all parsed descendants dirty (body lines are already
        # correctly indented from the re-indent + parse step).
        def _mark_dirty(t):
            t.dirty = True
            for c in t.children:
                _mark_dirty(c)
        for nt in new_tickets:
            _mark_dirty(nt)

        # Restore original children if not editing recursively
        # (done after _mark_dirty so saved children aren't touched)
        if saved_children is not None:
            new_root.children = saved_children
            for child in saved_children:
                child.parent = new_root

        # Fill defaults for new tickets created during edit
        if new_ids:
            now = _now()
            def _fill_new_defaults(t):
                if t.node_id in new_ids:
                    if "status" not in t.attrs:
                        t.attrs["status"] = "open"
                    if "created" not in t.attrs:
                        t.attrs["created"] = now
                    if "updated" not in t.attrs:
                        t.attrs["updated"] = now
                    if t._rank is None:
                        siblings = (t.parent.children
                                    if t.parent and isinstance(t.parent, Ticket)
                                    else project.tickets)
                        t._rank = rank_last(siblings)
                    t.dirty = True
                for c in t.children:
                    _fill_new_defaults(c)
            for nt in new_tickets:
                _fill_new_defaults(nt)

        # Replace in parent's children list or project.tickets
        if ticket.parent:
            children = ticket.parent.children
            idx = next((i for i, c in enumerate(children) if c is ticket), None)
            if idx is not None:
                children[idx:idx+1] = new_tickets
            ticket.parent.dirty = True
        else:
            idx = next((i for i, t in enumerate(project.tickets) if t is ticket), None)
            if idx is not None:
                project.tickets[idx:idx+1] = new_tickets
            if "tickets" in project.sections:
                project.sections["tickets"].dirty = True

        # Resolve ephemeral 'move' attrs on edited tickets
        _resolve_move_attrs(new_tickets, project)

    except Exception:
        if has_new:
            project.next_id = saved_next_id
            if "metadata" in project.sections and saved_metadata is not None:
                project.sections["metadata"].set_attr("next_id", saved_metadata)
        raise


def _handle_edit_command(project, cmd_args, req):
    """Handle 'edit' command — edit a single ticket/node in $EDITOR or non-interactively.

    Usage: edit ID [-r]
           edit --start ID [-r]
           edit --restart ID [-r]
           edit --accept [ID]
           edit --abort [ID]
    """
    plan_dir = getattr(project, '_plan_dir', None)
    if plan_dir is None:
        plan_dir = os.getcwd()
    plan_filename = getattr(project, '_plan_filename', '.PLAN.md')

    # Non-interactive dispatch
    if req.flags.get("start"):
        _handle_edit_start(project, cmd_args, req, plan_dir, plan_filename)
        return False  # no plan modification
    if req.flags.get("restart"):
        _handle_edit_restart(project, cmd_args, req, plan_dir, plan_filename)
        return False  # no plan modification
    if req.flags.get("accept"):
        result = _handle_edit_accept(project, cmd_args, req, plan_dir, plan_filename)
        return True if result else False
    if req.flags.get("abort"):
        _handle_edit_abort(cmd_args, plan_dir, plan_filename)
        return False  # no plan modification

    # Interactive edit (existing behavior)
    if not cmd_args:
        raise SystemExit("Error: edit requires a ticket ID")
    if len(cmd_args) > 1:
        raise SystemExit(f"Error: edit takes one target, got: {' '.join(cmd_args)}")
    node_id = cmd_args[0]
    node = project.lookup(node_id)
    if node is None:
        raise SystemExit(f"Error: ticket #{node_id} not found")
    editor = os.environ.get("EDITOR", "vi")
    recursive = req.flags.get("recursive", False)

    if isinstance(node, Ticket):
        _handle_edit_recursive(project, node, editor,
                               include_children=recursive)
        return

    content = _get_content(node)
    text = "\n".join(content)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md',
                                      delete=False) as f:
        f.write(text)
        tmppath = f.name

    try:
        result = subprocess.run([editor, tmppath])
        if result.returncode != 0:
            raise SystemExit(f"Error: editor exited with code {result.returncode}")

        with open(tmppath) as f:
            new_text = f.read()
    finally:
        os.unlink(tmppath)

    new_lines = new_text.rstrip('\n').split('\n') if new_text.strip() else []
    _parse_edited_content(new_lines, node)
    if isinstance(node, Section):
        node.dirty = True


def _handle_edit_recursive(project, ticket, editor, include_children=True):
    """Edit a ticket and its comments (and optionally children) in $EDITOR."""
    # Serialize the ticket (with or without children)
    out = []
    if include_children:
        _regenerate_ticket(ticket, out)
    else:
        _regenerate_ticket_only(ticket, out)

    # Normalize indent to 0
    min_indent = float('inf')
    for line in out:
        if line.strip():
            min_indent = min(min_indent, _indent_of(line))
    if min_indent > 0 and min_indent != float('inf'):
        out = [line[min_indent:] if len(line) >= min_indent else line
               for line in out]

    text = "\n".join(out)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md',
                                      delete=False) as f:
        f.write(text)
        tmppath = f.name

    try:
        result = subprocess.run([editor, tmppath])
        if result.returncode != 0:
            raise SystemExit(f"Error: editor exited with code {result.returncode}")

        with open(tmppath) as f:
            new_text = f.read()
    finally:
        os.unlink(tmppath)

    if not new_text.strip():
        return

    # Check for new tickets (bulk creation within edit)
    headers = _scan_bulk_headers(new_text)
    has_new = any(h[2] for h in headers)
    new_ids = set()
    saved_next_id = project.next_id
    saved_metadata = (project.sections["metadata"].get_attr("next_id")
                      if "metadata" in project.sections else None)
    if has_new:
        placeholder_map, new_ids, id_for_missing, next_counter = (
            _allocate_bulk_ids(project, headers, mode="edit")
        )
        new_text = _substitute_bulk_text(
            new_text, placeholder_map, id_for_missing
        )
        # Commit next_id (will be rolled back on error below)
        project.next_id = next_counter
        if "metadata" in project.sections:
            project.sections["metadata"].set_attr(
                "next_id", str(project.next_id)
            )

    try:
        # Re-indent the edited text to the ticket's original indent level
        edited_lines = new_text.rstrip('\n').split('\n')
        indent_prefix = " " * ticket.indent_level
        reindented = []
        for line in edited_lines:
            if line.strip():
                reindented.append(indent_prefix + line)
            else:
                reindented.append("")

        # Save original children before unregistering (for non-recursive edit)
        saved_children = ticket.children if not include_children else None

        # Unregister the old ticket from id_map
        if include_children:
            _unregister_recursive(project, ticket)
        else:
            # Only unregister ticket itself and comments, keep children registered
            if str(ticket.node_id) in project.id_map:
                del project.id_map[str(ticket.node_id)]
            if ticket.comments:
                _unregister_recursive(project, ticket.comments)

        # Re-parse the edited subtree
        new_tickets = []
        _parse_ticket_region(reindented, project, new_tickets, ticket.parent, 0)

        if not new_tickets:
            return

        # The first parsed ticket replaces the original
        new_root = new_tickets[0]
        new_root.indent_level = ticket.indent_level
        new_root.parent = ticket.parent
        new_root._rank = ticket._rank
        new_root.dirty = True

        # Mark all parsed descendants dirty (body lines are already
        # correctly indented from the re-indent + parse step).
        def _mark_dirty(t):
            t.dirty = True
            for c in t.children:
                _mark_dirty(c)
        for nt in new_tickets:
            _mark_dirty(nt)

        # Restore original children if not editing recursively
        # (done after _mark_dirty so saved children aren't touched)
        if saved_children is not None:
            new_root.children = saved_children
            for child in saved_children:
                child.parent = new_root

        # Fill defaults for new tickets created during edit
        if new_ids:
            now = _now()
            def _fill_new_defaults(t):
                if t.node_id in new_ids:
                    if "status" not in t.attrs:
                        t.attrs["status"] = "open"
                    if "created" not in t.attrs:
                        t.attrs["created"] = now
                    if "updated" not in t.attrs:
                        t.attrs["updated"] = now
                    if t._rank is None:
                        siblings = (t.parent.children
                                    if t.parent and isinstance(t.parent, Ticket)
                                    else project.tickets)
                        t._rank = rank_last(siblings)
                    t.dirty = True
                for c in t.children:
                    _fill_new_defaults(c)
            for nt in new_tickets:
                _fill_new_defaults(nt)

        # Replace in parent's children list or project.tickets
        if ticket.parent:
            children = ticket.parent.children
            idx = next((i for i, c in enumerate(children) if c is ticket), None)
            if idx is not None:
                # Replace the original ticket with new root, plus any extra
                # tickets parsed (if user split one ticket into multiple)
                children[idx:idx+1] = new_tickets
            ticket.parent.dirty = True
        else:
            idx = next((i for i, t in enumerate(project.tickets) if t is ticket), None)
            if idx is not None:
                project.tickets[idx:idx+1] = new_tickets
            if "tickets" in project.sections:
                project.sections["tickets"].dirty = True

        # Resolve ephemeral 'move' attrs on edited tickets
        _resolve_move_attrs(new_tickets, project)

    except Exception:
        # Rollback next_id if we allocated new IDs
        if has_new:
            project.next_id = saved_next_id
            if "metadata" in project.sections and saved_metadata is not None:
                project.sections["metadata"].set_attr("next_id", saved_metadata)
        raise


def _handle_mod(project, targets, req):
    """Handle 'mod' / '~' verb — apply DSL expression."""
    if not req.verb_args:
        raise SystemExit("Error: mod requires expression argument")
    expr = req.verb_args[0]
    for node in targets:
        if isinstance(node, Ticket):
            apply_mod(node, project, expr)


def _set_ticket_defaults(ticket, siblings):
    """Set default status, created, and updated on a new ticket."""
    if not ticket.get_attr("status"):
        ticket.set_attr("status", "open")
    if not ticket.get_attr("created"):
        ticket.set_attr("created", _now())
    if not ticket.get_attr("updated"):
        ticket.set_attr("updated", _now())
    if ticket._rank is None:
        ticket._rank = rank_last(siblings)


def _resolve_parent(project, parent_id):
    """Resolve parent_id to (parent_ticket_or_None, siblings_list)."""
    if parent_id is not None and parent_id != "0":
        parent = project.lookup(parent_id)
        if parent is None:
            raise SystemExit(f"Error: parent #{parent_id} not found")
        if not isinstance(parent, Ticket):
            raise SystemExit(f"Error: parent #{parent_id} is not a ticket")
        return parent, parent.children
    return None, project.tickets


def _handle_create_bulk(project, text, parent_id, req, output):
    """Handle bulk creation from markdown text."""
    parent, _ = _resolve_parent(project, parent_id)

    tickets, new_ids = _parse_bulk_markdown(
        text, project, parent=parent, mode="create"
    )

    # Add to parent or project.tickets
    target_list = parent.children if parent else project.tickets
    for t in tickets:
        if t not in target_list:
            target_list.append(t)
        if parent:
            t.dirty = True

    # Mark parent/section dirty
    if parent:
        parent.dirty = True
    elif "tickets" in project.sections:
        project.sections["tickets"].dirty = True

    # Output created IDs
    if "quiet" not in req.flags:
        for nid in sorted(new_ids):
            output.append(str(nid))


def _create_from_template(project, parsed_tmpl, parent_id, req, output):
    """Create a ticket from a parsed template dict. Shared by editor and stdin paths."""
    parent, siblings = _resolve_parent(project, parent_id)

    # Create ticket from parsed template
    new_id = project.allocate_id()
    ticket = Ticket(new_id, "", parsed_tmpl.get("ticket_type", "Task"))
    ticket.dirty = True
    ticket.title = parsed_tmpl["title"]

    if parent:
        ticket.parent = parent
        ticket.indent_level = parent.indent_level + 2
    else:
        ticket.indent_level = 0

    # Set attributes
    for k, v in parsed_tmpl["attrs"].items():
        if k == "move":
            _resolve_move_expr(v, ticket, project)
            continue
        ticket.set_attr(k, v)

    # Re-derive siblings (move expression may have changed parent)
    if ticket.parent and isinstance(ticket.parent, Ticket):
        siblings = ticket.parent.children
    else:
        siblings = project.tickets

    # Set body
    if parsed_tmpl["body"]:
        content_indent = " " * (ticket.indent_level + 2)
        for line in parsed_tmpl["body"].split('\n'):
            ticket.body_lines.append(content_indent + line if line else "")

    # Set defaults
    _set_ticket_defaults(ticket, siblings)

    if ticket not in siblings:
        siblings.append(ticket)
    project.register(ticket)

    if "quiet" not in req.flags:
        output.append(str(new_id))


def _handle_create(project, cmd_args, req, output):
    """Handle 'create' command — create new ticket."""
    # Parse: optional #parent, then expression
    parent_id = None
    expr_str = None
    for a in cmd_args:
        parsed = _parse_id_arg(a)
        if parsed is not None:
            parent_id = parsed
        else:
            expr_str = a

    use_stdin = expr_str == "-"
    use_editor = req.flags.get("edit") or (not expr_str and not use_stdin)

    if use_editor:
        # --- Editor mode ---
        # Determine parent and siblings for rank pre-fill
        parent, siblings = _resolve_parent(project, parent_id)

        default_move = f"last {parent_id}" if parent_id else ""

        # Pre-fill from expression if provided
        prefill_title = ""
        prefill_body = ""
        prefill_attrs = {}
        if expr_str:
            tmp = Ticket(0, "", "Task")
            # Use a detached project to prevent side effects (e.g. move
            # reparenting the temporary ticket into the real tree).
            apply_mod(tmp, None, f"set({expr_str})")
            prefill_title = tmp.title
            prefill_body = '\n'.join(l.strip() for l in tmp.body_lines if l.strip())
            for k, v in tmp.attrs.items():
                prefill_attrs[k] = v

        use_bulk = bool(req.flags.get("recursive"))
        template = _build_create_template(
            move=prefill_attrs.pop("move", default_move),
            title=prefill_title,
            body=prefill_body,
            extra_attrs=prefill_attrs,
            bulk=use_bulk,
        )

        # Editor loop with validation
        while True:
            edited = _open_editor(template)
            if edited is None:
                # User cancelled
                return
            # Detect bulk markdown: if input contains ticket headers, route to bulk mode
            if edited and any(RE_TICKET_BULK.match(l) for l in edited.split("\n")):
                return _handle_create_bulk(project, edited, parent_id, req, output)
            parsed_tmpl = _parse_create_template(edited)
            if parsed_tmpl is None:
                return
            if parsed_tmpl["errors"]:
                # Show errors, ask to re-edit or cancel
                for err in parsed_tmpl["errors"]:
                    print(f"Error: {err}", file=sys.stderr)
                try:
                    choice = input("[e]dit / [c]ancel? ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    choice = "c"
                if choice != "e":
                    return
                # Rebuild template with errors and user's content preserved
                template = _build_create_template(
                    move=parsed_tmpl["attrs"].get("move", default_move),
                    title=parsed_tmpl["title"],
                    body=parsed_tmpl["body"],
                    extra_attrs={k: v for k, v in parsed_tmpl["attrs"].items()
                                 if k != "move"},
                    errors=parsed_tmpl["errors"],
                    bulk=use_bulk,
                )
                continue
            break

        return _create_from_template(project, parsed_tmpl, parent_id, req, output)

    # --- Stdin mode: treat as template/bulk, same as editor output ---
    if use_stdin:
        edited = sys.stdin.read()
        if not edited or not edited.strip():
            return
        # Detect bulk markdown
        if any(RE_TICKET_BULK.match(l) for l in edited.split("\n")):
            return _handle_create_bulk(project, edited, parent_id, req, output)
        # Parse as template
        parsed_tmpl = _parse_create_template(edited)
        if parsed_tmpl is None:
            return
        if parsed_tmpl["errors"]:
            for err in parsed_tmpl["errors"]:
                print(f"Error: {err}", file=sys.stderr)
            raise SystemExit("Error: invalid template input from stdin")
        return _create_from_template(project, parsed_tmpl, parent_id, req, output)

    # --- Expression mode ---
    # Detect bulk markdown: if input contains ticket headers, route to bulk mode
    if expr_str and any(RE_TICKET_BULK.match(l) for l in expr_str.split("\n")):
        return _handle_create_bulk(project, expr_str, parent_id, req, output)

    if not expr_str:
        raise SystemExit("Error: create requires an expression with title")

    # Find parent (0 means root — create at top level)
    parent, siblings = _resolve_parent(project, parent_id)

    # Allocate ID
    new_id = project.allocate_id()

    # Create ticket
    ticket = Ticket(new_id, "", "Task")
    ticket.dirty = True

    if parent:
        ticket.parent = parent
        ticket.indent_level = parent.indent_level + 2
    else:
        ticket.indent_level = 0

    # Apply the expression via set()
    wrapped_expr = f"set({expr_str})"
    apply_mod(ticket, project, wrapped_expr)

    if not ticket.title:
        raise SystemExit("Error: create requires title attribute")

    # Re-derive siblings (move expression may have changed parent)
    if ticket.parent and isinstance(ticket.parent, Ticket):
        siblings = ticket.parent.children
    else:
        siblings = project.tickets

    # Set defaults
    _set_ticket_defaults(ticket, siblings)

    # Add to parent (move expression may have already added it)
    if ticket not in siblings:
        siblings.append(ticket)
    project.register(ticket)

    # Print created ticket number unless --quiet
    if "quiet" not in req.flags:
        output.append(str(new_id))



def _handle_status_verb(project, targets, req):
    """Handle 'status' verb — set ticket status."""
    if not req.verb_args:
        raise SystemExit("Error: status requires a status argument")
    new_status = req.verb_args[0]
    for node in targets:
        if isinstance(node, Ticket):
            node.set_attr("status", new_status)
            node.set_attr("updated", _now())


def _handle_close_verb(project, targets, req):
    """Handle 'close' verb — close ticket with optional resolution."""
    resolution = req.verb_args[0] if req.verb_args else "done"
    for node in targets:
        if isinstance(node, Ticket):
            node.set_attr("status", resolution)
            node.set_attr("updated", _now())


def _handle_reopen_verb(project, targets, req):
    """Handle 'reopen' verb — set status to open."""
    for node in targets:
        if isinstance(node, Ticket):
            node.set_attr("status", "open")
            node.set_attr("updated", _now())


def _handle_link(project, targets, req):
    """Handle 'link' verb — add a link between tickets."""
    args = req.verb_args
    if not args:
        raise SystemExit("Error: link requires a target ticket ID")
    if len(args) == 1:
        link_type, target_str = "related", args[0]
    else:
        link_type, target_str = args[0], args[1]
    # Validate target is numeric
    try:
        target_id = int(target_str)
    except ValueError:
        raise SystemExit(f"Error: link target must be a ticket ID (got '{target_str}')")
    # Validate link type
    if link_type not in LINK_MIRRORS:
        valid = ", ".join(sorted(LINK_MIRRORS.keys()))
        raise SystemExit(f"Error: unknown link type '{link_type}' (valid: {valid})")
    # Validate target exists
    target_node = project.lookup(target_id)
    if target_node is None:
        raise SystemExit(f"Error: ticket #{target_id} not found")

    for node in targets:
        if not isinstance(node, Ticket):
            continue
        if int(node.node_id) == target_id:
            raise SystemExit(f"Error: cannot link ticket #{node.node_id} to itself")
        add_link(project, node, link_type, target_id)
        node.set_attr("updated", _now())


def _handle_unlink(project, targets, req):
    """Handle 'unlink' verb — remove links between tickets."""
    args = req.verb_args
    if not args:
        raise SystemExit("Error: unlink requires a target ticket ID")
    if len(args) == 1:
        link_type, target_str = "all", args[0]
    else:
        link_type, target_str = args[0], args[1]
    # Validate target is numeric
    try:
        target_id = int(target_str)
    except ValueError:
        raise SystemExit(f"Error: unlink target must be a ticket ID (got '{target_str}')")
    # Validate link type
    if link_type != "all" and link_type not in LINK_MIRRORS:
        valid = ", ".join(sorted(LINK_MIRRORS.keys()))
        raise SystemExit(f"Error: unknown link type '{link_type}' (valid: all, {valid})")

    for node in targets:
        if not isinstance(node, Ticket):
            continue
        if link_type == "all":
            # Remove all links pointing at target_id
            links = _parse_links(node.get_attr("links", ""))
            for ltype in list(links.keys()):
                if target_id in links[ltype]:
                    remove_link(project, node, ltype, target_id)
        else:
            remove_link(project, node, link_type, target_id)
        node.set_attr("updated", _now())


def _handle_comment(project, targets, req, output):
    """Handle 'comment' selector+verb."""
    for node in targets:
        if not isinstance(node, Ticket):
            continue

        if req.verb == "get":
            if node.comments:
                content = _get_content(node.comments)
                output.extend(content)
        elif req.verb == "add":
            use_editor = req.flags.get("edit") or not req.verb_args
            if use_editor:
                text = _open_editor("")
                if text is None:
                    continue  # cancelled
                text = text.strip()
            else:
                text = _read_text_arg(req.verb_args[0])
            cid = project.allocate_id()
            _add_comment_to_ticket(node, project, cid, text)
        elif req.verb == "del":
            # Delete all comments
            if node.comments:
                _unregister_recursive(project, node.comments)
                node.comments = None
                node.dirty = True


def _handle_attr(project, targets, selector_args, req, output):
    """Handle 'attr' selector+verb."""
    if not selector_args:
        raise SystemExit("Error: attr requires attribute name")
    attr_name = selector_args[0]

    for node in targets:
        if req.verb == "get":
            val = node.get_attr(attr_name, "")
            output.append(val)
        elif req.verb == "replace":
            if not req.flags.get("force"):
                raise SystemExit("Error: attr replace requires --force")
            if not req.verb_args:
                raise SystemExit("Error: attr replace requires value")
            val = _read_text_arg(req.verb_args[0])
            old_val = node.get_attr(attr_name, "")
            node.set_attr(attr_name, val)
            if isinstance(node, Ticket):
                node.set_attr("updated", _now())
            # Handle link interlinking
            if attr_name == "links" and isinstance(node, Ticket):
                _reconcile_links(project, node, old_val, val)
        elif req.verb == "add":
            if not req.verb_args:
                raise SystemExit("Error: attr add requires value")
            val = _read_text_arg(req.verb_args[0])
            if attr_name == "links":
                existing = node.get_attr("links", "")
                new_val = (existing + " " + val).strip() if existing else val
                node.set_attr("links", new_val)
                if isinstance(node, Ticket):
                    node.set_attr("updated", _now())
                    # Add interlinks for new links
                    parsed = _parse_links(val)
                    for ltype, ids in parsed.items():
                        for tid in ids:
                            _add_interlink(project, node, ltype, tid)
            else:
                raise SystemExit(
                    f"Error: cannot add to scalar attribute '{attr_name}'. "
                    "Use replace --force."
                )
        elif req.verb == "del":
            if attr_name == "links" and isinstance(node, Ticket):
                # Remove all links and their mirrors
                old_links = _parse_links(node.get_attr("links", ""))
                for ltype, ids in old_links.items():
                    for tid in ids:
                        mirror = LINK_MIRRORS.get(ltype)
                        if mirror:
                            target = project.lookup(tid)
                            if target and isinstance(target, Ticket):
                                _raw_remove_link(target, mirror, node.node_id)
            node.del_attr(attr_name)
            if isinstance(node, Ticket):
                node.set_attr("updated", _now())


def _reconcile_links(project, ticket, old_val, new_val):
    """Remove old mirror links and add new mirror links."""
    old_links = _parse_links(old_val)
    new_links = _parse_links(new_val)

    # Remove mirrors for old links
    for ltype, ids in old_links.items():
        mirror = LINK_MIRRORS.get(ltype)
        if mirror:
            for tid in ids:
                target = project.lookup(tid)
                if target and isinstance(target, Ticket):
                    _raw_remove_link(target, mirror, ticket.node_id)

    # Add mirrors for new links
    for ltype, ids in new_links.items():
        mirror = LINK_MIRRORS.get(ltype)
        if mirror:
            for tid in ids:
                target = project.lookup(tid)
                if target and isinstance(target, Ticket):
                    _raw_add_link(target, mirror, ticket.node_id)


def _handle_move_verb(project, targets, req):
    """Handle 'move' verb — reparent and/or reorder tickets.

    Synopsis (verb args):
        move first           First among current siblings
        move last            Last among current siblings
        move first DEST      First child of DEST
        move last  DEST      Last child of DEST
        move before DEST     Before sibling DEST
        move after  DEST     After sibling DEST

    Multiple targets are moved in selection order, each placed
    sequentially at the requested position.
    """
    _DIRECTIONS = {"first", "last", "before", "after"}

    args = list(req.verb_args)
    if not args:
        raise SystemExit(
            "Error: move requires a direction (first, last, before, after)")

    # --- Parse DIRECTION (mandatory) -----------------------------------
    if args[0] not in _DIRECTIONS:
        raise SystemExit(
            f"Error: move requires a direction (first, last, before, after),"
            f" got: {args[0]}")
    direction = args.pop(0)

    # --- Parse optional DEST -------------------------------------------
    dest = None
    if args:
        dest_id = _parse_id_arg(args[0])
        if dest_id is None:
            raise SystemExit(f"Error: invalid destination: {args[0]}")
        if dest_id != "0":
            dest = project.lookup(dest_id)
            if dest is None:
                raise SystemExit(f"Error: ticket {dest_id} not found")
            if not isinstance(dest, Ticket):
                raise SystemExit(f"Error: #{dest_id} is not a ticket")

    # --- Validate ------------------------------------------------------
    if direction in ("before", "after") and dest is None:
        raise SystemExit(f"Error: move {direction} requires a ticket ID")

    # --- Process each target in order ----------------------------------
    # After the first target is placed, subsequent targets chain via
    # rank_after to preserve selection order.
    prev = None  # previous placed ticket (for chaining)
    for source in targets:
        if not isinstance(source, Ticket):
            continue

        # Detach source from current location
        if source.parent:
            source.parent.children = [c for c in source.parent.children
                                      if c is not source]
            source.parent.dirty = True
        else:
            project.tickets = [t for t in project.tickets if t is not source]

        if direction in ("first", "last"):
            # Reparent as child of dest (or current parent for first/last)
            if dest is not None:
                new_parent = dest
            else:
                # first/last without dest: stay with current parent
                new_parent = source.parent if isinstance(source.parent, Ticket) else None

            if new_parent is not None:
                source.parent = new_parent
                source.indent_level = new_parent.indent_level + 2
                new_parent.children.append(source)
                siblings = new_parent.children
                new_parent.dirty = True
            else:
                source.parent = None
                source.indent_level = 0
                project.tickets.append(source)
                siblings = project.tickets

            if prev is not None:
                # Chain: place after previously placed ticket
                r = rank_after(prev, siblings)
            elif direction == "first":
                r = rank_first(siblings)
            else:  # "last"
                r = rank_last(siblings)
            source._rank = r
        else:
            # before / after — attach as sibling of anchor
            anchor = prev if prev is not None else dest
            new_parent = anchor.parent if isinstance(anchor.parent, Ticket) else None
            if new_parent:
                new_siblings = new_parent.children
            else:
                new_siblings = project.tickets

            source.parent = new_parent
            source.indent_level = anchor.indent_level
            new_siblings.append(source)

            if prev is not None:
                # Chain: always after previously placed ticket
                r = rank_after(prev, new_siblings)
            elif direction == "before":
                r = rank_before(anchor, new_siblings)
            else:
                r = rank_after(anchor, new_siblings)
            source._rank = r

            if new_parent:
                new_parent.dirty = True

        _update_descendant_indent(source)
        prev = source
        source.set_attr("updated", _now())
        source.dirty = True


def _handle_check(project, output):
    """Handle 'check' command — validate document."""
    errors = []

    # Check unique IDs
    seen_ids = {}
    def _check_ids(node, path=""):
        nid = str(node.node_id)
        if nid in seen_ids:
            errors.append(f"Duplicate id: #{nid} at {path}")
        seen_ids[nid] = path

        if isinstance(node, Ticket):
            for child in node.children:
                _check_ids(child, f"{path}/#{child.node_id}")
            if node.comments:
                _check_ids(node.comments, f"{path}/comments")
                for comment in node.comments.comments:
                    _check_comment_ids(comment, path)

    def _check_comment_ids(comment, path):
        nid = str(comment.node_id)
        if nid in seen_ids:
            errors.append(f"Duplicate id: #{nid} at {path}")
        seen_ids[nid] = path
        for child in comment.children:
            _check_comment_ids(child, path)

    for t in project.tickets:
        _check_ids(t, f"#{t.node_id}")

    # Check next_id consistency
    max_ticket_id = 0
    for key, node in project.id_map.items():
        if isinstance(node, Ticket) and isinstance(node.node_id, int):
            max_ticket_id = max(max_ticket_id, node.node_id)
    if project.next_id <= max_ticket_id:
        errors.append(
            f"next_id ({project.next_id}) <= max ticket id ({max_ticket_id})"
        )

    # Check link targets exist
    for key, node in project.id_map.items():
        if isinstance(node, Ticket):
            links = _parse_links(node.get_attr("links", ""))
            for ltype, ids in links.items():
                for tid in ids:
                    if project.lookup(tid) is None:
                        errors.append(
                            f"Broken link: #{node.node_id} has {ltype}:#{tid} "
                            f"but #{tid} does not exist"
                        )

    # Check parent/child integrity
    for key, node in project.id_map.items():
        if isinstance(node, Ticket):
            for child in node.children:
                if child.parent is not node:
                    errors.append(
                        f"Parent/child mismatch: #{child.node_id} parent is not #{node.node_id}"
                    )

    # Check body indentation
    def _check_body_indent(ticket, path):
        min_indent = ticket.indent_level + 2
        for line in ticket.body_lines:
            if line.strip() and _indent_of(line) < min_indent:
                errors.append(
                    f"Body indentation: #{ticket.node_id} has body line "
                    f"with {_indent_of(line)} spaces, expected >= {min_indent}"
                )
                break
        for child in ticket.children:
            _check_body_indent(child, f"{path}/#{child.node_id}")

    for t in project.tickets:
        _check_body_indent(t, f"#{t.node_id}")

    # Check for in-flight edit files
    plan_dir = getattr(project, '_plan_dir', None)
    plan_filename = getattr(project, '_plan_filename', '.PLAN.md')
    if plan_dir:
        edit_files = _edit_file_glob(plan_dir, plan_filename)
        for fname, fpath in edit_files:
            mtime = os.path.getmtime(fpath)
            age = time.time() - mtime
            if age < 60:
                age_str = f"{int(age)}s ago"
            elif age < 3600:
                age_str = f"{int(age / 60)}m ago"
            else:
                age_str = f"{int(age / 3600)}h ago"
            errors.append(f"In-flight edit: {fname} (modified {age_str})")

    if errors:
        for e in errors:
            output.append(f"ERROR: {e}")
    else:
        output.append("OK: no errors found")


def _handle_fix(project, output):
    """Handle 'fix' command — auto-repair document."""
    fixed = []

    # Fix next_id
    max_id = 0
    for key, node in project.id_map.items():
        if isinstance(node, Ticket) and isinstance(node.node_id, int):
            max_id = max(max_id, node.node_id)
    if project.next_id <= max_id:
        project.next_id = max_id + 1
        if "metadata" in project.sections:
            project.sections["metadata"].set_attr("next_id", str(project.next_id))
        fixed.append(f"Fixed next_id to {project.next_id}")

    # Remove broken links
    for key, node in project.id_map.items():
        if isinstance(node, Ticket):
            links = _parse_links(node.get_attr("links", ""))
            changed = False
            for ltype in list(links.keys()):
                for tid in list(links[ltype]):
                    if project.lookup(tid) is None:
                        links[ltype].remove(tid)
                        changed = True
                        fixed.append(
                            f"Removed broken link {ltype}:#{tid} from #{node.node_id}"
                        )
                if not links[ltype]:
                    del links[ltype]
            if changed:
                result = _serialize_links(links)
                if result:
                    node.set_attr("links", result)
                else:
                    node.del_attr("links")

    if fixed:
        for f in fixed:
            output.append(f"FIXED: {f}")
    else:
        output.append("OK: nothing to fix")

# }}} # SOURCE END: 140-handlers.py

# SOURCE START: 145-merge-handlers.py {{{
# ---------------------------------------------------------------------------
# Merge command handlers (`plan merge` porcelain)
# ---------------------------------------------------------------------------
#
# Orchestrates the pure engine (115), the report renderer/parser (116) and the
# git plumbing (117) into the user-facing `plan merge` command and its modes
# (--resolve / --abort / --check). NO argument parsing here — that lives in
# 120-cli.py; main() (180) special-cases the merge command BEFORE its own
# discover_file/flock block (merge resolves its own sources/output and may run
# outside git), then calls _handle_merge(). This module takes its OWN exclusive
# lock on the output file (_OutputLock) for each read->merge->write.
#
# Concatenated after 140-handlers, so it may freely use everything in 010-140 —
# in particular merge_trees(), parse(), serialize(), render_reject(),
# parse_reject(), RejectError, VERSION_STR and the git helpers.
#
# CONTRACT: _handle_merge returns an exit code (0/1/2). Normal/status messages
# go to stdout via the `output` list; errors go straight to stderr (so callers
# can keep stdout clean). The function NEVER raises for expected error paths.

# Persisted across `plan merge <branch>` -> `plan merge --resolve`: the merge
# options needed to reproduce the original merge. Lives inside the per-output
# state dir so clearing that dir removes it for free.
_MERGE_OPTIONS_FILE = "options"

# User-facing side vocabulary <-> engine-internal side values. The CLI exposes
# the two merge sides as `to` (the side merged into — canonical) and `from` (the
# side merged from). The engine, snapshots and persisted options keep the
# historical `mine`/`theirs` names; we map at this boundary only.
_SIDE_TO_ENGINE = {"to": "mine", "from": "theirs"}


def _engine_side(value, default="theirs"):
    """Map a user-facing `to`/`from` side to its engine value (`mine`/`theirs`).

    Passes engine values through unchanged (so callers may hand us either), and
    falls back to `default` for None/unknown.
    """
    if value is None:
        return default
    return _SIDE_TO_ENGINE.get(value, value)


def _err(msg):
    """Print an error to stderr (one line)."""
    print(msg, file=sys.stderr)


def _err_prefixed(prefix, exc):
    """Print `<prefix>: <exc>` to stderr, avoiding a doubled prefix.

    Some lower-layer RuntimeErrors already start with 'merge:'; don't repeat it.
    """
    text = str(exc)
    if text.startswith(prefix):
        _err(text)
    else:
        _err("%s %s" % (prefix, text))


class _OutputLock:
    """Exclusive advisory lock on the merge OUTPUT file for read->merge->write.

    Mirrors main.py's flock pattern (LOCK_EX | LOCK_NB with a brief retry) so a
    `plan merge` writing `.PLAN.md` is mutually exclusive with concurrent
    `plan create`/`status`/... (which hold LOCK_EX on the same file). When the
    output equals the working-tree plan file this restores that exclusion; for a
    custom `-o`/outside-git output, locking that file is still the right unit.

    A no-op when flock is unavailable (`_has_flock` False) or `path` is None.
    Used as a context manager; raises SystemExit on lock-acquisition timeout.
    """

    def __init__(self, path):
        self.path = path
        self._fd = None

    def __enter__(self):
        if not _has_flock or not self.path:
            return self
        # Open for append so we never truncate; create if missing so a brand-new
        # output (e.g. -o newfile) can still be locked before its first write.
        self._fd = open(self.path, "a")
        for _attempt in range(20):
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                time.sleep(0.1)
        else:
            self._fd.close()
            self._fd = None
            raise SystemExit(
                "Error: could not acquire lock on %s "
                "(timed out after 2 seconds)" % self.path)
        return self

    def __exit__(self, *exc):
        if self._fd is not None:
            self._fd.close()
            self._fd = None
        return False


def _parse_text_or_none(text):
    """parse() a plan side, mapping a None/empty side to None (empty project)."""
    if text is None or text == "":
        return None
    return parse(text)


def _write_merge_options_at(state_dir, renumber, two_way=False, output=None):
    """Persist the merge options in an explicit `state_dir`.

    Written as simple `key=value` lines so --resolve can reproduce the exact
    same merge: the `renumber` choice, whether the original run used two-way mode
    (no diff3 base), and the output path (so --resolve writes the right file even
    when -o pointed elsewhere) all matter.
    """
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, _MERGE_OPTIONS_FILE), "w",
              encoding="utf-8") as f:
        f.write("renumber=%s\n" % renumber)
        f.write("two_way=%s\n" % ("true" if two_way else "false"))
        if output is not None:
            f.write("output=%s\n" % output)


def _read_merge_options_at(state_dir):
    """Read back persisted merge options from an explicit `state_dir`.

    Returns {'renumber': 'mine'|'theirs', 'two_way': bool, 'output': str|None}.
    Defaults `renumber` to 'theirs', `two_way` to False, `output` to None when
    the file is absent or malformed (so older .reject files keep working).
    """
    opts = {"renumber": "theirs", "two_way": False, "output": None}
    path = os.path.join(state_dir, _MERGE_OPTIONS_FILE)
    if not os.path.exists(path):
        return opts
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                stripped = line.strip()
                if not stripped or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                if k == "renumber" and v in ("mine", "theirs"):
                    opts["renumber"] = v
                elif k == "two_way":
                    opts["two_way"] = (v.strip().lower() == "true")
                elif k == "output":
                    opts["output"] = v
    except OSError:
        pass
    return opts


def _conflict_action_message(n, rp):
    """The actionable multi-line error shown when conflicts remain."""
    return (
        "merge: %d conflict(s) need manual resolution.\n"
        "  Wrote %s — edit the marked blocks, then:\n"
        "      plan merge --resolve     # apply your edits\n"
        "      plan merge --abort       # discard this merge"
        % (n, rp)
    )


def _list_conflicts(conflicts):
    """Render a short list of remaining conflicts for an error message."""
    parts = []
    for c in conflicts:
        if c.field and c.field != NODE_FIELD:
            parts.append("#%s (%s)" % (c.node_id, c.field))
        else:
            parts.append("#%s" % c.node_id)
    return ", ".join(parts)


def _maybe_launch_editor(reject_file, flags):
    """On a TTY with $EDITOR set and not --no-edit, open the .reject file.

    Best-effort convenience only; does NOT auto-apply (the user still runs
    --resolve). Any failure is swallowed so it never blocks the merge result.
    """
    if flags.get("no_edit"):
        return
    if not sys.stdout.isatty():
        return
    editor = os.environ.get("EDITOR")
    if not editor:
        return
    try:
        subprocess.run(shlex.split(editor) + [reject_file], check=False)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Source / output / state resolution shared by all modes
# ---------------------------------------------------------------------------

def _discover_file_or_none(flags):
    """discover_file(flags) but returns None instead of raising when absent."""
    try:
        return discover_file(flags)
    except SystemExit:
        return None


def _repo_root_for(path):
    """git_repo_root() rooted near `path` (or cwd if path is None); None if outside."""
    try:
        start = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
        return git_repo_root(start)
    except (RuntimeError, OSError):
        return None


def _relpath_for_commit_reads(plan_path, repo_root):
    """The in-repo path used to read `<ref>:<relpath>` commit sources, or None.

    This is the canonical PLAN file's path (the one tracked in git), NOT the
    output path — a commit source is the plan file as it existed on that ref. We
    return its path relative to the repo root. None means "undeterminable" (no
    repo, or no canonical plan path): the caller must NOT guess a relpath for a
    commit read (guessing reads the wrong/absent path and silently produces an
    empty side), so resolve_source errors on a commit source when relpath is None.
    """
    if repo_root is None or not plan_path:
        return None
    try:
        return _rel_to_repo(repo_root, plan_path)
    except (ValueError, OSError):
        return None


def _resolve_output_path(flags, to_spec, discovered):
    """Decide where the merged result is written.

    Precedence: -o/--output > the --to file (when `to` is a file spec) > the
    discovered plan file. Returns None when nothing can be determined.
    """
    if flags.get("merge_output"):
        return flags["merge_output"]
    # If --to names a file (file: prefix or an existing path), write back to it.
    if to_spec is not None:
        if to_spec.startswith("file:"):
            return to_spec[len("file:"):]
        if not to_spec.startswith("git:") and os.path.exists(to_spec):
            return to_spec
    return discovered


def _default_to_text(discovered):
    """Read the default `to` (working-tree plan file) content, or None if absent."""
    if discovered and os.path.exists(discovered):
        with open(discovered, encoding="utf-8") as f:
            return f.read()
    return None


def _precompute_output_path(flags):
    """Resolve the output path up front (before reading sources) for locking.

    Same precedence as _resolve_output_path, but resolved BEFORE gathering so we
    can take the output lock around the whole read->merge->write. Returns None
    when no output can be determined yet (the handler then errors after gather).
    """
    return _resolve_output_path(flags, flags.get("merge_to"),
                                _discover_file_or_none(flags))


# ---------------------------------------------------------------------------
# Entry point + mode dispatch
# ---------------------------------------------------------------------------

def _handle_merge(req, flags, output):
    """Handle the `merge` command. Returns an exit code (0/1/2).

    `flags` is the merged flag dict from all requests (the merge sources, output
    and options). Modes (mutually exclusive, in order): --abort, --resolve,
    --check, then the default merge. Stage 9: sources may be files or commits,
    the output may be elsewhere via -o, and the whole thing can run outside git.
    """
    if flags.get("abort"):
        return _merge_resolve_or_abort(flags, output, mode="abort")
    if flags.get("merge_resolve"):
        return _merge_resolve_or_abort(flags, output, mode="resolve")
    if flags.get("merge_both_from"):
        _err("merge: give a branch OR --from, not both")
        return 2
    if flags.get("merge_check"):
        return _merge_check(flags, output)
    return _merge_default(flags, output)


# ---------------------------------------------------------------------------
# Locate the in-progress merge state for --resolve / --abort
# ---------------------------------------------------------------------------

def _locate_state(flags):
    """Resolve (output_path, repo_root, state_dir, reject_file) for resolve/abort.

    The output defaults to the discovered plan file; -o overrides. Works outside
    git (state lives beside the output in `.plan-merge`).
    """
    discovered = _discover_file_or_none(flags)
    output_path = flags.get("merge_output") or discovered
    repo_root = _repo_root_for(output_path)
    if output_path is None:
        return None, repo_root, None, None
    state_dir = merge_state_dir(output_path, repo_root)
    reject_file = reject_path(output_path)
    return output_path, repo_root, state_dir, reject_file


def _merge_resolve_or_abort(flags, output, mode):
    """Shared front for --resolve / --abort (they locate state identically)."""
    output_path, repo_root, state_dir, reject_file = _locate_state(flags)
    label = "merge --abort" if mode == "abort" else "merge --resolve"

    if output_path is None:
        _err("%s: no output file (use -o to point at the in-progress merge)"
             % label)
        return 2
    if not merge_in_progress_at(reject_file):
        _err("%s: no merge in progress for %s" % (label, output_path))
        return 2

    # Lock the output across the write/restore (mutual exclusion with concurrent
    # `plan` writers on the same file).
    with _OutputLock(output_path):
        if mode == "abort":
            return _merge_abort(output_path, repo_root, state_dir,
                                reject_file, output)
        return _merge_resolve(output_path, repo_root, state_dir,
                              reject_file, output)


# ---------------------------------------------------------------------------
# --abort
# ---------------------------------------------------------------------------

def _merge_abort(output_path, repo_root, state_dir, reject_file, output):
    """Discard an in-progress merge: restore `to` (mine), clear state/index."""
    _base, mine_text, _theirs = read_snapshots_at(state_dir)
    # Restore the output file from the `to` (mine) snapshot.
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(mine_text if mine_text is not None else "")

    # Clear any unmerged index stages we may have set (in a repo only).
    if repo_root is not None:
        try:
            mark_resolved(repo_root, output_path)
        except RuntimeError:
            pass

    clear_merge_state_at(state_dir, reject_file)
    output.append("merge --abort: discarded in-progress merge; restored %s"
                  % output_path)
    return 0


# ---------------------------------------------------------------------------
# --resolve
# ---------------------------------------------------------------------------

def _merge_resolve(output_path, repo_root, state_dir, reject_file, output):
    """Apply an edited .reject: re-run the merge with the user's resolutions."""
    try:
        with open(reject_file, encoding="utf-8") as f:
            reject_text = f.read()
    except OSError as exc:
        _err("merge --resolve: cannot read %s: %s" % (reject_file, exc))
        return 2

    try:
        resolutions = parse_reject(reject_text)
    except RejectError as exc:
        _err("merge --resolve: %s" % exc.message)
        return 2

    base_text, mine_text, theirs_text = read_snapshots_at(state_dir)
    base = _parse_text_or_none(base_text)
    mine = _parse_text_or_none(mine_text)
    theirs = _parse_text_or_none(theirs_text)

    opts = _read_merge_options_at(state_dir)
    # The persisted output path is authoritative (the original merge may have
    # used -o to write elsewhere); fall back to the located output_path.
    target = opts.get("output") or output_path
    result = merge_trees(base, mine, theirs, renumber=opts["renumber"],
                         resolutions=resolutions, two_way=opts["two_way"])

    if result.conflicts:
        _err("merge --resolve: %d conflict(s) still unresolved: %s"
             % (len(result.conflicts), _list_conflicts(result.conflicts)))
        return 2

    with open(target, "w", encoding="utf-8") as f:
        f.write(serialize(result.project))

    # Finalize git state (in a repo only): mark the path resolved (git add).
    if repo_root is not None:
        try:
            mark_resolved(repo_root, target)
        except RuntimeError:
            pass

    clear_merge_state_at(state_dir, reject_file)
    output.append("merge --resolve: applied resolutions; wrote %s" % target)
    return 0


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------

def _merge_check(flags, output):
    """Dry run: compute the merge, report the conflict count, write NOTHING."""
    gathered = _gather_merge_inputs(flags, "merge --check")
    if isinstance(gathered, int):
        return gathered
    base, mine, theirs = gathered["base"], gathered["mine"], gathered["theirs"]

    renumber = _engine_side(flags.get("renumber"))
    prefer = _engine_side(flags.get("prefer"), default=None)
    result = merge_trees(base, mine, theirs, renumber=renumber, prefer=prefer,
                         two_way=gathered["two_way"])

    n = len(result.conflicts)
    if n:
        output.append("merge --check: %d conflict(s)" % n)
        return 1
    output.append("merge --check: clean")
    return 0


# ---------------------------------------------------------------------------
# Gather the three merge inputs from explicit sources (shared by check/default)
# ---------------------------------------------------------------------------

def _gather_merge_inputs(flags, errprefix):
    """Resolve --to/--from/--base into texts + labels, deciding three/two-way.

    Returns a dict on success:
      base/mine/theirs        parsed Project|None (engine inputs)
      base_text/to_text/from_text   raw side texts (for snapshots)
      to_label/from_label/base_label, to_branch/from_branch  (.reject labels)
      two_way                 True when no base could be established
      output_path, repo_root, state_dir, reject_file
    On error returns an int exit code (2) after printing to stderr.
    """
    from_spec = flags.get("merge_from")
    if not from_spec:
        _err("%s: a merge source is required "
             "(a branch, or --from <src>)" % errprefix)
        return 2

    discovered = _discover_file_or_none(flags)
    to_spec = flags.get("merge_to")
    base_spec = flags.get("merge_base")

    output_path = _resolve_output_path(flags, to_spec, discovered)
    repo_root = _repo_root_for(output_path or discovered)
    # Commit sources read the CANONICAL plan file at a ref, so the relpath is the
    # discovered plan file's in-repo path (NOT the output, which may be -o
    # elsewhere). None means undeterminable -> resolve_source errors on a commit
    # source rather than silently reading the wrong (absent) path.
    relpath = _relpath_for_commit_reads(discovered, repo_root)

    # --- resolve `from` (theirs): an explicit source MUST resolve to content. ---
    try:
        from_text, from_label = resolve_source(from_spec, repo_root, relpath)
    except SourceError as exc:
        _err("%s: --from %s" % (errprefix, exc))
        return 2
    if from_text is None:
        _err("%s: --from source %r has no content (file/ref-path absent); an "
             "explicit source must exist" % (errprefix, from_spec))
        return 2

    # --- resolve `to` (mine): explicit source, else the working-tree plan ---
    if to_spec is not None:
        try:
            to_text, to_label = resolve_source(to_spec, repo_root, relpath)
        except SourceError as exc:
            _err("%s: --to %s" % (errprefix, exc))
            return 2
        if to_text is None:
            _err("%s: --to source %r has no content (file/ref-path absent); an "
                 "explicit source must exist" % (errprefix, to_spec))
            return 2
        to_commit = source_commit(to_spec, repo_root)
    else:
        # The DEFAULT `to` is the working-tree plan file; it may legitimately be
        # absent (the plan is being added on the `from` side), so None is OK.
        to_text = _default_to_text(discovered)
        to_label = _default_to_label(discovered, repo_root)
        # The default working-tree `to` uses HEAD for base auto-detection.
        to_commit = "HEAD" if repo_root is not None else None

    # --- resolve / auto-detect base ---
    base_text = None
    base_label = "(none — two-way)"
    if base_spec is not None:
        try:
            base_text, base_label = resolve_source(base_spec, repo_root, relpath)
        except SourceError as exc:
            _err("%s: --base %s" % (errprefix, exc))
            return 2
        if base_text is None:
            _err("%s: --base source %r has no content (file/ref-path absent); an "
                 "explicit source must exist" % (errprefix, base_spec))
            return 2
    else:
        from_commit = source_commit(from_spec, repo_root)
        if repo_root is not None and to_commit and from_commit:
            mb = git_merge_base(repo_root, to_commit, from_commit)
            if mb:
                base_text = git_show(repo_root, mb, relpath)
                # render_reject appends "(merge-base)"; keep the label the bare sha.
                try:
                    base_label = git_short_sha(repo_root, mb)
                except RuntimeError:
                    base_label = mb

    two_way = (base_text is None)

    try:
        base = _parse_text_or_none(base_text)
        mine = _parse_text_or_none(to_text)
        theirs = _parse_text_or_none(from_text)
    except Exception as exc:
        _err("%s: could not parse a source: %s" % (errprefix, exc))
        return 2

    if output_path is None:
        output_path = discovered

    state_dir = merge_state_dir(output_path, repo_root) if output_path else None
    reject_file = reject_path(output_path) if output_path else None

    return {
        "base": base, "mine": mine, "theirs": theirs,
        "base_text": base_text, "to_text": to_text, "from_text": from_text,
        "base_label": base_label, "to_label": to_label, "from_label": from_label,
        "to_branch": _branch_token(to_label), "from_branch": _branch_token(from_label),
        "two_way": two_way,
        "output_path": output_path, "repo_root": repo_root,
        "state_dir": state_dir, "reject_file": reject_file,
    }


def _default_to_label(discovered, repo_root):
    """Label for the default working-tree `to` side."""
    if repo_root is not None:
        branch = git_current_branch(repo_root) or "HEAD"
        try:
            return "%s @ %s (working tree)" % (branch, git_short_sha(repo_root, "HEAD"))
        except RuntimeError:
            return "%s (working tree)" % branch
    return "%s (working tree)" % (discovered or ".PLAN.md")


def _branch_token(label):
    """Short branch/marker token derived from a label (first whitespace word)."""
    if not label:
        return "to"
    return label.split()[0]


# ---------------------------------------------------------------------------
# default: plan merge <from> [--to ...] [--base ...] [-o ...]
# ---------------------------------------------------------------------------

def _merge_default(flags, output):
    """Perform a structural merge of the `from` source into `to`, writing OUT."""
    if not flags.get("merge_from"):
        _err("merge: a merge source is required "
             "(a branch, or --from <src>; use --resolve / --abort otherwise)")
        return 2

    # Hold an exclusive lock on the output for the whole read->merge->write so a
    # concurrent `plan create`/`status` (LOCK_EX on the same .PLAN.md) can't race
    # us. The output is precomputed before gathering; gather reads the default
    # `to` under the lock.
    with _OutputLock(_precompute_output_path(flags)):
        return _merge_default_locked(flags, output)


def _merge_default_locked(flags, output):
    """The locked body of _merge_default (gather -> merge -> write)."""
    gathered = _gather_merge_inputs(flags, "merge")
    if isinstance(gathered, int):
        return gathered

    output_path = gathered["output_path"]
    if output_path is None:
        _err("merge: no output file. Provide -o OUT (or --to FILE), or run "
             "inside a repo with a .PLAN.md.")
        return 2

    repo_root = gathered["repo_root"]
    state_dir = gathered["state_dir"]
    reject_file = gathered["reject_file"]

    # Guard: refuse a new merge while one is in progress for this output.
    if merge_in_progress_at(reject_file):
        _err("merge: merge already in progress for %s; run 'plan merge "
             "--resolve' or 'plan merge --abort' first" % output_path)
        return 2

    renumber = _engine_side(flags.get("renumber"))
    prefer = _engine_side(flags.get("prefer"), default=None)
    result = merge_trees(gathered["base"], gathered["mine"], gathered["theirs"],
                         renumber=renumber, prefer=prefer,
                         two_way=gathered["two_way"])

    # Always write the merged tree (conflicts default to `to` -> always valid).
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(serialize(result.project))

    in_repo = repo_root is not None

    if not result.conflicts:
        # Clean (or --prefer resolved everything).
        if in_repo and (in_merge_or_rebase(repo_root) or _want_stage(flags)):
            try:
                mark_resolved(repo_root, output_path)
            except RuntimeError:
                pass
        output.append("merge: clean — wrote %s" % output_path)
        return 0

    # --- Conflicts remain: write snapshots + options + .reject. ---
    base_text = gathered["base_text"]
    to_text = gathered["to_text"]
    from_text = gathered["from_text"]
    write_snapshots_at(state_dir, base_text, to_text, from_text)
    _write_merge_options_at(state_dir, renumber, two_way=gathered["two_way"],
                            output=output_path)

    annotate_conflict_lines(result.conflicts, to_text, from_text)
    reject_text = render_reject(
        result.conflicts,
        plan_path=output_path,
        base_label=gathered["base_label"],
        to_label=gathered["to_label"],
        from_label=gathered["from_label"],
        to_branch=gathered["to_branch"],
        from_branch=gathered["from_branch"],
        snapshot_dir=state_dir,
        plan_version=VERSION_STR,
    )
    with open(reject_file, "w", encoding="utf-8") as f:
        f.write(reject_text)

    # Git state: inside a merge/rebase, or explicit --stage, mark the index
    # unmerged. Standalone default and outside-git: do NOT touch the index.
    if in_repo and (in_merge_or_rebase(repo_root) or _want_stage(flags)):
        try:
            mark_unmerged(repo_root, output_path, base_text, to_text, from_text)
        except RuntimeError:
            pass

    # Convenience: open $EDITOR on the .reject on a TTY (does not auto-apply).
    _maybe_launch_editor(reject_file, flags)

    _err(_conflict_action_message(len(result.conflicts), reject_file))
    return 1


def _want_stage(flags):
    """True if --stage was given and --no-stage was not (explicit opt-in)."""
    if flags.get("no_stage"):
        return False
    return bool(flags.get("stage"))


# ---------------------------------------------------------------------------
# Git merge driver entry: `plan merge-driver %O %A %B %P`
# ---------------------------------------------------------------------------

def _read_file_text(path):
    """Read a file as text, mapping a missing file to '' (engine: empty => None)."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _handle_merge_driver(base_file, ours_file, theirs_file, pathname):
    """git merge driver: `plan merge-driver %O %A %B %P`. Returns an exit code.

    git invokes this during merge/rebase/cherry-pick/stash-pop for `.PLAN.md`.
    Positional args are temp files: %O=base, %A=ours/MINE (also the OUTPUT file —
    git takes its post-run contents), %B=theirs; %P is the in-repo pathname.

    Index ownership: the driver does NOT touch the git index. git records the
    path's merge state from our exit code (0 = resolved, non-zero = unmerged).
    On conflicts we write the auto-merged tree (mine defaults) into %A, drop a
    `.reject` + snapshots next to the real plan file, and exit 1 so git marks the
    path unmerged; the user then runs `plan merge --resolve` and `git add`.

    Fail-safe: any unexpected error still leaves %A as a usable plan file (the
    auto-merged or the original mine content) and exits non-zero, so git falls
    back to recording the path conflicted rather than truncating the file.
    """
    # Capture ours (%A = MINE) BEFORE we overwrite %A with the merged content.
    mine_text = _read_file_text(ours_file)
    base_text = _read_file_text(base_file)
    theirs_text = _read_file_text(theirs_file)

    # Fail-safe corner: the plan file is new on theirs and absent/empty in ours
    # (%A empty). git would otherwise call the driver with an empty %A; the
    # correct merged result is simply theirs' full content, not a skeleton
    # rebuilt from an empty mine (which would drop theirs' title/sections). Take
    # theirs verbatim and report it clean.
    if (mine_text is None or mine_text.strip() == "") and \
            theirs_text is not None and theirs_text.strip() != "":
        with open(ours_file, "w", encoding="utf-8") as f:
            f.write(theirs_text)
        return 0

    try:
        base = _parse_text_or_none(base_text)
        mine = _parse_text_or_none(mine_text)
        theirs = _parse_text_or_none(theirs_text)

        # Driver uses defaults: renumber theirs, no --prefer.
        result = merge_trees(base, mine, theirs, renumber="theirs")
    except Exception as exc:  # pragma: no cover - defensive
        # Engine failed unexpectedly: leave %A as the original mine content so
        # git has a usable (un-truncated) file, and let git mark it conflicted.
        _err("merge-driver: structural merge failed: %s" % exc)
        with open(ours_file, "w", encoding="utf-8") as f:
            f.write(mine_text)
        return 1

    # Write the merged tree (conflicts default to mine) back into %A — this is
    # the content git takes for the working tree.
    with open(ours_file, "w", encoding="utf-8") as f:
        f.write(serialize(result.project))

    if not result.conflicts:
        return 0

    # --- Conflicts: write snapshots + .reject next to the real plan file. ---
    # In driver context we only have temp files, so resolve %P to the worktree
    # plan path (cwd is the worktree during a git merge).
    try:
        repo_root = git_repo_root()
    except (RuntimeError, OSError):
        repo_root = os.getcwd()
    if os.path.isabs(pathname):
        real_plan_path = pathname
    else:
        real_plan_path = os.path.join(repo_root, pathname)

    # State lives in the per-output namespaced dir (consistent with the
    # porcelain merge), so `plan merge --resolve` finds it for this plan file.
    state_dir = merge_state_dir(real_plan_path, repo_root)
    try:
        write_snapshots_at(state_dir, base_text, mine_text, theirs_text)
        # Persist options so `plan merge --resolve` reproduces this exact merge.
        _write_merge_options_at(state_dir, "theirs", output=real_plan_path)

        annotate_conflict_lines(result.conflicts, mine_text, theirs_text)
        reject_text = render_reject(
            result.conflicts,
            plan_path=real_plan_path,
            base_label="(merge-base)",
            to_label="to (current branch)",
            from_label="from (incoming)",
            to_branch="to",
            from_branch="from",
            snapshot_dir=state_dir,
            plan_version=VERSION_STR,
        )
        rp = reject_path(real_plan_path)
        with open(rp, "w", encoding="utf-8") as f:
            f.write(reject_text)
        _err(_conflict_action_message(len(result.conflicts), rp))
    except Exception as exc:  # pragma: no cover - defensive
        # %A already holds the valid auto-merged tree; just report and let git
        # record the path unmerged on our non-zero exit.
        _err("merge-driver: could not write conflict files: %s" % exc)

    # Do NOT mark_unmerged: git records the path unmerged from our exit code.
    return 1


# ---------------------------------------------------------------------------
# resolve: the two-way structural cousin (recover from raw conflict markers)
# ---------------------------------------------------------------------------
#
# `plan resolve` is the degraded cousin of `plan merge` for a plan file that
# already contains raw git conflict markers (someone merged WITHOUT the driver).
# It reconstructs the `mine` (ours-side) and `theirs` documents — and a `base`
# document if diff3-style `|||||||` sections are present — by walking the marked
# file, then runs the SAME engine: a proper three-way merge when a base is
# available, otherwise the lossy two-way mode (a shared ID is the same node, any
# divergence conflicts). It writes the auto-merged tree (conflicts default to
# mine, markers gone) and, when conflicts remain, reuses the merge .reject flow
# so `plan merge --resolve` can finish per-field.

_RE_CONFLICT_START = re.compile(r'^<{7}(\s|$)')
_RE_CONFLICT_BASE = re.compile(r'^\|{7}(\s|$)')
_RE_CONFLICT_SEP = re.compile(r'^={7}(\s|$)')
_RE_CONFLICT_END = re.compile(r'^>{7}(\s|$)')


def _has_conflict_markers(text):
    """True if `text` contains any git conflict-start marker line."""
    for line in text.split("\n"):
        if _RE_CONFLICT_START.match(line):
            return True
    return False


def _reconstruct_sides(text):
    """Walk a marker-laden document into (mine_text, theirs_text, base_text).

    Non-conflict regions are copied into all three reconstructions. Inside each
    conflict hunk:
      - ours-side lines (between '<<<<<<<' and the base/sep marker) -> mine
      - base-side lines (diff3, between '|||||||' and '=======')    -> base
      - theirs-side lines (between '=======' and '>>>>>>>')         -> theirs

    base_text is returned as None when NO diff3 base section appeared anywhere
    (a plain 2-way conflict file); in that case the caller runs two-way mode.
    Tolerates an unterminated final hunk (best-effort).
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    mine, theirs, base = [], [], []
    saw_base_section = False

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _RE_CONFLICT_START.match(line):
            # Enter a conflict hunk. Collect the three regions.
            ours_lines, base_lines, theirs_lines = [], [], []
            section = "ours"
            i += 1
            while i < n:
                cur = lines[i]
                if _RE_CONFLICT_BASE.match(cur):
                    section = "base"
                    saw_base_section = True
                    i += 1
                    continue
                if _RE_CONFLICT_SEP.match(cur):
                    section = "theirs"
                    i += 1
                    continue
                if _RE_CONFLICT_END.match(cur):
                    i += 1
                    break
                if section == "ours":
                    ours_lines.append(cur)
                elif section == "base":
                    base_lines.append(cur)
                else:
                    theirs_lines.append(cur)
                i += 1
            mine.extend(ours_lines)
            theirs.extend(theirs_lines)
            # Diff3 base content belongs to the reconstructed base; for a plain
            # 2-way hunk (no base section) the base simply has neither side.
            base.extend(base_lines)
            continue

        # Ordinary (non-conflict) line: shared by all reconstructions.
        mine.append(line)
        theirs.append(line)
        base.append(line)
        i += 1

    mine_text = "\n".join(mine)
    theirs_text = "\n".join(theirs)
    base_text = "\n".join(base) if saw_base_section else None
    return mine_text, theirs_text, base_text


def _handle_resolve(plan_path, raw_text, output):
    """Recover a plan file containing raw git conflict markers. Returns an exit code.

    Self-contained: reads nothing else, does its own file writes, returns
    0/1/2. main() calls sys.exit() on the result.

      0 — no markers (nothing to do) OR markers reconciled cleanly.
      1 — markers reconciled but field conflicts remain (file cleaned to
          mine-defaults + .reject written; finish with `plan merge --resolve`).
      2 — a .reject merge is already in progress, or a hard error (parse,
          no git repo when conflicts need snapshots).
    """
    if raw_text is None:
        raw_text = ""

    # No conflict markers -> nothing to resolve (keep historical behavior).
    if not _has_conflict_markers(raw_text):
        output.append("OK: no conflicts found")
        return 0

    # Refuse if a structured merge is already mid-flight (its .reject is the
    # source of truth; mixing the two would corrupt state).
    if merge_in_progress(plan_path):
        _err("resolve: a merge is already in progress; finish it with "
             "'plan merge --resolve' or 'plan merge --abort' first")
        return 2

    # Reconstruct the sides from the markers.
    mine_text, theirs_text, base_text = _reconstruct_sides(raw_text)

    try:
        mine = _parse_text_or_none(mine_text)
        theirs = _parse_text_or_none(theirs_text)
        base = _parse_text_or_none(base_text)
    except Exception as exc:
        _err("resolve: could not parse reconstructed sides: %s" % exc)
        return 2

    # With a diff3 base -> proper three-way; otherwise lossy two-way.
    two_way = base is None
    try:
        if two_way:
            result = merge_trees(None, mine, theirs, two_way=True)
        else:
            result = merge_trees(base, mine, theirs)
    except Exception as exc:
        _err("resolve: structural merge failed: %s" % exc)
        return 2

    # Primary goal: write the auto-merged tree (markers gone -> valid file).
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(serialize(result.project))

    mode_note = ("two-way recovery (no merge-base; add/delete cannot be "
                 "distinguished — best-effort, lossy)" if two_way
                 else "three-way recovery (using the diff3 base)")

    if not result.conflicts:
        output.append("resolve: %s — reconciled cleanly; wrote %s "
                      "(conflict markers removed)." % (mode_note, plan_path))
        return 0

    # Conflicts remain: reuse the structured .reject flow so the user can finish
    # per-field with `plan merge --resolve`. This needs a git repo for snapshots.
    try:
        repo_root = git_repo_root(os.path.dirname(os.path.abspath(plan_path)))
    except RuntimeError:
        # No repo: we still cleaned the file to mine-defaults; we just can't
        # offer the per-field resolution workflow.
        output.append(
            "resolve: %s — wrote %s with %d field(s) defaulted to your side "
            "(no git repo, so per-field resolution is unavailable; review the "
            "merged result)."
            % (mode_note, plan_path, len(result.conflicts)))
        return 1

    # Use the per-output namespaced state dir (consistent with porcelain merge),
    # so `plan merge --resolve` finds the snapshots/options for this plan file.
    state_dir = merge_state_dir(plan_path, repo_root)
    write_snapshots_at(state_dir, base_text or "", mine_text, theirs_text)
    _write_merge_options_at(state_dir, "theirs", two_way=two_way, output=plan_path)

    annotate_conflict_lines(result.conflicts, mine_text, theirs_text)
    reject_text = render_reject(
        result.conflicts,
        plan_path=plan_path,
        base_label="(reconstructed)" if not two_way else "(none — two-way)",
        to_label="to (ours, from conflict markers)",
        from_label="from (theirs, from conflict markers)",
        to_branch="to",
        from_branch="from",
        snapshot_dir=state_dir,
        plan_version=VERSION_STR,
    )
    rp = reject_path(plan_path)
    with open(rp, "w", encoding="utf-8") as f:
        f.write(reject_text)

    _err(
        "resolve: %s.\n"
        "  %d field(s) could not be auto-resolved (defaulted to your side).\n"
        "  Wrote %s — run 'plan merge --resolve' to choose per-field, or\n"
        "  'plan merge --abort' to keep the current file."
        % (mode_note, len(result.conflicts), rp))
    return 1
# }}} # SOURCE END: 145-merge-handlers.py

# SOURCE START: 150-dispatch.py {{{
# ---------------------------------------------------------------------------
# Command Dispatch
# ---------------------------------------------------------------------------

def _classify_query(expr, project):
    """Classify a query expression as 'selector' or 'filter'.

    Evaluates against the first ticket in the project to determine
    return type.  int/list/set → selector, bool/other → filter.
    """
    all_tickets = _all_project_tickets(project)
    if not all_tickets:
        return "filter"
    sample = eval_filter(all_tickets[0], expr)
    if not isinstance(sample, bool) and isinstance(sample, (int, list, set)):
        return "selector"
    return "filter"


def _execute_pipeline(project, req):
    """Execute the selection pipeline and return resolved targets.

    Pipeline steps are executed left-to-right:
    - Selectors (bare IDs, -r, list/set/int queries) add to the set
    - Filters (bool queries) narrow the set

    Initial set: empty if first step is a selector, all tickets if first
    step is a filter.  No steps → empty (verb handler decides default).

    The -p flag is not a pipeline step — it is applied after the pipeline
    by _expand_targets or _handle_list.
    """
    steps = req.pipeline
    if not steps:
        return []

    all_tickets = None
    def _get_all():
        nonlocal all_tickets
        if all_tickets is None:
            all_tickets = _all_project_tickets(project)
        return all_tickets

    # Classify first step to determine initial set
    first = steps[0]
    if first[0] in ("id", "r"):
        targets = []
    elif first[0] == "q":
        if _classify_query(first[1], project) == "selector":
            targets = []
        else:
            targets = list(_get_all())
    else:
        targets = []

    # Helper: collect descendants
    def _add_descendants(current, seen):
        new = []
        def _walk(ticket):
            for c in ticket.children:
                if c.node_id not in seen:
                    seen.add(c.node_id)
                    new.append(c)
                    _walk(c)
        for t in current:
            if isinstance(t, Ticket):
                _walk(t)
        return new

    # Helper: collect ancestors
    def _add_ancestors(current, seen):
        new = []
        for t in current:
            if isinstance(t, Ticket):
                p = t.parent
                while p is not None and isinstance(p, Ticket):
                    if p.node_id not in seen:
                        seen.add(p.node_id)
                        new.append(p)
                    p = p.parent
        return new

    # Execute pipeline steps
    for step in steps:
        kind = step[0]

        if kind == "id":
            node = project.lookup(step[1])
            if node is None:
                raise SystemExit(f"Error: ticket #{step[1]} not found")
            if node.node_id not in {t.node_id for t in targets}:
                targets.append(node)

        elif kind == "r":
            seen = set(t.node_id for t in targets)
            targets.extend(_add_descendants(list(targets), seen))

        elif kind == "q":
            expr = step[1]
            if _classify_query(expr, project) == "selector":
                q_ids = set()
                for ticket in _get_all():
                    result = eval_filter(ticket, expr)
                    if isinstance(result, int) and not isinstance(result, bool):
                        q_ids.add(result)
                    elif isinstance(result, (list, set)):
                        q_ids.update(int(x) for x in result)
                seen = set(t.node_id for t in targets)
                for sid in q_ids:
                    node = project.lookup(str(sid))
                    if node and isinstance(node, Ticket) and node.node_id not in seen:
                        targets.append(node)
                        seen.add(node.node_id)
            else:
                targets = [t for t in targets if eval_filter(t, expr)]

    # Re-sort tickets in tree-walk order
    ticket_targets = [t for t in targets if isinstance(t, Ticket)]
    non_tickets = [t for t in targets if not isinstance(t, Ticket)]
    if ticket_targets:
        ticket_targets = _topo_order(project, ticket_targets)
    return non_tickets + ticket_targets


def dispatch(project, req, output):
    """Dispatch a single parsed request.

    Two branches:
    1. Command dispatch — commands parse their own args.
    2. Selector + Verb dispatch — pipeline resolves targets, then verb runs.
    """
    global _project
    _project = project
    modified = False

    # Branch 1: Command dispatch
    if req.command is not None:
        cmd_name, cmd_args = req.command
        if cmd_name in ("help", "h"):
            topic = cmd_args[0] if cmd_args else None
            _handle_help(output, command=topic)
            return modified
        if cmd_name == "create":
            _handle_create(project, cmd_args, req, output)
            return True
        if cmd_name == "edit":
            result = _handle_edit_command(project, cmd_args, req)
            # Non-interactive: start returns False (no plan modification),
            # accept returns True/None, abort handled in main().
            # Interactive edit always modifies.
            return result if result is not None else True
        if cmd_name == "check":
            _handle_check(project, output)
            return False
        if cmd_name == "fix":
            _handle_fix(project, output)
            return True
        if cmd_name == "resolve":
            return "resolve"
        if cmd_name == "merge":
            return "merge"
        return modified

    # Branch 2: Selector + Verb dispatch
    targets = None

    # Special case: 'id' selector — lookup any node by string ID
    if req.selector_type == "id" and not req.selector_args:
        raise SystemExit("Error: 'id' selector requires a node identifier")
    if req.selector_type == "id" and req.selector_args:
        node_id = req.selector_args[0]
        node = project.lookup(node_id)
        if node is None:
            raise SystemExit(f"Error: node '{node_id}' not found")
        if isinstance(node, Ticket):
            # Inject into pipeline as first step
            req.pipeline.insert(0, ("id", str(node.node_id)))
        else:
            # Non-ticket node: bypass pipeline
            targets = [node]
        req.selector_type = None

    # Phase 2: Execute pipeline (if not already resolved above)
    if targets is None:
        targets = _execute_pipeline(project, req)

    # Phase 2b: -p flag adds ancestors (applied after pipeline, position-independent)
    if req.flags.get("parent") and targets:
        seen = set(t.node_id for t in targets if isinstance(t, Ticket))
        for t in list(targets):
            if isinstance(t, Ticket):
                p = t.parent
                while p is not None and isinstance(p, Ticket):
                    if p.node_id not in seen:
                        seen.add(p.node_id)
                        targets.append(p)
                    p = p.parent
        targets = _topo_order(project, [t for t in targets if isinstance(t, Ticket)])

    # Phase 3: Apply sub-resource selector narrowing
    if req.selector_type == "comment":
        if not targets:
            raise SystemExit("Error: comment selector requires a ticket ID")
        _handle_comment(project, targets, req, output)
        return req.verb in ("add", "del")
    if req.selector_type == "attr":
        if not targets:
            raise SystemExit("Error: attr selector requires a ticket ID")
        _handle_attr(project, targets, req.selector_args, req, output)
        return req.verb in ("replace", "add", "del", "mod")
    if req.selector_type == "project":
        _handle_project(project, req.selector_args, req, output)
        return req.verb in ("add", "replace", "del")

    # Phase 4: Dispatch verb on resolved targets
    # 'next' is sugar for 'list order -n 1' (user -n overrides the default)
    if req.verb == "next":
        req.verb = "list"
        if "order" not in req.verb_args:
            req.verb_args.append("order")
        if "n" not in req.flags:
            req.flags["n"] = 1

    # list works without targets (shows top-level); other verbs require them
    if req.verb != "list" and not targets:
        raise SystemExit(f"Error: '{req.verb}' requires a ticket ID")

    if req.verb == "list":
        _handle_list(project, targets, req, output)
    elif req.verb == "get":
        _handle_get(project, targets, req, output)
    elif req.verb == "replace":
        _handle_replace(project, targets, req)
        modified = True
    elif req.verb == "add":
        _handle_add(project, targets, req)
        modified = True
    elif req.verb == "del":
        _handle_del(project, targets, req)
        modified = True
    elif req.verb == "mod":
        _handle_mod(project, targets, req)
        modified = True
    elif req.verb == "link":
        _handle_link(project, targets, req)
        modified = True
    elif req.verb == "unlink":
        _handle_unlink(project, targets, req)
        modified = True
    elif req.verb == "status":
        _handle_status_verb(project, targets, req)
        modified = True
    elif req.verb == "close":
        _handle_close_verb(project, targets, req)
        modified = True
    elif req.verb == "reopen":
        _handle_reopen_verb(project, targets, req)
        modified = True
    elif req.verb == "move":
        _handle_move_verb(project, targets, req)
        modified = True
    return modified
# }}} # SOURCE END: 150-dispatch.py

# SOURCE START: 160-install-files+.py {{{
# ---------------------------------------------------------------------------
# Claude Code Plugin (embedded)
# ---------------------------------------------------------------------------
# `plan install` writes these files to create a Claude Code plugin.
# This dict is the single source of truth for plugin content.
#
# Embedded files:
#   .claude-plugin/plugin.json
#   hooks/hooks.json
#   hooks/scripts/load-plan-context.sh
#   skills/dispatch-with-plan/SKILL.md
#   skills/planning-with-plan/SKILL.md
#   skills/team-with-plan/SKILL.md
# ---------------------------------------------------------------------------

_PLUGIN_FILES = {
    '.claude-plugin/plugin.json': r'''{
  "name": "claude-plan",
  "description": "Integrate the plan CLI ticket tracker with Claude Code for structured planning and team coordination",
  "version": "1.0.10",
  "license": "MIT",
  "keywords": ["planning", "tickets", "task-tracking", "team-coordination"]
}
''',
    'hooks/hooks.json': r'''{
  "description": "Load plan ticket status at session start",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/load-plan-context.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
''',
    'hooks/scripts/load-plan-context.sh': r'''#!/bin/bash
set -euo pipefail

# Locate the plan file using the same discovery logic as `plan`:
# 1. PLAN_MD env var
# 2. .PLAN.md at git root
plan_file="${PLAN_MD:-}"

if [ -z "$plan_file" ]; then
    git_root=$(git rev-parse --show-toplevel 2>/dev/null || true)
    if [ -n "$git_root" ] && [ -f "$git_root/.PLAN.md" ]; then
        plan_file="$git_root/.PLAN.md"
    fi
fi

if [ -z "$plan_file" ] || [ ! -f "$plan_file" ]; then
    # No plan file found — nothing to inject
    exit 0
fi

# Show current ticket status
status=$(plan -f "$plan_file" list 2>/dev/null || true)

if [ -n "$status" ]; then
    cat <<EOF
Plan file: $plan_file

Current tickets:
$status
EOF
fi
''',
    'skills/dispatch-with-plan/SKILL.md': r'''---
name: dispatch-with-plan
description: Use when dispatching subagents (via the Agent tool) to work on tickets from the plan. You are the leader — you pick tickets, dispatch workers one at a time, and track progress.
---

# Dispatch with Plan

Dispatch subagents via the Agent tool to execute tickets from `.PLAN.md`. You are the leader — you pick tickets in order, send them to workers, and track progress.

**Announce at start:** "I'm using the dispatch-with-plan skill to coordinate subagents."

## When to Use

- You have tickets in `.PLAN.md` and want subagents to execute them
- Single leader dispatching workers via the Agent tool

Getting tickets overview/list:
- `plan N -r ls` gives structured view of subtasks.
- `plan N -r ls order` gives subtasks in order of execution.

## Leader Role

You are the coordinator — do not implement tickets yourself.
Delegate all implementation work to subagents. Your job: pick tickets, dispatch workers, review results.
If a worker fails, dispatch a new agent to fix it — do not fix it yourself.

## The Dispatch Loop

### 1. Get the next ticket

```bash
plan list order -n 1
```

### 2. Read the ticket

```bash
plan N
```

### 3. Dispatch a worker subagent

Use the Agent tool. Paste the full ticket content into the prompt — do not make the worker read the plan file. Use the worker prompt template below.

### 4. Process the return

When the worker returns, review the result. Then get the next ticket and repeat.

## Worker Prompt Template

Include this in the Agent tool prompt when dispatching:

```
You are implementing ticket #N: [TITLE]

## Ticket Content

[PASTE FULL TICKET CONTENT HERE]

## Your Workflow

1. Start the ticket: plan N status in-progress
2. Do the work — follow the ticket description.
3. Add notes as you go: plan N comment add "What you did or found"
4. If you discover additional work, create a subticket of your current ticket:
   plan create N 'title="Discovered subtask"'
   If the issue is out of scope of this ticket, create it elsewhere.
5. When done: plan N close
6. Report back: what you implemented, files changed, any issues.
7. For body restructuring: plan edit --start N, edit the file, plan edit --accept.
```

## Integration

- Use **claude-plan:planning-with-plan** to create the initial ticket breakdown
- Use **claude-plan:team-with-plan** instead for persistent named agents with assignees
''',
    'skills/planning-with-plan/SKILL.md': r'''---
name: planning-with-plan
description: Use when you need to plan, track, or execute a multi-step implementation task. Replaces ad-hoc markdown checklists and TodoWrite with the `plan` CLI ticket tracker. Use for any task with 3+ steps.
---

# Planning with Plan

Use the `plan` CLI to create, track, and execute implementation tasks in a structured ticket hierarchy stored in `.PLAN.md`.

**Announce at start:** "I'm using the planning-with-plan skill to track this work."

## When to Use

- Multi-step implementation tasks (3+ steps)
- Feature development requiring a breakdown
- Any work where you would normally create a TodoWrite checklist or an md plan file

## Quick Reference

```bash
plan create 'title="Step name"'              # Create top-level task
plan create PARENT 'title="Subtask"'          # Create subtask under PARENT
plan list                                     # List all tickets
plan list is_open                             # Filter to open tickets
plan 'status == "in-progress"' list           # Filter to in-progress tickets
plan -p is_open list                          # Open tickets with ancestor path
plan N                                        # View ticket content
plan N status in-progress                     # Mark as in-progress
plan N close                                  # Mark as done
plan N comment add "Note"                     # Add a note
plan list ready                               # Show actionable tickets
plan list order                               # Show execution order

```

## The Process

### Step 1: Break Down the Work

Create a ticket hierarchy. For multiple tickets, write them as markdown:

```bash
plan create [parent] - <<'EOF'
* ## Epic: Implement feature X

  Feature description and acceptance criteria.

  * ## Write failing tests

    Test the core behavior.

  * ## Implement core logic

    Build the feature.

  * ## Update documentation

    Update relevant docs.
EOF
```

Tickets are executed in creation order — list them in the sequence you want.
Use `plan move` to reorder after creation. For cross-branch dependencies,
use `{#placeholder}` IDs and `links: blocked:#placeholder` to cross-reference
between new tickets:

```bash
* ## Set up database {#db}
    ...
* ## Build API {#api}
        links: blocked:#db
    ...
```

For single tickets, use the expression syntax:

```bash
plan create 'title="Quick fix"'
plan create 1 'title="Subtask under #1"'
```

### Step 2: Execute Tasks

Work through tickets in order. For each:

1. **Start it:** `plan N status in-progress`
2. **Do the work** — follow the ticket description, write code, run tests.
3. **Add notes** as you go: `plan N comment add "Discovered edge case"`
4. **Close it:** `plan N close`
5. **Check what's next:** `plan list ready` or `plan list order`

### Step 3: Report Progress

Between batches of work, show the user where things stand:

```bash
plan list --format 'f"{indent}#{id} [{status}] {title}"'
```

### Step 4: Adapt

If new work surfaces: `plan create PARENT 'title="Handle newly discovered case"'`
If a task is unnecessary: `plan N close wontfix`
If you need to restructure a ticket body or subtree: `plan edit --start N`, edit the file, `plan edit --accept`.

## Replacing TodoWrite

| TodoWrite | plan equivalent |
|-----------|-----------------|
| `TaskCreate(subject="...")` | `plan create 'title="..."'` |
| `TaskUpdate(id, status="in_progress")` | `plan N status in-progress` |
| `TaskUpdate(id, status="completed")` | `plan N close` |
| `TaskList()` | `plan list --format 'f"{indent}#{id} [{status}] {title}"'` |

## Integration

- For subagent dispatch, use **claude-plan:dispatch-with-plan**
- For persistent named agents with assignees, use **claude-plan:team-with-plan**
''',
    'skills/team-with-plan/SKILL.md': r'''---
name: team-with-plan
description: Use when coordinating multiple subagents or a team of agents on implementation tasks. Replaces TaskCreate/TaskUpdate/TaskList with the `plan` CLI for richer coordination via tickets, comments, queries, and hierarchy.
---

# Team Coordination with Plan

Coordinate a team of subagents using the `plan` CLI ticket tracker instead of the built-in task system.

**Announce at start:** "I'm using the team-with-plan skill to coordinate this work."

## When to Use

- Dispatching 2+ subagents on implementation work
- Complex multi-task plans requiring coordination

## Leader Role

When coordinating subagents, you are the coordinator — do not implement tickets yourself.
Delegate all implementation work to subagents. Your job: create tickets, dispatch workers, monitor progress, review results.
If a worker fails, dispatch a new agent to fix it — do not fix it yourself.

## Quick Reference — Leader

```bash
plan create 'title="Task name", assignee="agent-name"'   # Create and assign
plan list --format 'f"{indent}#{id} [{status}] {assignee}: {title}"'     # Dashboard
plan list ready                                           # Actionable items
plan list order                                           # Execution order
plan N comment add "Feedback note"                        # Add feedback
```

## Quick Reference — Agent

```bash
plan 'assignee == "my-name" and is_open' list                  # My work
plan N status in-progress                                      # Start
plan N -r ls                                                   # Structured view of subtasks
plan N -r ls order                                             # Subtasks in execution order
plan N comment add "Found issue, fixing"                       # Note
plan N close                                                   # Done
plan list ready                                                # What's next
plan list order                                                # Execution order
```

## Agent Prompt Template

Include this in subagent dispatch prompts:

```
## Task Tracking

Use the `plan` CLI to manage your assigned work:

- Find your tasks: plan 'assignee == "YOUR-NAME" and is_open' list
- View a task: plan N
- Structured view of subtasks: plan N -r ls
- Subtasks in execution order: plan N -r ls order
- Start work: plan N status in-progress
- Add notes: plan N comment add "Description of what you did or found"
- Complete: plan N close
- Check for more: plan list ready (or plan list order)
- Create subtasks if needed: plan create PARENT 'title="New subtask", assignee="YOUR-NAME"'
- If blocked: plan N comment add "Blocked: reason"
- For body restructuring: plan edit --start N, edit the file, plan edit --accept
```

## Merging Plan Branches

When workers commit plan changes on separate branches, reconcile them with the structure-aware merge driver (install once per repo: `plan install git`). With it configured, `git merge`/`rebase` merges plan files automatically — no manual step on the clean path.

On a **conflict**, the driver writes a `<file>.reject` sidecar and marks the file unmerged; the plan file itself stays valid (defaulting to the current branch's side), so there are no `<<<<<<<` markers in it. To finish: edit each block in the `.reject` to keep ONE side (`--- to ---` or `--- from ---`), then `plan merge --resolve && git add <file>` (or `plan merge --abort`). Agents run non-interactively — the driver already produced the `.reject`; just resolve it.

Merge a specific branch's plan on demand with `plan merge <branch>`. Recover a plan file already broken by raw git conflict markers with `plan resolve`.

## Integration

- Use **claude-plan:planning-with-plan** to create the initial work breakdown
- Compatible with TeamCreate for agent lifecycle management
''',
}

_CLAUDE_MD_SECTION = r'''
## Task tracking

Use the `plan` CLI for ALL task tracking. Do not use TodoWrite or TaskCreate.

Load skills:
* `planning-with-plan` from `.claude/plugins/claude-plan/skills/planning-with-plan/SKILL.md`
* `dispatch-with-plan` from `.claude/plugins/claude-plan/skills/dispatch-with-plan/SKILL.md`
* `team-with-plan` from `.claude/plugins/claude-plan/skills/team-with-plan/SKILL.md`

### Before starting work
- Break the task into tickets: `plan create 'title="Step name"'`
- For subtasks: `plan create PARENT 'title="Subtask"'`
- Create tickets in preferred execution order (or reorder with `plan move`)
- Put details in each subtask body (`plan N add "what to do"`), not as a TODO list in the parent
- Review the breakdown: `plan list`

### While working
- Before starting a ticket: `plan N status in-progress`
- After completing a ticket: `plan N close`
- Add notes when useful: `plan N comment add "What happened"`
- If new work surfaces: `plan create PARENT 'title="New task"'`
- If a task is unnecessary: `plan N close wontfix`
- Check what's next: `plan list ready` or `plan list order`

### Reporting progress
- Show status: `plan list --format 'f"{indent}#{id} [{status}] {title}"'`

### Merging branches
Plan files merge automatically when the git merge driver is installed (`plan install git`): `git merge`/`rebase` reconciles them structurally. If a merge reports a **conflict** in a plan file, the driver left a `<file>.reject` sidecar (the plan file itself stays valid, defaulting to your side) — there are no `<<<<<<<` markers to hand-edit. Finish it: edit each block in the `.reject` to keep ONE side (`--- to ---` or `--- from ---`), then `plan merge --resolve && git add <file>` — or `plan merge --abort` to discard. Merge another branch's plan manually with `plan merge <branch>`; recover a file already broken by raw conflict markers with `plan resolve`.

### For subagents / team workers
When dispatching subagents, you are the coordinator — do not implement tickets yourself.

Include these instructions in the subagent prompt:
- Find your tasks: `plan 'assignee == "YOUR-NAME" and is_open' list`
- View a task: `plan N`
- Structured view of subtasks: `plan N -r ls`
- Subtasks in execution order: `plan N -r ls order`
- Start work: `plan N status in-progress`
- Add notes: `plan N comment add "Description of what you did"`
- Complete: `plan N close`
- Check for more: `plan list ready` or `plan list order`
- Create subtasks if needed: `plan create PARENT 'title="Subtask", assignee="YOUR-NAME"'`
'''

_CLAUDE_MD_MARKER = '## Task tracking'

_CODEX_MD_SECTION = r'''
## Task tracking

Use the `plan` CLI for ALL task tracking.

### Before starting work
- Break the task into tickets: `plan create 'title="Step name"'`
- For subtasks: `plan create PARENT 'title="Subtask"'`
- Create tickets in preferred execution order (or reorder with `plan move`)
- Put details in each subtask body (`plan N add "what to do"`), not as a TODO list in the parent
- Review the breakdown: `plan list`

### While working
- Before starting a ticket: `plan N status in-progress`
- After completing a ticket: `plan N close`
- Add notes when useful: `plan N comment add "What happened"`
- If new work surfaces: `plan create PARENT 'title="New task"'`
- If a task is unnecessary: `plan N close wontfix`
- Check what's next: `plan list ready` or `plan list order`

### Reporting progress
- Show status: `plan list --format 'f"{indent}#{id} [{status}] {title}"'`

### Merging branches
Plan files merge automatically when the git merge driver is installed (`plan install git`): `git merge`/`rebase` reconciles them structurally. If a merge reports a **conflict** in a plan file, the driver left a `<file>.reject` sidecar (the plan file itself stays valid, defaulting to your side) — there are no `<<<<<<<` markers to hand-edit. Finish it: edit each block in the `.reject` to keep ONE side (`--- to ---` or `--- from ---`), then `plan merge --resolve && git add <file>` — or `plan merge --abort` to discard. Merge another branch's plan manually with `plan merge <branch>`; recover a file already broken by raw conflict markers with `plan resolve`.

### For subagents / team workers
When dispatching subagents, you are the coordinator — do not implement tickets yourself.

Include these instructions in the subagent prompt:
- Find your tasks: `plan 'assignee == "YOUR-NAME" and is_open' list`
- View a task: `plan N`
- Structured view of subtasks: `plan N -r ls`
- Subtasks in execution order: `plan N -r ls order`
- Start work: `plan N status in-progress`
- Add notes: `plan N comment add "Description of what you did"`
- Complete: `plan N close`
- Check for more: `plan list ready` or `plan list order`
- Create subtasks if needed: `plan create PARENT 'title="Subtask", assignee="YOUR-NAME"'`
'''

_CODEX_MD_MARKER = '## Task tracking'


# }}} # SOURCE END: 160-install-files+.py

# SOURCE START: 170-install.py {{{
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


def _remove_md_section(content, marker):
    """Remove a marker-delimited section from markdown content.

    Returns the remaining content (may be empty string).
    """
    if marker not in content:
        return content
    idx = content.index(marker)
    # Trim preceding newlines
    while idx > 0 and content[idx - 1] == "\n":
        idx -= 1
    before = content[:idx]
    after_section = content[content.index(marker):]
    # Find end of our section: next ## heading or end of file
    lines = after_section.split("\n")
    end = len(lines)
    for i, line in enumerate(lines):
        if i > 0 and line.startswith("## ") and line != marker:
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


def _remove_claude_md_section(content):
    return _remove_md_section(content, _CLAUDE_MD_MARKER)


def _handle_install(scope):
    """Install plan binary, Claude Code plugin, and CLAUDE.md instructions.

    scope: 'local' (current directory), 'user' (~/.local/bin + ~/.claude), or
    'git' (ONLY the git merge driver in the current repo — no binary/plugin/
    CLAUDE.md).
    """
    if scope not in ("local", "user", "git"):
        raise SystemExit(
            "Error: install requires 'local', 'user', or 'git' argument")

    # 'git' target: configure ONLY the merge driver in the current repo.
    if scope == "git":
        _install_merge_driver(strict=True)
        print("Done.")
        return

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

    # --- AGENTS.md (Codex) ---
    if scope == "local":
        agents_md_path = os.path.join(os.getcwd(), "AGENTS.md")
    else:
        agents_md_path = os.path.expanduser("~/.codex/instructions.md")

    existing = ""
    if os.path.exists(agents_md_path):
        with open(agents_md_path) as f:
            existing = f.read()

    if _CODEX_MD_MARKER in existing:
        new_content = _remove_md_section(existing, _CODEX_MD_MARKER)
        if new_content.strip():
            with open(agents_md_path, "w") as f:
                f.write(new_content + _CODEX_MD_SECTION)
        else:
            with open(agents_md_path, "w") as f:
                f.write(_CODEX_MD_SECTION)
        print(f"AGENTS.md: replaced section in {agents_md_path}")
    else:
        os.makedirs(os.path.dirname(agents_md_path) or ".", exist_ok=True)
        with open(agents_md_path, "a") as f:
            f.write(_CODEX_MD_SECTION)
        print(f"AGENTS.md: updated {agents_md_path}")

    # --- Git merge driver (local scope only) ---
    if scope == "local":
        _install_merge_driver()

    print("Done.")


_DRIVER_PLAN_FILE = ".PLAN.md"
_DRIVER_REJECT_PATTERN = ".PLAN.md.reject"


def _resolve_repo_root_or_skip(strict):
    """Resolve the current git repo root, or signal "no repo".

    Returns the repo root path, or None when the cwd is not a git repository
    (or git is unavailable). When `strict` is True (the standalone `git` target,
    whose ONLY job is the driver), a missing repo is a hard error
    (SystemExit, non-zero exit); otherwise it is a silent skip (the `local`
    target, where the driver is a bonus on top of a full install).
    """
    try:
        return git_repo_root()
    except (RuntimeError, OSError):
        if strict:
            raise SystemExit(
                "Error: 'git' target requires a git repository "
                "(run inside a git work tree)")
        return None


def _install_merge_driver(strict=False):
    """Configure the structure-aware git merge driver in the current repo.

    Adds `.PLAN.md merge=plan` to .gitattributes, sets merge.plan.* in the
    repo's git config, and ignores the `.reject` sidecar. When `strict` is False
    (the `local` target) a non-git cwd is a silent skip; when True (the `git`
    target) it is a hard error.
    """
    repo_root = _resolve_repo_root_or_skip(strict)
    if repo_root is None:
        print("Merge driver: skipped (not a git repository)")
        return

    ensure_gitattributes(repo_root, _DRIVER_PLAN_FILE)
    set_merge_driver(repo_root)
    ensure_gitignore(repo_root, _DRIVER_REJECT_PATTERN)
    print(f"Merge driver: configured in {repo_root}")
    print(f"  .gitattributes: {_DRIVER_PLAN_FILE} merge=plan")
    print(f"  git config: merge.plan.driver = {_MERGE_DRIVER_CMD}")
    print(f"  .gitignore: {_DRIVER_REJECT_PATTERN}")


def _uninstall_merge_driver(strict=False):
    """Remove the structure-aware git merge driver config from the current repo.

    Idempotent: removes the .gitattributes line, the merge.plan config section,
    and the `.reject` .gitignore line; tolerates any being absent. When `strict`
    is False (the `local` target) a non-git cwd is a silent skip; when True (the
    `git` target) it is a hard error.
    """
    repo_root = _resolve_repo_root_or_skip(strict)
    if repo_root is None:
        print("Merge driver: skipped (not a git repository)")
        return

    remove_gitattributes(repo_root, _DRIVER_PLAN_FILE)
    unset_merge_driver(repo_root)
    remove_gitignore(repo_root, _DRIVER_REJECT_PATTERN)
    print(f"Merge driver: removed from {repo_root}")


def _handle_uninstall(scope):
    """Uninstall plan binary, Claude Code plugin, and CLAUDE.md instructions.

    scope: 'local' (current directory), 'user' (~/.local/bin + ~/.claude), or
    'git' (ONLY the git merge driver in the current repo).
    """
    if scope not in ("local", "user", "git"):
        raise SystemExit(
            "Error: uninstall requires 'local', 'user', or 'git' argument")

    # 'git' target: remove ONLY the merge driver from the current repo.
    if scope == "git":
        _uninstall_merge_driver(strict=True)
        print("Done.")
        return

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

    # --- AGENTS.md (Codex) ---
    if scope == "local":
        agents_md_path = os.path.join(os.getcwd(), "AGENTS.md")
    else:
        agents_md_path = os.path.expanduser("~/.codex/instructions.md")

    if os.path.exists(agents_md_path):
        with open(agents_md_path) as f:
            content = f.read()

        if _CODEX_MD_MARKER in content:
            new_content = _remove_md_section(content, _CODEX_MD_MARKER)
            if new_content.strip():
                with open(agents_md_path, "w") as f:
                    f.write(new_content)
                print(f"AGENTS.md: removed task tracking section from {agents_md_path}")
            else:
                os.remove(agents_md_path)
                # Clean up empty parent dir for user scope
                if scope == "user":
                    parent = os.path.dirname(agents_md_path)
                    if os.path.isdir(parent) and not os.listdir(parent):
                        os.rmdir(parent)
                print(f"AGENTS.md: removed {agents_md_path} (was empty)")
        else:
            print(f"AGENTS.md: no task tracking section found")
    else:
        print(f"AGENTS.md: not found at {agents_md_path}")

    # --- Git merge driver (local scope only) ---
    if scope == "local":
        _uninstall_merge_driver()

# }}} # SOURCE END: 170-install.py

# SOURCE START: 180-main.py {{{
# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    """Main entry point."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        output = []
        _handle_help(output)
        for line in output:
            print(line)
        return

    # Handle --version anywhere in argv
    if "--version" in argv:
        print(f"{VERSION_STR} {VERSION_DATE}")
        return

    # Handle install/uninstall before parsing (no plan file needed)
    if argv[0] == "install":
        if len(argv) < 2:
            raise SystemExit(
                "Error: install requires 'local', 'user', or 'git' argument")
        _handle_install(argv[1])
        return
    if argv[0] == "uninstall":
        if len(argv) < 2:
            raise SystemExit(
                "Error: uninstall requires 'local', 'user', or 'git' argument")
        _handle_uninstall(argv[1])
        return

    # Git merge driver entry: `plan merge-driver %O %A %B %P`. Intercepted early
    # because git passes raw positional temp files (not the normal grammar), and
    # the driver needs git + raw text. It writes %A itself and returns an exit
    # code (0 = clean, non-zero = conflict; git then records the path unmerged).
    if argv[0] == "merge-driver":
        positional = argv[1:]
        if len(positional) != 4:
            raise SystemExit(
                "Error: merge-driver requires exactly 4 arguments: "
                "<base> <ours> <theirs> <path>")
        rc = _handle_merge_driver(positional[0], positional[1],
                                  positional[2], positional[3])
        sys.exit(rc)

    # Parse requests
    requests = parse_argv(argv)

    # Extract file flag from first request (flags are global)
    flags = {}
    for req in requests:
        flags.update(req.flags)

    # Check for help-only requests
    for req in requests:
        if req.command is not None and req.command[0] in ("help", "h"):
            output = []
            topic = req.command[1][0] if req.command[1] else None
            _handle_help(output, command=topic)
            for line in output:
                print(line)
            return

    # Merge: intercepted BEFORE main's discover_file/flock block. Stage 9 made
    # merge work on explicit --to/--from/--base sources and `-o OUT`, possibly
    # entirely outside a git repo and without a discoverable .PLAN.md, so it
    # can't use main's single-file flock. The handler does its own source
    # resolution + output discovery and takes its OWN exclusive lock on the
    # output file for the read->merge->write (see _OutputLock in 145). It
    # returns an exit code (0/1/2); status to stdout, errors to stderr.
    for req in requests:
        if req.command is not None and req.command[0] == "merge":
            output = []
            rc = _handle_merge(req, flags, output)
            for line in output:
                print(line)
            sys.exit(rc)

    # Discover file
    filepath = discover_file(flags)
    abs_filepath = os.path.abspath(filepath)
    plan_dir = os.path.dirname(abs_filepath)
    plan_filename = os.path.basename(abs_filepath)

    # Handle --abort before acquiring flock (it only touches temp files)
    for req in requests:
        if (req.command is not None and req.command[0] == "edit"
                and req.flags.get("abort")):
            cmd_args = req.command[1]
            _handle_edit_abort(cmd_args, plan_dir, plan_filename)
            return

    # Determine if all requests are read-only
    # edit --start is NOT read-only (it reads plan data to export)
    # edit --accept is NOT read-only (it modifies the plan)
    # edit --abort is handled above (before flock)
    is_read_only = all(
        (req.command is not None and req.command[0] in {"check", "help", "h"}) or
        (req.command is None and req.verb in ("get", "list"))
        for req in requests
    )

    # Acquire file lock for the duration of execution (if flock available)
    lock_fd = None
    try:
        if _has_flock and (os.path.exists(filepath) or not is_read_only):
            lock_fd = open(filepath, "a")
            lock_mode = fcntl.LOCK_SH if is_read_only else fcntl.LOCK_EX
            for _attempt in range(20):
                try:
                    fcntl.flock(lock_fd, lock_mode | fcntl.LOCK_NB)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise SystemExit(
                    f"Error: could not acquire lock on {filepath} "
                    f"(timed out after 2 seconds)")

        # Read file or bootstrap
        file_exists = os.path.exists(filepath)
        if not file_exists or os.path.getsize(filepath) == 0:
            if is_read_only:
                raise SystemExit(f"Error: file not found: {filepath}")
            text = ""
        else:
            text = open(filepath).read()

        # Check for resolve command (works on raw text, not parsed). The new
        # resolve is the two-way structural cousin of merge: it reconstructs the
        # sides from raw git conflict markers, runs the engine, writes the plan
        # file itself, and returns an exit code (0/1/2). Status to stdout.
        for req in requests:
            if req.command is not None and req.command[0] == "resolve":
                output = []
                rc = _handle_resolve(filepath, text, output)
                for line in output:
                    print(line)
                sys.exit(rc)

        # Parse document
        project = parse(text)
        if not project.title:
            _bootstrap_project(project)

        # Store plan directory and filename on project for handlers to access
        project._plan_dir = plan_dir
        project._plan_filename = plan_filename

        # Dispatch all requests
        output = []
        modified = False
        for req in requests:
            result = dispatch(project, req, output)
            if result:
                modified = True

        # Print output
        for line in output:
            print(line)

        # Write back if modified
        if modified:
            out_text = serialize(project)
            with open(filepath, "w") as f:
                f.write(out_text)
    finally:
        if lock_fd is not None:
            lock_fd.close()


if __name__ == "__main__":
    main()
# }}} # SOURCE END: 180-main.py

