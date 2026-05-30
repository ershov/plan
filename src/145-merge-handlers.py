# ---------------------------------------------------------------------------
# Merge command handlers (`plan merge` porcelain)
# ---------------------------------------------------------------------------
#
# Orchestrates the pure engine (115), the report renderer/parser (116) and the
# git plumbing (117) into the user-facing `plan merge` command and its modes
# (--resolve / --abort / --check). NO argument parsing here — that lives in
# 120-cli.py; main() (180) special-cases the merge command BEFORE its own
# discover_file/flock block (merge resolves its own sources/output and may run
# outside git), then calls _handle_merge(). This module takes its OWN exclusive
# lock on the output file (_OutputLock) for each read->merge->write.
#
# Concatenated after 140-handlers, so it may freely use everything in 010-140 —
# in particular merge_trees(), parse(), serialize(), render_reject(),
# parse_reject(), RejectError, VERSION_STR and the git helpers.
#
# CONTRACT: _handle_merge returns an exit code (0/1/2). Normal/status messages
# go to stdout via the `output` list; errors go straight to stderr (so callers
# can keep stdout clean). The function NEVER raises for expected error paths.

# Persisted across `plan merge <branch>` -> `plan merge --resolve`: the merge
# options needed to reproduce the original merge. Lives inside the per-output
# state dir so clearing that dir removes it for free.
_MERGE_OPTIONS_FILE = "options"

# User-facing side vocabulary <-> engine-internal side values. The CLI exposes
# the two merge sides as `to` (the side merged into — canonical) and `from` (the
# side merged from). The engine, snapshots and persisted options keep the
# historical `mine`/`theirs` names; we map at this boundary only.
_SIDE_TO_ENGINE = {"to": "mine", "from": "theirs"}


def _engine_side(value, default="theirs"):
    """Map a user-facing `to`/`from` side to its engine value (`mine`/`theirs`).

    Passes engine values through unchanged (so callers may hand us either), and
    falls back to `default` for None/unknown.
    """
    if value is None:
        return default
    return _SIDE_TO_ENGINE.get(value, value)


def _err(msg):
    """Print an error to stderr (one line)."""
    print(msg, file=sys.stderr)


def _err_prefixed(prefix, exc):
    """Print `<prefix>: <exc>` to stderr, avoiding a doubled prefix.

    Some lower-layer RuntimeErrors already start with 'merge:'; don't repeat it.
    """
    text = str(exc)
    if text.startswith(prefix):
        _err(text)
    else:
        _err("%s %s" % (prefix, text))


class _OutputLock:
    """Exclusive advisory lock on the merge OUTPUT file for read->merge->write.

    Mirrors main.py's flock pattern (LOCK_EX | LOCK_NB with a brief retry) so a
    `plan merge` writing `.PLAN.md` is mutually exclusive with concurrent
    `plan create`/`status`/... (which hold LOCK_EX on the same file). When the
    output equals the working-tree plan file this restores that exclusion; for a
    custom `-o`/outside-git output, locking that file is still the right unit.

    A no-op when flock is unavailable (`_has_flock` False) or `path` is None.
    Used as a context manager; raises SystemExit on lock-acquisition timeout.
    """

    def __init__(self, path):
        self.path = path
        self._fd = None

    def __enter__(self):
        if not _has_flock or not self.path:
            return self
        # Open for append so we never truncate; create if missing so a brand-new
        # output (e.g. -o newfile) can still be locked before its first write.
        self._fd = open(self.path, "a")
        for _attempt in range(20):
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                time.sleep(0.1)
        else:
            self._fd.close()
            self._fd = None
            raise SystemExit(
                "Error: could not acquire lock on %s "
                "(timed out after 2 seconds)" % self.path)
        return self

    def __exit__(self, *exc):
        if self._fd is not None:
            self._fd.close()
            self._fd = None
        return False


def _parse_text_or_none(text):
    """parse() a plan side, mapping a None/empty side to None (empty project)."""
    if text is None or text == "":
        return None
    return parse(text)


def _write_merge_options_at(state_dir, renumber, two_way=False, output=None):
    """Persist the merge options in an explicit `state_dir`.

    Written as simple `key=value` lines so --resolve can reproduce the exact
    same merge: the `renumber` choice, whether the original run used two-way mode
    (no diff3 base), and the output path (so --resolve writes the right file even
    when -o pointed elsewhere) all matter.
    """
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, _MERGE_OPTIONS_FILE), "w",
              encoding="utf-8") as f:
        f.write("renumber=%s\n" % renumber)
        f.write("two_way=%s\n" % ("true" if two_way else "false"))
        if output is not None:
            f.write("output=%s\n" % output)


def _read_merge_options_at(state_dir):
    """Read back persisted merge options from an explicit `state_dir`.

    Returns {'renumber': 'mine'|'theirs', 'two_way': bool, 'output': str|None}.
    Defaults `renumber` to 'theirs', `two_way` to False, `output` to None when
    the file is absent or malformed (so older .reject files keep working).
    """
    opts = {"renumber": "theirs", "two_way": False, "output": None}
    path = os.path.join(state_dir, _MERGE_OPTIONS_FILE)
    if not os.path.exists(path):
        return opts
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                stripped = line.strip()
                if not stripped or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                if k == "renumber" and v in ("mine", "theirs"):
                    opts["renumber"] = v
                elif k == "two_way":
                    opts["two_way"] = (v.strip().lower() == "true")
                elif k == "output":
                    opts["output"] = v
    except OSError:
        pass
    return opts


def _conflict_action_message(n, rp):
    """The actionable multi-line error shown when conflicts remain."""
    return (
        "merge: %d conflict(s) need manual resolution.\n"
        "  Wrote %s — edit the marked blocks, then:\n"
        "      plan merge --resolve     # apply your edits\n"
        "      plan merge --abort       # discard this merge"
        % (n, rp)
    )


def _list_conflicts(conflicts):
    """Render a short list of remaining conflicts for an error message."""
    parts = []
    for c in conflicts:
        if c.field and c.field != NODE_FIELD:
            parts.append("#%s (%s)" % (c.node_id, c.field))
        else:
            parts.append("#%s" % c.node_id)
    return ", ".join(parts)


def _maybe_launch_editor(reject_file, flags):
    """On a TTY with $EDITOR set and not --no-edit, open the .reject file.

    Best-effort convenience only; does NOT auto-apply (the user still runs
    --resolve). Any failure is swallowed so it never blocks the merge result.
    """
    if flags.get("no_edit"):
        return
    if not sys.stdout.isatty():
        return
    editor = os.environ.get("EDITOR")
    if not editor:
        return
    try:
        subprocess.run(shlex.split(editor) + [reject_file], check=False)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Source / output / state resolution shared by all modes
# ---------------------------------------------------------------------------

def _discover_file_or_none(flags):
    """discover_file(flags) but returns None instead of raising when absent."""
    try:
        return discover_file(flags)
    except SystemExit:
        return None


def _repo_root_for(path):
    """git_repo_root() rooted near `path` (or cwd if path is None); None if outside."""
    try:
        start = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
        return git_repo_root(start)
    except (RuntimeError, OSError):
        return None


def _relpath_for_commit_reads(plan_path, repo_root):
    """The in-repo path used to read `<ref>:<relpath>` commit sources, or None.

    This is the canonical PLAN file's path (the one tracked in git), NOT the
    output path — a commit source is the plan file as it existed on that ref. We
    return its path relative to the repo root. None means "undeterminable" (no
    repo, or no canonical plan path): the caller must NOT guess a relpath for a
    commit read (guessing reads the wrong/absent path and silently produces an
    empty side), so resolve_source errors on a commit source when relpath is None.
    """
    if repo_root is None or not plan_path:
        return None
    try:
        return _rel_to_repo(repo_root, plan_path)
    except (ValueError, OSError):
        return None


def _resolve_output_path(flags, to_spec, discovered):
    """Decide where the merged result is written.

    Precedence: -o/--output > the --to file (when `to` is a file spec) > the
    discovered plan file. Returns None when nothing can be determined.
    """
    if flags.get("merge_output"):
        return flags["merge_output"]
    # If --to names a file (file: prefix or an existing path), write back to it.
    if to_spec is not None:
        if to_spec.startswith("file:"):
            return to_spec[len("file:"):]
        if not to_spec.startswith("git:") and os.path.exists(to_spec):
            return to_spec
    return discovered


def _default_to_text(discovered):
    """Read the default `to` (working-tree plan file) content, or None if absent."""
    if discovered and os.path.exists(discovered):
        with open(discovered, encoding="utf-8") as f:
            return f.read()
    return None


def _precompute_output_path(flags):
    """Resolve the output path up front (before reading sources) for locking.

    Same precedence as _resolve_output_path, but resolved BEFORE gathering so we
    can take the output lock around the whole read->merge->write. Returns None
    when no output can be determined yet (the handler then errors after gather).
    """
    return _resolve_output_path(flags, flags.get("merge_to"),
                                _discover_file_or_none(flags))


# ---------------------------------------------------------------------------
# Entry point + mode dispatch
# ---------------------------------------------------------------------------

def _handle_merge(req, flags, output):
    """Handle the `merge` command. Returns an exit code (0/1/2).

    `flags` is the merged flag dict from all requests (the merge sources, output
    and options). Modes (mutually exclusive, in order): --abort, --resolve,
    --check, then the default merge. Stage 9: sources may be files or commits,
    the output may be elsewhere via -o, and the whole thing can run outside git.
    """
    if flags.get("abort"):
        return _merge_resolve_or_abort(flags, output, mode="abort")
    if flags.get("merge_resolve"):
        return _merge_resolve_or_abort(flags, output, mode="resolve")
    if flags.get("merge_both_from"):
        _err("merge: give a branch OR --from, not both")
        return 2
    if flags.get("merge_check"):
        return _merge_check(flags, output)
    return _merge_default(flags, output)


# ---------------------------------------------------------------------------
# Locate the in-progress merge state for --resolve / --abort
# ---------------------------------------------------------------------------

def _locate_state(flags):
    """Resolve (output_path, repo_root, state_dir, reject_file) for resolve/abort.

    The output defaults to the discovered plan file; -o overrides. Works outside
    git (state lives beside the output in `.plan-merge`).
    """
    discovered = _discover_file_or_none(flags)
    output_path = flags.get("merge_output") or discovered
    repo_root = _repo_root_for(output_path)
    if output_path is None:
        return None, repo_root, None, None
    state_dir = merge_state_dir(output_path, repo_root)
    reject_file = reject_path(output_path)
    return output_path, repo_root, state_dir, reject_file


def _merge_resolve_or_abort(flags, output, mode):
    """Shared front for --resolve / --abort (they locate state identically)."""
    output_path, repo_root, state_dir, reject_file = _locate_state(flags)
    label = "merge --abort" if mode == "abort" else "merge --resolve"

    if output_path is None:
        _err("%s: no output file (use -o to point at the in-progress merge)"
             % label)
        return 2
    if not merge_in_progress_at(reject_file):
        _err("%s: no merge in progress for %s" % (label, output_path))
        return 2

    # Lock the output across the write/restore (mutual exclusion with concurrent
    # `plan` writers on the same file).
    with _OutputLock(output_path):
        if mode == "abort":
            return _merge_abort(output_path, repo_root, state_dir,
                                reject_file, output)
        return _merge_resolve(output_path, repo_root, state_dir,
                              reject_file, output)


# ---------------------------------------------------------------------------
# --abort
# ---------------------------------------------------------------------------

def _merge_abort(output_path, repo_root, state_dir, reject_file, output):
    """Discard an in-progress merge: restore `to` (mine), clear state/index."""
    _base, mine_text, _theirs = read_snapshots_at(state_dir)
    # Restore the output file from the `to` (mine) snapshot.
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(mine_text if mine_text is not None else "")

    # Clear any unmerged index stages we may have set (in a repo only).
    if repo_root is not None:
        try:
            mark_resolved(repo_root, output_path)
        except RuntimeError:
            pass

    clear_merge_state_at(state_dir, reject_file)
    output.append("merge --abort: discarded in-progress merge; restored %s"
                  % output_path)
    return 0


# ---------------------------------------------------------------------------
# --resolve
# ---------------------------------------------------------------------------

def _merge_resolve(output_path, repo_root, state_dir, reject_file, output):
    """Apply an edited .reject: re-run the merge with the user's resolutions."""
    try:
        with open(reject_file, encoding="utf-8") as f:
            reject_text = f.read()
    except OSError as exc:
        _err("merge --resolve: cannot read %s: %s" % (reject_file, exc))
        return 2

    try:
        resolutions = parse_reject(reject_text)
    except RejectError as exc:
        _err("merge --resolve: %s" % exc.message)
        return 2

    base_text, mine_text, theirs_text = read_snapshots_at(state_dir)
    base = _parse_text_or_none(base_text)
    mine = _parse_text_or_none(mine_text)
    theirs = _parse_text_or_none(theirs_text)

    opts = _read_merge_options_at(state_dir)
    # The persisted output path is authoritative (the original merge may have
    # used -o to write elsewhere); fall back to the located output_path.
    target = opts.get("output") or output_path
    result = merge_trees(base, mine, theirs, renumber=opts["renumber"],
                         resolutions=resolutions, two_way=opts["two_way"])

    if result.conflicts:
        _err("merge --resolve: %d conflict(s) still unresolved: %s"
             % (len(result.conflicts), _list_conflicts(result.conflicts)))
        return 2

    with open(target, "w", encoding="utf-8") as f:
        f.write(serialize(result.project))

    # Finalize git state (in a repo only): mark the path resolved (git add).
    if repo_root is not None:
        try:
            mark_resolved(repo_root, target)
        except RuntimeError:
            pass

    clear_merge_state_at(state_dir, reject_file)
    output.append("merge --resolve: applied resolutions; wrote %s" % target)
    return 0


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------

def _merge_check(flags, output):
    """Dry run: compute the merge, report the conflict count, write NOTHING."""
    gathered = _gather_merge_inputs(flags, "merge --check")
    if isinstance(gathered, int):
        return gathered
    base, mine, theirs = gathered["base"], gathered["mine"], gathered["theirs"]

    renumber = _engine_side(flags.get("renumber"))
    prefer = _engine_side(flags.get("prefer"), default=None)
    result = merge_trees(base, mine, theirs, renumber=renumber, prefer=prefer,
                         two_way=gathered["two_way"])

    n = len(result.conflicts)
    if n:
        output.append("merge --check: %d conflict(s)" % n)
        return 1
    output.append("merge --check: clean")
    return 0


# ---------------------------------------------------------------------------
# Gather the three merge inputs from explicit sources (shared by check/default)
# ---------------------------------------------------------------------------

def _gather_merge_inputs(flags, errprefix):
    """Resolve --to/--from/--base into texts + labels, deciding three/two-way.

    Returns a dict on success:
      base/mine/theirs        parsed Project|None (engine inputs)
      base_text/to_text/from_text   raw side texts (for snapshots)
      to_label/from_label/base_label, to_branch/from_branch  (.reject labels)
      two_way                 True when no base could be established
      output_path, repo_root, state_dir, reject_file
    On error returns an int exit code (2) after printing to stderr.
    """
    from_spec = flags.get("merge_from")
    if not from_spec:
        _err("%s: a merge source is required "
             "(a branch, or --from <src>)" % errprefix)
        return 2

    discovered = _discover_file_or_none(flags)
    to_spec = flags.get("merge_to")
    base_spec = flags.get("merge_base")

    output_path = _resolve_output_path(flags, to_spec, discovered)
    repo_root = _repo_root_for(output_path or discovered)
    # Commit sources read the CANONICAL plan file at a ref, so the relpath is the
    # discovered plan file's in-repo path (NOT the output, which may be -o
    # elsewhere). None means undeterminable -> resolve_source errors on a commit
    # source rather than silently reading the wrong (absent) path.
    relpath = _relpath_for_commit_reads(discovered, repo_root)

    # --- resolve `from` (theirs): an explicit source MUST resolve to content. ---
    try:
        from_text, from_label = resolve_source(from_spec, repo_root, relpath)
    except SourceError as exc:
        _err("%s: --from %s" % (errprefix, exc))
        return 2
    if from_text is None:
        _err("%s: --from source %r has no content (file/ref-path absent); an "
             "explicit source must exist" % (errprefix, from_spec))
        return 2

    # --- resolve `to` (mine): explicit source, else the working-tree plan ---
    if to_spec is not None:
        try:
            to_text, to_label = resolve_source(to_spec, repo_root, relpath)
        except SourceError as exc:
            _err("%s: --to %s" % (errprefix, exc))
            return 2
        if to_text is None:
            _err("%s: --to source %r has no content (file/ref-path absent); an "
                 "explicit source must exist" % (errprefix, to_spec))
            return 2
        to_commit = source_commit(to_spec, repo_root)
    else:
        # The DEFAULT `to` is the working-tree plan file; it may legitimately be
        # absent (the plan is being added on the `from` side), so None is OK.
        to_text = _default_to_text(discovered)
        to_label = _default_to_label(discovered, repo_root)
        # The default working-tree `to` uses HEAD for base auto-detection.
        to_commit = "HEAD" if repo_root is not None else None

    # --- resolve / auto-detect base ---
    base_text = None
    base_label = "(none — two-way)"
    if base_spec is not None:
        try:
            base_text, base_label = resolve_source(base_spec, repo_root, relpath)
        except SourceError as exc:
            _err("%s: --base %s" % (errprefix, exc))
            return 2
        if base_text is None:
            _err("%s: --base source %r has no content (file/ref-path absent); an "
                 "explicit source must exist" % (errprefix, base_spec))
            return 2
    else:
        from_commit = source_commit(from_spec, repo_root)
        if repo_root is not None and to_commit and from_commit:
            mb = git_merge_base(repo_root, to_commit, from_commit)
            if mb:
                base_text = git_show(repo_root, mb, relpath)
                # render_reject appends "(merge-base)"; keep the label the bare sha.
                try:
                    base_label = git_short_sha(repo_root, mb)
                except RuntimeError:
                    base_label = mb

    two_way = (base_text is None)

    try:
        base = _parse_text_or_none(base_text)
        mine = _parse_text_or_none(to_text)
        theirs = _parse_text_or_none(from_text)
    except Exception as exc:
        _err("%s: could not parse a source: %s" % (errprefix, exc))
        return 2

    if output_path is None:
        output_path = discovered

    state_dir = merge_state_dir(output_path, repo_root) if output_path else None
    reject_file = reject_path(output_path) if output_path else None

    return {
        "base": base, "mine": mine, "theirs": theirs,
        "base_text": base_text, "to_text": to_text, "from_text": from_text,
        "base_label": base_label, "to_label": to_label, "from_label": from_label,
        "to_branch": _branch_token(to_label), "from_branch": _branch_token(from_label),
        "two_way": two_way,
        "output_path": output_path, "repo_root": repo_root,
        "state_dir": state_dir, "reject_file": reject_file,
    }


def _default_to_label(discovered, repo_root):
    """Label for the default working-tree `to` side."""
    if repo_root is not None:
        branch = git_current_branch(repo_root) or "HEAD"
        try:
            return "%s @ %s (working tree)" % (branch, git_short_sha(repo_root, "HEAD"))
        except RuntimeError:
            return "%s (working tree)" % branch
    return "%s (working tree)" % (discovered or ".PLAN.md")


def _branch_token(label):
    """Short branch/marker token derived from a label (first whitespace word)."""
    if not label:
        return "to"
    return label.split()[0]


# ---------------------------------------------------------------------------
# default: plan merge <from> [--to ...] [--base ...] [-o ...]
# ---------------------------------------------------------------------------

def _merge_default(flags, output):
    """Perform a structural merge of the `from` source into `to`, writing OUT."""
    if not flags.get("merge_from"):
        _err("merge: a merge source is required "
             "(a branch, or --from <src>; use --resolve / --abort otherwise)")
        return 2

    # Hold an exclusive lock on the output for the whole read->merge->write so a
    # concurrent `plan create`/`status` (LOCK_EX on the same .PLAN.md) can't race
    # us. The output is precomputed before gathering; gather reads the default
    # `to` under the lock.
    with _OutputLock(_precompute_output_path(flags)):
        return _merge_default_locked(flags, output)


def _merge_default_locked(flags, output):
    """The locked body of _merge_default (gather -> merge -> write)."""
    gathered = _gather_merge_inputs(flags, "merge")
    if isinstance(gathered, int):
        return gathered

    output_path = gathered["output_path"]
    if output_path is None:
        _err("merge: no output file. Provide -o OUT (or --to FILE), or run "
             "inside a repo with a .PLAN.md.")
        return 2

    repo_root = gathered["repo_root"]
    state_dir = gathered["state_dir"]
    reject_file = gathered["reject_file"]

    # Guard: refuse a new merge while one is in progress for this output.
    if merge_in_progress_at(reject_file):
        _err("merge: merge already in progress for %s; run 'plan merge "
             "--resolve' or 'plan merge --abort' first" % output_path)
        return 2

    renumber = _engine_side(flags.get("renumber"))
    prefer = _engine_side(flags.get("prefer"), default=None)
    result = merge_trees(gathered["base"], gathered["mine"], gathered["theirs"],
                         renumber=renumber, prefer=prefer,
                         two_way=gathered["two_way"])

    # Always write the merged tree (conflicts default to `to` -> always valid).
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(serialize(result.project))

    in_repo = repo_root is not None

    if not result.conflicts:
        # Clean (or --prefer resolved everything).
        if in_repo and (in_merge_or_rebase(repo_root) or _want_stage(flags)):
            try:
                mark_resolved(repo_root, output_path)
            except RuntimeError:
                pass
        output.append("merge: clean — wrote %s" % output_path)
        return 0

    # --- Conflicts remain: write snapshots + options + .reject. ---
    base_text = gathered["base_text"]
    to_text = gathered["to_text"]
    from_text = gathered["from_text"]
    write_snapshots_at(state_dir, base_text, to_text, from_text)
    _write_merge_options_at(state_dir, renumber, two_way=gathered["two_way"],
                            output=output_path)

    annotate_conflict_lines(result.conflicts, to_text, from_text)
    reject_text = render_reject(
        result.conflicts,
        plan_path=output_path,
        base_label=gathered["base_label"],
        to_label=gathered["to_label"],
        from_label=gathered["from_label"],
        to_branch=gathered["to_branch"],
        from_branch=gathered["from_branch"],
        snapshot_dir=state_dir,
        plan_version=VERSION_STR,
    )
    with open(reject_file, "w", encoding="utf-8") as f:
        f.write(reject_text)

    # Git state: inside a merge/rebase, or explicit --stage, mark the index
    # unmerged. Standalone default and outside-git: do NOT touch the index.
    if in_repo and (in_merge_or_rebase(repo_root) or _want_stage(flags)):
        try:
            mark_unmerged(repo_root, output_path, base_text, to_text, from_text)
        except RuntimeError:
            pass

    # Convenience: open $EDITOR on the .reject on a TTY (does not auto-apply).
    _maybe_launch_editor(reject_file, flags)

    _err(_conflict_action_message(len(result.conflicts), reject_file))
    return 1


def _want_stage(flags):
    """True if --stage was given and --no-stage was not (explicit opt-in)."""
    if flags.get("no_stage"):
        return False
    return bool(flags.get("stage"))


# ---------------------------------------------------------------------------
# Git merge driver entry: `plan merge-driver %O %A %B %P`
# ---------------------------------------------------------------------------

def _read_file_text(path):
    """Read a file as text, mapping a missing file to '' (engine: empty => None)."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _handle_merge_driver(base_file, ours_file, theirs_file, pathname):
    """git merge driver: `plan merge-driver %O %A %B %P`. Returns an exit code.

    git invokes this during merge/rebase/cherry-pick/stash-pop for `.PLAN.md`.
    Positional args are temp files: %O=base, %A=ours/MINE (also the OUTPUT file —
    git takes its post-run contents), %B=theirs; %P is the in-repo pathname.

    Index ownership: the driver does NOT touch the git index. git records the
    path's merge state from our exit code (0 = resolved, non-zero = unmerged).
    On conflicts we write the auto-merged tree (mine defaults) into %A, drop a
    `.reject` + snapshots next to the real plan file, and exit 1 so git marks the
    path unmerged; the user then runs `plan merge --resolve` and `git add`.

    Fail-safe: any unexpected error still leaves %A as a usable plan file (the
    auto-merged or the original mine content) and exits non-zero, so git falls
    back to recording the path conflicted rather than truncating the file.
    """
    # Capture ours (%A = MINE) BEFORE we overwrite %A with the merged content.
    mine_text = _read_file_text(ours_file)
    base_text = _read_file_text(base_file)
    theirs_text = _read_file_text(theirs_file)

    # Fail-safe corner: the plan file is new on theirs and absent/empty in ours
    # (%A empty). git would otherwise call the driver with an empty %A; the
    # correct merged result is simply theirs' full content, not a skeleton
    # rebuilt from an empty mine (which would drop theirs' title/sections). Take
    # theirs verbatim and report it clean.
    if (mine_text is None or mine_text.strip() == "") and \
            theirs_text is not None and theirs_text.strip() != "":
        with open(ours_file, "w", encoding="utf-8") as f:
            f.write(theirs_text)
        return 0

    try:
        base = _parse_text_or_none(base_text)
        mine = _parse_text_or_none(mine_text)
        theirs = _parse_text_or_none(theirs_text)

        # Driver uses defaults: renumber theirs, no --prefer.
        result = merge_trees(base, mine, theirs, renumber="theirs")
    except Exception as exc:  # pragma: no cover - defensive
        # Engine failed unexpectedly: leave %A as the original mine content so
        # git has a usable (un-truncated) file, and let git mark it conflicted.
        _err("merge-driver: structural merge failed: %s" % exc)
        with open(ours_file, "w", encoding="utf-8") as f:
            f.write(mine_text)
        return 1

    # Write the merged tree (conflicts default to mine) back into %A — this is
    # the content git takes for the working tree.
    with open(ours_file, "w", encoding="utf-8") as f:
        f.write(serialize(result.project))

    if not result.conflicts:
        return 0

    # --- Conflicts: write snapshots + .reject next to the real plan file. ---
    # In driver context we only have temp files, so resolve %P to the worktree
    # plan path (cwd is the worktree during a git merge).
    try:
        repo_root = git_repo_root()
    except (RuntimeError, OSError):
        repo_root = os.getcwd()
    if os.path.isabs(pathname):
        real_plan_path = pathname
    else:
        real_plan_path = os.path.join(repo_root, pathname)

    # State lives in the per-output namespaced dir (consistent with the
    # porcelain merge), so `plan merge --resolve` finds it for this plan file.
    state_dir = merge_state_dir(real_plan_path, repo_root)
    try:
        write_snapshots_at(state_dir, base_text, mine_text, theirs_text)
        # Persist options so `plan merge --resolve` reproduces this exact merge.
        _write_merge_options_at(state_dir, "theirs", output=real_plan_path)

        annotate_conflict_lines(result.conflicts, mine_text, theirs_text)
        reject_text = render_reject(
            result.conflicts,
            plan_path=real_plan_path,
            base_label="(merge-base)",
            to_label="to (current branch)",
            from_label="from (incoming)",
            to_branch="to",
            from_branch="from",
            snapshot_dir=state_dir,
            plan_version=VERSION_STR,
        )
        rp = reject_path(real_plan_path)
        with open(rp, "w", encoding="utf-8") as f:
            f.write(reject_text)
        _err(_conflict_action_message(len(result.conflicts), rp))
    except Exception as exc:  # pragma: no cover - defensive
        # %A already holds the valid auto-merged tree; just report and let git
        # record the path unmerged on our non-zero exit.
        _err("merge-driver: could not write conflict files: %s" % exc)

    # Do NOT mark_unmerged: git records the path unmerged from our exit code.
    return 1


# ---------------------------------------------------------------------------
# resolve: the two-way structural cousin (recover from raw conflict markers)
# ---------------------------------------------------------------------------
#
# `plan resolve` is the degraded cousin of `plan merge` for a plan file that
# already contains raw git conflict markers (someone merged WITHOUT the driver).
# It reconstructs the `mine` (ours-side) and `theirs` documents — and a `base`
# document if diff3-style `|||||||` sections are present — by walking the marked
# file, then runs the SAME engine: a proper three-way merge when a base is
# available, otherwise the lossy two-way mode (a shared ID is the same node, any
# divergence conflicts). It writes the auto-merged tree (conflicts default to
# mine, markers gone) and, when conflicts remain, reuses the merge .reject flow
# so `plan merge --resolve` can finish per-field.

_RE_CONFLICT_START = re.compile(r'^<{7}(\s|$)')
_RE_CONFLICT_BASE = re.compile(r'^\|{7}(\s|$)')
_RE_CONFLICT_SEP = re.compile(r'^={7}(\s|$)')
_RE_CONFLICT_END = re.compile(r'^>{7}(\s|$)')


def _has_conflict_markers(text):
    """True if `text` contains any git conflict-start marker line."""
    for line in text.split("\n"):
        if _RE_CONFLICT_START.match(line):
            return True
    return False


def _reconstruct_sides(text):
    """Walk a marker-laden document into (mine_text, theirs_text, base_text).

    Non-conflict regions are copied into all three reconstructions. Inside each
    conflict hunk:
      - ours-side lines (between '<<<<<<<' and the base/sep marker) -> mine
      - base-side lines (diff3, between '|||||||' and '=======')    -> base
      - theirs-side lines (between '=======' and '>>>>>>>')         -> theirs

    base_text is returned as None when NO diff3 base section appeared anywhere
    (a plain 2-way conflict file); in that case the caller runs two-way mode.
    Tolerates an unterminated final hunk (best-effort).
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    mine, theirs, base = [], [], []
    saw_base_section = False

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _RE_CONFLICT_START.match(line):
            # Enter a conflict hunk. Collect the three regions.
            ours_lines, base_lines, theirs_lines = [], [], []
            section = "ours"
            i += 1
            while i < n:
                cur = lines[i]
                if _RE_CONFLICT_BASE.match(cur):
                    section = "base"
                    saw_base_section = True
                    i += 1
                    continue
                if _RE_CONFLICT_SEP.match(cur):
                    section = "theirs"
                    i += 1
                    continue
                if _RE_CONFLICT_END.match(cur):
                    i += 1
                    break
                if section == "ours":
                    ours_lines.append(cur)
                elif section == "base":
                    base_lines.append(cur)
                else:
                    theirs_lines.append(cur)
                i += 1
            mine.extend(ours_lines)
            theirs.extend(theirs_lines)
            # Diff3 base content belongs to the reconstructed base; for a plain
            # 2-way hunk (no base section) the base simply has neither side.
            base.extend(base_lines)
            continue

        # Ordinary (non-conflict) line: shared by all reconstructions.
        mine.append(line)
        theirs.append(line)
        base.append(line)
        i += 1

    mine_text = "\n".join(mine)
    theirs_text = "\n".join(theirs)
    base_text = "\n".join(base) if saw_base_section else None
    return mine_text, theirs_text, base_text


def _handle_resolve(plan_path, raw_text, output):
    """Recover a plan file containing raw git conflict markers. Returns an exit code.

    Self-contained: reads nothing else, does its own file writes, returns
    0/1/2. main() calls sys.exit() on the result.

      0 — no markers (nothing to do) OR markers reconciled cleanly.
      1 — markers reconciled but field conflicts remain (file cleaned to
          mine-defaults + .reject written; finish with `plan merge --resolve`).
      2 — a .reject merge is already in progress, or a hard error (parse,
          no git repo when conflicts need snapshots).
    """
    if raw_text is None:
        raw_text = ""

    # No conflict markers -> nothing to resolve (keep historical behavior).
    if not _has_conflict_markers(raw_text):
        output.append("OK: no conflicts found")
        return 0

    # Refuse if a structured merge is already mid-flight (its .reject is the
    # source of truth; mixing the two would corrupt state).
    if merge_in_progress(plan_path):
        _err("resolve: a merge is already in progress; finish it with "
             "'plan merge --resolve' or 'plan merge --abort' first")
        return 2

    # Reconstruct the sides from the markers.
    mine_text, theirs_text, base_text = _reconstruct_sides(raw_text)

    try:
        mine = _parse_text_or_none(mine_text)
        theirs = _parse_text_or_none(theirs_text)
        base = _parse_text_or_none(base_text)
    except Exception as exc:
        _err("resolve: could not parse reconstructed sides: %s" % exc)
        return 2

    # With a diff3 base -> proper three-way; otherwise lossy two-way.
    two_way = base is None
    try:
        if two_way:
            result = merge_trees(None, mine, theirs, two_way=True)
        else:
            result = merge_trees(base, mine, theirs)
    except Exception as exc:
        _err("resolve: structural merge failed: %s" % exc)
        return 2

    # Primary goal: write the auto-merged tree (markers gone -> valid file).
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write(serialize(result.project))

    mode_note = ("two-way recovery (no merge-base; add/delete cannot be "
                 "distinguished — best-effort, lossy)" if two_way
                 else "three-way recovery (using the diff3 base)")

    if not result.conflicts:
        output.append("resolve: %s — reconciled cleanly; wrote %s "
                      "(conflict markers removed)." % (mode_note, plan_path))
        return 0

    # Conflicts remain: reuse the structured .reject flow so the user can finish
    # per-field with `plan merge --resolve`. This needs a git repo for snapshots.
    try:
        repo_root = git_repo_root(os.path.dirname(os.path.abspath(plan_path)))
    except RuntimeError:
        # No repo: we still cleaned the file to mine-defaults; we just can't
        # offer the per-field resolution workflow.
        output.append(
            "resolve: %s — wrote %s with %d field(s) defaulted to your side "
            "(no git repo, so per-field resolution is unavailable; review the "
            "merged result)."
            % (mode_note, plan_path, len(result.conflicts)))
        return 1

    # Use the per-output namespaced state dir (consistent with porcelain merge),
    # so `plan merge --resolve` finds the snapshots/options for this plan file.
    state_dir = merge_state_dir(plan_path, repo_root)
    write_snapshots_at(state_dir, base_text or "", mine_text, theirs_text)
    _write_merge_options_at(state_dir, "theirs", two_way=two_way, output=plan_path)

    annotate_conflict_lines(result.conflicts, mine_text, theirs_text)
    reject_text = render_reject(
        result.conflicts,
        plan_path=plan_path,
        base_label="(reconstructed)" if not two_way else "(none — two-way)",
        to_label="to (ours, from conflict markers)",
        from_label="from (theirs, from conflict markers)",
        to_branch="to",
        from_branch="from",
        snapshot_dir=state_dir,
        plan_version=VERSION_STR,
    )
    rp = reject_path(plan_path)
    with open(rp, "w", encoding="utf-8") as f:
        f.write(reject_text)

    _err(
        "resolve: %s.\n"
        "  %d field(s) could not be auto-resolved (defaulted to your side).\n"
        "  Wrote %s — run 'plan merge --resolve' to choose per-field, or\n"
        "  'plan merge --abort' to keep the current file."
        % (mode_note, len(result.conflicts), rp))
    return 1
