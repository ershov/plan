# ---------------------------------------------------------------------------
# Merge Git Plumbing (subprocess + filesystem primitives)
# ---------------------------------------------------------------------------
#
# Focused, testable primitives for the porcelain `merge` command (Stage 4) and
# the git merge driver + install config (Stage 5). NO CLI, NO argument parsing.
#
# Concatenated after the report module (116), so it may freely use everything
# defined in 010-116 — in particular parse(), serialize(), the Conflict class,
# render_reject(), and the stdlib imports (os, re, subprocess, ...) from the
# preamble.
#
# ISOLATION CONTRACT: every function that touches git takes an explicit
# `repo_root` (or a path it derives the repo from) and runs git with
# cwd=repo_root. Nothing here relies on the process's current working directory.


# ---------------------------------------------------------------------------
# Git query helpers
# ---------------------------------------------------------------------------

def _git(args, repo_root, check=True, input_text=None, timeout=30):
    """Run `git <args>` with cwd=repo_root and return stdout (text).

    Raises a clear RuntimeError on non-zero exit when `check` is True; otherwise
    returns stdout regardless of exit code (caller inspects). `input_text`, when
    given, is fed to git's stdin.
    """
    proc = subprocess.run(
        ["git"] + list(args),
        cwd=repo_root,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "git %s failed (exit %d): %s"
            % (" ".join(args), proc.returncode,
               (proc.stderr or proc.stdout or "").strip())
        )
    return proc.stdout


def git_repo_root(start=None):
    """Return the repository top-level directory (via rev-parse --show-toplevel).

    `start` is the directory to run git in; defaults to the process cwd. Raises
    RuntimeError when not inside a git work tree.
    """
    cwd = start or os.getcwd()
    out = _git(["rev-parse", "--show-toplevel"], cwd)
    return out.strip()


def git_show(repo_root, ref, rel_path):
    """Return the contents of `<ref>:<rel_path>` or None if absent at that ref.

    Used to read the plan file as it existed at the merge-base / on the other
    branch. None means the file did not exist there (added on only one side).
    """
    proc = subprocess.run(
        ["git", "show", "%s:%s" % (ref, rel_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_merge_base(repo_root, a, b):
    """Return the merge-base sha of two refs, or None if there is none."""
    proc = subprocess.run(
        ["git", "merge-base", a, b],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def git_rev_parse(repo_root, ref):
    """Resolve a ref to its full object sha. Raises if it doesn't resolve."""
    return _git(["rev-parse", "--verify", "%s^{commit}" % ref], repo_root).strip()


def git_short_sha(repo_root, ref):
    """Resolve a ref to its abbreviated (short) object sha."""
    return _git(["rev-parse", "--short", "%s^{commit}" % ref], repo_root).strip()


def git_current_branch(repo_root):
    """Return the current branch name, or None on a detached HEAD."""
    out = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root).strip()
    if out == "HEAD" or out == "":
        return None
    return out


def git_ref_exists(repo_root, ref):
    """True if `ref` resolves to a commit in this repo."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "%s^{commit}" % ref],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# Explicit source resolution (--to / --from / --base)
# ---------------------------------------------------------------------------
#
# A "source spec" names one side of a merge. Three forms:
#   git:<ref>   force a git commit/ref (requires a repo)
#   file:<path> force a filesystem path
#   <bare>      auto: an existing path is a file; else a resolvable git ref;
#               else an error.
# A file source is read directly from disk; a commit source is read as
# `<ref>:<relpath>` (relpath = the plan file's in-repo path). Returns
# (text, label) where text is None when the file/ref-path is absent (so a side
# can legitimately be "added"). The label is human-readable for the .reject
# header / block markers.


class SourceError(Exception):
    """A merge source spec could not be resolved to a file or git ref."""


def _resolve_commit_source(ref, repo_root, relpath, display=None):
    """Resolve a git commit source: read <ref>:<relpath>. Returns (text, label)."""
    if repo_root is None:
        raise SourceError(
            "git source %r requires a git repository" % (display or ref))
    if relpath is None:
        # Without a known canonical plan path we cannot read <ref>:<path>, and
        # guessing would silently read the wrong (likely absent) path. Error
        # instead of producing an empty side.
        raise SourceError(
            "cannot determine the plan file path for commit source %r; "
            "run inside the repo or use --file" % (display or ref))
    if not git_ref_exists(repo_root, ref):
        raise SourceError("git ref %r does not resolve to a commit" % ref)
    text = git_show(repo_root, ref, relpath)
    try:
        label = "%s @ %s" % (ref, git_short_sha(repo_root, ref))
    except RuntimeError:
        label = ref
    return text, label


def _resolve_file_source(path):
    """Resolve a filesystem source. Returns (text|None, label=path)."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read(), path
    return None, path


def resolve_source(spec, repo_root, relpath):
    """Resolve a merge source spec to (text, label).

    spec      a source spec string (git:<ref> | file:<path> | bare).
    repo_root the repository top-level, or None when outside a git repo.
    relpath   the canonical plan file's path relative to repo_root, used for
              commit reads (<ref>:<relpath>). None means "undeterminable"; a
              commit source then raises SourceError rather than guessing.

    Raises SourceError on a spec that is neither a file nor a resolvable ref, or
    on a commit source when relpath is None.
    """
    if spec is None:
        raise SourceError("missing source")
    if spec.startswith("git:"):
        ref = spec[len("git:"):]
        if not ref:
            raise SourceError("empty git ref in %r" % spec)
        return _resolve_commit_source(ref, repo_root, relpath, display=spec)
    if spec.startswith("file:"):
        return _resolve_file_source(spec[len("file:"):])
    # Bare: an existing path wins; else try a git ref; else error.
    if os.path.exists(spec):
        return _resolve_file_source(spec)
    if repo_root is not None and git_ref_exists(repo_root, spec):
        return _resolve_commit_source(spec, repo_root, relpath)
    raise SourceError(
        "%r is not a file or git ref" % spec
        + ("" if repo_root is not None
           else " (and we are not inside a git repository)"))


def source_commit(spec, repo_root):
    """Return the commit ref a source spec points at, or None for a file source.

    Used by base auto-detection (a merge-base needs a commit on each side). A
    `file:` source or an existing path is NOT a commit. A `git:<ref>` or a bare
    name that resolves to a commit (and is not an existing path) is.
    """
    if spec is None:
        return None
    if spec.startswith("git:"):
        ref = spec[len("git:"):]
        return ref or None
    if spec.startswith("file:"):
        return None
    if os.path.exists(spec):
        return None
    if repo_root is not None and git_ref_exists(repo_root, spec):
        return spec
    return None


# ---------------------------------------------------------------------------
# Path helper
# ---------------------------------------------------------------------------

def _rel_to_repo(repo_root, plan_path):
    """The path of plan_path relative to repo_root, with forward slashes."""
    rel = os.path.relpath(os.path.abspath(plan_path), os.path.abspath(repo_root))
    return rel.replace(os.sep, "/")


# ---------------------------------------------------------------------------
# Snapshots & in-progress state (paths)
# ---------------------------------------------------------------------------

def reject_path(plan_path):
    """Path of the sidecar `.reject` file for plan_path."""
    return plan_path + ".reject"


def snapshot_dir(repo_root):
    """The base directory under which per-merge state dirs live (inside .git).

    Kept for the existing test helpers; concrete merges use
    merge_state_dir(output_path, repo_root), which namespaces a subdirectory of
    this per output so two in-flight merges in one repo don't clobber each other.
    """
    return os.path.join(repo_root, ".git", "plan-merge")


def _output_state_key(output_path):
    """A short, filesystem-safe key identifying a merge by its output path.

    First 12 hex of sha256(abspath(output)). Used to namespace the in-repo state
    dir so concurrent `-o` merges keep separate snapshots/options/.reject state.
    """
    abspath = os.path.abspath(output_path)
    return _hashlib.sha256(abspath.encode("utf-8")).hexdigest()[:12]


def merge_state_dir(output_path, repo_root):
    """Directory holding the snapshots + options for a merge writing `output_path`.

    Inside a repo -> <repo_root>/.git/plan-merge/<key> (hidden in .git, never
    committed), namespaced per output so multiple in-flight merges don't collide.
    Outside a repo -> <dirname(output_path)>/.plan-merge, beside the output file
    so `--resolve`/`--abort` can find it without git (one in-flight merge per
    output directory, which is the natural unit there).
    """
    if repo_root is not None:
        return os.path.join(repo_root, ".git", "plan-merge",
                            _output_state_key(output_path))
    out_dir = os.path.dirname(os.path.abspath(output_path))
    return os.path.join(out_dir, ".plan-merge")


_SNAPSHOT_NAMES = ("base", "mine", "theirs")


def write_snapshots_at(state_dir, base_text, mine_text, theirs_text):
    """Write base/mine/theirs snapshots into an explicit `state_dir`.

    A None side is written as an empty file (so the trio always exists and
    read_snapshots_at round-trips a consistent shape). Returns the state dir.
    """
    os.makedirs(state_dir, exist_ok=True)
    for name, text in zip(_SNAPSHOT_NAMES, (base_text, mine_text, theirs_text)):
        with open(os.path.join(state_dir, name), "w", encoding="utf-8") as f:
            f.write(text if text is not None else "")
    return state_dir


def read_snapshots_at(state_dir):
    """Read the three snapshots from an explicit `state_dir`.

    Returns (base_text, mine_text, theirs_text); a missing file reads as None.
    """
    out = []
    for name in _SNAPSHOT_NAMES:
        path = os.path.join(state_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out.append(f.read())
        else:
            out.append(None)
    return tuple(out)


def clear_merge_state_at(state_dir, reject_file):
    """Remove a `.reject` file and a snapshot/state dir (explicit paths).

    When the state dir is a per-output subdir of `.git/plan-merge`, also remove
    the now-empty parent so no stale empty directory lingers — but ONLY when it
    is empty, so other in-flight merges (their own subdirs) are preserved.
    """
    if reject_file and os.path.exists(reject_file):
        os.remove(reject_file)
    if state_dir and os.path.isdir(state_dir):
        shutil.rmtree(state_dir)
        parent = os.path.dirname(os.path.abspath(state_dir))
        if os.path.basename(parent) == "plan-merge" and os.path.isdir(parent):
            try:
                os.rmdir(parent)  # only succeeds when empty
            except OSError:
                pass


def write_snapshots(repo_root, base_text, mine_text, theirs_text):
    """Write snapshots into <repo_root>/.git/plan-merge/ (in-repo convenience)."""
    return write_snapshots_at(snapshot_dir(repo_root),
                              base_text, mine_text, theirs_text)


def read_snapshots(repo_root):
    """Read snapshots from <repo_root>/.git/plan-merge/ (in-repo convenience)."""
    return read_snapshots_at(snapshot_dir(repo_root))


def clear_merge_state(repo_root, plan_path):
    """Remove the `.reject` file and the `.git/plan-merge/` snapshot dir."""
    clear_merge_state_at(snapshot_dir(repo_root), reject_path(plan_path))


def merge_in_progress(plan_path):
    """True if a merge is in progress (the `.reject` file exists)."""
    return os.path.exists(reject_path(plan_path))


def merge_in_progress_at(reject_file):
    """True if a merge is in progress for an explicit `.reject` path."""
    return os.path.exists(reject_file)


# ---------------------------------------------------------------------------
# Advisory line annotation
# ---------------------------------------------------------------------------

# A node header line, anywhere in serialized plan text: '* ## ... {#<id>}'.
# Group 1 = leading whitespace + bullet (used to gauge nesting depth); group 2
# = the id token inside the braces.
_ANNOTATE_HEADER_RE = re.compile(r'^(\s*\*\s+)##\s+.*\{#([^}]+)\}\s*$')


def _header_lines(text):
    """Yield (line_index_0based, indent_width, id_token) for every node header.

    indent_width is the number of leading whitespace columns before the '*'
    bullet, used to determine nesting depth (a node's span ends at the next
    header at the same-or-shallower indent).
    """
    out = []
    if text is None:
        return out
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = _ANNOTATE_HEADER_RE.match(line)
        if m:
            indent = len(m.group(1)) - len(m.group(1).lstrip(" "))
            out.append((i, indent, m.group(2)))
    return out


def _node_span(text, node_id):
    """Return a 1-based (start_line, end_line) span for node_id in text, or None.

    The span runs from the node's '{#<id>}' header line to the line before the
    next header at the same-or-shallower indent (or EOF). Best-effort only.
    """
    if text is None:
        return None
    headers = _header_lines(text)
    n_lines = len(text.split("\n"))
    target = str(node_id)
    for k, (idx, indent, tok) in enumerate(headers):
        if tok != target:
            continue
        # End = line before the next header at same-or-shallower indent, or EOF.
        end_idx = n_lines - 1
        for (nidx, nindent, _ntok) in headers[k + 1:]:
            if nindent <= indent:
                end_idx = nidx - 1
                break
        # Trim trailing blank lines from the span.
        all_lines = text.split("\n")
        while end_idx > idx and all_lines[end_idx].strip() == "":
            end_idx -= 1
        return (idx + 1, end_idx + 1)
    return None


def annotate_conflict_lines(conflicts, mine_text, theirs_text):
    """Best-effort: set mine_lines/theirs_lines spans on each conflict.

    For each conflict, locate its node in the mine and theirs snapshots and set
    a 1-based (start, end) span pointing at the node's '{#<id>}' header through
    the line before the next same-or-shallower header (or EOF). A node absent on
    a side (e.g. modify-delete) leaves that side's lines as None. This is
    ADVISORY only — it never raises; any difficulty leaves the span None.
    """
    if not conflicts:
        return
    for c in conflicts:
        try:
            c.mine_lines = _node_span(mine_text, c.node_id)
        except Exception:
            c.mine_lines = None
        try:
            c.theirs_lines = _node_span(theirs_text, c.node_id)
        except Exception:
            c.theirs_lines = None


# ---------------------------------------------------------------------------
# Git index / conflict-state management
# ---------------------------------------------------------------------------

def in_merge_or_rebase(repo_root):
    """True if a merge or rebase is currently in progress.

    Consults the real git dir via `git rev-parse --git-path` (robust to worktrees
    and non-default git dirs): checks MERGE_HEAD, rebase-merge/, rebase-apply/.
    """
    for name in ("MERGE_HEAD", "rebase-merge", "rebase-apply"):
        try:
            p = _git(["rev-parse", "--git-path", name], repo_root).strip()
        except RuntimeError:
            continue
        if not os.path.isabs(p):
            p = os.path.join(repo_root, p)
        if os.path.exists(p):
            return True
    return False


def _hash_object(repo_root, text):
    """Write `text` as a blob into the object store; return its sha."""
    return _git(["hash-object", "-w", "--stdin"], repo_root,
                input_text=text if text is not None else "").strip()


def mark_unmerged(repo_root, plan_path, base_text, mine_text, theirs_text):
    """Mark plan_path as 'unmerged' in the index via stages 1/2/3.

    For each non-None side, write a blob (git hash-object -w) and feed an
    index-info line "<mode> <sha> <stage>\\t<rel_path>" (mode 100644) to
    `git update-index --index-info`. Stage 1=base, 2=mine, 3=theirs. Afterwards
    `git status` reports the path unmerged and `git commit` is blocked until a
    `git add`.
    """
    rel = _rel_to_repo(repo_root, plan_path)
    # Clear any existing index entry first so stale stages don't linger.
    _git(["update-index", "--force-remove", "--", rel], repo_root, check=False)

    lines = []
    for stage, text in ((1, base_text), (2, mine_text), (3, theirs_text)):
        if text is None:
            continue
        sha = _hash_object(repo_root, text)
        lines.append("100644 %s %d\t%s" % (sha, stage, rel))
    if not lines:
        return
    payload = "\n".join(lines) + "\n"
    _git(["update-index", "--index-info"], repo_root, input_text=payload)


def mark_resolved(repo_root, plan_path):
    """Clear the unmerged stages by `git add`-ing the path."""
    rel = _rel_to_repo(repo_root, plan_path)
    _git(["add", "--", rel], repo_root)


# ---------------------------------------------------------------------------
# Install-config helpers (driver / .gitattributes / .gitignore)
# ---------------------------------------------------------------------------

_MERGE_DRIVER_NAME = "plan structure-aware merge"
_MERGE_DRIVER_CMD = "plan merge-driver %O %A %B %P"


def _read_lines_file(path):
    """Read a text file into a list of lines (no trailing newlines). [] if absent."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if text == "":
        return []
    lines = text.split("\n")
    # Drop a single trailing empty element produced by a final newline.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _write_lines_file(path, lines):
    """Write a list of lines back, one per line, with a trailing newline.

    An empty list removes the file (idempotent for the remove_* helpers).
    """
    if not lines:
        if os.path.exists(path):
            os.remove(path)
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _add_line_idempotent(path, line):
    """Append `line` to the file iff it is not already present (exact match)."""
    lines = _read_lines_file(path)
    if line in lines:
        return
    lines.append(line)
    _write_lines_file(path, lines)


def _remove_line_idempotent(path, line):
    """Remove every exact-match occurrence of `line` from the file."""
    lines = _read_lines_file(path)
    kept = [ln for ln in lines if ln != line]
    if len(kept) != len(lines):
        _write_lines_file(path, kept)


def ensure_gitattributes(repo_root, rel_plan):
    """Idempotently add '<rel_plan> merge=plan' to <repo_root>/.gitattributes."""
    line = "%s merge=plan" % rel_plan
    _add_line_idempotent(os.path.join(repo_root, ".gitattributes"), line)


def remove_gitattributes(repo_root, rel_plan):
    """Idempotently remove the '<rel_plan> merge=plan' .gitattributes line."""
    line = "%s merge=plan" % rel_plan
    _remove_line_idempotent(os.path.join(repo_root, ".gitattributes"), line)


def set_merge_driver(repo_root):
    """Configure the repo-local merge.plan driver in .git/config (idempotent)."""
    _git(["config", "merge.plan.name", _MERGE_DRIVER_NAME], repo_root)
    _git(["config", "merge.plan.driver", _MERGE_DRIVER_CMD], repo_root)


def unset_merge_driver(repo_root):
    """Remove the merge.plan config section. Tolerates an absent section."""
    proc = subprocess.run(
        ["git", "config", "--remove-section", "merge.plan"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Exit 128 == "no such section"; that is fine (idempotent).
    return proc.returncode in (0, 128)


def ensure_gitignore(repo_root, pattern):
    """Idempotently add `pattern` as a line in <repo_root>/.gitignore."""
    _add_line_idempotent(os.path.join(repo_root, ".gitignore"), pattern)


def remove_gitignore(repo_root, pattern):
    """Idempotently remove the `pattern` line from <repo_root>/.gitignore."""
    _remove_line_idempotent(os.path.join(repo_root, ".gitignore"), pattern)
