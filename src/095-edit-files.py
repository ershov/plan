# ---------------------------------------------------------------------------
# Non-Interactive Edit File Utilities
# ---------------------------------------------------------------------------

import glob
import hashlib


def _edit_content_hash(content):
    """Compute a short hash of content for edit file naming."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:8]


def _edit_file_parts(plan_filename):
    """Split plan filename into (base, ext) for edit file naming.

    E.g. '.PLAN.md' -> ('.PLAN', '.md'), 'MYPLAN' -> ('MYPLAN', '')
    """
    if plan_filename.endswith(".md"):
        return plan_filename[:-3], ".md"
    return plan_filename, ""


def _edit_file_encode(plan_filename, ticket_id, flags, content_hash):
    """Build temp filename from edit parameters.

    plan_filename: basename of plan file, e.g. '.PLAN.md'
    ticket_id: str (digits)
    flags: set of single-letter strings, e.g. {"r"}
    content_hash: str, 8 hex chars
    """
    base, ext = _edit_file_parts(plan_filename)
    parts = ["edit", str(ticket_id)]
    for f in sorted(flags):
        assert len(f) == 1 and f.isalpha()
        parts.append(f)
    parts.append(content_hash[:8])
    return base + "-" + "-".join(parts) + ext


def _edit_file_decode(filename, plan_filename):
    """Parse temp filename -> (ticket_id, flags_set, content_hash) or None.

    Returns None if filename does not match the pattern.
    """
    base, ext = _edit_file_parts(plan_filename)
    prefix = base + "-edit-"
    if not filename.startswith(prefix) or not filename.endswith(ext):
        return None
    stem = filename[len(prefix):]
    if ext:
        stem = stem[:-len(ext)]
    parts = stem.split("-")
    if len(parts) < 2:
        return None
    ticket_id = parts[0]
    if not ticket_id.isdigit():
        return None
    content_hash = parts[-1]
    if len(content_hash) != 8:
        return None
    flags = set(parts[1:-1])
    return ticket_id, flags, content_hash


def _edit_file_glob(plan_dir, plan_filename, ticket_id=None):
    """Find edit files in plan_dir, optionally filtered by ticket_id.

    Returns list of (filename, full_path) tuples.
    """
    base, ext = _edit_file_parts(plan_filename)
    pattern = os.path.join(plan_dir, base + "-edit-*" + ext)
    results = []
    for path in glob.glob(pattern):
        fname = os.path.basename(path)
        decoded = _edit_file_decode(fname, plan_filename)
        if decoded is None:
            continue
        if ticket_id is not None and decoded[0] != str(ticket_id):
            continue
        results.append((fname, path))
    return results


def _edit_list_remaining(plan_dir, plan_filename, output, exclude_path=None):
    """List remaining in-flight edit files (for status messages)."""
    remaining = _edit_file_glob(plan_dir, plan_filename)
    if exclude_path:
        remaining = [(f, p) for f, p in remaining if p != exclude_path]
    if remaining:
        output.append("")
        output.append(f"In-flight edits ({len(remaining)}):")
        for fname, fpath in remaining:
            mtime = os.path.getmtime(fpath)
            age = time.time() - mtime
            if age < 60:
                age_str = f"{int(age)}s ago"
            elif age < 3600:
                age_str = f"{int(age / 60)}m ago"
            else:
                age_str = f"{int(age / 3600)}h ago"
            output.append(f"  {fname} ({age_str})")
