# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    """Main entry point."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        output = []
        _handle_help(output)
        for line in output:
            print(line)
        return

    # Handle --version anywhere in argv
    if "--version" in argv:
        print(f"{VERSION_STR} {VERSION_DATE}")
        return

    # Handle install/uninstall before parsing (no plan file needed)
    if argv[0] == "install":
        if len(argv) < 2:
            raise SystemExit("Error: install requires 'local' or 'user' argument")
        _handle_install(argv[1])
        return
    if argv[0] == "uninstall":
        if len(argv) < 2:
            raise SystemExit("Error: uninstall requires 'local' or 'user' argument")
        _handle_uninstall(argv[1])
        return

    # Parse requests
    requests = parse_argv(argv)

    # Extract file flag from first request (flags are global)
    flags = {}
    for req in requests:
        flags.update(req.flags)

    # Check for help-only requests
    for req in requests:
        if req.command is not None and req.command[0] in ("help", "h"):
            output = []
            topic = req.command[1][0] if req.command[1] else None
            _handle_help(output, command=topic)
            for line in output:
                print(line)
            return

    # Discover file
    filepath = discover_file(flags)
    abs_filepath = os.path.abspath(filepath)
    plan_dir = os.path.dirname(abs_filepath)
    plan_filename = os.path.basename(abs_filepath)

    # Handle --abort before acquiring flock (it only touches temp files)
    for req in requests:
        if (req.command is not None and req.command[0] == "edit"
                and req.flags.get("abort")):
            cmd_args = req.command[1]
            _handle_edit_abort(cmd_args, plan_dir, plan_filename)
            return

    # Determine if all requests are read-only
    # edit --start is NOT read-only (it reads plan data to export)
    # edit --accept is NOT read-only (it modifies the plan)
    # edit --abort is handled above (before flock)
    is_read_only = all(
        (req.command is not None and req.command[0] in {"check", "help", "h"}) or
        (req.command is None and req.verb in ("get", "list"))
        for req in requests
    )

    # Acquire file lock for the duration of execution (if flock available)
    lock_fd = None
    try:
        if _has_flock and (os.path.exists(filepath) or not is_read_only):
            lock_fd = open(filepath, "a")
            lock_mode = fcntl.LOCK_SH if is_read_only else fcntl.LOCK_EX
            for _attempt in range(20):
                try:
                    fcntl.flock(lock_fd, lock_mode | fcntl.LOCK_NB)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise SystemExit(
                    f"Error: could not acquire lock on {filepath} "
                    f"(timed out after 2 seconds)")

        # Read file or bootstrap
        file_exists = os.path.exists(filepath)
        if not file_exists or os.path.getsize(filepath) == 0:
            if is_read_only:
                raise SystemExit(f"Error: file not found: {filepath}")
            text = ""
        else:
            text = open(filepath).read()

        # Check for resolve command (works on raw text, not parsed)
        for req in requests:
            if req.command is not None and req.command[0] == "resolve":
                output = []
                result_text = _handle_resolve(None, output, filepath=filepath,
                                               raw_text=text)
                for line in output:
                    print(line)
                if result_text is not None:
                    with open(filepath, "w") as f:
                        f.write(result_text)
                return

        # Parse document
        project = parse(text)
        if not project.title:
            _bootstrap_project(project)

        # Store plan directory and filename on project for handlers to access
        project._plan_dir = plan_dir
        project._plan_filename = plan_filename

        # Dispatch all requests
        output = []
        modified = False
        for req in requests:
            result = dispatch(project, req, output)
            if result:
                modified = True

        # Print output
        for line in output:
            print(line)

        # Write back if modified
        if modified:
            out_text = serialize(project)
            with open(filepath, "w") as f:
                f.write(out_text)
    finally:
        if lock_fd is not None:
            lock_fd.close()


if __name__ == "__main__":
    main()
