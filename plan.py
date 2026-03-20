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
import textwrap

try:
    import fcntl
    _has_flock = True
except ImportError:
    _has_flock = False
# }}} # SOURCE END: 010-preambula.py

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

    # Step 2: Rejoin and replace all placeholders with real IDs
    result = "\n".join(lines)
    for placeholder, real_id in placeholder_map.items():
        result = result.replace(placeholder, real_id)

    # Step 3: Check for any remaining undefined placeholders (non-numeric #id)
    remaining = [m for m in re.findall(r"#([a-zA-Z0-9_-]+)", result)
                 if not m.isdigit()]
    if remaining:
        unique = sorted(set(f"#{r}" for r in remaining))
        raise SystemExit(
            f"Undefined placeholder references: {', '.join(unique)}"
        )

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

# SOURCE START: 120-cli.py {{{
# ---------------------------------------------------------------------------
# CLI Parser
# ---------------------------------------------------------------------------

COMMANDS = {"create", "edit",
            "check", "fix", "resolve", "help", "h"}
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
  resolve           Resolve merge conflicts
  install local|user  Install binary, Claude Code plugin, and CLAUDE.md
  uninstall local|user  Remove binary, plugin, and CLAUDE.md section
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

  Examples:
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
plan edit — Edit in external editor

Usage:
  plan edit ID                   Edit single ticket
  plan edit ID -r                Edit entire subtree in one editor

Opens the ticket or node content in $EDITOR for interactive editing.
Saves changes back to the plan file on exit. ID can be a ticket
number, section name, or any node identifier.

When editing recursively (-r), you can add new tickets by writing
* ## headers without an ID or with {#newXXX} placeholders.
New ticket IDs, timestamps, and status are auto-assigned.

Flags:
  -r, --recursive    Edit the entire subtree (ticket + children) recursively.

Examples:
  plan edit 5                    Edit ticket #5
  plan edit 5 -r                 Edit ticket #5 and all children
  plan edit description          Edit project description section
  plan edit project              Edit the project root node
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
plan install — Install plan binary, Claude Code plugin, and CLAUDE.md

Usage:
  plan install local    Install into current directory / project
  plan install user     Install into ~/.local/bin and ~/.claude

What gets installed:
  Binary    'local': ./plan, 'user': ~/.local/bin/plan
            Skipped if plan is already on PATH.
  Plugin    'local': .claude/plugins/claude-plan/
            'user': ~/.claude/plugins/claude-plan/
            Registered in the corresponding settings.json.
  CLAUDE.md 'local': ./CLAUDE.md
            'user': ~/.claude/CLAUDE.md
            Appends task tracking instructions. Skipped if already present.
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
plan resolve — Resolve merge conflicts

Usage:
  plan resolve

Parses git merge conflict markers in the plan file and attempts
to produce a clean merged document.
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
plan uninstall — Remove plan binary, Claude Code plugin, and CLAUDE.md section

Usage:
  plan uninstall local    Remove from current directory / project
  plan uninstall user     Remove from ~/.local/bin and ~/.claude

Removes the binary, plugin directory, settings.json registration, and
the task tracking section from CLAUDE.md. Empty files and directories
are cleaned up.
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


def _build_create_template(move="", parent="", title="", errors=None,
                            body="", extra_attrs=None, bulk=False):
    """Build the editor template for create command.

    Args:
        rank: pre-computed rank value
        parent: parent ticket ID or empty string
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
    lines.append(f"{attr_prefix}parent: {parent}")
    lines.append(f"{attr_prefix}move: {move}")
    if extra_attrs:
        for key, val in extra_attrs.items():
            if key not in ("parent", "move", "assignee", "links"):
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

    Returns dict with keys: title, attrs, body, parent, errors.
    Returns None if text is empty.
    """
    if not text or not text.strip():
        return None

    lines = text.split('\n')
    result = {"title": "", "attrs": {}, "body": "", "parent": None, "errors": []}

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
            if key == "parent":
                result["parent"] = value if value else None
            elif value:  # drop blank optional attrs
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


def _handle_edit_command(project, cmd_args, req):
    """Handle 'edit' command — edit a single ticket/node in $EDITOR.

    Usage: edit ID [-r]
    -r includes children in the edit buffer.
    """
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
        new_root.dirty = True

        # Restore original children if not editing recursively
        if saved_children is not None:
            new_root.children = saved_children
            for child in saved_children:
                child.parent = new_root

        # Mark all descendants dirty and fix body indentation
        def _fixup(t):
            t.dirty = True
            content_indent = " " * (t.indent_level + 2)
            fixed = []
            for bl in t.body_lines:
                if bl.strip():
                    fixed.append(content_indent + bl.lstrip())
                else:
                    fixed.append("")
            t.body_lines = fixed
            for c in t.children:
                _fixup(c)
        for nt in new_tickets:
            _fixup(nt)

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
    # Resolve parent from template (may differ from CLI arg)
    tmpl_parent = parsed_tmpl["parent"]
    parent, siblings = _resolve_parent(project, tmpl_parent or parent_id)

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

        default_move = ""

        # Pre-fill from expression if provided
        prefill_title = ""
        prefill_body = ""
        prefill_attrs = {}
        if expr_str:
            tmp = Ticket(0, "", "Task")
            apply_mod(tmp, project, f"set({expr_str})")
            prefill_title = tmp.title
            prefill_body = '\n'.join(l.strip() for l in tmp.body_lines if l.strip())
            for k, v in tmp.attrs.items():
                prefill_attrs[k] = v

        use_bulk = bool(req.flags.get("recursive"))
        template = _build_create_template(
            move=prefill_attrs.pop("move", default_move),
            parent=parent_id or "",
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
                    parent=parsed_tmpl["parent"] or "",
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


def _handle_resolve(project_unused, output, filepath=None, raw_text=None):
    """Handle 'resolve' command — resolve git merge conflicts."""
    if raw_text is None and filepath:
        with open(filepath) as f:
            raw_text = f.read()
    elif raw_text is None:
        output.append("OK: no conflicts found")
        return None

    lines = raw_text.split('\n')
    resolved = []
    i = 0
    n = len(lines)
    had_conflicts = False

    while i < n:
        line = lines[i]

        # Conflict start
        if line.startswith('<<<<<<<'):
            had_conflicts = True
            ours = []
            theirs = []
            i += 1
            in_ours = True

            while i < n:
                if lines[i].startswith('======='):
                    in_ours = False
                    i += 1
                    continue
                if lines[i].startswith('>>>>>>>'):
                    i += 1
                    break
                if in_ours:
                    ours.append(lines[i])
                else:
                    theirs.append(lines[i])
                i += 1

            # Merge strategy: compare timestamp lines, keep newer
            merged = _merge_conflict_block(ours, theirs)
            resolved.extend(merged)
            continue

        resolved.append(line)
        i += 1

    if not had_conflicts:
        output.append("OK: no conflicts found")
        return None

    result_text = '\n'.join(resolved)
    output.append(f"Resolved {sum(1 for l in lines if l.startswith('<<<<<<<'))} conflict(s)")
    return result_text


def _merge_conflict_block(ours, theirs):
    """Merge a conflict block, preferring newer timestamps."""
    # Check if both sides are attribute blocks with timestamps
    ours_attrs = _try_parse_attrs(ours)
    theirs_attrs = _try_parse_attrs(theirs)

    if ours_attrs and theirs_attrs:
        # Merge attributes, preferring newer timestamps
        merged = dict(ours_attrs)
        for k, v in theirs_attrs.items():
            if k in ("updated", "created"):
                # Compare timestamps
                ours_val = merged.get(k, "")
                if v > ours_val:
                    merged[k] = v
            elif k not in merged:
                merged[k] = v
        # Reconstruct attribute lines
        indent = ""
        if ours and ours[0]:
            indent = " " * _indent_of(ours[0])
        result = []
        for k, v in merged.items():
            result.append(f"{indent}{k}: {v}")
        return result

    # Default: use ours (but include unique lines from theirs)
    ours_set = set(l.strip() for l in ours)
    result = list(ours)
    for line in theirs:
        if line.strip() not in ours_set and line.strip():
            result.append(line)
    return result


def _try_parse_attrs(lines):
    """Try to parse lines as attribute key:value pairs."""
    attrs = {}
    for line in lines:
        if not line.strip():
            continue
        m = RE_ATTR.match(line)
        if m:
            attrs[m.group(2)] = m.group(3)
        else:
            return None  # Not all attribute lines
    return attrs if attrs else None

# }}} # SOURCE END: 140-handlers.py

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
            _handle_edit_command(project, cmd_args, req)
            return True
        if cmd_name == "check":
            _handle_check(project, output)
            return False
        if cmd_name == "fix":
            _handle_fix(project, output)
            return True
        if cmd_name == "resolve":
            return "resolve"
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
  "version": "1.0.0",
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
- Start work: plan N status in-progress
- Add notes: plan N comment add "Description of what you did or found"
- Complete: plan N close
- Check for more: plan list ready (or plan list order)
- Create subtasks if needed: plan create PARENT 'title="New subtask", assignee="YOUR-NAME"'
- If blocked: plan N comment add "Blocked: reason"
```

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

### For subagents / team workers
When dispatching subagents, you are the coordinator — do not implement tickets yourself.

Include these instructions in the subagent prompt:
- Find your tasks: `plan 'assignee == "YOUR-NAME" and is_open' list`
- View a task: `plan N`
- Start work: `plan N status in-progress`
- Add notes: `plan N comment add "Description of what you did"`
- Complete: `plan N close`
- Check for more: `plan list ready` or `plan list order`
- Create subtasks if needed: `plan create PARENT 'title="Subtask", assignee="YOUR-NAME"'`
'''

_CLAUDE_MD_MARKER = '## Task tracking'


# }}} # SOURCE END: 160-install-files+.py

# SOURCE START: 170-install.py {{{
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

    # Handle install/uninstall before parsing (no plan file needed)
    if argv[0] == "install":
        if len(argv) < 2:
            raise SystemExit("Error: install requires 'local' or 'user' argument")
        _handle_install(argv[1])
        return
    if argv[0] == "uninstall":
        if len(argv) < 2:
            raise SystemExit("Error: uninstall requires 'local' or 'user' argument")
        _handle_uninstall(argv[1])
        return

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

    # Discover file
    filepath = discover_file(flags)

    # Determine if all requests are read-only
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
            fcntl.flock(lock_fd,
                        fcntl.LOCK_SH if is_read_only else fcntl.LOCK_EX)

        # Read file or bootstrap
        file_exists = os.path.exists(filepath)
        if not file_exists or os.path.getsize(filepath) == 0:
            if is_read_only:
                raise SystemExit(f"Error: file not found: {filepath}")
            text = ""
        else:
            text = open(filepath).read()

        # Check for resolve command (works on raw text, not parsed)
        for req in requests:
            if req.command is not None and req.command[0] == "resolve":
                output = []
                result_text = _handle_resolve(None, output, filepath=filepath,
                                               raw_text=text)
                for line in output:
                    print(line)
                if result_text is not None:
                    with open(filepath, "w") as f:
                        f.write(result_text)
                return

        # Parse document
        project = parse(text)
        if not project.title:
            _bootstrap_project(project)

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

