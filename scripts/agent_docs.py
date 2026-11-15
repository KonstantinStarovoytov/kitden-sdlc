"""The one client for Agent Docs, the owner's search over the docs of Claude Code, Codex and
Cursor.

The Cohere key costs the owner money. It goes only to HOST, only over https, only in the
X-Cohere-Api-Key header of a /search request. It is never in an address, a printed line,
an error message or repr(). The host is a constant; nothing passed in can change it, and no
redirect is followed. A failed call prints one line: the status code or the error's class
name, never the answer.
"""

import json
import sys
import time
import urllib.error
import urllib.request

from doc_address import USER_AGENT, allowed, load_hosts

HOST = "agent-docs-mcp.onrender.com"
SEARCH = f"https://{HOST}/search"
HEALTH = f"https://{HOST}/health"
OPENAPI = f"https://{HOST}/openapi.json"
KEY_HEADER = "X-Cohere-Api-Key"
PRODUCTS = ("claude-code", "codex", "cursor", "mcp")
TIMEOUT = 15
TRIES = 2
LIMIT = 1024 * 1024
QUERY_MAX = 500
PASSAGES = 3
TEXT_MAX = 1500
WAKE_FOR = 90
WAKE_PAUSE = 5


class _Refuse(urllib.request.HTTPRedirectHandler):
    """Follows no redirect: urllib then raises HTTPError with the 3xx code."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_opener(*handlers) -> urllib.request.OpenerDirector:
    """A urllib opener that follows no redirect. `handlers` go in too: tests use them to
    answer without the network."""
    return urllib.request.build_opener(_Refuse(), *handlers)


def _follows_redirects(opener) -> bool:
    redirects = [h for h in opener.handlers
                 if isinstance(h, urllib.request.HTTPRedirectHandler)]
    return not redirects or any(not isinstance(h, _Refuse) for h in redirects)


def _is_timeout(err: BaseException) -> bool:
    return isinstance(err, TimeoutError) or (
        isinstance(err, urllib.error.URLError) and isinstance(err.reason, TimeoutError))


def _why(err: BaseException) -> str:
    """The status code of an HTTP error, or the error's class name: never its message."""
    if isinstance(err, urllib.error.HTTPError):
        return str(err.code)
    return type(err).__name__


def _say(what: str, why: str) -> None:
    print(f"Agent Docs {what} failed: {why}", file=sys.stderr)


class _BadAnswer(ValueError):
    """The answer was not 200, was over 1 MB, was not JSON or had another shape."""


def _passages(doc, hosts) -> list[dict]:
    """The passages of a /search answer whose address is a doc address, at most three."""
    if not isinstance(doc, dict) or not isinstance(doc.get("passages"), list):
        raise _BadAnswer("the answer has another shape")
    found = []
    for item in doc["passages"]:
        if not isinstance(item, dict) or not all(
                isinstance(item.get(name), str) for name in ("url", "heading", "content")):
            raise _BadAnswer("a passage has another shape")
        if allowed(item["url"], hosts):
            found.append({"url": item["url"], "heading": item["heading"],
                          "text": item["content"][:TEXT_MAX]})
    return found[:PASSAGES]


def _names_product(doc) -> bool:
    """Whether the /search request schema in an OpenAPI document has a `product` property."""
    schema = doc["paths"]["/search"]["post"]["requestBody"]["content"]["application/json"][
        "schema"]
    ref = schema.get("$ref")
    if ref is not None:
        name = ref.removeprefix("#/components/schemas/")
        schema = doc["components"]["schemas"][name]
    properties = schema["properties"]
    return isinstance(properties, dict) and "product" in properties


class Search:
    """Searches Agent Docs with the caller's Cohere key.

    `asked` counts calls to search() and `failed` those that got no answer. wake() and
    has_product() send no key and are not counted.
    """

    def __init__(self, key: str, opener=None, sleep=time.sleep):
        # Printable ASCII only: anything else cannot go in a header. The message leaves the
        # key out.
        if not isinstance(key, str) or not key or any(not "!" <= c <= "~" for c in key):
            raise ValueError("the Cohere key is empty or has a character a header cannot carry")
        if opener is not None and _follows_redirects(opener):
            raise ValueError("the opener must come from agent_docs.make_opener: "
                             "it follows no redirect")
        self._key = key
        self._opener = opener or make_opener()
        self._sleep = sleep
        self._hosts = load_hosts()
        self.asked = 0
        self.failed = 0

    def __repr__(self) -> str:
        return f"Search(host={HOST!r}, asked={self.asked}, failed={self.failed})"

    def _send(self, address: str, data: bytes | None = None):
        """Read one answer from `address`, one of this module's own addresses. The only
        place a request is made, and the only place the key is added: to /search alone.

        The body, at most 1 MB. Raises on any failure; a /search timeout is tried twice.
        """
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        # The address is one of the https constants above.
        request = urllib.request.Request(address, data=data, headers=headers)  # noqa: S310
        if address == SEARCH:
            # Kept out of any redirect, though the opener follows none.
            request.add_unredirected_header(KEY_HEADER, self._key)
        # wake() has its own loop, and has_product() reads once.
        tries = TRIES if address == SEARCH else 1
        for attempt in range(tries):
            try:
                with self._opener.open(request, timeout=TIMEOUT) as resp:
                    if resp.status != 200:
                        raise urllib.error.HTTPError(address, resp.status, "", None, None)
                    body = resp.read(LIMIT + 1)
                break
            except Exception as err:
                if isinstance(err, urllib.error.HTTPError):
                    err.close()
                if attempt + 1 < tries and _is_timeout(err):
                    continue
                raise
        if len(body) > LIMIT:
            raise _BadAnswer("the answer is over 1 MB")
        return body

    def search(self, query: str, product: str) -> list[dict]:
        """At most three passages, each {"url", "heading", "text"}, for `query` in the docs
        of `product`. [] on any failure, counted in `failed`. Never raises."""
        self.asked += 1
        try:
            if product not in PRODUCTS:
                raise _BadAnswer("unknown product")
            if not isinstance(query, str) or not query.strip():
                raise _BadAnswer("empty query")
            data = json.dumps({"query": query.strip()[:QUERY_MAX], "limit": PASSAGES,
                               "product": product}).encode()
            return _passages(json.loads(self._send(SEARCH, data)), self._hosts)
        except Exception as err:
            self.failed += 1
            _say("search", _why(err))
            return []

    def wake(self) -> bool:
        """Ask /health, without the key, until it answers 200 or 90 seconds have passed.
        Never raises."""
        start = time.monotonic()
        waited = 0
        while True:
            try:
                self._send(HEALTH)
                return True
            except Exception as err:
                why = _why(err)
            if waited >= WAKE_FOR or time.monotonic() - start >= WAKE_FOR:
                _say("wake", why)
                return False
            try:
                self._sleep(WAKE_PAUSE)
            except Exception as err:
                _say("wake", _why(err))
                return False
            waited += WAKE_PAUSE

    def has_product(self) -> bool:
        """Whether the server's /search takes `product`, from its /openapi.json, read once
        without the key. False on any failure."""
        try:
            return _names_product(json.loads(self._send(OPENAPI)))
        except Exception as err:
            _say("openapi read", _why(err))
            return False
