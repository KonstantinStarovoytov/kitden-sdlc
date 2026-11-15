import email.message
import io
import json
import urllib.error
import urllib.request
import urllib.response

import pytest

import agent_docs
from agent_docs import HOST, Search, make_opener

KEY = "Zq7Ck3TestKeyVb9Lr2Mw8Yp4"
SEARCH = "https://agent-docs-mcp.onrender.com/search"
HEALTH = "https://agent-docs-mcp.onrender.com/health"
OPENAPI = "https://agent-docs-mcp.onrender.com/openapi.json"
PAGE = "https://code.claude.com/docs/en/mcp.md"
MB = 1024 * 1024


class Body(io.BytesIO):
    """A body that records how much each read asked for."""

    def __init__(self, data):
        super().__init__(data)
        self.sizes = []

    def read(self, size=-1):
        self.sizes.append(size)
        return super().read(size)


class FakeWeb(urllib.request.HTTPSHandler):
    """Answers https requests without the network and records each request it gets.

    `answers` maps an address to a list of answers used in turn (the last one repeats). An
    answer is (status, headers, body) or an exception to raise. An address not in `answers`
    gives 404.
    """

    def __init__(self, answers):
        super().__init__()
        self.answers = {address: list(items) for address, items in answers.items()}
        self.asked = []
        self.bodies = []

    def https_open(self, req):
        self.asked.append(req)
        items = self.answers.get(req.full_url, [(404, {}, b"missing")])
        answer = items.pop(0) if len(items) > 1 else items[0]
        if isinstance(answer, BaseException):
            raise answer
        status, headers, data = answer
        head = email.message.Message()
        for name, value in headers.items():
            head[name] = value
        body = Body(data)
        self.bodies.append(body)
        resp = urllib.response.addinfourl(body, head, req.full_url, status)
        resp.msg = "fake"
        return resp


def json_answer(doc, status=200):
    return (status, {"Content-Type": "application/json"}, json.dumps(doc).encode())


def passage(url=PAGE, heading="Add a server", content="Run claude mcp add.", **more):
    return {"rank": 1, "title": "MCP", "heading": heading, "url": url, "score": 0.9,
            "content": content, "description": "d", "other_sections": [], **more}


def client(answers, sleeps=None):
    fake = FakeWeb(answers)
    sleep = sleeps.append if sleeps is not None else _no_sleep
    return fake, Search(KEY, opener=make_opener(fake), sleep=sleep)


def _no_sleep(seconds):
    raise AssertionError("no sleep expected")


def key_header(req):
    return req.get_header("X-cohere-api-key")


# The host


def test_host_is_the_agent_docs_server():
    assert HOST == "agent-docs-mcp.onrender.com"


def test_an_opener_that_can_follow_redirects_is_refused():
    with pytest.raises(ValueError) as caught:
        Search(KEY, opener=urllib.request.build_opener(FakeWeb({})))
    assert KEY not in str(caught.value)


def test_an_opener_with_a_second_redirect_handler_is_refused():
    opener = make_opener(FakeWeb({}))
    opener.add_handler(urllib.request.HTTPRedirectHandler())
    with pytest.raises(ValueError):
        Search(KEY, opener=opener)


@pytest.mark.parametrize("bad", ["", "two words", "line\nbreak", "tab\tkey", "café", None, 7])
def test_a_key_a_header_cannot_carry_is_refused_without_showing_it(bad):
    with pytest.raises(ValueError) as caught:
        Search(bad)
    if isinstance(bad, str) and bad:
        assert bad not in str(caught.value)


# The search request


def test_search_posts_the_query_to_the_search_address_with_the_key_header():
    fake, search = client({SEARCH: [json_answer({"passages": [passage()]})]})
    found = search.search("How do I add an MCP server?", "claude-code")
    assert found == [{"url": PAGE, "heading": "Add a server", "text": "Run claude mcp add."}]
    [req] = fake.asked
    assert req.full_url == SEARCH
    assert req.get_method() == "POST"
    assert key_header(req) == KEY
    assert json.loads(req.data) == {"query": "How do I add an MCP server?", "limit": 3,
                                    "product": "claude-code"}
    assert req.get_header("Content-type") == "application/json"
    assert req.timeout == 15
    assert search.asked == 1 and search.failed == 0


def test_search_sends_no_authorization_header_and_no_key_in_the_address_or_body():
    fake, search = client({SEARCH: [json_answer({"passages": []})]})
    search.search("hooks", "codex")
    [req] = fake.asked
    names = [name.lower() for name, _ in req.header_items()]
    assert "authorization" not in names
    assert KEY not in req.full_url
    assert KEY not in req.data.decode()


def test_the_key_header_is_not_one_a_redirect_would_carry():
    fake, search = client({SEARCH: [json_answer({"passages": []})]})
    search.search("hooks", "codex")
    [req] = fake.asked
    assert "X-cohere-api-key" in req.unredirected_hdrs
    assert "X-cohere-api-key" not in req.headers


def test_the_query_is_cut_to_500_characters():
    fake, search = client({SEARCH: [json_answer({"passages": []})]})
    search.search("q" * 800, "cursor")
    assert json.loads(fake.asked[0].data)["query"] == "q" * 500


def test_a_query_that_looks_like_an_address_still_goes_to_the_search_address():
    fake, search = client({SEARCH: [json_answer({"passages": []})]})
    search.search("https://example.com/search", "mcp")
    assert fake.asked[0].full_url == SEARCH


@pytest.mark.parametrize("product", ["claude-code", "codex", "cursor", "mcp"])
def test_each_product_is_sent(product):
    fake, search = client({SEARCH: [json_answer({"passages": []})]})
    search.search("hooks", product)
    assert json.loads(fake.asked[0].data)["product"] == product


@pytest.mark.parametrize("product", ["", "claude", "../health", None])
def test_an_unknown_product_fails_without_a_request(product, capsys):
    fake, search = client({})
    assert search.search("hooks", product) == []
    assert fake.asked == []
    assert search.failed == 1


@pytest.mark.parametrize("query", ["", "   ", None, 5])
def test_an_empty_query_fails_without_a_request(query):
    fake, search = client({})
    assert search.search(query, "codex") == []
    assert fake.asked == []
    assert search.failed == 1


# The answer


def test_at_most_three_passages_come_back():
    answer = {"passages": [passage(heading=f"h{n}") for n in range(5)]}
    fake, search = client({SEARCH: [json_answer(answer)]})
    assert [p["heading"] for p in search.search("hooks", "codex")] == ["h0", "h1", "h2"]


def test_text_is_cut_to_1500_characters():
    fake, search = client({SEARCH: [json_answer({"passages": [passage(content="x" * 2000)]})]})
    assert search.search("hooks", "codex")[0]["text"] == "x" * 1500


def test_a_caller_can_ask_for_a_longer_cut():
    fake, search = client({SEARCH: [json_answer({"passages": [passage(content="x" * 5000)]})]})
    assert search.search("hooks", "codex", cut=4000)[0]["text"] == "x" * 4000


def test_the_cut_keeps_a_word_at_character_2500():
    content = "y" * 2499 + " hooks"
    fake, search = client({SEARCH: [json_answer({"passages": [passage(content=content)]})]})
    assert search.search("hooks", "codex", cut=4000)[0]["text"].endswith(" hooks")


@pytest.mark.parametrize("url", [
    "https://example.com/docs/a",
    "http://code.claude.com/docs/en/mcp.md",
    "https://code.claude.com/blog/post",
    "https://code.claude.com/docs/en/mcp.md?x=1",
    "javascript:alert(1)",
])
def test_a_passage_whose_address_is_not_a_doc_address_is_dropped(url):
    answer = {"passages": [passage(url=url), passage(heading="kept")]}
    fake, search = client({SEARCH: [json_answer(answer)]})
    assert search.search("hooks", "codex") == [
        {"url": PAGE, "heading": "kept", "text": "Run claude mcp add."}]
    assert search.failed == 0


def test_no_passages_is_an_empty_answer_not_a_failure():
    fake, search = client({SEARCH: [json_answer({"passages": []})]})
    assert search.search("hooks", "codex") == []
    assert search.failed == 0


@pytest.mark.parametrize("doc", [
    [],
    {},
    {"passages": "none"},
    {"passages": [{"url": PAGE, "heading": "h"}]},
    {"passages": [passage(content=None)]},
    {"passages": [passage(heading=3)]},
    {"passages": ["text"]},
])
def test_an_answer_of_another_shape_is_a_failure(doc):
    fake, search = client({SEARCH: [json_answer(doc)]})
    assert search.search("hooks", "codex") == []
    assert search.failed == 1


# Failures


def html():
    return (200, {"Content-Type": "text/html"}, b"<html><body>Service waking up</body></html>")


FAILURES = {
    "401": [(401, {"Content-Type": "application/json"}, b'{"detail":"bad key"}')],
    "429": [(429, {"Content-Type": "application/json"}, b'{"detail":"too many"}')],
    "500": [(500, {}, b"oops")],
    "redirect": [(302, {"Location": "https://example.com/search"}, b"")],
    "temporary redirect": [(307, {"Location": "https://example.com/search"}, b"")],
    "timeout": [TimeoutError("timed out")],
    "timeout wrapped": [urllib.error.URLError(TimeoutError("timed out"))],
    "connection refused": [urllib.error.URLError(ConnectionRefusedError())],
    "html": [html()],
    "not utf-8": [(200, {}, b"\xff\xfe\x00")],
    "five megabytes": [(200, {"Content-Type": "application/json"}, b" " * (5 * MB))],
    "one byte over": [(200, {"Content-Type": "application/json"},
                       b'{"passages": []}' + b" " * (MB - 15))],
}


@pytest.mark.parametrize("name", FAILURES)
def test_a_failure_gives_no_passages_and_is_counted(name, capsys):
    fake, search = client({SEARCH: FAILURES[name], "https://example.com/search": [html()]})
    assert search.search("hooks", "codex") == []
    assert search.asked == 1 and search.failed == 1
    assert all(req.full_url == SEARCH for req in fake.asked)
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_makes_no_second_request(status, capsys):
    fake, search = client({SEARCH: [(status, {"Location": PAGE}, b"")],
                           PAGE: [json_answer({"passages": [passage()]})]})
    assert search.search("hooks", "codex") == []
    assert [req.full_url for req in fake.asked] == [SEARCH]
    assert capsys.readouterr().err.strip().endswith(str(status))


def test_an_answer_of_exactly_one_megabyte_is_read():
    data = b'{"passages": []}' + b" " * (MB - 16)
    assert len(data) == MB
    fake, search = client({SEARCH: [(200, {"Content-Type": "application/json"}, data)]})
    assert search.search("hooks", "codex") == []
    assert search.failed == 0


def test_at_most_one_megabyte_and_one_byte_is_read():
    fake, search = client({SEARCH: [(200, {}, b" " * (5 * MB))]})
    search.search("hooks", "codex")
    assert fake.bodies[0].sizes == [MB + 1]


def test_a_timeout_is_tried_twice():
    fake, search = client({SEARCH: [TimeoutError("timed out")]})
    assert search.search("hooks", "codex") == []
    assert len(fake.asked) == 2
    assert all(req.timeout == 15 for req in fake.asked)
    assert search.asked == 1 and search.failed == 1


def test_an_answer_after_one_timeout_is_used():
    fake, search = client({SEARCH: [TimeoutError("timed out"),
                                    json_answer({"passages": [passage()]})]})
    assert len(search.search("hooks", "codex")) == 1
    assert len(fake.asked) == 2
    assert search.failed == 0


def test_a_429_is_not_tried_again():
    fake, search = client({SEARCH: FAILURES["429"]})
    search.search("hooks", "codex")
    assert len(fake.asked) == 1


def test_a_failure_prints_the_status_code_only(capsys):
    fake, search = client({SEARCH: [(429, {}, b"secret answer body")]})
    search.search("hooks", "codex")
    out = capsys.readouterr()
    assert out.out == ""
    assert "429" in out.err
    assert "secret answer body" not in out.err


def test_a_failure_prints_the_error_class_name_only(capsys):
    fake, search = client({SEARCH: [urllib.error.URLError("detail of the error")]})
    search.search("hooks", "codex")
    err = capsys.readouterr().err
    assert "URLError" in err
    assert "detail of the error" not in err


def test_a_shape_failure_prints_no_part_of_the_answer(capsys):
    fake, search = client({SEARCH: [json_answer({"passages": "answer words"})]})
    search.search("hooks", "codex")
    assert "answer words" not in capsys.readouterr().err


def test_search_never_raises_even_when_the_opener_breaks():
    class Broken(urllib.request.HTTPSHandler):
        def https_open(self, req):
            raise RuntimeError("broken")

    search = Search(KEY, opener=make_opener(Broken()))
    assert search.search("hooks", "codex") == []
    assert search.failed == 1


def test_counters_add_up_over_several_searches():
    fake, search = client({SEARCH: [json_answer({"passages": []}), FAILURES["429"][0],
                                    json_answer({"passages": []})]})
    for _ in range(3):
        search.search("hooks", "codex")
    assert search.asked == 3 and search.failed == 1


# The key is never shown


def test_the_key_is_not_in_repr_or_str():
    search = Search(KEY)
    assert KEY not in repr(search)
    assert KEY not in str(search)
    assert HOST in repr(search)


@pytest.mark.parametrize("name", FAILURES)
def test_the_key_is_in_nothing_printed(name, capsys):
    fake, search = client({SEARCH: FAILURES[name], HEALTH: [(503, {}, KEY.encode())],
                           OPENAPI: [(500, {}, KEY.encode())]}, sleeps=[])
    search.search("hooks", "codex")
    search.wake()
    search.has_product()
    out = capsys.readouterr()
    assert KEY not in out.out
    assert KEY not in out.err
    assert KEY[:8] not in out.out + out.err


def test_the_key_is_in_no_error_the_opener_raises(capsys):
    """Even an error whose message holds the key is shown by its class name only."""

    class Echo(urllib.request.HTTPSHandler):
        def https_open(self, req):
            raise OSError(f"failed with {key_header(req)}")

    search = Search(KEY, opener=make_opener(Echo()))
    assert search.search("hooks", "codex") == []
    out = capsys.readouterr()
    assert KEY not in out.out + out.err


# wake


def test_wake_asks_health_without_the_key():
    fake, search = client({HEALTH: [json_answer({"status": "ok"})]})
    assert search.wake() is True
    [req] = fake.asked
    assert req.full_url == HEALTH
    assert req.get_method() == "GET"
    assert key_header(req) is None
    assert KEY not in str(req.header_items())


def test_wake_tries_again_until_health_answers():
    sleeps = []
    fake, search = client({HEALTH: [(503, {}, b""), TimeoutError("timed out"),
                                    json_answer({"status": "ok"})]}, sleeps=sleeps)
    assert search.wake() is True
    assert len(fake.asked) == 3
    assert all(key_header(req) is None for req in fake.asked)
    assert len(sleeps) == 2


def test_wake_stops_after_90_seconds_and_says_so(capsys):
    sleeps = []
    fake, search = client({HEALTH: [(503, {}, b"asleep")]}, sleeps=sleeps)
    assert search.wake() is False
    assert sum(sleeps) == 90
    assert len(fake.asked) == len(sleeps) + 1
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "503" in err and "asleep" not in err


def test_wake_does_not_follow_a_redirect():
    sleeps = []
    fake, search = client({HEALTH: [(302, {"Location": PAGE}, b"")], PAGE: [html()]},
                          sleeps=sleeps)
    assert search.wake() is False
    assert {req.full_url for req in fake.asked} == {HEALTH}


def test_wake_never_raises():
    class Broken(urllib.request.HTTPSHandler):
        def https_open(self, req):
            raise RuntimeError("broken")

    search = Search(KEY, opener=make_opener(Broken()), sleep=lambda seconds: None)
    assert search.wake() is False


def test_wake_does_not_count_as_a_search():
    fake, search = client({HEALTH: [json_answer({"status": "ok"})]})
    search.wake()
    assert search.asked == 0 and search.failed == 0


# has_product


def openapi(search_request, ref=True):
    schema = {"$ref": "#/components/schemas/SearchRequest"} if ref else search_request
    return {
        "openapi": "3.1.0",
        "paths": {"/search": {"post": {"requestBody": {
            "content": {"application/json": {"schema": schema}}, "required": True}}}},
        "components": {"schemas": {"SearchRequest": search_request}},
    }


WITHOUT = {"type": "object", "required": ["query"],
           "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}
WITH = {"type": "object", "required": ["query"],
        "properties": {**WITHOUT["properties"], "product": {"type": "string"}}}


def test_has_product_is_true_when_the_search_request_names_product():
    fake, search = client({OPENAPI: [json_answer(openapi(WITH))]})
    assert search.has_product() is True
    [req] = fake.asked
    assert req.full_url == OPENAPI
    assert req.get_method() == "GET"
    assert key_header(req) is None


def test_has_product_reads_a_schema_written_in_place():
    fake, search = client({OPENAPI: [json_answer(openapi(WITH, ref=False))]})
    assert search.has_product() is True


def test_has_product_is_false_when_the_search_request_does_not_name_product():
    fake, search = client({OPENAPI: [json_answer(openapi(WITHOUT))]})
    assert search.has_product() is False


def test_has_product_is_false_when_only_another_request_names_product():
    doc = openapi(WITHOUT)
    doc["components"]["schemas"]["AskRequest"] = WITH
    fake, search = client({OPENAPI: [json_answer(doc)]})
    assert search.has_product() is False


@pytest.mark.parametrize("answer", [
    (500, {}, b"oops"),
    (302, {"Location": PAGE}, b""),
    html(),
    TimeoutError("timed out"),
    json_answer({"paths": {}}),
    json_answer({"paths": {"/search": {"post": {"requestBody": "product"}}}}),
    json_answer({**openapi(WITHOUT), "components": {"schemas": {
        "SearchRequest": {"properties": "product"}}}}),
    json_answer([]),
    (200, {}, b" " * (MB + 1)),
])
def test_has_product_is_false_on_any_failure(answer):
    fake, search = client({OPENAPI: [answer], PAGE: [json_answer(openapi(WITH))]})
    assert search.has_product() is False
    assert {req.full_url for req in fake.asked} == {OPENAPI}


def test_has_product_reads_once_even_after_a_timeout():
    fake, search = client({OPENAPI: [TimeoutError("timed out"), json_answer(openapi(WITH))]})
    assert search.has_product() is False
    assert len(fake.asked) == 1


def test_has_product_reads_the_real_shape_of_today():
    """The SearchRequest of the server's /openapi.json, read on 2026-11-15: no product yet."""
    today = {"properties": {
        "query": {"type": "string", "maxLength": 500, "minLength": 1, "title": "Query"},
        "limit": {"anyOf": [{"type": "integer", "maximum": 50.0, "minimum": 1.0},
                            {"type": "null"}], "title": "Limit"}},
        "type": "object", "required": ["query"], "title": "SearchRequest"}
    fake, search = client({OPENAPI: [json_answer(openapi(today))]})
    assert search.has_product() is False


def test_has_product_does_not_count_as_a_search():
    fake, search = client({OPENAPI: [json_answer(openapi(WITH))]})
    search.has_product()
    assert search.asked == 0 and search.failed == 0


def test_the_module_reads_no_address_but_its_own():
    assert agent_docs.SEARCH == SEARCH
    assert agent_docs.HEALTH == HEALTH
    assert agent_docs.OPENAPI == OPENAPI
