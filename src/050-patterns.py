# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

RE_PROJECT = re.compile(r'^#\s+(.+?)\s*\{#project\}\s*$')
RE_SECTION = re.compile(r'^##\s+(.+?)\s*\{#([^}]+)\}\s*$')
_RE_TICKET_CORE = r'(?!Comments\s)(?:Ticket:\s*)?(?:(?P<type>[^:]+?):\s+)?(?P<title>.+?)'
RE_TICKET  = re.compile(
    r'^(?P<bullet>\s*\*\s+)##\s+' + _RE_TICKET_CORE + r'\s*\{#(?P<id>\d+)\}\s*$'
)
RE_TICKET_BULK = re.compile(
    r'^(?P<bullet>\s*\*\s+)##\s+' + _RE_TICKET_CORE + r'\s*(?:\{#(?P<id>[a-zA-Z0-9_-]+)\})?\s*$'
)
RE_TICKET_HEADER = re.compile(
    r'##\s+' + _RE_TICKET_CORE + r'\s*\{#\d+\}\s*$'
)
RE_COMMENTS = re.compile(
    r'^(\s*\*\s+)##\s+Comments\s*\{#([^}]+)\}\s*$'
)
RE_COMMENT = re.compile(
    r'^(\s*\*\s+)(.+?)\s*\{#([^}]+)\}\s*$'
)
RE_ATTR = re.compile(r'^(\s+)(\S+):\s?(.*?)\s*$')
