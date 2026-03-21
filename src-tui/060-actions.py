##############################################################################
# Actions — operations triggered by keybindings
##############################################################################

_KNOWN_STATUSES = [
    'open', 'in-progress', 'assigned', 'blocked', 'reviewing', 'testing',
    'backlog', 'deferred', 'future', 'someday', 'wishlist', 'paused', 'on-hold',
    'done', 'wontfix',
]


def _show_error(err):
    """Show error text in the preview pane. Cleared on next keypress."""
    global error_text, _preview_scroll, needs_redraw
    error_text = err
    _preview_scroll = 0
    needs_redraw = needs_redraw | {'preview'}


def _status_bar_message(msg):
    """Show an action prompt on the info separator — bold yellow on blue, rest separator."""
    layout = layout_panes()
    row = layout['info_row']
    cols = layout['cols']
    if row <= 0:
        return
    S = '\u2500'
    move(row, 1)
    clear_line()
    set_style(fg=11, bg=4, bold=True)
    write(msg[:cols])
    pos = len(msg)
    if pos < cols:
        set_style(fg=8)
        write(S * (cols - pos))
    reset_style()
    flush()


def _read_string(prompt):
    """Read a string from the user on the info separator. Returns string or None if cancelled."""
    buf = ''
    layout = layout_panes()
    row = layout['info_row']
    cols = layout['cols']
    if row <= 0:
        return None
    S = '\u2500'
    while True:
        move(row, 1)
        clear_line()
        # Prompt in bold yellow on blue
        set_style(fg=11, bg=4, bold=True)
        write(prompt[:cols])
        pos = len(prompt)
        # Input in normal text
        if pos < cols:
            _sb_style()
            remaining = cols - pos
            write(buf[:remaining])
            pos += min(len(buf), remaining)
        # Fill rest with separator
        if pos < cols:
            set_style(fg=8)
            write(S * (cols - pos))
        reset_style()
        flush()

        key = read_key()
        if key == 'enter':
            return buf
        elif key in ('esc', 'ctrl-c'):
            return None
        elif key == 'backspace':
            if buf:
                buf = buf[:-1]
        elif len(key) == 1 and key.isprintable():
            buf += key


def action_close():
    """Close selected tickets, or cursor ticket if nothing selected."""
    global selected, needs_redraw
    if selected:
        ids = list(selected)
    else:
        t = cursor_ticket()
        if t is None:
            return
        ids = [t['id']]
    ids = [i for i in ids if i != 0]
    if not ids:
        return
    err = plan_close(ids)
    if err:
        _show_error(err)
        return
    selected.discard(0)
    reload()


def action_reopen():
    """Reopen selected tickets, or cursor ticket if nothing selected."""
    global selected, needs_redraw
    if selected:
        ids = list(selected)
    else:
        t = cursor_ticket()
        if t is None:
            return
        ids = [t['id']]
    ids = [i for i in ids if i != 0]
    if not ids:
        return
    err = plan_reopen(ids)
    if err:
        _show_error(err)
        return
    reload()


def action_status():
    """Status selection mini-mode."""
    global needs_redraw

    # Determine affected ids
    if selected:
        ids = [i for i in selected if i != 0]
    else:
        t = cursor_ticket()
        if t is None:
            return
        ids = [t['id']]
        ids = [i for i in ids if i != 0]
    if not ids:
        return

    status_list = _KNOWN_STATUSES + ['custom...']
    status_cursor = 0
    layout = layout_panes()
    cols, _ = term_size()

    while True:
        # Render status list in the preview pane area
        top = layout['prev_top']
        height = layout['prev_height']
        for i in range(height):
            move(top + i, 1)
            clear_line()
            idx = i
            if idx < len(status_list):
                label = status_list[idx]
                if idx == status_cursor:
                    set_style(reverse=True)
                    write(('  ' + label).ljust(cols)[:cols])
                    reset_style()
                else:
                    write('  ' + label)
            # else: blank line already cleared
        flush()

        key = read_key()
        if key in ('j', 'down'):
            if status_cursor < len(status_list) - 1:
                status_cursor += 1
        elif key in ('k', 'up'):
            if status_cursor > 0:
                status_cursor -= 1
        elif key in ('g', 'home'):
            status_cursor = 0
        elif key in ('G', 'end'):
            status_cursor = len(status_list) - 1
        elif key == 'enter':
            break
        elif key in ('esc', 'ctrl-c'):
            needs_redraw = {'all'}
            return

    chosen = status_list[status_cursor]

    if chosen == 'custom...':
        chosen = _read_string('Status: ')
        if chosen is None or chosen.strip() == '':
            needs_redraw = {'all'}
            return
        chosen = chosen.strip()

    err = plan_status(ids, chosen)
    if err:
        _show_error(err)
        return
    reload()


def action_edit(recursive=False):
    """Edit the ticket under cursor."""
    t = cursor_ticket()
    if t is None:
        return
    term_suspend()
    plan_edit(t['id'], recursive=recursive)
    term_resume()
    reload()


def action_create():
    """Create a new ticket with position prompt."""
    global needs_redraw

    _status_bar_message('Create: \u2191before \u2193after \u2190first child \u2192last child  (Esc cancel)')

    key = read_key()
    if key in ('esc', 'ctrl-c'):
        needs_redraw = {'all'}
        return
    mode_map = {
        'up': 'before', 'i': 'before', 'k': 'before',
        'down': 'after', 'a': 'after', 'j': 'after',
        'left': 'first', 'I': 'first',
        'right': 'last', 'A': 'last',
    }
    mode = mode_map.get(key)
    if mode is None:
        needs_redraw = {'all'}
        return

    t = cursor_ticket()
    if t is None:
        needs_redraw = {'all'}
        return
    cursor_id = t['id']
    if cursor_id == 0:
        # Try to use first real ticket
        vis = visible_tickets()
        found = False
        for vt in vis:
            if vt['id'] != 0:
                cursor_id = vt['id']
                found = True
                break
        if not found:
            needs_redraw = {'all'}
            return

    term_suspend()
    plan_create(mode, cursor_id)
    term_resume()
    reload()


def action_view(recursive=False):
    """View ticket in a pager."""
    t = cursor_ticket()
    if t is None:
        return
    tid = t['id']

    # Build plan command for getting text
    if tid == 0:
        args = [PLAN_BIN, 'project', 'get']
    else:
        args = [PLAN_BIN, str(tid), 'get']
        if recursive:
            args = [PLAN_BIN, str(tid), '-r', 'get']

    # Detect pager
    pager = None
    for candidate in ('batcat', 'bat'):
        path = shutil.which(candidate)
        if path:
            pager = [path, '--language=md', '--style=plain', '--paging=always']
            break
    if pager is None:
        env_pager = os.environ.get('PAGER', '')
        if env_pager:
            pager = [env_pager]
        else:
            pager = ['less']

    term_suspend()
    try:
        plan_proc = subprocess.Popen(args, stdout=subprocess.PIPE)
        pager_proc = subprocess.Popen(pager, stdin=plan_proc.stdout)
        plan_proc.stdout.close()
        pager_proc.wait()
        plan_proc.wait()
    except Exception:
        pass
    term_resume()


def action_move():
    """Move selected tickets relative to cursor."""
    global selected, needs_redraw

    if not selected:
        _status_bar_message('Select tickets to move first')
        read_key()
        needs_redraw = {'all'}
        return

    t = cursor_ticket()
    if t is None or t['id'] == 0:
        _status_bar_message('Move cursor to a destination ticket')
        read_key()
        needs_redraw = {'all'}
        return
    dest_id = t['id']

    _status_bar_message('Move: \u2191before \u2193after \u2190first child \u2192last child  (Esc cancel)')

    key = read_key()
    if key in ('esc', 'ctrl-c'):
        needs_redraw = {'all'}
        return
    relation_map = {
        'up': 'before', 'i': 'before',
        'down': 'after', 'a': 'after',
        'left': 'first', 'I': 'first',
        'right': 'last', 'A': 'last',
    }
    relation = relation_map.get(key)
    if relation is None:
        needs_redraw = {'all'}
        return

    ids = [i for i in selected if i != 0 and i != dest_id]
    if not ids:
        needs_redraw = {'all'}
        return

    err = plan_move(ids, relation, dest_id)
    if err:
        _show_error(err)
        return
    selected.clear()
    reload()


def action_help():
    """Toggle help mode — shows help text in the preview pane."""
    global help_mode, _preview_scroll, needs_redraw
    help_mode = not help_mode
    _preview_scroll = 0
    needs_redraw = needs_redraw | {'preview'}
