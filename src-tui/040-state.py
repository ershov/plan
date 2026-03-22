##############################################################################
# Application State — module-level variables and state helpers
##############################################################################

all_tickets = []      # flat list of ticket dicts from plan_list() (full tree, cached)
cursor = 0            # integer index into the visible tickets list
scope = None          # ticket ID (int) or None for root
expanded = set()      # set of ticket IDs that have been expanded
selected = set()      # set of ticket IDs for multi-select
search_query = ''     # string, empty when not in search mode
search_mode = False   # bool, whether keystrokes go to search input
preview_text = ''     # cached string for preview pane
children_list = []    # cached list of dicts for subtickets pane
needs_redraw = set()  # set of strings: 'list', 'subtickets', 'preview', 'status', 'all'
show_preview = True   # whether the preview pane is visible (Ctrl-P toggles)
help_mode = False     # when True, preview pane shows help text instead of ticket
error_text = ''       # when non-empty, preview pane shows error output
insert_mode = False   # when True, showing "-- here --" marker for create/move
insert_pos = 0        # gap position in visible list (1..N)
insert_depth = 0      # depth of the insertion marker
insert_callback = None  # callable(relation, dest_id) on confirm
insert_label = ''       # 'create' or 'move' — shown in the marker
_preview_scroll = 0   # scroll offset within the preview pane
_last_preview_id = -1 # tracks which ticket ID the preview is cached for

_visible_cache = None # cached result of visible_tickets()
_visible_dirty = True # flag: rebuild visible list on next call


def _mark_visible_dirty():
    """Mark the visible tickets cache as stale."""
    global _visible_dirty
    _visible_dirty = True


def visible_tickets():
    """Return the list of ticket dicts that should be displayed.

    Caches its result; only rebuilds when _visible_dirty is True.
    """
    global _visible_cache, _visible_dirty

    if not _visible_dirty and _visible_cache is not None:
        return _visible_cache

    # Build id_map from all_tickets (excluding synthetic entries)
    id_map = {}
    for t in all_tickets:
        id_map[t['id']] = t

    result = []

    if scope is None:
        # Root scope — prepend synthetic Project entry
        project_entry = {
            'id': 0,
            'parent': 0,
            'status': '',
            'has_children': True,
            'depth': 0,
            'title': 'Project',
        }
        result.append(project_entry)

        # Determine base depth (minimum depth in all_tickets)
        if all_tickets:
            base_depth = min(t['depth'] for t in all_tickets)
        else:
            base_depth = 0

        for t in all_tickets:
            if t['depth'] == base_depth:
                # Always visible at root level
                result.append(t)
            else:
                # Deeper ticket: walk parent chain, every ancestor between
                # base_depth (exclusive) and this ticket must be in expanded
                visible = True
                cur = t
                while cur['depth'] > base_depth:
                    pid = cur['parent']
                    parent = id_map.get(pid)
                    if parent is None:
                        # Parent not in our list — treat as visible if at
                        # base_depth + 1 (shouldn't happen, but be safe)
                        break
                    if parent['depth'] >= base_depth and parent['id'] not in expanded:
                        visible = False
                        break
                    cur = parent
                if visible:
                    result.append(t)
    else:
        # Scoped view — scope ticket is at depth D; children are at D+1
        scope_ticket = id_map.get(scope)
        if scope_ticket is None:
            # Scope ticket not found; return empty
            _visible_cache = []
            _visible_dirty = False
            return _visible_cache

        scope_depth = scope_ticket['depth']
        child_base = scope_depth + 1

        # Include the scope ticket itself as the first entry
        result.append(scope_ticket)

        for t in all_tickets:
            if t['id'] == scope:
                continue  # already included above
            if t['depth'] < child_base:
                continue  # not a descendant within scope
            if t['depth'] == child_base:
                # Direct child of scope — always visible
                result.append(t)
            else:
                # Deeper descendant: walk parent chain up to child_base,
                # every intermediate ancestor must be in expanded
                visible = True
                cur = t
                while cur['depth'] > child_base:
                    pid = cur['parent']
                    parent = id_map.get(pid)
                    if parent is None:
                        visible = False
                        break
                    if parent['id'] not in expanded:
                        visible = False
                        break
                    cur = parent
                if visible:
                    result.append(t)

    _visible_cache = result
    _visible_dirty = False
    return _visible_cache


def reload():
    """Reload all tickets from disk and refresh state."""
    global all_tickets, cursor, needs_redraw

    # Save current cursor ticket ID for position restoration
    vis = visible_tickets()
    old_ticket_id = vis[cursor]['id'] if 0 <= cursor < len(vis) else None

    # Invalidate caches and refetch
    cache_invalidate()
    _mark_visible_dirty()
    all_tickets = plan_list(scope)
    _mark_visible_dirty()  # all_tickets changed

    # Rebuild visible list
    vis = visible_tickets()

    # Restore cursor position
    if old_ticket_id is not None:
        found = False
        for i, t in enumerate(vis):
            if t['id'] == old_ticket_id:
                cursor = i
                found = True
                break
        if not found:
            # Clamp to valid range
            if vis:
                cursor = min(cursor, len(vis) - 1)
            else:
                cursor = 0
    else:
        cursor = 0

    needs_redraw = {'all'}
    update_preview()


_preview_gen = 0          # incremented on each new request; stale results discarded
_preview_event = threading.Event()
_preview_req = None       # (gen, tid) — latest pending request
_preview_result = None    # (text, children) — set by worker, consumed by main thread
_preview_worker_started = False

def _preview_worker():
    """Single background thread: fetch preview data one request at a time.

    Lets each subprocess finish naturally — never kills mid-flight.
    After each subprocess completes, checks if the request is still current.
    If a newer request arrived while we were busy, loops immediately to serve it.

    Stores results in _preview_result for the main thread to consume — never
    touches needs_redraw directly (avoiding a cross-thread race on set replacement).
    """
    global _preview_req, _preview_result
    while True:
        _preview_event.wait()
        _preview_event.clear()

        while True:
            # Grab the latest request
            req = _preview_req
            _preview_req = None
            if req is None:
                break
            gen, tid = req

            if gen != _preview_gen:
                break

            text = plan_get(tid)
            if gen != _preview_gen:
                continue  # stale — but check if a newer request is pending

            if tid == 0:
                tickets = all_tickets
                if tickets:
                    bd = min(t['depth'] for t in tickets)
                else:
                    bd = 0
                ch = [t for t in tickets if t['depth'] == bd]
            else:
                ch = plan_children(tid)

            if gen != _preview_gen:
                continue  # stale — check for newer request

            _preview_result = (text, ch)
            notify_wake()
            break


def apply_preview_result():
    """Consume pending result from the preview worker (called on main thread only)."""
    global preview_text, children_list, _preview_result, needs_redraw
    result = _preview_result
    if result is not None:
        _preview_result = None
        preview_text, children_list = result
        needs_redraw.add('subtickets')
        needs_redraw.add('preview')


def update_preview():
    """Request async refresh of preview_text and children_list for cursor ticket."""
    global _last_preview_id, _preview_scroll, _preview_gen, _preview_req
    global _preview_worker_started, preview_text, children_list, needs_redraw

    vis = visible_tickets()
    if not vis or cursor < 0 or cursor >= len(vis):
        if _last_preview_id != -1:
            _last_preview_id = -1
            _preview_gen += 1
            preview_text = ''
            children_list = []
            needs_redraw.add('subtickets')
            needs_redraw.add('preview')
        return

    ticket = vis[cursor]
    tid = ticket['id']

    if tid == _last_preview_id:
        return  # already showing this ticket

    _last_preview_id = tid
    _preview_scroll = 0

    # Clear stale content immediately so the pane doesn't show the wrong ticket
    preview_text = ''
    children_list = []
    needs_redraw.add('subtickets')
    needs_redraw.add('preview')

    # Start the worker thread once
    if not _preview_worker_started:
        _preview_worker_started = True
        t = threading.Thread(target=_preview_worker, daemon=True)
        t.start()

    # Submit new request (overwrites any pending; in-flight finishes naturally)
    _preview_gen += 1
    _preview_req = (_preview_gen, tid)
    _preview_event.set()


def cursor_ticket():
    """Return the ticket dict at the current cursor position, or None."""
    vis = visible_tickets()
    if 0 <= cursor < len(vis):
        return vis[cursor]
    return None


def _cursor_id():
    """Return the ticket ID under the cursor, or None."""
    t = cursor_ticket()
    return t['id'] if t else None


def _cursor_to_id(saved_id):
    """Move cursor to the ticket with saved_id, or clamp to bounds."""
    global cursor
    if saved_id is not None:
        vis = visible_tickets()
        for i, t in enumerate(vis):
            if t['id'] == saved_id:
                cursor = i
                return
    vis = visible_tickets()
    if vis:
        cursor = min(cursor, len(vis) - 1)
    else:
        cursor = 0


def _ensure_visible_and_cursor(ticket_id):
    """Expand ancestors so ticket_id is visible, then move cursor to it."""
    global cursor, _visible_dirty
    if ticket_id is None or ticket_id <= 0:
        return
    # Expand all ancestors of ticket_id
    id_map = {t['id']: t for t in all_tickets}
    tid = ticket_id
    while True:
        t = id_map.get(tid)
        if t is None:
            break
        pid = t['parent']
        if pid == 0 or pid == tid:
            break
        p = id_map.get(pid)
        if p is not None and p.get('has_children'):
            expanded.add(pid)
        tid = pid
    _visible_dirty = True
    vis = visible_tickets()
    for i, t in enumerate(vis):
        if t['id'] == ticket_id:
            cursor = i
            return
