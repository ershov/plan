##############################################################################
# Actions — operations triggered by keybindings
##############################################################################

_KNOWN_STATUSES = [
    # Open — active (most used first)
    'in-progress', 'open', 'blocked', 'assigned', 'reviewing', 'testing',
    # Open — deferred
    'backlog', 'deferred', 'paused', 'on-hold', 'future', 'someday', 'wishlist',
    # Closed
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
        if key == '_notify':
            if g_resize_flag:
                g_resize_flag = False
                layout = layout_panes()
                row = layout['info_row']
                cols = layout['cols']
                render_full()
            continue
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
    """Status selection with fzf-style filtering."""
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

    all_statuses = _KNOWN_STATUSES + ['custom...']
    filter_query = ''
    status_cursor = 0

    def _filtered():
        if not filter_query:
            return list(all_statuses)
        q = filter_query.lower()
        return [s for s in all_statuses if q in s.lower()]

    while True:
        layout = layout_panes()
        cols, _ = term_size()
        visible = _filtered()

        # Clamp cursor
        if status_cursor >= len(visible):
            status_cursor = max(0, len(visible) - 1)

        # Render filter prompt on info row
        info_row = layout['info_row']
        if info_row > 0:
            S = '\u2500'
            move(info_row, 1)
            clear_line()
            prompt = ' status> '
            set_style(fg=11, bg=4, bold=True)
            write(prompt[:cols])
            pos = len(prompt)
            if pos < cols:
                _sb_style()
                write(filter_query[:cols - pos])
                pos += min(len(filter_query), cols - pos)
            if pos < cols:
                set_style(fg=8)
                write(S * (cols - pos))
            reset_style()

        # Render status list in the preview pane area
        top = layout['prev_top']
        height = layout['prev_height']
        for i in range(height):
            move(top + i, 1)
            clear_line()
            if i < len(visible):
                label = visible[i]
                if i == status_cursor:
                    set_style(reverse=True)
                    write(('  ' + label).ljust(cols)[:cols])
                    reset_style()
                else:
                    write('  ' + label)
        flush()

        key = read_key()
        if key == '_notify':
            if g_resize_flag:
                g_resize_flag = False
                render_full()
            continue
        if key in ('down', 'ctrl-n'):
            if visible:
                status_cursor = (status_cursor + 1) % len(visible)
        elif key in ('up', 'ctrl-p'):
            if visible:
                status_cursor = (status_cursor - 1) % len(visible)
        elif key == 'home':
            status_cursor = 0
        elif key == 'end':
            if visible:
                status_cursor = len(visible) - 1
        elif key == 'enter':
            if visible:
                break
        elif key in ('esc', 'ctrl-c'):
            needs_redraw = {'all'}
            return
        elif key == 'backspace':
            if filter_query:
                filter_query = filter_query[:-1]
                status_cursor = 0
        elif len(key) == 1 and key.isprintable():
            filter_query += key
            status_cursor = 0

    chosen = visible[status_cursor]

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
    rc = plan_edit(t['id'], recursive=recursive)
    term_resume()
    if rc != 0:
        _show_error('edit command failed (exit {})'.format(rc))
    reload()


def _do_create(relation, dest_id):
    """Insert-mode callback: create a ticket at the resolved position."""
    old_ids = {t['id'] for t in all_tickets}
    term_suspend()
    rc = plan_create(relation, dest_id)
    term_resume()
    if rc != 0:
        _show_error('create command failed (exit {})'.format(rc))
    reload()
    for t in all_tickets:
        if t['id'] not in old_ids:
            _ensure_visible_and_cursor(t['id'])
            break


def _do_create_recursive(relation, dest_id):
    """Insert-mode callback: bulk create tickets at the resolved position."""
    old_ids = {t['id'] for t in all_tickets}
    term_suspend()
    rc = plan_create(relation, dest_id, recursive=True)
    term_resume()
    if rc != 0:
        _show_error('create command failed (exit {})'.format(rc))
    reload()
    # Cursor to first new ticket
    for t in all_tickets:
        if t['id'] not in old_ids:
            _ensure_visible_and_cursor(t['id'])
            break


def _enter_insert_for_create(callback, label):
    """Common logic to enter insert mode for create/create-recursive."""
    global insert_mode, insert_pos, insert_depth, insert_callback, insert_label, needs_redraw

    vis = visible_tickets()
    if not vis:
        return
    t = cursor_ticket()
    if t is None:
        return

    insert_mode = True
    insert_pos = cursor + 1
    insert_depth = _auto_insert_depth(insert_pos, vis)
    insert_label = label
    insert_callback = callback
    needs_redraw = {'all'}


def action_create():
    """Enter insert mode to pick where the new ticket goes."""
    _enter_insert_for_create(_do_create, 'create')


def action_create_recursive():
    """Enter insert mode to pick where bulk-created tickets go."""
    _enter_insert_for_create(_do_create_recursive, 'create -r')


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
        plan_proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        plan_stdout = plan_proc.stdout.read()
        plan_stderr = plan_proc.stderr.read()
        plan_proc.wait()
        # Log the plan command
        _fake = subprocess.CompletedProcess(
            args=args, returncode=plan_proc.returncode,
            stdout=plan_stdout.decode('utf-8', errors='replace'),
            stderr=plan_stderr.decode('utf-8', errors='replace'),
        )
        _log_command(args, _fake)
        if plan_proc.returncode != 0:
            term_resume()
            _show_error(plan_stderr.decode('utf-8', errors='replace').strip()
                        or 'view command failed')
            return
        # Feed output to pager
        pager_proc = subprocess.Popen(pager, stdin=subprocess.PIPE)
        try:
            pager_proc.stdin.write(plan_stdout)
            pager_proc.stdin.close()
        except BrokenPipeError:
            pass
        pager_proc.wait()
    except Exception:
        pass
    term_resume()


def _do_move(relation, dest_id):
    """Insert-mode callback: move selected tickets to the resolved position."""
    global selected
    ids = [i for i in selected if i != 0 and i != dest_id]
    if not ids:
        return
    first_id = ids[0]
    err = plan_move(ids, relation, dest_id)
    if err:
        _show_error(err)
        return
    selected.clear()
    reload()
    _ensure_visible_and_cursor(first_id)


def action_move():
    """Enter insert mode to pick where to move selected tickets."""
    global insert_mode, insert_pos, insert_depth, insert_callback, insert_label, needs_redraw

    if not selected:
        t = cursor_ticket()
        if t is None or t['id'] == 0:
            return
        selected.add(t['id'])

    vis = visible_tickets()
    if not vis:
        return
    t = cursor_ticket()
    if t is None:
        return

    insert_mode = True
    insert_pos = cursor + 1
    insert_depth = _auto_insert_depth(insert_pos, vis)
    insert_label = 'move'
    insert_callback = _do_move
    needs_redraw = {'all'}


def action_command_log():
    """Show command log in a pager."""
    text = command_log_text()
    pager = os.environ.get('PAGER', '') or 'less'
    term_suspend()
    try:
        proc = subprocess.Popen([pager, '-R'], stdin=subprocess.PIPE)
        try:
            proc.stdin.write(text.encode('utf-8', errors='replace'))
            proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.wait()
    except Exception:
        pass
    term_resume()
    reload()


def action_help():
    """Toggle help mode — shows help text in the preview pane."""
    global help_mode, _preview_scroll, needs_redraw
    help_mode = not help_mode
    _preview_scroll = 0
    needs_redraw = needs_redraw | {'preview'}
