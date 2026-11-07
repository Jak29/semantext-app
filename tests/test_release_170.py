"""The 1.7.0 release attack (Koinos): the proxy says Connection: close on every reply, so a client that reuses its
connection never meets a closed socket."""
import http.client
import json

from tests.test_proxy import C, GOOD_BODY, T, ask, env, json_turn  # noqa: F401 (env is a fixture)


def test_a_whole_reply_says_connection_close(env):
    stub, client, port, *_ = env
    stub.replies.append(json_turn(T("hi"), stop="end_turn"))
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", "/v1/messages", body=json.dumps({"model": "claude-opus-5-5", "max_tokens": 5,
                                                        "messages": [{"role": "user", "content": "x"}]}),
              headers={"Content-Type": "application/json", "x-semantext-agent": "coder",
                       "x-api-key": "sk-test-canary-0000000000000000"})
    r = c.getresponse()
    r.read()
    assert r.status == 200 and (r.getheader("Connection") or "").lower() == "close"


def test_one_client_many_requests_none_fail(env):
    stub, client, *_ = env
    for _ in range(40):
        stub.replies.append(json_turn(T("reading"), C("Read", {"path": "a.txt"})))
    for _ in range(40):
        assert ask(client, False).content[1].input == {"path": "a.txt"}           # max_retries=0: no retry hides it
