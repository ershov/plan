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

