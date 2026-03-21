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
            result = _handle_edit_command(project, cmd_args, req)
            # Non-interactive: start returns False (no plan modification),
            # accept returns True/None, abort handled in main().
            # Interactive edit always modifies.
            return result if result is not None else True
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
