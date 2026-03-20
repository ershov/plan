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

