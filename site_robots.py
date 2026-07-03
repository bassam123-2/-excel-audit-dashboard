"""Search-engine exclusion constants (no Django dependency)."""

ROBOTS_META_CONTENT = "noindex, nofollow, noarchive, nosnippet"

ROBOTS_HTTP_HEADER_VALUE = ROBOTS_META_CONTENT

ROBOTS_META_HTML = (
    f'  <meta name="robots" content="{ROBOTS_META_CONTENT}" />\n'
    f'  <meta name="googlebot" content="{ROBOTS_META_CONTENT}" />\n'
)

ROBOTS_TXT = "User-agent: *\nDisallow: /\n"
