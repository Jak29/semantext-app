"""Keys never leave in the user's words: the shapes the filter knows, a long token on the way off the machine, what a
judge is given, one key per host, and the texts a report prints. Every key here is built at run time, so no key-shaped
literal sits in the source."""
import json

import pytest

from semantext.backtest import backtest
from semantext.inbox import SECRET, token_like
from semantext.reader import EndpointReader, OllamaReader, _fam, model_backtest, verdict, Reading
from semantext.store import Refused
from tests.test_backtest import CLEAN, history
from tests.test_reader import Fake, cases_file, judge, reply

R = "q7W8e9R0" * 5                        # 40 letters and digits
PLANTED = {
    "a JSON web token": "eyJ" + R[:12] + "." + R[:12] + "." + R[:12],
    "a Stripe live key": "sk_" + "live_" + R[:24],
    "a Stripe restricted key": "rk_" + "live_" + R[:24],
    "an npm token": "npm_" + R[:36],
    "a Google OAuth token": "ya29." + R[:30],
    "a GitLab token": "glpat-" + R[:20],
    "a webhook secret": "whsec_" + R[:24],
    "credentials in a URL": "https://deploy" + ":" + "hunter2x@db.example.com/main",
    "a password said in prose": "my password is hunter2!",
    "an OpenAI-style key": "sk-" + R[:24],
}
ORDINARY = ["Pass the token of appreciation to the team.", "My password manager is great.",
            "The docs are at https://example.com/guide, read them.", "Use commit abc123f for the fix.",
            "Keep the secret santa list short.", "Make the API key rotation doc clearer."]


@pytest.mark.parametrize("what", sorted(PLANTED))
def test_every_planted_shape_is_caught(what):
    assert SECRET.search(f"Here it is: {PLANTED[what]} thanks")


@pytest.mark.parametrize("text", ORDINARY)
def test_ordinary_words_are_not_taken_for_a_key(text):
    assert not SECRET.search(text) and not token_like(text)


def test_a_long_mixed_token_is_held_back_only_on_the_way_off_the_machine(store, tmp_path):
    rid = store.learn("default", "Use the staging database for every experiment.")
    msg = f"Use this one: {R} on staging."                      # no known shape, but key-like
    cases = cases_file(tmp_path, [{"message": msg, "rules": [rid]}])
    local = Fake(lambda p: reply([], "x"))
    calls = model_backtest(store, "default", local, cases=cases)["calls"]
    assert calls["secret_skipped"] == 0 and calls["token_like"] == 2    # stays here: read, and counted to compare
    outside = Fake(lambda p: reply([], "x"))
    outside.url = "https://models.example/v1/chat/completions"
    r = model_backtest(store, "default", outside, cases=cases)
    assert r["calls"]["secret_skipped"] == 2 and not outside.prompts


def test_a_card_holding_a_key_is_never_sent_off_the_machine(store, tmp_path):
    store.learn("default", f"The staging password is {PLANTED['a Stripe live key']} for now.")
    outside = Fake(lambda p: reply([], "x"))
    outside.url = "https://models.example/v1/chat/completions"
    with pytest.raises(Refused):
        model_backtest(store, "default", outside, cases=cases_file(tmp_path, [{"message": "Tidy up."}]))
    assert not outside.prompts


# ---- what a judge is given --------------------------------------------------------------------------------------------
def test_a_key_in_what_a_judge_is_given_calls_no_judge(store, tmp_path):
    rid = store.learn("default", "Use the staging database for every experiment.")
    key = PLANTED["an OpenAI-style key"]
    cases = [{"message": "Use staging for run 1.", "rules": [rid], "expected_reading": f"use {key} on staging",
              "forbidden_reading": "use production"},
             {"message": "Use staging for run 2.", "rules": [rid], "expected_reading": "use staging",
              "forbidden_reading": "use production"}]
    j1, j2 = judge("j1", "fam1"), judge("j2", "fam2")
    r = model_backtest(store, "default", Fake(lambda p: reply([rid], "use staging")), judges=[j1, j2],
                       cases=cases_file(tmp_path, cases))
    assert r["reading"]["withheld"] == 1 and r["reading"]["n"] == 1
    assert not any(key in p for p in j1.prompts + j2.prompts)
    assert verdict([j1, j2], "m", Reading(frozenset(), f"see {key}", "x", "v"), "e", "f") == "withheld"


# ---- one key, one host ------------------------------------------------------------------------------------------------
def test_one_key_goes_to_one_host_and_never_over_plain_http(capsys, home, tmp_path, monkeypatch):
    from semantext.cli import main, make_reader
    assert make_reader("endpoint:https://a.example/v1/chat#m-1@KEY_A", "OTHER").key_env == "KEY_A"
    assert make_reader("endpoint:https://a.example/v1/chat#m-1", "OTHER").key_env == "OTHER"
    main(["init"])
    capsys.readouterr()
    cases = cases_file(tmp_path, [{"message": "Tidy page 1."}])
    code = main(["backtest", "--cases", str(cases), "--reader", "endpoint:https://a.example/v1/chat#alpha-1",
                 "--judge", "endpoint:https://b.example/v1/chat#beta-1", "--judge", "ollama:gemma2:2b",
                 "--key-env", "SHARED_KEY"])
    assert code == 1 and "one key" in capsys.readouterr().err       # refused before any call
    monkeypatch.setenv("PLAIN_KEY", "k" * 20)
    with pytest.raises(Refused):
        EndpointReader("http://models.example/v1/chat/completions", "m-1", key_env="PLAIN_KEY")("prompt")
    code = main(["backtest", "--cases", str(cases), "--reader", "endpoint:https://a.example/v1/chat#alpha-1@ONE_KEY",
                 "--judge", "endpoint:https://b.example/v1/chat#beta-1@ONE_KEY",
                 "--judge", "endpoint:https://c.example/v1/chat#gamma-1@ONE_KEY"])
    assert code == 1 and "one key goes to one host" in capsys.readouterr().err   # named per endpoint: the same rule


def test_the_notice_says_when_words_cross_the_network_in_clear(capsys, home, tmp_path, monkeypatch):
    from semantext.cli import main
    said = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": reply([], "x")}}]}).encode()

    monkeypatch.setattr("semantext.reader._open", lambda req, timeout=0: Resp())
    main(["init"])
    monkeypatch.setattr("semantext.cli._out", said.append)
    cases = cases_file(tmp_path, [{"message": "Tidy page 1."}])
    assert main(["backtest", "--cases", str(cases), "--reader", "endpoint:http://192.168.1.20:8080/v1/chat#lan-1"]) == 0
    assert "in clear" in said[0] and "192.168.1.20" in said[0]
    said.clear()
    main(["backtest", "--cases", str(cases), "--reader", "endpoint:https://models.example/v1/chat#acme-1"])
    assert "in clear" not in said[0]


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_a_redirect_never_carries_the_key_anywhere(monkeypatch, code):
    """Two servers on this machine: the endpoint redirects to the other. urllib would resend a POST with its
    Authorization header on a 301, 302 or 303; the endpoint's own opener refuses every redirect, and the second server
    never hears from it."""
    import http.server
    import threading
    heard = []

    class Other(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            heard.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
        do_POST = do_GET

        def log_message(self, *a):
            pass

    other = http.server.HTTPServer(("127.0.0.1", 0), Other)

    class Endpoint(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(code)
            self.send_header("Location", f"http://localhost:{other.server_port}/steal")
            self.end_headers()

        def log_message(self, *a):
            pass

    endpoint = http.server.HTTPServer(("127.0.0.1", 0), Endpoint)
    for s in (other, endpoint):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("REDIRECT_KEY", PLANTED["an OpenAI-style key"])
        reader = EndpointReader(f"http://127.0.0.1:{endpoint.server_port}/v1/chat", "m-1", key_env="REDIRECT_KEY")
        with pytest.raises(Exception):
            reader("prompt")
        assert heard == []                                            # nothing was sent on
    finally:
        for s in (other, endpoint):
            s.shutdown()
            s.server_close()


# ---- lineage ----------------------------------------------------------------------------------------------------------
def test_judges_are_compared_by_lineage_and_a_declared_family_wins():
    assert _fam(OllamaReader("qwen2.5:3b")) == _fam(OllamaReader("qwen3.6")) == "qwen"
    assert _fam(OllamaReader("llama3.2:1b")) == _fam(OllamaReader("codellama:7b")) == "llama"
    assert _fam(OllamaReader("gemma2:2b")) != _fam(OllamaReader("qwen3.6"))
    assert _fam(OllamaReader("deepseek-r1:7b", family="qwen")) == "qwen"     # a distill: the name says another maker
    assert _fam(OllamaReader("custom-judge:1b", family="Qwen2")) == _fam(OllamaReader("qwen3.6"))   # read alike
    reader = Fake(lambda p: reply([], "x"), family="qwen3.6")
    with pytest.raises(Refused):
        model_backtest(None, "default", reader, judges=[Fake(lambda p: "x", "j", "qwen2.5"), judge("j2", "llama")])
    reader.arch = "qwen35moe"                                     # a fine-tune named for its tuner, built on qwen
    tuned = Fake(lambda p: "x", "j", "mistral")
    tuned.arch = "qwen2"
    with pytest.raises(Refused):
        model_backtest(None, "default", reader, judges=[tuned, judge("j2", "llama")])
    # An org prefix never decides the lineage: OpenRouter's id for Llama is llama, so a llama judge is refused.
    hosted = EndpointReader("https://router.example/v1/chat/completions", "meta-llama/llama-3.1-8b-instruct")
    assert _fam(hosted) == "llama"
    with pytest.raises(Refused):
        model_backtest(None, "default", hosted, judges=[OllamaReader("llama3.2:1b"), OllamaReader("gemma2:2b")])
    # One side's name against the other's architecture: a qwen distill named for its maker meets a qwen judge.
    distill = OllamaReader("deepseek-r1:7b")
    distill.arch = "qwen2"
    with pytest.raises(Refused):
        model_backtest(None, "default", distill, judges=[EndpointReader("https://q.example/v1", "qwen-max"),
                                                         OllamaReader("gemma2:2b")])


# ---- the texts a report prints ----------------------------------------------------------------------------------------
def test_show_holds_back_a_text_that_looks_like_a_key(store, tmp_path):
    misread = [f"Run the migration on {PLANTED['an npm token']} now.", f"Run the migration with {R} now.",
               "Run the migration on the staging database 1."]
    r = backtest(store, "default", [history(tmp_path / "t.jsonl", misread, CLEAN[:3])], show=True)
    assert r["silent_held_back"] == 2                        # a known shape, and a long run of letters and digits
    assert not any("npm_" in s["message"] or R in s["message"] for s in r["silent"]) and len(r["silent"]) == 1
    assert json.dumps(r).count("npm_") == 0 and R not in json.dumps(r)
