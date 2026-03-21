# ---------------------------------------------------------------------------
# CLI Parser
# ---------------------------------------------------------------------------

COMMANDS = {"create", "edit",
            "check", "fix", "resolve", "help", "h"}
SELECTORS = {"comment", "attr", "project", "id"}  # bare ints detected by isdigit()
VERBS = {"get", "list", "ls", "replace", "add", "+", "del", "mod", "~",
         "link", "unlink", "next", "status", "close", "reopen", "move"}

def _parse_id_arg(arg):
    """Parse a ticket ID from a CLI argument.

    Accepts bare integer N only.  Returns the ID string or None.
    """
    if arg.isdigit():
        return arg
    return None


class ParsedRequest:
    """A single parsed request from the command line."""
    def __init__(self):
        self.verb = None           # str or None
        self.command = None        # (name, args_list) or None
        self.selector_type = None  # "comment" | "attr" | "project" | None
        self.selector_args = []    # e.g. ["assignee"] for attr, ["description"] for project
        self.pipeline = []         # ordered steps: ("id",val) | ("q",expr) | ("r",) | ("p",)
        self.flags = {}            # --force, -r, -n, -q, --format, --file, etc.
        self.verb_args = []        # arguments to the verb

    @property
    def targets(self):
        """Extract bare ticket IDs from pipeline (backward compat)."""
        return [s[1] for s in self.pipeline if s[0] == "id"]


def parse_argv(argv):
    """Parse command-line arguments into a list of ParsedRequest.

    --file/-f is a global flag extracted before splitting by ';'.
    """
    # Extract global --file/-f before splitting
    file_path = None
    filtered = []
    i = 0
    n = len(argv)
    while i < n:
        if argv[i] in ("--file", "-f") and i + 1 < n:
            if file_path is not None:
                raise SystemExit("Error: --file/-f specified more than once")
            file_path = argv[i + 1]
            i += 2
        else:
            filtered.append(argv[i])
            i += 1

    groups = _split_on_semicolons(filtered)
    requests = []
    for group in groups:
        req = _parse_single_request(group)
        if file_path is not None:
            req.flags["file"] = file_path
        requests.append(req)
    return requests


def _split_on_semicolons(argv):
    """Split argv list on ';' tokens."""
    groups = []
    current = []
    for arg in argv:
        if arg == ";":
            if current:
                groups.append(current)
            current = []
        else:
            current.append(arg)
    if current:
        groups.append(current)
    return groups if groups else [[]]


def _parse_flag(argv, i, n, req):
    """Try to parse a flag at position i. Returns new i if consumed, else None."""
    arg = argv[i]
    if arg == "--force":
        req.flags["force"] = True
        return i + 1
    if arg in ("-r", "--recursive"):
        req.flags["recursive"] = True
        req.pipeline.append(("r",))
        return i + 1
    if arg in ("-p", "--parent"):
        req.flags["parent"] = True
        return i + 1
    if arg in ("-h", "--help"):
        req.flags["help"] = True
        return i + 1
    if arg == "-n" and i + 1 < n:
        req.flags["n"] = int(argv[i + 1])
        return i + 2
    if arg == "-q" and i + 1 < n:
        req.flags.setdefault("q", []).append(argv[i + 1])
        req.pipeline.append(("q", argv[i + 1]))
        return i + 2
    if arg == "--format" and i + 1 < n:
        req.flags["format"] = argv[i + 1]
        return i + 2
    if arg == "--title" and i + 1 < n:
        req.flags["title"] = argv[i + 1]
        return i + 2
    if arg == "--text" and i + 1 < n:
        req.flags["text"] = argv[i + 1]
        return i + 2
    if arg == "--attr" and i + 1 < n:
        req.flags["attr_filter"] = argv[i + 1]
        return i + 2
    if arg == "--quiet":
        req.flags["quiet"] = True
        return i + 1
    if arg in ("-e", "--edit"):
        req.flags["edit"] = True
        return i + 1
    if arg == "--start":
        req.flags["start"] = True
        return i + 1
    if arg == "--restart":
        req.flags["restart"] = True
        return i + 1
    if arg == "--accept":
        req.flags["accept"] = True
        return i + 1
    if arg == "--abort":
        req.flags["abort"] = True
        return i + 1
    return None


def _parse_single_request(argv):
    """Parse a single request (no semicolons).

    Two paths:
    1. If the first non-flag token is a command → command dispatch.
       Commands must be the first word.
    2. Otherwise → normal scanning for verbs, selectors, pipeline steps.
    """
    req = ParsedRequest()
    i = 0
    n = len(argv)

    # Consume leading flags
    while i < n:
        new_i = _parse_flag(argv, i, n, req)
        if new_i is not None:
            i = new_i
        else:
            break

    # Path 1: First content token is a command
    if i < n and argv[i] in COMMANDS:
        return _parse_command(argv, i, n, req)

    # Path 2: Normal scanning (verbs, selectors, pipeline)
    while i < n:
        arg = argv[i]

        # --- Flags (can appear anywhere) ---
        new_i = _parse_flag(argv, i, n, req)
        if new_i is not None:
            i = new_i
            continue

        # --- Verbs ---
        if arg in VERBS:
            if req.verb is not None:
                raise SystemExit(
                    f"Error: multiple verbs: '{req.verb}' and '{arg}'")
            req.verb = {"+": "add", "~": "mod", "ls": "list"}.get(arg, arg)
            i += 1
            # Consume verb arguments
            if req.verb in ("replace", "add", "mod"):
                if i < n and not _is_keyword(argv[i]):
                    req.verb_args.append(argv[i])
                    i += 1
            elif req.verb == "list":
                if i < n and argv[i] == "order":
                    req.verb_args.append(argv[i])
                    i += 1
            elif req.verb in ("link", "unlink"):
                while i < n and len(req.verb_args) < 2:
                    a = argv[i]
                    if _is_keyword(a) or a.startswith("-"):
                        break
                    req.verb_args.append(a)
                    i += 1
            elif req.verb in ("status", "close"):
                while i < n:
                    a = argv[i]
                    if _is_keyword(a) or a.startswith("-"):
                        break
                    id_val = _parse_id_arg(a)
                    if id_val is not None:
                        req.pipeline.append(("id", id_val))
                        i += 1
                        continue
                    # First non-integer is the status value
                    if not req.verb_args:
                        req.verb_args.append(a)
                        i += 1
                    break
            elif req.verb == "move":
                _MOVE_DIRS = {"first", "last", "before", "after"}
                while i < n:
                    a = argv[i]
                    if a in _MOVE_DIRS:
                        req.verb_args.append(a)
                        i += 1
                        # Read destination (bare int) after direction
                        if i < n:
                            dest_id = _parse_id_arg(argv[i])
                            if dest_id is not None:
                                req.verb_args.append(argv[i])
                                i += 1
                        break
                    dest_id = _parse_id_arg(a)
                    if dest_id is not None:
                        req.pipeline.append(("id", dest_id))
                        i += 1
                        continue
                    if _is_keyword(a) or a.startswith("-"):
                        break
                    break
            continue

        # --- Bare integer (selector: ticket ID) ---
        id_val = _parse_id_arg(arg)
        if id_val is not None:
            if req.selector_type == "project":
                raise SystemExit(
                    "Error: cannot mix ticket IDs with 'project' selector")
            req.pipeline.append(("id", id_val))
            i += 1
            continue

        # --- Named selectors ---
        if arg in SELECTORS:
            if arg == "comment":
                if req.selector_type not in (None, "comment"):
                    raise SystemExit(
                        f"Error: cannot mix selector types: "
                        f"'{req.selector_type}' and 'comment'")
                req.selector_type = "comment"
                i += 1
                continue

            if arg == "attr":
                if req.selector_type not in (None, "attr"):
                    raise SystemExit(
                        f"Error: cannot mix selector types: "
                        f"'{req.selector_type}' and 'attr'")
                req.selector_type = "attr"
                i += 1
                # Consume attr name — any non-flag token (even keywords
                # like "status" can be attribute names)
                if i < n and not argv[i].startswith("-"):
                    req.selector_args.append(argv[i])
                    i += 1
                continue

            if arg == "project":
                if any(s[0] == "id" for s in req.pipeline):
                    raise SystemExit(
                        "Error: cannot mix ticket IDs with 'project' selector")
                if req.selector_type not in (None, "project"):
                    raise SystemExit(
                        f"Error: cannot mix selector types: "
                        f"'{req.selector_type}' and 'project'")
                req.selector_type = "project"
                i += 1
                # Section name — don't consume verbs/selectors/flags
                if i < n and not _is_keyword(argv[i]):
                    req.selector_args.append(argv[i])
                    i += 1
                continue

            if arg == "id":
                if req.selector_type not in (None, "id"):
                    raise SystemExit(
                        f"Error: cannot mix selector types: "
                        f"'{req.selector_type}' and 'id'")
                req.selector_type = "id"
                i += 1
                # Node ID — any non-flag token (keywords like "project"
                # are valid node IDs)
                if i < n and not argv[i].startswith("-"):
                    req.selector_args.append(argv[i])
                    i += 1
                continue

        # --- Verb arg that landed after flags ---
        if req.verb in ("replace", "add", "mod") and not req.verb_args:
            req.verb_args.append(arg)
            i += 1
            continue
        if req.verb in ("link", "unlink") and len(req.verb_args) < 2:
            req.verb_args.append(arg)
            i += 1
            continue
        if req.verb in ("status", "close") and not req.verb_args:
            id_val = _parse_id_arg(arg)
            if id_val is not None:
                req.pipeline.append(("id", id_val))
            else:
                req.verb_args.append(arg)
            i += 1
            continue

        # --- Implicit query ---
        _validate_implicit_q(arg)
        req.flags.setdefault("q", []).append(arg)
        req.pipeline.append(("q", arg))
        i += 1
        continue

    # --- Post-parse ---
    # -h flag converts to help command
    if req.flags.get("help"):
        if req.verb:
            req.command = ("help", [req.verb])
        elif req.selector_type:
            req.command = ("help", [req.selector_type])
        else:
            req.command = ("help", [])
        return req

    # Default verb is 'get' when no command present
    if req.verb is None:
        req.verb = "get"

    # Validation
    if req.verb in ("list", "next") and req.selector_type in ("comment", "attr"):
        raise SystemExit(
            f"Error: '{req.verb}' verb cannot be used with "
            f"'{req.selector_type}' selector")

    return req


def _parse_command(argv, i, n, req):
    """Parse a command starting at position i.

    Commands consume all remaining non-flag tokens as arguments.
    """
    cmd = argv[i]
    i += 1
    cmd_args = []

    if cmd in ("help", "h"):
        # help takes one optional topic
        while i < n:
            new_i = _parse_flag(argv, i, n, req)
            if new_i is not None:
                i = new_i
                continue
            if not cmd_args:
                cmd_args.append(argv[i])
                i += 1
            else:
                break
        req.command = ("help", cmd_args)

    elif cmd in ("check", "fix", "resolve"):
        req.command = (cmd, [])

    else:
        # create, edit: consume all remaining non-flag tokens
        while i < n:
            new_i = _parse_flag(argv, i, n, req)
            if new_i is not None:
                i = new_i
                continue
            cmd_args.append(argv[i])
            i += 1
        req.command = (cmd, cmd_args)

    # -h flag converts to help about this command
    if req.flags.get("help") and req.command[0] not in ("help", "h"):
        req.command = ("help", [req.command[0]])

    return req


def _validate_implicit_q(arg):
    """Validate an implicit query argument.

    Bare identifiers must be known DSL names; compound expressions must
    reference at least one known DSL name (to catch typos like 'qwe == asd'
    where DefaultNamespace returns '' for both sides).
    """
    known_lower = sorted(n for n in DSL_FILTER_NAMES if n[0].islower())
    if not arg.isidentifier():
        # Compound expression — compile and check referenced names
        try:
            code = compile(arg, "<query>", "eval")
        except SyntaxError as e:
            raise SystemExit(
                f"Error: invalid filter expression: {arg}\n  {e.msg}")
        unknown = [n for n in code.co_names if n not in DSL_FILTER_NAMES]
        if len(unknown) > 1 and not any(
                n in DSL_FILTER_NAMES for n in code.co_names):
            raise SystemExit(
                f"Error: unknown name(s) in filter: {', '.join(unknown)}\n"
                f"  Known: {', '.join(known_lower)}"
            )
        return
    if arg not in DSL_FILTER_NAMES:
        if arg in COMMANDS:
            raise SystemExit(
                f"Error: '{arg}' is a command and must be the first word\n"
                f"  Usage: plan {arg} ..."
            )
        raise SystemExit(
            f"Error: unknown filter name: {arg}\n"
            f"  Known: {', '.join(known_lower)}"
        )


def _is_keyword(arg):
    """Check if arg is a known selector, verb, or flag keyword.

    Commands are not included — they are only valid as the first word.
    """
    return arg in SELECTORS or arg in VERBS or arg in (
        "--force", "-r", "--recursive", "-n", "-q", "--format",
        "--title", "--text", "--attr", "-p", "--parent", "-h", "--help",
        "-e", "--edit", "--quiet",
        "--start", "--restart", "--accept", "--abort",
    )
