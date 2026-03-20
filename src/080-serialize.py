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

