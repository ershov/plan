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

