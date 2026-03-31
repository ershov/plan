##############################################################################
# Main Loop & Entry Point
##############################################################################


def _search_text(ticket):
    """Return the searchable text for a ticket (matches visible list format)."""
    tid = ticket['id']
    if tid == 0:
        return 'Project'
    return '#{} [{}] {}'.format(tid, ticket['status'], ticket['title'])


def _search_matches(text):
    """Check if all space-separated search fragments match text (case-insensitive)."""
    if not search_query:
        return False
    frags = search_query.lower().split()
    if not frags:
        return False
    low = text.lower()
    return all(f in low for f in frags)


def _search_next(start, direction=1):
    """Find the next matching ticket index from start in the given direction.

    direction=1 for forward, -1 for backward. Wraps around.
    Returns the index or None if no match.
    """
    vis = visible_tickets()
    if not vis or not search_query:
        return None
    n = len(vis)
    for step in range(1, n + 1):
        idx = (start + step * direction) % n
        if _search_matches(_search_text(vis[idx])):
            return idx
    return None


def _search_jump_nearest():
    """Jump cursor to the nearest match from the current position (forward first)."""
    global cursor
    idx = _search_next(cursor - 1, 1)  # start before cursor so cursor itself matches
    if idx is not None:
        cursor = idx


def _auto_insert_depth(pos, vis):
    """Compute the natural depth for an insertion marker at gap position pos."""
    if not vis:
        return 0
    if pos <= 0:
        return vis[0]['depth'] if vis else 0
    above = vis[pos - 1]
    if pos < len(vis):
        below = vis[pos]
        if below['depth'] > above['depth']:
            return below['depth']
    return above['depth']


def _resolve_insert(pos, depth, vis):
    """Convert insert position + depth into (relation, dest_id) for plan command.

    Returns (relation, dest_id) or (None, None) if invalid.
    """
    if not vis or pos <= 0:
        return (None, None)

    above = vis[pos - 1]

    # Can't reference synthetic Project entry
    if above['id'] == 0:
        if pos < len(vis):
            return ('before', vis[pos]['id'])
        return (None, None)

    if depth > above['depth']:
        # Inserting as child of above
        return ('first', above['id'])
    elif depth == above['depth']:
        # Inserting as sibling after above
        return ('after', above['id'])
    else:
        # Walk up parent chain to find ancestor at the target depth
        id_map = {t['id']: t for t in all_tickets}
        cur = above
        while cur['depth'] > depth:
            parent = id_map.get(cur['parent'])
            if parent is None:
                break
            cur = parent
        return ('after', cur['id'])


def _handle_insert_key(key):
    """Handle a keypress while in insert mode."""
    global insert_mode, insert_pos, insert_depth, insert_callback, needs_redraw, _visible_dirty

    vis = visible_tickets()
    max_pos = len(vis)  # valid positions: 1..max_pos
    min_pos = 1  # skip Project/scope entry at position 0

    if key in ('j', 'down'):
        if insert_pos < max_pos:
            insert_pos += 1
            insert_depth = _auto_insert_depth(insert_pos, vis)
            needs_redraw = needs_redraw | {'list'}

    elif key in ('k', 'up'):
        if insert_pos > min_pos:
            insert_pos -= 1
            insert_depth = _auto_insert_depth(insert_pos, vis)
            needs_redraw = needs_redraw | {'list'}

    elif key in ('g', 'home'):
        insert_pos = min_pos
        insert_depth = _auto_insert_depth(insert_pos, vis)
        needs_redraw = needs_redraw | {'list'}

    elif key in ('G', 'end'):
        insert_pos = max_pos
        insert_depth = _auto_insert_depth(insert_pos, vis)
        needs_redraw = needs_redraw | {'list'}

    elif key == 'pgdn':
        layout = layout_panes()
        page_size = layout['list_height']
        insert_pos = min(max_pos, insert_pos + page_size)
        insert_depth = _auto_insert_depth(insert_pos, vis)
        needs_redraw = needs_redraw | {'list'}

    elif key == 'pgup':
        layout = layout_panes()
        page_size = layout['list_height']
        insert_pos = max(min_pos, insert_pos - page_size)
        insert_depth = _auto_insert_depth(insert_pos, vis)
        needs_redraw = needs_redraw | {'list'}

    elif key == 'right':
        # Indent: make it a child of the entry above
        # If above has children, expand it so they become visible
        if insert_pos > 0 and insert_pos <= len(vis):
            above = vis[insert_pos - 1]
            if above['id'] != 0 and insert_depth <= above['depth']:
                if above.get('has_children') and above['id'] not in expanded:
                    expanded.add(above['id'])
                    _visible_dirty = True
                    # Refresh vis — children are now visible after above
                    vis = visible_tickets()
                    max_pos = len(vis)
                    # Find where above is in the new list and position after it
                    for idx in range(len(vis)):
                        if vis[idx]['id'] == above['id']:
                            insert_pos = idx + 1
                            break
                insert_depth = above['depth'] + 1
                needs_redraw = {'all'}

    elif key == 'left':
        # First: if the entry right after the marker is at the same depth,
        # has children, and is expanded — just collapse it (like nav mode)
        if insert_pos < len(vis):
            after = vis[insert_pos]
            if (after['depth'] == insert_depth
                    and after.get('has_children')
                    and after['id'] in expanded):
                expanded.discard(after['id'])
                _visible_dirty = True
                vis = visible_tickets()
                needs_redraw = {'all'}
                return

        # Otherwise: outdent and move marker before the parent
        # If already at the last-child position, stay there (after subtree)
        base = 0
        if scope is not None:
            for t in all_tickets:
                if t['id'] == scope:
                    base = t['depth'] + 1
                    break
        if insert_depth > base:
            new_depth = insert_depth - 1
            # Find the parent entry at new_depth by walking up
            parent_idx = None
            for p in range(insert_pos - 1, -1, -1):
                if vis[p]['depth'] == new_depth:
                    parent_idx = p
                    break
                if vis[p]['depth'] < new_depth:
                    break
            if parent_idx is not None:
                # Check: is the marker already after all children of this parent?
                # i.e., is there no entry at insert_depth between marker and parent?
                after_last_child = True
                for s in range(insert_pos, len(vis)):
                    if vis[s]['depth'] <= new_depth:
                        break
                    if vis[s]['depth'] == insert_depth:
                        after_last_child = False
                        break
                if after_last_child:
                    # Already after last child — find end of parent's subtree
                    sub_end = parent_idx + 1
                    for s in range(parent_idx + 1, len(vis)):
                        if vis[s]['depth'] > new_depth:
                            sub_end = s + 1
                        else:
                            break
                    insert_pos = sub_end
                else:
                    # Go before the parent
                    insert_pos = parent_idx
            insert_depth = new_depth
            needs_redraw = needs_redraw | {'list'}

    elif key == 'enter':
        # Confirm insertion
        relation, dest_id = _resolve_insert(insert_pos, insert_depth, vis)
        cb = insert_callback
        insert_mode = False
        insert_callback = None
        needs_redraw = {'all'}
        if relation and dest_id and cb:
            cb(relation, dest_id)

    elif key in ('esc', 'ctrl-c', 'q'):
        # Cancel
        insert_mode = False
        insert_callback = None
        needs_redraw = {'all'}

    elif key == '_notify':
        apply_preview_result()

    else:
        # Pass unhandled keys (Alt-arrows, Ctrl-P, Shift-arrows, etc.) to normal handler
        result = _handle_normal_key(key)
        # Visible list may have changed (e.g. collapse) — clamp insert_pos
        vis = visible_tickets()
        if insert_pos > len(vis):
            insert_pos = max(1, len(vis))
            insert_depth = _auto_insert_depth(insert_pos, vis)
            needs_redraw = needs_redraw | {'list'}
        return result

    return None


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

    elif key == 'space' or (len(key) == 1 and key.isprintable()):
        search_query += ' ' if key == 'space' else key
        _search_jump_nearest()
        needs_redraw = needs_redraw | {'list', 'info'}
        update_preview()

    else:
        # Pass non-printable keys (arrows, ctrl-*, alt-*, etc.) to normal handler
        return _handle_normal_key(key)

    return None


def _handle_normal_key(key):
    """Handle a keypress in normal mode."""
    global cursor, scope, expanded, selected, search_mode, search_query
    global needs_redraw, _visible_dirty, show_preview, _preview_scroll, help_mode, error_text
    global _scroll_offset

    # Async preview load completed — consume result on main thread
    if key == '_notify':
        apply_preview_result()
        return None

    # Silently ignore unhandled mouse events (button release, right-click, etc.)
    if key == '_mouse':
        return None

    _is_scroll = key.startswith('scroll-')

    # Error mode: scrollable, any non-scroll/mouse key dismisses
    if error_text and key not in ('shift-up', 'shift-down', 'alt-pgup', 'alt-pgdn') and not _is_scroll:
        error_text = ''
        _preview_scroll = 0
        needs_redraw = needs_redraw | {'preview'}
        return None

    # In help mode, shift-up/down scroll help; ? toggles off; anything else exits
    if help_mode and key not in ('shift-up', 'shift-down', 'alt-pgup', 'alt-pgdn', '?', 'f1', 'ctrl-p') and not _is_scroll:
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
            # Save expanded state for current scope
            scope_key = scope  # None for root
            _expanded_by_scope[scope_key] = set(expanded)
            scope = t['id']
            cursor = 0
            expanded.clear()
            expanded.update(_expanded_by_scope.get(scope, ()))
            _visible_dirty = True
            reload()

    elif key == 'alt-up':
        # Scope up to parent — cursor stays on the ticket we're leaving
        if scope is not None:
            old_scope = scope
            # Save expanded state for current scope
            _expanded_by_scope[scope] = set(expanded)
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
            expanded.update(_expanded_by_scope.get(scope, ()))
            _visible_dirty = True
            reload()
            _cursor_to_id(old_scope)

    elif key == 'ctrl-p':
        # Toggle preview pane
        show_preview = not show_preview
        needs_redraw = {'all'}
        if show_preview:
            update_preview()

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
        # Toggle select and move cursor down
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

    elif key == 'alt-pgdn':
        # Scroll preview one page down
        lines = _preview_lines()
        layout = layout_panes()
        content_lines = max(1, layout['prev_height'] - 1)
        max_scroll = max(0, len(lines) - content_lines)
        _preview_scroll = min(max_scroll, _preview_scroll + content_lines)
        needs_redraw = needs_redraw | {'preview'}

    elif key == 'alt-pgup':
        # Scroll preview one page up
        layout = layout_panes()
        content_lines = max(1, layout['prev_height'] - 1)
        _preview_scroll = max(0, _preview_scroll - content_lines)
        needs_redraw = needs_redraw | {'preview'}

    elif key.startswith('mouse-click:'):
        # Click on list item to select it
        parts = key.split(':')
        row = int(parts[1])
        layout = layout_panes()
        lt, lh = layout['list_top'], layout['list_height']
        if lt <= row < lt + lh:
            vis_idx = _scroll_offset + (row - lt)
            vis = visible_tickets()
            if 0 <= vis_idx < len(vis):
                cursor = vis_idx
                needs_redraw = needs_redraw | {'list'}
                update_preview()

    elif key.startswith('scroll-up:'):
        parts = key.split(':')
        row = int(parts[1])
        layout = layout_panes()
        if row > layout['prev_top']:
            # Over preview: scroll preview up
            if _preview_scroll > 0:
                _preview_scroll = max(0, _preview_scroll - 3)
                needs_redraw = needs_redraw | {'preview'}
        else:
            # Over list (or subtickets): scroll viewport up
            if _scroll_offset > 0:
                _scroll_offset = max(0, _scroll_offset - 3)
                # Clamp cursor into visible range
                old_cursor = cursor
                if cursor >= _scroll_offset + layout['list_height']:
                    cursor = _scroll_offset + layout['list_height'] - 1
                needs_redraw = needs_redraw | {'list'}
                if cursor != old_cursor:
                    update_preview()

    elif key.startswith('scroll-down:'):
        parts = key.split(':')
        row = int(parts[1])
        layout = layout_panes()
        if row > layout['prev_top']:
            # Over preview: scroll preview down
            lines = _preview_lines()
            content_lines = max(0, layout['prev_height'] - 1)
            max_scroll = max(0, len(lines) - content_lines)
            if _preview_scroll < max_scroll:
                _preview_scroll = min(max_scroll, _preview_scroll + 3)
                needs_redraw = needs_redraw | {'preview'}
        else:
            # Over list (or subtickets): scroll viewport down
            vis = visible_tickets()
            max_offset = max(0, len(vis) - layout['list_height'])
            if _scroll_offset < max_offset:
                _scroll_offset = min(max_offset, _scroll_offset + 3)
                # Clamp cursor into visible range
                old_cursor = cursor
                if cursor < _scroll_offset:
                    cursor = _scroll_offset
                needs_redraw = needs_redraw | {'list'}
                if cursor != old_cursor:
                    update_preview()

    elif key == '/':
        search_mode = True
        search_query = ''
        needs_redraw = needs_redraw | {'info'}

    elif key == 'alt- ':
        # Toggle select and move cursor up
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

    elif key == 'e':
        action_edit()

    elif key == 'E':
        action_edit(recursive=True)

    elif key == 'c':
        action_create()

    elif key == 'C':
        action_create_recursive()

    elif key == 'm':
        action_move()

    elif key == 'v':
        action_view()

    elif key == 'V':
        action_view(recursive=True)

    elif key == '~':
        action_command_log()

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
        # Reset terminal and redraw without reloading data
        write('\033[!p')  # soft terminal reset (DECSTR)
        _enter_raw()
        needs_redraw = {'all'}

    elif key == 'ctrl-r':
        cache_invalidate()
        reload()

    return None


def main(initial_scope):
    global scope, cursor, expanded, selected, search_query, search_mode, needs_redraw
    global g_resize_flag

    scope = initial_scope
    reload()
    if _last_list_error:
        sys.exit(_last_list_error)
    render_full()

    while True:
        key = read_key()

        # Check resize flag
        if g_resize_flag:
            g_resize_flag = False
            needs_redraw = {'all'}

        if insert_mode:
            result = _handle_insert_key(key)
            if result == 'quit':
                return
        elif search_mode:
            result = _handle_search_key(key)
            if result == 'quit':
                return
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


_USAGE_TEXT = """\
Usage: plan-tui [-f FILE] [TICKET_ID]

  Browse and manage plan tickets in a terminal UI.

Options:
  -f, --file FILE    Use a specific plan file
  TICKET_ID          Start with scope set to this ticket
  -h, --help, help   Show this help

"""

def _show_help_and_exit():
    """Print full help (usage + hotkeys) through a pager and exit."""
    text = _USAGE_TEXT + _HELP_TEXT + '\n'
    pager = os.environ.get('PAGER', '') or 'less'
    try:
        proc = subprocess.Popen([pager], stdin=subprocess.PIPE)
        try:
            proc.stdin.write(text.encode('utf-8', errors='replace'))
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.wait()
    except Exception:
        sys.stdout.write(text)
    sys.exit(0)


if __name__ == '__main__':
    if not sys.stdin.isatty():
        sys.exit('plan-tui requires a terminal')
    _initial_scope = None
    _args = sys.argv[1:]
    while _args:
        if _args[0] in ('-f', '--file'):
            if len(_args) < 2:
                sys.exit('-f/--file requires an argument')
            os.environ['PLAN_MD'] = _args[1]
            _args = _args[2:]
        elif _args[0] in ('-h', '--help', 'h', 'help'):
            _show_help_and_exit()
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
