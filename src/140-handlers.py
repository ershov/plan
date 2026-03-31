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

