##############################################################################
# Data Layer — all plan interaction through subprocess calls
##############################################################################

import time as _time

_cache = {}
_command_log = []  # list of (timestamp, cmd_str, stdout, stderr, returncode) tuples
_COMMAND_LOG_MAX = 50


_CYAN = '\033[36m'
_RED = '\033[31m'
_RESET = '\033[0m'


def command_log_text():
    """Return the command log as a single string with ANSI colors."""
    if not _command_log:
        return '(no commands logged yet)\n'
    parts = []
    for ts, cmd, out, err, rc in _command_log:
        parts.append('')
        t = _time.strftime('%H:%M:%S', _time.localtime(ts))
        if rc != 0:
            parts.append(f'{_CYAN}[{t}] $ {cmd}  [exit {rc}]{_RESET}')
        else:
            parts.append(f'{_CYAN}[{t}] $ {cmd}{_RESET}')
        if out:
            parts.append(out)
        if err:
            parts.append(f'{_RED}{err}{_RESET}')
    return '\n'.join(parts) + '\n'


def _log_command(args, result):
    """Append a completed command to the log."""
    cmd_str = ' '.join(args)
    _command_log.append((_time.time(), cmd_str, result.stdout or '', result.stderr or '', result.returncode))
    if len(_command_log) > _COMMAND_LOG_MAX:
        del _command_log[:len(_command_log) - _COMMAND_LOG_MAX]


def cache_invalidate():
    """Clear the entire cache."""
    _cache.clear()


def cache_invalidate_ticket(ticket_id):
    """Clear cached preview and children for a specific ticket."""
    if 'preview' in _cache:
        _cache['preview'].pop(ticket_id, None)
    if 'children' in _cache:
        _cache['children'].pop(ticket_id, None)


def _run_plan(*args):
    """Run plan command with captured output. Returns CompletedProcess."""
    full_args = [PLAN_BIN] + list(args)
    try:
        result = subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
    except Exception:
        # Return a fake CompletedProcess on failure (timeout, missing binary, etc.)
        result = subprocess.CompletedProcess(
            args=full_args,
            returncode=1,
            stdout='',
            stderr='',
        )
    _log_command(full_args, result)
    return result


def _parse_ticket_line(line):
    """Parse a tab-separated ticket line into a dict."""
    parts = line.split('\t', 5)
    if len(parts) < 6:
        return None
    return {
        'id': int(parts[0]),
        'parent': int(parts[1]),
        'status': parts[2],
        'has_children': parts[3] == '1',
        'depth': int(parts[4]),
        'title': parts[5],
    }


_LIST_FORMAT = 'f"{id}\\t{parent}\\t{status}\\t{1 if children() else 0}\\t{depth}\\t{title}"'

_last_list_error = ''


def plan_list(scope):
    """Get all tickets. Returns list of dicts.

    scope=None for root, scope=ticket_id to list descendants of that ticket.
    """
    global _last_list_error

    if 'list' in _cache and _cache.get('list_scope') == scope:
        return _cache['list']

    if scope is None:
        result = _run_plan('list', '--format', _LIST_FORMAT)
    else:
        result = _run_plan(
            'is_descendant_of({})'.format(scope),
            str(scope),
            'list',
            '--format', _LIST_FORMAT,
        )

    if result.returncode != 0:
        _last_list_error = result.stderr.strip() or 'plan command failed'
        return []

    _last_list_error = ''

    tickets = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        ticket = _parse_ticket_line(line)
        if ticket is not None:
            tickets.append(ticket)

    _cache['list'] = tickets
    _cache['list_scope'] = scope
    return tickets


def plan_get(ticket_id):
    """Get ticket details. Returns (text, error) tuple."""
    hit = _cache.get('preview', {}).get(ticket_id)
    if hit is not None:
        return hit, ''

    if ticket_id == 0:
        result = _run_plan('project', 'get')
    else:
        result = _run_plan(str(ticket_id), 'get')

    if result.returncode != 0:
        return '', result.stderr.strip() or 'get command failed'

    text = result.stdout
    _cache.setdefault('preview', {})[ticket_id] = text
    return text, ''


def plan_children(ticket_id):
    """Get direct children of a ticket. Returns (list_of_dicts, error) tuple."""
    hit = _cache.get('children', {}).get(ticket_id)
    if hit is not None:
        return hit, ''

    result = _run_plan(
        str(ticket_id), '-r',
        'list',
        '--format', _LIST_FORMAT,
    )

    if result.returncode != 0:
        _cache.setdefault('children', {})[ticket_id] = []
        return [], result.stderr.strip() or 'list children failed'

    lines = result.stdout.splitlines()
    # Skip the first result (the ticket itself)
    lines = lines[1:]

    # Determine the parent depth: direct children are at parent_depth + 1
    parent_depth = None
    children = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        ticket = _parse_ticket_line(line)
        if ticket is None:
            continue
        if parent_depth is None:
            # First child tells us the expected depth
            parent_depth = ticket['depth'] - 1
        if ticket['depth'] == parent_depth + 1:
            children.append(ticket)

    _cache.setdefault('children', {})[ticket_id] = children
    return children, ''


def plan_status(ids, status):
    """Set status on tickets. Skip id=0. Returns error string or ''."""
    filtered = [str(i) for i in ids if i != 0]
    if not filtered:
        return ''
    result = _run_plan(*filtered + ['status', status])
    if result.returncode != 0:
        return result.stderr.strip() or 'status command failed'
    return ''


def plan_close(ids):
    """Close tickets. Skip id=0. Returns error string or ''."""
    filtered = [str(i) for i in ids if i != 0]
    if not filtered:
        return ''
    result = _run_plan(*filtered + ['close'])
    if result.returncode != 0:
        return result.stderr.strip() or 'close command failed'
    return ''


def plan_reopen(ids):
    """Reopen tickets. Skip id=0. Returns error string or ''."""
    filtered = [str(i) for i in ids if i != 0]
    if not filtered:
        return ''
    result = _run_plan(*filtered + ['reopen'])
    if result.returncode != 0:
        return result.stderr.strip() or 'reopen command failed'
    return ''


def plan_edit(ticket_id, recursive=False):
    """Edit a ticket in the editor. Returns subprocess return code.

    Does NOT suspend/resume terminal — caller handles that.
    """
    try:
        if ticket_id == 0:
            args = [PLAN_BIN, 'edit', 'project']
        else:
            args = [PLAN_BIN, 'edit', str(ticket_id)]
        if recursive:
            # -r flag goes after the ID
            if ticket_id == 0:
                args = [PLAN_BIN, 'edit', '-r', 'project']
            else:
                args = [PLAN_BIN, 'edit', '-r', str(ticket_id)]
        result = subprocess.run(args)
        _log_command(args, result)
        return result.returncode
    except Exception:
        return 1


def plan_create(mode, cursor_id, recursive=False):
    """Create a new ticket. Returns subprocess return code.

    Does NOT suspend/resume terminal — caller handles that.
    With recursive=True, passes -r for bulk creation.
    """
    try:
        args = [PLAN_BIN, 'create', '-e']
        if recursive:
            args.append('-r')
        args.append('title="New ticket", move="{} {}"'.format(mode, cursor_id))
        result = subprocess.run(args)
        _log_command(args, result)
        return result.returncode
    except Exception:
        return 1


def plan_move(ids, relation, dest_id):
    """Move tickets. relation is one of: before, after, first, last. Skip id=0.
    Returns error string or ''."""
    filtered = [str(i) for i in ids if i != 0]
    if not filtered:
        return ''
    result = _run_plan(*filtered + ['move', relation, str(dest_id)])
    if result.returncode != 0:
        return result.stderr.strip() or 'move command failed'
    return ''
