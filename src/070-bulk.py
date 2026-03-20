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

