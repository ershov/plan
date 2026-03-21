##############################################################################
# Main Loop & Entry Point
##############################################################################


def _search_next(start, direction=1):
    """Find the next matching ticket index from start in the given direction.

    direction=1 for forward, -1 for backward. Wraps around.
    Returns the index or None if no match.
    """
    vis = visible_tickets()
    if not vis or not search_query:
        return None
    q = search_query.lower()
    n = len(vis)
    for step in range(1, n + 1):
        idx = (start + step * direction) % n
        if q in vis[idx].get('title', '').lower():
            return idx
    return None


def _search_jump_nearest():
    """Jump cursor to the nearest match from the current position (forward first)."""
    global cursor
    idx = _search_next(cursor - 1, 1)  # start before cursor so cursor itself matches
    if idx is not None:
        cursor = idx


def _handle_search_key(key):
    """Handle a keypress while in search mode."""
    global search_query, search_mode, cursor, needs_redraw

    if key == 'enter':
        # Find next match forward from current cursor
        idx = _search_next(cursor, 1)
        if idx is not None:
            cursor = idx
            needs_redraw = needs_redraw | {'list'}
            update_preview()

    elif key in ('shift-enter', 'alt-enter'):
        # Find previous match backward from current cursor
        idx = _search_next(cursor, -1)
        if idx is not None:
            cursor = idx
            needs_redraw = needs_redraw | {'list'}
            update_preview()

    elif key in ('esc', 'ctrl-c'):
        search_mode = False
        needs_redraw = needs_redraw | {'list', 'info'}

    elif key == 'backspace':
        if search_query:
            search_query = search_query[:-1]
            if search_query:
                _search_jump_nearest()
            needs_redraw = needs_redraw | {'list', 'info'}
            update_preview()
        else:
            search_mode = False
            needs_redraw = needs_redraw | {'list', 'info'}

    elif len(key) == 1 and key.isprintable():
        search_query += key
        _search_jump_nearest()
        needs_redraw = needs_redraw | {'list', 'info'}
        update_preview()


def _handle_normal_key(key):
    """Handle a keypress in normal mode."""
    global cursor, scope, expanded, selected, search_mode, search_query
    global needs_redraw, _visible_dirty, show_preview, _preview_scroll, help_mode, error_text

    # Async preview load completed — consume result on main thread
    if key == '_notify':
        apply_preview_result()
        return None

    # Error mode: scrollable, any non-scroll key dismisses
    if error_text and key not in ('shift-up', 'shift-down', 'space', 'b'):
        error_text = ''
        _preview_scroll = 0
        needs_redraw = needs_redraw | {'preview'}
        return None

    # In help mode, shift-up/down scroll help; ? toggles off; anything else exits
    if help_mode and key not in ('shift-up', 'shift-down', 'space', 'b', '?', 'f1', 'ctrl-p'):
        help_mode = False
        _preview_scroll = 0
        needs_redraw = needs_redraw | {'preview'}
        return None

    vis = visible_tickets()
    max_idx = len(vis) - 1 if vis else 0

    if key in ('j', 'down'):
        if cursor < max_idx:
            cursor += 1
        needs_redraw = needs_redraw | {'list'}
        update_preview()

    elif key in ('k', 'up'):
        if cursor > 0:
            cursor -= 1
        needs_redraw = needs_redraw | {'list'}
        update_preview()

    elif key in ('g', 'home'):
        cursor = 0
        needs_redraw = needs_redraw | {'list'}
        update_preview()

    elif key in ('G', 'end'):
        cursor = max_idx
        needs_redraw = needs_redraw | {'list'}
        update_preview()

    elif key == 'pgup':
        layout = layout_panes()
        page_size = layout['list_height']
        cursor = max(0, cursor - page_size)
        needs_redraw = needs_redraw | {'list'}
        update_preview()

    elif key == 'pgdn':
        layout = layout_panes()
        page_size = layout['list_height']
        cursor = min(max_idx, cursor + page_size)
        needs_redraw = needs_redraw | {'list'}
        update_preview()

    elif key == 'enter':
        t = cursor_ticket()
        if t is not None and t.get('has_children'):
            saved = _cursor_id()
            tid = t['id']
            if tid in expanded:
                expanded.discard(tid)
            else:
                expanded.add(tid)
            _visible_dirty = True
            _cursor_to_id(saved)
            needs_redraw = needs_redraw | {'list'}
            update_preview()

    elif key == 'right':
        # Expand one node
        t = cursor_ticket()
        if t is not None and t.get('has_children') and t['id'] not in expanded:
            saved = _cursor_id()
            expanded.add(t['id'])
            _visible_dirty = True
            _cursor_to_id(saved)
            needs_redraw = needs_redraw | {'list'}
            update_preview()

    elif key == 'left':
        # Collapse one node, or move to parent if already collapsed / no children
        t = cursor_ticket()
        if t is not None and t['id'] in expanded:
            saved = _cursor_id()
            expanded.discard(t['id'])
            _visible_dirty = True
            _cursor_to_id(saved)
            needs_redraw = needs_redraw | {'list'}
            update_preview()
        elif t is not None and t['id'] != 0:
            # Move cursor to parent in visible list
            parent_id = t['parent']
            if parent_id is not None:
                vis = visible_tickets()
                for i, vt in enumerate(vis):
                    if vt['id'] == parent_id:
                        cursor = i
                        needs_redraw = needs_redraw | {'list'}
                        update_preview()
                        break

    elif key == 'alt-right':
        # Expand recursively: all siblings at cursor's level (and their descendants)
        # On Project (id=0): expand everything
        t = cursor_ticket()
        if t is not None:
            saved = _cursor_id()
            if t['id'] == 0:
                for tk in all_tickets:
                    if tk.get('has_children'):
                        expanded.add(tk['id'])
            else:
                parent_id = t['parent']
                def _expand_tree(tid):
                    expanded.add(tid)
                    for tk in all_tickets:
                        if tk['parent'] == tid and tk.get('has_children'):
                            _expand_tree(tk['id'])
                for tk in all_tickets:
                    if tk['parent'] == parent_id and tk.get('has_children'):
                        _expand_tree(tk['id'])
            _visible_dirty = True
            _cursor_to_id(saved)
            needs_redraw = {'all'}
            update_preview()

    elif key == 'alt-left':
        # Collapse recursively: all siblings at cursor's level (and their descendants)
        # On Project (id=0): collapse everything
        t = cursor_ticket()
        if t is not None:
            saved = _cursor_id()
            if t['id'] == 0:
                expanded.clear()
            else:
                parent_id = t['parent']
                to_collapse = set()
                def _collect_tree(tid):
                    to_collapse.add(tid)
                    for tk in all_tickets:
                        if tk['parent'] == tid:
                            _collect_tree(tk['id'])
                for tk in all_tickets:
                    if tk['parent'] == parent_id:
                        _collect_tree(tk['id'])
                expanded -= to_collapse
            _visible_dirty = True
            _cursor_to_id(saved)
            needs_redraw = {'all'}
            update_preview()

    elif key == 'alt-down':
        # Scope down into ticket
        t = cursor_ticket()
        if t is not None and t['id'] > 0:
            scope = t['id']
            cursor = 0
            expanded.clear()
            _visible_dirty = True
            reload()

    elif key == 'alt-up':
        # Scope up to parent — cursor stays on the ticket we're leaving
        if scope is not None:
            old_scope = scope
            parent_id = None
            for t in all_tickets:
                if t['id'] == scope:
                    parent_id = t['parent']
                    break
            if parent_id is None or parent_id == 0:
                scope = None
            else:
                scope = parent_id
            cursor = 0
            expanded.clear()
            _visible_dirty = True
            reload()
            _cursor_to_id(old_scope)

    elif key == 'ctrl-p':
        # Toggle preview pane
        show_preview = not show_preview
        needs_redraw = {'all'}

    elif key == 'shift-down':
        # Scroll preview pane down (works for ticket preview and help)
        lines = _preview_lines()
        layout = layout_panes()
        content_lines = max(0, layout['prev_height'] - 1)
        max_scroll = max(0, len(lines) - content_lines)
        if _preview_scroll < max_scroll:
            _preview_scroll += 1
            needs_redraw = needs_redraw | {'preview'}

    elif key == 'shift-up':
        # Scroll preview pane up (works for ticket preview and help)
        if _preview_scroll > 0:
            _preview_scroll -= 1
            needs_redraw = needs_redraw | {'preview'}

    elif key == 'space':
        # Scroll preview one page down
        lines = _preview_lines()
        layout = layout_panes()
        content_lines = max(1, layout['prev_height'] - 1)
        max_scroll = max(0, len(lines) - content_lines)
        _preview_scroll = min(max_scroll, _preview_scroll + content_lines)
        needs_redraw = needs_redraw | {'preview'}

    elif key == 'b':
        # Scroll preview one page up
        layout = layout_panes()
        content_lines = max(1, layout['prev_height'] - 1)
        _preview_scroll = max(0, _preview_scroll - content_lines)
        needs_redraw = needs_redraw | {'preview'}

    elif key == '/':
        search_mode = True
        search_query = ''
        needs_redraw = needs_redraw | {'info'}

    elif key == 'tab':
        t = cursor_ticket()
        if t is not None and t['id'] != 0:
            tid = t['id']
            if tid in selected:
                selected.discard(tid)
            else:
                selected.add(tid)
            # Move cursor down
            if cursor < max_idx:
                cursor += 1
            needs_redraw = needs_redraw | {'list', 'info'}

    elif key == 'btab':
        t = cursor_ticket()
        if t is not None and t['id'] != 0:
            tid = t['id']
            if tid in selected:
                selected.discard(tid)
            else:
                selected.add(tid)
            # Move cursor up
            if cursor > 0:
                cursor -= 1
            needs_redraw = needs_redraw | {'list', 'info'}

    elif key == 'ctrl-a':
        for t in vis:
            if t['id'] != 0:
                selected.add(t['id'])
        needs_redraw = needs_redraw | {'list', 'info'}

    elif key == 'ctrl-n':
        selected.clear()
        needs_redraw = needs_redraw | {'list', 'info'}

    elif key == 's':
        action_status()

    elif key == 'c':
        action_close()

    elif key == 'o':
        action_reopen()

    elif key == 'e':
        action_edit()

    elif key == 'E':
        action_edit(recursive=True)

    elif key == 'n':
        action_create()

    elif key == 'm':
        action_move()

    elif key == 'v':
        action_view()

    elif key == 'V':
        action_view(recursive=True)

    elif key in ('?', 'f1'):
        action_help()

    elif key == 'q':
        return 'quit'

    elif key in ('esc', 'ctrl-c'):
        # Esc/Ctrl-C: cancel current mode first, then quit
        if help_mode:
            help_mode = False
            _preview_scroll = 0
            needs_redraw = needs_redraw | {'preview'}
        elif selected:
            selected.clear()
            needs_redraw = needs_redraw | {'list', 'info'}
        else:
            return 'quit'

    elif key == 'ctrl-l':
        cache_invalidate()
        reload()
        needs_redraw = {'all'}

    return None


def main(initial_scope):
    global scope, cursor, expanded, selected, search_query, search_mode, needs_redraw
    global g_resize_flag

    scope = initial_scope
    reload()
    render_full()

    while True:
        key = read_key()

        # Check resize flag
        if g_resize_flag:
            g_resize_flag = False
            needs_redraw = {'all'}

        if search_mode:
            _handle_search_key(key)
        else:
            result = _handle_normal_key(key)
            if result == 'quit':
                return

        # Check resize flag again (might have been set during key handling)
        if g_resize_flag:
            g_resize_flag = False
            needs_redraw = {'all'}

        if needs_redraw:
            render_partial()


if __name__ == '__main__':
    if not sys.stdin.isatty():
        sys.exit('plan-tui requires a terminal')
    # Parse arguments: optional -f/--file and optional ticket ID for initial scope
    _initial_scope = None
    _args = sys.argv[1:]
    while _args:
        if _args[0] in ('-f', '--file'):
            if len(_args) < 2:
                sys.exit('-f/--file requires an argument')
            os.environ['PLAN_MD'] = _args[1]
            _args = _args[2:]
        elif _args[0] in ('-h', '--help'):
            print('Usage: plan-tui [-f FILE] [TICKET_ID]')
            sys.exit(0)
        elif _args[0].isdigit():
            _initial_scope = int(_args[0])
            _args = _args[1:]
        else:
            sys.exit('Unknown argument: {}'.format(_args[0]))
    try:
        term_init()
        main(_initial_scope)
    finally:
        term_restore()
