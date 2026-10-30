"""The Gates reader against the confirmed findings of the round 3 review (d205b4a): each test names its finding, fails
on d205b4a, and has a must-pass arm beside its must-refuse arm where one can be written.
"""
from __future__ import annotations

import json

from semantext.sources.gates import config
from test_sources_gates import load, touch, world


# ---------------------------------------------------------------- gates_config/F1: show() never raises
def test_config_f1_show_writes_any_lone_surrogate_as_a_replacement():
    for odd in ("\ud800", "\udd00", "\udc7f", "\udfff"):
        assert config.show(f"C:\\x\\caf{odd}y") == "C:/x/caf\ufffdy"
    # must pass: an escaped byte that is not UTF-8 is still one U+FFFD, and escaped bytes that are UTF-8 read back
    assert config.show("/tmp/\udcff/c") == "/tmp/\ufffd/c"
    assert config.show("/tmp/caf\udcc3\udca9") == "/tmp/caf\u00e9"
    assert config.show("C:\\plain\\path") == "C:/plain/path"


def test_config_f1_a_seats_root_holding_a_lone_surrogate_is_a_problem_never_an_exception(tmp_path):
    # Since 1.4 the seats file is read one way by every reader and the card hook (pathrule.read_seats, as the person's
    # inbox parses it): a lone surrogate written as an escape refuses the whole file, said as a problem, never read.
    # Before, this reader kept the root as a missing root, and later as a bad path.
    data = '{"roots": [{"name": "r", "kind": "repo", "path": "' + (tmp_path / "nowhere").as_posix() + '/caf\\ud800"}], ' \
           '"seats": {}}'
    assert "\ud800" in json.loads(data)["roots"][0]["path"]
    path = touch(tmp_path / "roots.json", data)
    out = load({"seats": str(path)}, world(tmp_path))
    assert [p["kind"] for p in out["problems"]] == ["bad-json"] and out["repos"] == []
    json.dumps(out, ensure_ascii=False).encode("utf-8")   # the answer holds no lone surrogate: it can be sent
    # must pass: the same root without the surrogate is read, a missing root
    path = touch(tmp_path / "roots.json", data.replace("\\ud800", ""))
    out = load({"seats": str(path)}, world(tmp_path))
    assert [p["kind"] for p in out["problems"]] == ["missing-root"] and out["repos"][0]["present"] is False
