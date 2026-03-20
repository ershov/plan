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
