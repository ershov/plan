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
