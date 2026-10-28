"""The known differences between the estate's digest.py and envcard, written where a parity check can read them
(envcard.KNOWN_DIGEST_DIFFERENCES): exactly the two empty shapes, each with both sides and why, and envcard's side
holding as written. digest.py is not in this package and is not run here."""
from __future__ import annotations

from pathlib import Path

import yaml

from semantext import envcard


def test_the_two_known_differences_are_named_with_both_sides_and_why():
    known = envcard.KNOWN_DIGEST_DIFFERENCES
    assert [k["case"] for k in known] == ["entries-absent", "entries-empty"]
    assert all({"case", "shape", "digest", "envcard", "why"} <= set(k) and all(k[f] for f in k) for k in known)


def test_envcard_does_what_the_known_difference_says_on_each_shape(tmp_path: Path):
    head = {"environment": {"id": "e", "version": "1.0.0", "status": "ratified", "ratified_by": "owner"}}
    shapes = {"entries-absent": head, "entries-empty": {**head, "entries": []}}
    for case, data in shapes.items():
        (tmp_path / case).mkdir()
        p = tmp_path / case / "SEMANTICS.yaml"
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        assert envcard.card(p).splitlines() == ["## e 1.0.0 (ratified, ratified by owner)", envcard.NO_RULES], case
    # must-refuse: an environment with a rule is no known difference, and shows no such line
    (tmp_path / "full").mkdir()
    full = tmp_path / "full" / "SEMANTICS.yaml"
    full.write_text(yaml.safe_dump({**head, "entries": [{"id": "e.one", "statement": "One.", "ratified_by": "owner",
                                                         "provenance": {"type": "EXPLICIT"}}]}), encoding="utf-8")
    assert envcard.NO_RULES not in envcard.card(full)
