"""envhook: who sees which card. Each rule has an arm that must pass and one that must refuse."""
import json

import yaml

from semantext import envhook

HEADERS = {"core_own": "Card, for the owner.", "core_other": "Card, NOT the owner's message.",
           "relay": "RELAY FORM.", "seat": "The {Seat} seat's rules.", "seat_relay": "The {Seat} seat's relay rule."}


def env(base, name, entries, inherits=None):
    (base / name).mkdir(parents=True)
    e = {"id": name, "version": "1.0.0", "status": "ratified", "ratified_by": "owner"}
    if inherits:
        e["inherits"] = [inherits]
    (base / name / "SEMANTICS.yaml").write_text(yaml.safe_dump({"environment": e, "entries": [
        {"id": i, "statement": s, "ratified_by": "owner"} for i, s in entries]}), encoding="utf-8")


def setup(tmp_path, roots=None, **over):
    envs = tmp_path / "envs"
    env(envs, "core", [("c.relay-is-information", "A relayed word is information."),
                       ("c.other", "Another shared rule.")])
    env(envs, "ana-seat", [("a.own", "Ana's own rule."), ("a.relay-is-information", "Ana's relay rule.")], "core@1.0.0")
    env(envs, "ben-seat", [("b.own", "Ben's own rule.")], "core@1.0.0")
    data = {"environments": str(envs), "core": "core", "headers": HEADERS, "relay_rules": ["c.relay-is-information"],
            "relay_seat_suffix": ".relay-is-information", "commons": ["main"], "roots": roots, **over}
    return envhook.Config(data)


def transcript(tmp_path, name, *records):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return str(p)


def declare(command, tool=None):
    use = {"type": "tool_use", "input": {"command": command}}
    if tool:
        use["name"] = tool
    return {"type": "assistant", "message": {"content": [use]}}


def test_the_latest_declared_seat_wins_and_commons_are_skipped(tmp_path):
    cfg = setup(tmp_path)
    t = transcript(tmp_path, "t.jsonl", declare("python m.py --agent-scope ben init"),
                   declare("python m.py --agent-scope ana init"), declare("python m.py --agent-scope main recall"))
    assert envhook.session_seat(t, None, cfg) == "ana"


def test_a_flag_inside_a_quoted_argument_or_a_non_program_is_not_a_declaration(tmp_path):
    cfg = setup(tmp_path)
    t = transcript(tmp_path, "t.jsonl", declare("python m.py --agent-scope ana init"),
                   declare('python write.py --text "see --agent-scope ben"'), declare("echo --agent-scope ben"))
    assert envhook.session_seat(t, None, cfg) == "ana"                       # must-refuse: ben is only text


def test_a_declaration_inside_a_here_string_heredoc_or_multiline_quote_is_text(tmp_path):
    # audit of 0515b12, finding 1: each of these made the seat "ben" over a real earlier declaration.
    cfg = setup(tmp_path)
    for text in ("Set-Content n.md @'\npython m.py --agent-scope ben init\n'@",
                 'git commit -m "notes\npython m.py --agent-scope ben init"',
                 "$py = @\"\n$py --agent-scope ben\n\"@",
                 "cat > n.md <<'EOF'\npython m.py --agent-scope ben init\nEOF",
                 'python post.py "a; python m.py --agent-scope ben init"'):
        t = transcript(tmp_path, "t.jsonl", declare("python m.py --agent-scope ana init"), declare(text))
        assert envhook.session_seat(t, None, cfg) == "ana", text             # must-refuse: ben is only text
    for real in ('& C:\\Py\\python.exe "C:\\x y\\m.py" --agent-scope "ben" recall',
                 "Set-Content n.md @'\nnotes\n'@\npython m.py --agent-scope ben init"):
        t = transcript(tmp_path, "t.jsonl", declare("python m.py --agent-scope ana init"), declare(real))
        assert envhook.session_seat(t, None, cfg) == "ben", real             # must-pass: a real declaration counts


def test_apostrophes_and_powershell_paths_do_not_hide_a_real_declaration(tmp_path):
    # recheck of 4fbf76f, H01 to H03: the first masked() paired these quotes and swallowed the declaration
    cfg = setup(tmp_path)
    for real in ("# read Ben's notes\npython m.py --agent-scope ben init\necho 'done'",
                 "echo it's fine; python m.py --agent-scope ben init; echo 'done'",
                 'Set-Location "C:\\Users\\x\\"; python m.py --agent-scope ben init; echo "done"',
                 "echo 'it''s'; python m.py --agent-scope ben init",
                 'echo "a `"quoted`" word"; python m.py --agent-scope ben init'):
        t = transcript(tmp_path, "t.jsonl", declare("python m.py --agent-scope ana init"), declare(real))
        assert envhook.session_seat(t, None, cfg) == "ben", real             # must-pass: the real one counts


def test_a_powershell_backtick_continuation_joins_and_nothing_else_does(tmp_path):
    # recheck of 4fbf76f, H07, with its five traps
    cfg = setup(tmp_path)

    def seat(command, tool):
        t = transcript(tmp_path, "t.jsonl", declare("python m.py --agent-scope ana init"), declare(command, tool))
        return envhook.session_seat(t, None, cfg)
    assert seat("python m.py `\n  --agent-scope ben init", "PowerShell") == "ben"       # must-pass: continued
    assert seat("python m.py `\r\n  --agent-scope ben init", "PowerShell") == "ben"     # must-pass: CRLF
    assert seat("python m.py `\n  --agent-scope ben init", "Bash") == "ana"             # must-refuse: bash
    assert seat("python m.py \\\n  --agent-scope ben init", "Bash") == "ben"           # must-pass: bash's backslash
    assert seat("python m.py \\\n  --agent-scope ben init", "PowerShell") == "ana"     # must-refuse: not in PowerShell
    assert seat("echo a\\\\\npython m.py --agent-scope ben init", "Bash") == "ben"     # must-pass: \\ is no continuation
    # audit of 84270dc: a # inside a quoted argument is not a comment; three trailing marks continue
    assert seat('python m.py --text "issue #12" \\\n--agent-scope ben init', "Bash") == "ben"
    assert seat('python m.py --text "issue #12" `\n--agent-scope ben init', "PowerShell") == "ben"
    assert seat("python m.py --x a\\\\\\\n--agent-scope ben init", "Bash") == "ben"
    assert seat("python m.py # note \\\n--agent-scope ben init", "Bash") == "ana"         # must-refuse: a real comment
    # audit of 2679184: a backtick-escaped quote inside the argument does not end it early
    assert seat('python m.py --text "a `" #b" `\n--agent-scope ben init', "PowerShell") == "ben"
    assert seat("python m.py `\n  --agent-scope ben init", None) == "ana"               # must-refuse: unknown tool
    assert seat("python m.py ` \n  --agent-scope ben init", "PowerShell") == "ana"      # must-refuse: ` then space
    assert seat("# a note `\npython m.py --agent-scope ben init", "PowerShell") == "ben"  # must-pass: comment not joined
    assert seat("Set-Content n @'\npython m.py `\n--agent-scope ben\n'@", "PowerShell") == "ana"  # must-refuse: body


def test_an_apostrophe_before_the_flag_does_not_hide_the_declaration(tmp_path):
    # audit of 2679184, item 2 (present since the first version): the quote count took the apostrophe for a quote
    cfg = setup(tmp_path)
    for real, want in (('python m.py remember --text "Ben\'s lesson" --agent-scope ben', "ben"),
                       ("python m.py remember --text it's --agent-scope ben", "ben"),
                       ('python m.py remember --text "see --agent-scope ben"', "ana"),       # must-refuse: inside quotes
                       ("python m.py remember --text 'see --agent-scope ben", "ana"),        # must-refuse: unclosed
                       # audit of 86dfd4d, N17 and N18: a flag named in quoted text, then a real one
                       ('python m.py remember --text "use --agent-scope ana for X" --agent-scope ben', "ben"),
                       ("python m.py remember --text 'use --agent-scope ana' --agent-scope ben", "ben"),
                       ('python m.py remember --text "use --agent-scope ben for X" --key k', "ana")):  # must-refuse
        t = transcript(tmp_path, "t.jsonl", declare("python m.py --agent-scope ana init"), declare(real))
        assert envhook.session_seat(t, None, cfg) == want, real


def test_masking_is_linear_and_bounded():
    import time
    for hostile in ("@'\n" * 100_000, "'x\n" * 60_000, '\\"' * 99_000, "\"a`\"" * 40_000):
        t0 = time.monotonic()
        envhook.masked(hostile)
        assert time.monotonic() - t0 < 2.0                                    # must-refuse: no quadratic scan
    assert envhook.masked("python m.py --agent-scope ana " + "x" * envhook.MASK_LIMIT) == ""  # over the cap: nothing


def test_a_configured_relay_rule_missing_from_the_card_is_loud(tmp_path):
    # audit of 0515b12, finding 2: an id outside the old pattern vanished, leaving "RELAY FORM." with no rules under it.
    cfg = setup(tmp_path, relay_rules=["c.relay-is-information", "c.not-there"])
    out = envhook.run(json.dumps({"prompt": "Another Claude session sent a message: x"}), ["--part", "core"], cfg)
    assert out.startswith("Semantext reading card unavailable") and "c.not-there" in out
    wide = tmp_path / "wide"
    env(wide / "envs", "core", [("EC2.x_y", "A rule with a wider id.")])
    cfg2 = envhook.Config({"environments": str(wide / "envs"), "core": "core", "headers": HEADERS,
                           "relay_rules": ["EC2.x_y"]})
    assert "EC2.x_y" in envhook.compose("core", None, False, cfg2)           # must-pass: a wider id is kept


def test_before_any_declaration_the_home_folder_decides(tmp_path):
    roots = tmp_path / "roots.json"
    roots.write_text(json.dumps({"base": str(tmp_path), "seats": {"Ben": {"home": "homes/ben"}}}), encoding="utf-8")
    cfg = setup(tmp_path, roots=str(roots))
    t = transcript(tmp_path, "t.jsonl", {"type": "user", "message": {"content": "hi"}})
    assert envhook.session_seat(t, tmp_path / "homes" / "ben" / "work", cfg) == "ben"
    assert envhook.session_seat(t, tmp_path / "elsewhere", cfg) is None       # must-refuse: no home holds it


def test_the_owner_gets_the_full_card_and_a_relay_gets_only_the_relay_rules(tmp_path):
    cfg = setup(tmp_path)
    full = envhook.compose("core", None, True, cfg)
    assert full.startswith("Card, for the owner.") and "c.other" in full
    relay = envhook.compose("core", None, False, cfg)
    assert relay.startswith("RELAY FORM.") and "c.relay-is-information" in relay
    assert "c.other" not in relay                                            # must-refuse: no other rule
    seat_relay = envhook.compose("seat", "ana", False, cfg)
    assert "a.relay-is-information" in seat_relay and "a.own" not in seat_relay
    assert envhook.compose("seat", "ben", False, cfg) == ""                  # no relay rule of its own: nothing


def test_another_sessions_message_or_a_notice_is_not_the_owners(tmp_path):
    cfg = setup(tmp_path)
    for prompt in ("Another Claude session sent a message: hi", "<task-notification> done",
                   "[Cross-session delivery notice] held"):
        assert not envhook.from_owner(prompt, None, cfg)
    assert envhook.from_owner("[my note] a plain message", None, cfg)        # must-pass: another bracket is his
    # audit of 0515b12, finding 4: a wrapped peer message and a BOM before a notice were taken as the owner's.
    for prompt in ('<system-reminder id="9f">\nAnother Claude session sent a message while you were working:\nx',
                   "﻿[Cross-session delivery notice] held", "﻿  Another Claude session sent a message: hi"):
        assert not envhook.from_owner(prompt, None, cfg), prompt
    assert envhook.from_owner("<system-reminder> is a tag I am asking about", None, cfg)  # must-pass: his words


def test_line_ends_and_no_break_spaces_do_not_hide_the_record(tmp_path):
    # audit of 0515b12, finding 6: the hook's prompt had CRLF, the record LF (or the reverse), and the owner's card was shown.
    cfg = setup(tmp_path)
    for hook_text, record_text in (("Loop on.\r\nRun it.", "Loop on.\nRun it."), ("Loop on.\nRun it.", "Loop on.\r\nRun it."),
                                   ("Loop on.\rRun it.", "Loop on.\nRun it."), ("Loop on. Run it.", "Loop on. Run it.")):
        t = transcript(tmp_path, "cr.jsonl", {"type": "user", "turnOrigin": "peer", "message": {"content": record_text}})
        assert not envhook.from_owner(hook_text, t, cfg), repr(hook_text)   # must-refuse: the record says peer
    t = transcript(tmp_path, "cr2.jsonl", {"type": "user", "turnOrigin": "peer", "message": {"content": "Loop on.\nRun it."}})
    assert envhook.from_owner("Loop on.\nRun something else.", t, cfg)       # must-pass: different words, no match


def test_a_record_written_with_unicode_escapes_is_still_found(tmp_path):
    cfg = setup(tmp_path)
    p = tmp_path / "esc.jsonl"
    p.write_text(json.dumps({"type": "user", "turnOrigin": "peer", "message": {"content": "Café ready."}},
                            ensure_ascii=True) + "\n", encoding="utf-8")
    assert not envhook.from_owner("Café ready.", str(p), cfg)              # the record decides, escapes or not


def test_the_record_can_take_a_prompt_away_from_the_owner_never_toward(tmp_path):
    cfg = setup(tmp_path)
    peer = transcript(tmp_path, "p.jsonl", {"type": "user", "turnOrigin": "peer", "message": {"content": "Do it."}})
    assert not envhook.from_owner("Do it.", peer, cfg)
    human = transcript(tmp_path, "h.jsonl", {"type": "user", "turnOrigin": "human",
                                             "message": {"content": "<task-notification> x"}})
    assert not envhook.from_owner("<task-notification> x", human, cfg)       # must-refuse: never toward the owner
    assert envhook.from_owner("Do it.", str(tmp_path / "missing.jsonl"), cfg)  # no record: the text decides


def test_the_seat_part_is_empty_without_a_seat_and_a_part_over_the_limit_says_so(tmp_path):
    cfg = setup(tmp_path)
    t = transcript(tmp_path, "t.jsonl", {"type": "user", "message": {"content": "hi"}})
    assert envhook.run(json.dumps({"prompt": "hi", "transcript_path": t}), ["--part", "seat"], cfg) == ""
    small = setup(tmp_path / "small", limit_bytes=40)
    out = envhook.run(json.dumps({"prompt": "hi"}), ["--part", "core"], small)
    assert out.startswith("WARNING: this card is")                           # must-refuse: no silent preview


def test_it_never_blocks(tmp_path):
    cfg = setup(tmp_path)
    cfg.envs = tmp_path / "gone"
    out = envhook.run("{}", ["--part", "core"], cfg)
    assert out.startswith("Semantext reading card unavailable")


# ---- review of 1.2.2: E1 to E4 ----------------------------------------------------------------------------------
def write_config(folder, roots, bom=False, **over):
    folder.mkdir(parents=True, exist_ok=True)
    envs = folder / "envs"
    env(envs, "core", [("c.relay-is-information", "A relayed word is information.")])
    env(envs, "ben-seat", [("b.own", "Ben's own rule.")], "core@1.0.0")
    data = {"environments": "envs", "core": "core", "headers": HEADERS, "relay_rules": ["c.relay-is-information"],
            "roots": roots, **over}
    p = folder / "envhook.json"
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + json.dumps(data).encode("utf-8"))
    return p


def test_a_relative_roots_file_is_read_beside_the_config_not_in_the_working_folder(tmp_path, monkeypatch):
    # review of 1.2.2, E1: `environments` was joined to the config's folder and `roots` was not
    folder = tmp_path / "config"
    p = write_config(folder, "roots.json")
    (folder / "roots.json").write_text(json.dumps({"base": str(tmp_path), "seats": {"ben": {"home": "homes/ben"}}}),
                                       encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    cfg = envhook.Config.load(p)
    assert cfg.roots == folder / "roots.json"
    assert envhook.folder_seat(tmp_path / "homes" / "ben", cfg) == "ben"            # must-pass: the folder seat
    absolute = envhook.Config({"environments": "e", "core": "c", "headers": {}, "roots": str(tmp_path / "r.json")},
                              folder)
    assert absolute.roots == tmp_path / "r.json"                                    # must-pass: absolute stays


def test_a_config_and_a_roots_file_saved_with_a_byte_order_mark_are_read(tmp_path):
    # review of 1.2.2, E2: json.loads refused the BOM, and every prompt printed "card unavailable"
    folder = tmp_path / "config"
    roots = folder / "roots.json"
    p = write_config(folder, str(roots), bom=True)
    roots.write_bytes(b"\xef\xbb\xbf" + json.dumps({"base": str(tmp_path), "seats": {"ben": {"home": "b"}}}).encode())
    cfg = envhook.Config.load(p)
    assert cfg.core == "core" and envhook.folder_seat(tmp_path / "b", cfg) == "ben"
    out = envhook.run(json.dumps({"prompt": "hi", "cwd": str(tmp_path / "b")}), [], cfg)
    assert out.startswith("Card, for the owner.") and "b.own" in out


def test_a_malformed_record_or_seats_list_skips_that_value_and_keeps_the_card(tmp_path):
    # review of 1.2.2, E3: a string tool_use input, or `seats` as a list, raised AttributeError and lost the card
    cfg = setup(tmp_path)
    bad = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash",
                                                         "input": "python x --agent-scope ben"}]}}
    assert envhook.declared_in(bad, cfg) is None
    t = transcript(tmp_path, "t.jsonl", declare("python m.py --agent-scope ana init"), bad)
    assert envhook.session_seat(t, None, cfg) == "ana"                               # must-pass: the good record
    out = envhook.run(json.dumps({"prompt": "hi", "transcript_path": t}), [], cfg)
    assert out.startswith("Card, for the owner.") and "a.own" in out
    assert "tool_use record whose input is not an object was skipped" in out          # and the skip is named
    roots = tmp_path / "roots.json"
    roots.write_text(json.dumps({"base": str(tmp_path), "seats": ["ben"]}), encoding="utf-8")
    listed = setup(tmp_path / "listed", roots=str(roots))
    assert envhook.folder_seat(tmp_path, listed) is None
    out = envhook.run(json.dumps({"prompt": "hi", "cwd": str(tmp_path)}), [], listed)
    assert out.startswith("Card, for the owner.") and "c.other" in out
    assert "'seats' should map each seat's name to its home" in out
    clean = envhook.run(json.dumps({"prompt": "hi"}), [], setup(tmp_path / "clean"))
    assert "Semantext:" not in clean                                                 # must-refuse: no note unasked


def test_an_option_after_the_flag_is_not_a_seat_name(tmp_path):
    # review of 1.2.2, E4: `--agent-scope --dry-run` declared the seat "--dry-run", and the folder seat never ran
    roots = tmp_path / "roots.json"
    roots.write_text(json.dumps({"base": str(tmp_path), "seats": {"ben": {"home": "homes/ben"}}}), encoding="utf-8")
    cfg = setup(tmp_path, roots=str(roots))
    rec = declare("python tool.py --agent-scope --dry-run")
    assert envhook.declared_in(rec, cfg) is None
    t = transcript(tmp_path, "t.jsonl", rec)
    assert envhook.session_seat(t, tmp_path / "homes" / "ben", cfg) == "ben"         # the folder seat stands
    assert envhook.declared_in(declare("python tool.py --agent-scope ana-2 --dry-run"), cfg) == "ana-2"   # must-pass
    assert envhook.declared_in(declare("python tool.py --agent-scope _x"), cfg) == "_x"
