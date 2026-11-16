"""One check for every doc address a watcher script reads.

An address is read only when it is https, on a host in config/doc-hosts.yml, and its path
starts with that host's path. It may not carry a query, a port or a user. A redirect is
followed only to an address that passes the same check.

It also holds what every script uses to show a doc address or a heading from outside, so a
script that cannot import watch_sources.py (which imports it) has them too.
"""

import re
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config" / "doc-hosts.yml"
USER_AGENT = "kitden-sdlc-watcher (+https://github.com/KonstantinStarovoytov/kitden-sdlc)"
TIMEOUT = 20
LIMIT = 2 * 1024 * 1024
REDIRECTS = (301, 302, 303, 307, 308)
HEADING_MAX = 80
HEADING_MARKS = " -_.,:()/"
# An address is shown only with these characters: none of them can break a table cell or a
# code span.
SHOWABLE = re.compile(r"https://[A-Za-z0-9._~:/%@!$&'()*+,;=-]+")
# The clients whose doc text is not given to a model or kept in a file, until the owner
# answers question 4 of the spec (docs/superpowers/specs/2026-11-15-agent-docs-design.md):
# Cursor's terms forbid to reproduce its docs. The watcher still reads their pages and keeps
# hashes only.
NO_TEXT_CLIENTS = ("cursor",)


def load_hosts(path=CONFIG) -> list[tuple[str, str]]:
    """The (host, path_start) pairs in the config, with the host in lower case.

    Raises ValueError when a path does not start and end with "/": "/docs" would also allow
    "/docsx".
    """
    with open(path, encoding="utf-8") as f:
        entries = yaml.safe_load(f)
    pairs = [(str(e["host"]).lower(), str(e["path"])) for e in entries]
    for host, start in pairs:
        if not (start.startswith("/") and start.endswith("/")):
            raise ValueError(f"path for {host} must start and end with '/': {start}")
    return pairs


def allowed(address: str, hosts) -> bool:
    """Whether `address` is an https address on a listed host under that host's path."""
    # Only printable ASCII: no space, no DEL, no control or non-ASCII character such as U+202E.
    if not isinstance(address, str) or any(not "!" <= c <= "~" or c == "\\" for c in address):
        return False
    try:
        parts = urllib.parse.urlsplit(address)
    except ValueError:
        return False
    if parts.scheme != "https" or "?" in address or not parts.netloc:
        return False
    # The whole netloc must be the host: this refuses a user, a password and any port.
    netloc = parts.netloc.lower()
    # A ".." or "." step could climb out of the allowed path once the server cleans it up.
    steps = urllib.parse.unquote(parts.path).split("/")
    if "." in steps or ".." in steps:
        return False
    return any(netloc == host.lower() and parts.path.startswith(start)
               for host, start in hosts)


class _Follow(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to an allowed address; any other raises before the request."""

    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl, self.hosts):
            raise ValueError(f"redirected to an address that is not allowed: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Stop(urllib.request.HTTPRedirectHandler):
    """Hands back the redirect answer itself, so nothing is followed."""

    def _stop(self, req, fp, code, msg, headers):
        return fp

    http_error_301 = http_error_302 = http_error_303 = _stop
    http_error_307 = http_error_308 = _stop


def make_opener(hosts, follow: bool, *handlers) -> urllib.request.OpenerDirector:
    """A urllib opener that follows only allowed redirects, or with `follow` false, none.

    `handlers` go in too: tests use them to answer without the network.
    """
    redirects = _Follow(hosts) if follow else _Stop()
    return urllib.request.build_opener(redirects, *handlers)


def _open(address: str, hosts, opener):
    if not allowed(address, hosts):
        raise ValueError(f"address is not allowed: {address}")
    # `allowed` has just checked the address is https.
    request = urllib.request.Request(address, headers={"User-Agent": USER_AGENT})  # noqa: S310
    return opener.open(request, timeout=TIMEOUT)


def read(address: str, hosts, opener=None) -> tuple[str, str, str]:
    """The body, the content type and the address read from, after allowed redirects.

    Raises ValueError for an address, or a redirect, that is not allowed, and OSError when
    the read fails: an HTTP error, a timeout, or a body over 2 MB.

    The 20 second timeout is the limit for one socket operation (connecting, or one wait for
    data), not for the whole read. A slow server can take longer in all; the 2 MB cap is what
    bounds the rest.
    """
    opener = opener or make_opener(hosts, True)
    with _open(address, hosts, opener) as resp:
        final = resp.geturl()
        if not allowed(final, hosts):
            raise ValueError(f"ended at an address that is not allowed: {final}")
        body = resp.read(LIMIT + 1)
        if len(body) > LIMIT:
            raise OSError(f"page is over {LIMIT} bytes: {final}")
        charset = resp.headers.get_content_charset() or "utf-8"
        try:
            text = body.decode(charset, errors="replace")
        except LookupError:
            # The server named a charset Python does not know: read it as utf-8.
            text = body.decode("utf-8", errors="replace")
        return text, resp.headers.get_content_type(), final


def location(address: str, hosts, opener=None) -> str | None:
    """Ask for `address` once, without following a redirect. The redirect's target when it
    is allowed, else None. Raises like `read`."""
    opener = opener or make_opener(hosts, False)
    with _open(address, hosts, opener) as resp:
        target = resp.headers.get("Location") if resp.status in REDIRECTS else None
    if not target:
        return None
    target = urllib.parse.urljoin(address, target)
    return target if allowed(target, hosts) else None


def clean_heading(text: str) -> str:
    """Letters, digits, spaces and -_.,:()/ only, at most 80 characters."""
    kept = "".join(" " if c.isspace() else c for c in text
                   if c.isalnum() or c in HEADING_MARKS or c.isspace())
    return " ".join(kept.split())[:HEADING_MAX].strip()


def page_of(url, hosts) -> str:
    """The page of a passage's address, without its fragment and `.md`, when it may be
    shown; else ""."""
    if not isinstance(url, str) or not allowed(url, hosts):
        return ""
    page = urllib.parse.urldefrag(url).url.removesuffix(".md")
    if not SHOWABLE.fullmatch(page) or not allowed(page, hosts):
        return ""
    return page
