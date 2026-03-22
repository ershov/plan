##############################################################################
# Rendering — three panes + status bar, cursor-addressed writes
##############################################################################

_scroll_offset = 0  # scroll offset for list pane


def layout_panes():
    """Calculate pane positions. Returns dict with geometry for all panes."""
    cols, rows = term_size()

    available = rows  # all rows for panes (no dedicated status bar)

    # List pane: 30% of screen
    list_height = max(1, int(available * 0.30))
    list_top = 1

    if not show_preview:
        # Preview hidden — list gets all available space, no sub/preview panes
        list_height = available
        return {
            'list_top': list_top,
            'list_height': list_height,
            'sub_top': list_top + list_height,
            'sub_height': 0,
            'prev_top': list_top + list_height,
            'prev_height': 0,
            'info_row': 0,
            'cols': cols,
        }

    # Subtickets pane: up to 30% of available, shrinks to fit children_list
    if rows < 20:
        # Too small — hide subtickets entirely
        sub_height = 0
    else:
        sub_max = max(1, int(available * 0.30))
        # Multi-column layout: compute rows needed given terminal width
        content_rows = _sub_needed_rows(cols) if children_list else 0
        needed = 1 + content_rows if content_rows > 0 else 0  # +1 for separator
        sub_height = min(sub_max, needed) if needed > 0 else 0

    sub_top = list_top + list_height

    # Preview pane gets the remainder
    prev_top = sub_top + sub_height
    prev_height = available - list_height - sub_height
    if prev_height < 0:
        prev_height = 0

    # Info row = first separator after list (children or preview)
    info_row = sub_top if sub_height > 0 else (prev_top if prev_height > 0 else 0)

    return {
        'list_top': list_top,
        'list_height': list_height,
        'sub_top': sub_top,
        'sub_height': sub_height,
        'prev_top': prev_top,
        'prev_height': prev_height,
        'info_row': info_row,
        'cols': cols,
    }


def render_list(top, height, cols):
    """Render the list pane."""
    global _scroll_offset

    visible = visible_tickets()
    cursor_pos = cursor

    # In insert mode, inject the "-- here --" marker into the display list
    if insert_mode:
        marker = {
            'id': -1, 'parent': 0, 'status': '',
            'has_children': False, 'depth': insert_depth,
            'title': ' -- {} -- '.format(insert_label or 'here'),
        }
        visible = list(visible)  # copy to avoid mutating cache
        visible.insert(insert_pos, marker)
        cursor_pos = insert_pos

    # Adjust scroll offset to keep cursor visible
    if cursor_pos < _scroll_offset:
        _scroll_offset = cursor_pos
    if cursor_pos >= _scroll_offset + height:
        _scroll_offset = cursor_pos - height + 1
    if _scroll_offset < 0:
        _scroll_offset = 0

    # Determine base depth for indentation relative to scope
    if scope is not None:
        # In scoped view, the scope ticket is first and its depth is the base
        base_depth = visible[0]['depth'] if visible else 0
    else:
        # Root view: Project entry is depth 0, real tickets have their own depth
        base_depth = 0

    for row_idx in range(height):
        vis_idx = _scroll_offset + row_idx
        move(top + row_idx, 1)
        clear_line()

        if vis_idx >= len(visible):
            # Blank line
            continue

        ticket = visible[vis_idx]
        tid = ticket['id']
        is_cursor_line = (vis_idx == cursor_pos)

        # Insert mode marker — render distinctively and skip normal logic
        if tid == -1:
            rel_depth = ticket['depth'] - base_depth
            if rel_depth < 0:
                rel_depth = 0
            line = '  ' + '  ' * rel_depth + '  # ' + ticket['title']
            if len(line) > cols:
                line = line[:cols]
            set_style(fg=11, bg=4, bold=True)
            write(line)
            if len(line) < cols:
                write(' ' * (cols - len(line)))
            reset_style()
            continue

        is_selected = (tid in selected)
        is_search_match = (
            search_query
            and search_query.lower() in ticket['title'].lower()
        )

        # Build the line content
        # Selection prefix
        if is_selected:
            prefix = '* '
        else:
            prefix = '  '

        if tid == 0:
            # Project entry — no indent, no marker
            line = prefix + 'Project'
        else:
            # Indent based on depth relative to base
            rel_depth = ticket['depth'] - base_depth
            if rel_depth < 0:
                rel_depth = 0
            indent = '  ' * rel_depth

            # Expand/collapse marker
            if ticket['has_children']:
                if tid in expanded:
                    marker = '\u25bc '  # down triangle
                else:
                    marker = '\u25b6 '  # right triangle
            else:
                marker = '  '

            line = '{}{}{}'.format(
                prefix, indent,
                '#{} [{}] {}'.format(tid, ticket['status'], ticket['title']),
            )
            # We need to insert the marker — rebuild properly
            line = '{}{}'.format(prefix, indent)
            marker_start = len(line)
            line += marker
            line += '#{} [{}] {}'.format(tid, ticket['status'], ticket['title'])

        # Truncate to terminal width
        if len(line) > cols:
            line = line[:cols]

        # Apply styling
        if is_cursor_line:
            set_style(reverse=True)
            write(line)
            # Pad to fill width for reverse video
            if len(line) < cols:
                write(' ' * (cols - len(line)))
            reset_style()
        elif is_selected and is_search_match:
            # Selected + search match: bold cyan with yellow for match
            set_style(fg=6, bold=True)
            write(line)
            reset_style()
        elif is_selected:
            set_style(fg=6, bold=True)
            write(line)
            reset_style()
        elif is_search_match:
            set_style(fg=3)
            write(line)
            reset_style()
        else:
            # Normal line — render marker in blue if present
            if tid != 0 and ticket['has_children']:
                # Write prefix + indent, then marker in blue, then rest
                marker_text = '\u25bc ' if tid in expanded else '\u25b6 '
                pre = prefix + ('  ' * (ticket['depth'] - base_depth if ticket['depth'] - base_depth > 0 else 0))
                rest = '#{} [{}] {}'.format(tid, ticket['status'], ticket['title'])
                full = pre + marker_text + rest
                if len(full) > cols:
                    full = full[:cols]
                # Write prefix/indent part
                write(pre)
                # Write marker in blue
                pre_len = len(pre)
                marker_end = pre_len + len(marker_text)
                if pre_len < cols:
                    set_style(fg=4)
                    marker_portion = full[pre_len:min(marker_end, cols)]
                    write(marker_portion)
                    reset_style()
                # Write rest
                if marker_end < cols:
                    write(full[marker_end:])
            else:
                write(line)


_SUB_WRAP = 80   # wrap child entries at this width
_SUB_INDENT = '    '  # continuation indent for wrapped lines


def _fmt_child(child):
    """Format a child ticket for the subtickets pane."""
    return '#{} [{}] {}'.format(child['id'], child['status'], child['title'])


def _wrap_entry(text, width):
    """Wrap text at width. Returns list of lines; continuation lines are indented."""
    if len(text) <= width:
        return [text]
    lines = [text[:width]]
    rest = text[width:]
    indent = _SUB_INDENT
    cont_w = width - len(indent)
    if cont_w < 10:
        cont_w = width
        indent = ''
    while rest:
        lines.append(indent + rest[:cont_w])
        rest = rest[cont_w:]
    return lines


def _sub_layout(children, cols):
    """Compute multi-column layout for children entries.

    Each entry is wrapped at _SUB_WRAP.  For column-width calculation, the
    capped width (min of actual, _SUB_WRAP) is used so long titles don't
    force single-column.

    Returns (num_cols, col_width, slot_rows, entry_lines) where:
      - slot_rows[i] = number of display rows for entry i
      - entry_lines[i] = list of wrapped lines for entry i
      - num_rows can be derived from slot assignments
    """
    if not children:
        return (1, cols, [], [])

    raw = [_fmt_child(c) for c in children]
    entry_lines = [_wrap_entry(e, _SUB_WRAP) for e in raw]
    slot_rows = [len(lines) for lines in entry_lines]

    # Column width based on capped entry width
    max_w = min(max(len(e) for e in raw), _SUB_WRAP)
    gap = 2
    col_width = max_w + gap
    # Allow one extra partial column — it will be truncated at screen edge
    full_cols = max(1, (cols + gap) // col_width)
    num_cols = min(full_cols + 1, len(children))

    return (num_cols, col_width, slot_rows, entry_lines)


def _distribute_to_columns(num_cols, slot_rows):
    """Distribute entries across columns balancing by display lines, not count.

    Returns list of (start, end) index ranges, one per column.
    """
    n = len(slot_rows)
    if n == 0 or num_cols == 0:
        return []
    total_lines = sum(slot_rows)
    target = (total_lines + num_cols - 1) // num_cols  # ideal lines per column
    cols = []
    start = 0
    for c in range(num_cols):
        if c == num_cols - 1:
            # Last column gets the rest
            cols.append((start, n))
            break
        col_h = 0
        end = start
        while end < n:
            if col_h + slot_rows[end] > target and col_h > 0:
                break
            col_h += slot_rows[end]
            end += 1
        cols.append((start, end))
        start = end
    return cols


def _sub_total_rows(num_cols, slot_rows):
    """Total display rows for a column-major layout with multi-row entries."""
    if not slot_rows or num_cols == 0:
        return 0
    ranges = _distribute_to_columns(num_cols, slot_rows)
    return max(sum(slot_rows[s:e]) for s, e in ranges) if ranges else 0


def _sub_needed_rows(cols):
    """Return number of content rows needed for children_list (multi-column)."""
    if not children_list:
        return 0
    num_cols, _, slot_rows, _ = _sub_layout(children_list, cols)
    return _sub_total_rows(num_cols, slot_rows)


def render_subtickets(top, height, cols, info=False):
    """Render the subtickets pane with a separator."""
    if height <= 0:
        return

    _render_sep(top, cols, 'Children', info=info)

    content_lines = height - 1
    if not children_list or content_lines <= 0:
        for i in range(content_lines):
            move(top + 1 + i, 1)
            clear_line()
        return

    num_cols, col_width, slot_rows, entry_lines = _sub_layout(children_list, cols)
    ranges = _distribute_to_columns(num_cols, slot_rows)

    # Build per-column line arrays
    col_lines = []
    for start, end in ranges:
        lines = []
        for idx in range(start, end):
            lines.extend(entry_lines[idx])
        col_lines.append(lines)

    total_rows = max((len(cl) for cl in col_lines), default=0)

    for row in range(content_lines):
        move(top + 1 + row, 1)
        clear_line()
        if row >= total_rows:
            continue
        parts = []
        for c in range(num_cols):
            cl = col_lines[c]
            cell = cl[row] if row < len(cl) else ''
            if c < num_cols - 1:
                parts.append(cell.ljust(col_width)[:col_width])
            else:
                parts.append(cell)
        line = ''.join(parts)
        if len(line) > cols:
            line = line[:cols]
        write(line)


def _preview_lines():
    """Return the lines currently shown in the preview pane."""
    if error_text:
        return error_text.split('\n')
    if help_mode:
        return _HELP_TEXT.split('\n')
    return preview_text.split('\n') if preview_text else []


def render_preview(top, height, cols, info=False):
    """Render the preview pane."""
    if height <= 0:
        return

    label = 'Error' if error_text else ('Help' if help_mode else 'Preview')
    _render_sep(top, cols, label, info=info)

    # Content (with scroll offset)
    content_lines = height - 1
    lines = _preview_lines()
    for i in range(content_lines):
        move(top + 1 + i, 1)
        clear_line()
        src_idx = i + _preview_scroll
        if src_idx < len(lines):
            line = lines[src_idx]
            # Replace tabs with spaces for display
            line = line.replace('\t', '    ')
            if len(line) > cols:
                line = line[:cols]
            write(line)


_SB_BG = 236   # dark gray background for action prompts
_SB_FG = 252   # light gray text

def _sb_style(**kw):
    """Set status bar base style (dark bg, light fg) with optional overrides."""
    set_style(fg=kw.get('fg', _SB_FG), bg=kw.get('bg', _SB_BG),
              bold=kw.get('bold', False), reverse=kw.get('reverse', False))


def _render_sep(row, cols, label, info=False):
    """Render a separator line. If info=True, include selection/search indicators."""
    S = '\u2500'
    move(row, 1)
    clear_line()

    sel_count = len(selected) if info else 0
    search = search_query if info and search_mode else None
    label_str = ' {} '.format(label)

    # Build the line segment by segment, tracking column position
    pos = 0

    # -- positions 1-2: separator
    set_style(fg=8)
    n = min(2, cols)
    write(S * n)
    pos = n

    # -- position 3: selection count [N] in bold cyan
    if sel_count > 0 and pos < cols:
        sel_str = '[{}]'.format(sel_count)
        set_style(fg=6, bold=True)
        write(sel_str[:cols - pos])
        pos += len(sel_str)
        set_style(fg=8)

    # -- separator fill to position 7 (before search at 8)
    if pos < 7 and pos < cols:
        write(S * min(7 - pos, cols - pos))
        pos = min(7, cols)

    # -- position 8: search prompt + query, or key hints
    if search is not None and pos < cols:
        prompt = '/'
        set_style(fg=11, bg=4, bold=True)
        write(prompt[:cols - pos])
        pos += len(prompt)
        if pos < cols:
            reset_style()
            write(search[:cols - pos])
            pos += len(search)
        set_style(fg=8)
    elif info and pos < cols:
        # Show context-sensitive key hints in subtle gray
        if insert_mode:
            hints = 'enter:ok  \u2190\u2192:indent  esc:cancel'
        else:
            hints = ' n:new  e:edit  m:move  o/c/s:open/close/status  /:search  alt-\u2191\u2193:scope '
        avail = cols - pos - len(label_str) - 3  # room before label
        if avail > 10:
            h = hints[:avail]
            set_style(fg=242)
            write(h)
            pos += len(h)
        set_style(fg=8)

    # -- separator fill to label
    label_start = cols - len(label_str) - 1
    if label_start < pos + 1:
        label_start = pos + 1
    if pos < label_start and pos < cols:
        write(S * min(label_start - pos, cols - pos))
        pos = min(label_start, cols)

    # -- label
    if pos < cols:
        avail = cols - pos
        write(label_str[:avail])
        pos += min(len(label_str), avail)

    # -- trailing separator
    if pos < cols:
        write(S * (cols - pos))

    reset_style()


def _pane_info_flags(layout):
    """Return (sub_info, prev_info) booleans: which pane's separator is the info row."""
    ir = layout['info_row']
    return (layout['sub_height'] > 0 and layout['sub_top'] == ir,
            layout['prev_height'] > 0 and layout['prev_top'] == ir)


def render_full():
    """Full screen redraw."""
    global needs_redraw

    write('\033[2J')
    layout = layout_panes()
    sub_info, prev_info = _pane_info_flags(layout)
    render_list(layout['list_top'], layout['list_height'], layout['cols'])
    render_subtickets(layout['sub_top'], layout['sub_height'], layout['cols'], info=sub_info)
    render_preview(layout['prev_top'], layout['prev_height'], layout['cols'], info=prev_info)
    flush()
    needs_redraw = set()


def render_partial():
    """Selective redraw based on needs_redraw flags."""
    global needs_redraw

    if 'all' in needs_redraw:
        render_full()
        return

    layout = layout_panes()
    sub_info, prev_info = _pane_info_flags(layout)

    if 'list' in needs_redraw:
        render_list(layout['list_top'], layout['list_height'], layout['cols'])
    if 'subtickets' in needs_redraw:
        render_subtickets(layout['sub_top'], layout['sub_height'], layout['cols'], info=sub_info)
    if 'preview' in needs_redraw:
        render_preview(layout['prev_top'], layout['prev_height'], layout['cols'], info=prev_info)
    if 'info' in needs_redraw:
        # Redraw just the info separator line
        ir = layout['info_row']
        if ir > 0:
            if sub_info:
                _render_sep(ir, layout['cols'], 'Children', info=True)
            elif prev_info:
                label = 'Error' if error_text else ('Help' if help_mode else 'Preview')
                _render_sep(ir, layout['cols'], label, info=True)

    flush()
    needs_redraw = set()


_HELP_TEXT = """\
plan-tui -- Terminal UI for plan tickets

NAVIGATION
  j, Down          Cursor down
  k, Up            Cursor up
  g, Home          First item
  G, End           Last item
  PgUp, PgDn       Page up/down
  Right            Expand node / move to first child
  Left             Collapse node / move to parent
  Alt-Right        Expand siblings recursively
  Alt-Left         Collapse siblings recursively
  Alt-Down         Scope down into ticket
  Alt-Up           Scope up to parent

PREVIEW
  Space            Scroll preview page down
  b                Scroll preview page up
  Shift-Down       Scroll preview line down
  Shift-Up         Scroll preview line up
  Ctrl-P           Toggle preview pane

SEARCH
  /                Enter search mode
  Enter            Next match
  Shift-Enter      Previous match
  Esc, Ctrl-C      Exit search mode

SELECTION
  Tab              Toggle select
  Ctrl-A           Select all visible
  Ctrl-N           Deselect all

ACTIONS
  s                Change status
  c                Close ticket
  o                Reopen ticket
  e                Edit in editor
  E                Edit recursively
  n                Create (enter insert mode)
  N                Create bulk/recursive
  m                Move (enter insert mode)
  v                View in pager
  V                View recursively

INSERT MODE (n/m)
  j/k, Up/Down     Move insertion marker
  Right            Make child of entry above
  Left             Outdent
  Enter            Confirm
  Esc, q           Cancel

OTHER
  ?                Help (toggle)
  q                Quit
  Esc, Ctrl-C      Cancel / back to normal / quit
  Ctrl-L           Refresh"""


