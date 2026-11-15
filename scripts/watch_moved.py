"""Find the list's doc pages that moved.

Agent Docs keeps a manifest of every doc page it holds. A list address that is not in it has
moved or is gone. Each such address is asked for once, without following a redirect:

- moved: it redirects to an allowed address; `to` is that address.
- maybe: no redirect, but the manifest has a page on the same host with the same last path
  part; `to` is that page.
- absent: neither; `to` is "".

Only the manifest's addresses are read, never what it says about a page.
"""

import json
import urllib.parse

from doc_address import allowed


def manifest_addresses(body: str) -> set[str]:
    """The addresses in a manifest: the keys of its `documents`.

    Raises ValueError when the body is not JSON shaped {"documents": {...}}.
    """
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get("documents"), dict):
        raise ValueError("manifest must be an object with a 'documents' object")
    return set(data["documents"])


def _bare(address: str) -> str:
    return address.removesuffix(".md")


def _last_part(address: str) -> str:
    return urllib.parse.urlsplit(address).path.rstrip("/").rsplit("/", 1)[-1]


def _maybe(address: str, manifest: list[str]) -> str:
    host = urllib.parse.urlsplit(address).netloc.lower()
    last = _last_part(address)
    if not last:
        return ""
    for key in manifest:
        if urllib.parse.urlsplit(key).netloc.lower() == host and _last_part(_bare(key)) == last:
            return _bare(key)
    return ""


def moved(pages: dict[str, str], manifest: set[str], hosts, locate) -> list[dict]:
    """One record for each address in `pages` (address: client) that is not in `manifest`.

    `locate(address)` gives the allowed address it redirects to, or None. If it raises, that
    counts as no redirect. The records are sorted by address.
    """
    known = sorted(key for key in manifest if allowed(key, hosts))
    found = set(known)
    result = []
    for address in sorted(pages):
        if address + ".md" in found or address in found:
            continue
        try:
            target = locate(address)
        except Exception:  # noqa: BLE001 - any failure to ask counts as no redirect
            target = None
        if target and allowed(target, hosts):
            verdict, to = "moved", _bare(target)
        else:
            to = _maybe(address, known)
            verdict = "maybe" if to else "absent"
        result.append({"address": address, "client": pages[address],
                       "verdict": verdict, "to": to})
    return result
