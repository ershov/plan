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

