"""The `semantext` command, end to end, in a temporary home."""
import json

import pytest

from semantext import __version__
from semantext.cli import main


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and __version__ in capsys.readouterr().out


def test_init_and_card(capsys, home):
    code, out, _ = run(capsys, "init")
    assert code == 0 and str(home) in out
    code, out, _ = run(capsys, "card")
    assert code == 0 and out.startswith("# Semantext")


def test_a_new_environment_from_suggestions(capsys, home):
    code, out, _ = run(capsys, "env", "new", "Office")
    assert code == 0 and "Made Office (office)" in out
    code, out, _ = run(capsys, "env")
    assert "* office" in out
    code, out, _ = run(capsys, "env", "use", "default")
    assert code == 0 and "Default" in out


def test_teach_rules_toggle_and_undo(capsys, home):
    run(capsys, "teach", "Answer", "in", "one", "line")
    code, out, _ = run(capsys, "rules")
    assert "default.learned-1" in out and "Answer in one line" in out
    run(capsys, "toggle", "default.learned-1")
    assert "Answer in one line" not in run(capsys, "card")[1]
    code, out, _ = run(capsys, "undo", "--last")
    assert code == 0 and "Answer in one line" in run(capsys, "card")[1]
    run(capsys, "undo", "default.learned-1")
    assert "Answer in one line" not in run(capsys, "card")[1]
    assert "archived" in run(capsys, "rules", "--all")[1]


def test_read_saves_nothing(capsys, home):
    code, out, _ = run(capsys, "read", "Can", "you", "delete", "it?")
    assert code == 0 and "A question" in out and "Needs your word" in out


def test_hear_recall_propose_and_forget(capsys, home):
    run(capsys, "hear", "Never use emoji in answers")
    assert "Never use emoji" in run(capsys, "recall")[1]
    code, out, _ = run(capsys, "propose")
    assert "1. Never use emoji in answers." in out
    code, out, _ = run(capsys, "propose", "--accept", "1")
    assert code == 0 and "Accepted 1" in out
    assert "Never use emoji in answers. (learned)" in run(capsys, "card")[1]
    assert "Forgot 1 item" in run(capsys, "forget", "--all")[1]


def test_config_hear_prompts(capsys, home):
    assert "off" in run(capsys, "config", "hear-prompts")[1]
    run(capsys, "config", "hear-prompts", "on")
    assert "on" in run(capsys, "config", "hear-prompts")[1]


def test_install_prints_first_and_applies_only_when_asked(capsys, home, tmp_path):
    settings = tmp_path / "settings.json"
    code, out, _ = run(capsys, "install", "claude-code", "--settings", str(settings), "--command", "semantext hook")
    assert code == 0 and '"UserPromptSubmit"' in out and not settings.exists()
    code, out, _ = run(capsys, "install", "claude-code", "--apply", "--settings", str(settings),
                       "--command", "semantext hook")
    assert code == 0 and "Connected" in out
    assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
    code, out, _ = run(capsys, "uninstall", "claude-code", "--apply", "--settings", str(settings))
    assert code == 0 and "Disconnected" in out


def test_install_with_the_default_command_connects_and_backs_up(capsys, home, tmp_path):
    # The plain form a new user types. (An option once shared its name with the sub-command and turned this into
    # the help text, exit 0; a test that always passed --command could not see it.)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    code, out, _ = run(capsys, "install", "claude-code")
    assert code == 0 and '"UserPromptSubmit"' in out and "semantext" in out and "usage:" not in out
    code, out, _ = run(capsys, "install", "claude-code", "--apply", "--settings", str(settings))
    assert code == 0 and "Connected" in out
    hooks = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
    assert any("semantext" in h["command"] and "hook" in h["command"] for g in hooks for h in g["hooks"])
    assert list(tmp_path.glob("settings.json.semantext-backup-*"))


@pytest.mark.parametrize("argv", [["init"], ["card"], ["env"], ["env", "ideas"], ["rules"], ["read", "hi"],
                                  ["where"], ["recall"], ["propose"], ["config", "hear-prompts"],
                                  ["install", "claude-code"], ["uninstall", "claude-code"], ["doctor"]])
def test_every_command_runs_its_own_handler_not_the_help(capsys, home, argv):
    code, out, err = run(capsys, *argv)
    assert code == 0 and not out.startswith("usage:"), argv


def test_env_new_with_no_matching_pack_starts_empty_and_shows_how_to_add(capsys, home):
    code, out, _ = run(capsys, "env", "new", "Zzyzx")
    assert code == 0 and "Made Zzyzx (zzyzx) with 0 suggested rules" in out
    assert "starts empty" in out and "work.outcome-first" in out and "semantext env add" in out
    assert "* zzyzx" in run(capsys, "env")[1]
    code, out, _ = run(capsys, "env", "add", "work.outcome-first", "game.no-spoilers")
    assert code == 0 and "Added 2 rules to Zzyzx" in out
    assert "zzyzx.outcome-first" in run(capsys, "card")[1]
    code, out, _ = run(capsys, "env", "add", "work.outcome-first")
    assert code == 0 and "already holds them" in out


def test_env_new_with_pick_starts_with_exactly_those(capsys, home):
    code, out, _ = run(capsys, "env", "new", "Zzyzx", "--pick", "work.outcome-first", "game.no-spoilers")
    assert code == 0 and "Made Zzyzx (zzyzx) with 2 suggested rules" in out and "starts empty" not in out


def test_env_add_refuses_an_unknown_suggestion_and_changes_nothing(capsys, home):
    run(capsys, "init")
    before = run(capsys, "card")[1]
    code, _, err = run(capsys, "env", "add", "work.nope")
    assert code == 1 and "no such suggestion: work.nope" in err
    assert run(capsys, "card")[1] == before


def test_env_new_refuses_an_unknown_pick(capsys, home):
    code, _, err = run(capsys, "env", "new", "Lab", "--pick", "work.nope")
    assert code == 1 and "no such suggestion: work.nope" in err


def test_profile_is_another_name_for_env(capsys, home):
    # "Profile" is the word a first user reached for; it finds the same command.
    code, out, _ = run(capsys, "profile", "new", "Office")
    assert code == 0 and "Made Office (office)" in out
    assert "* office" in run(capsys, "profile", "list")[1]


def test_env_use_takes_a_name_or_a_title_ignoring_case(capsys, home):
    run(capsys, "env", "new", "Deep Work", "--none")
    run(capsys, "env", "use", "default")
    code, out, _ = run(capsys, "env", "use", "deep", "WORK")
    assert code == 0 and "Active environment: Deep Work" in out
    code, out, _ = run(capsys, "env", "use", "DEFAULT")
    assert code == 0 and "Active environment: Default" in out
    assert "(Deep Work environment)" in run(capsys, "card", "--env", "deep work")[1]
    code, _, err = run(capsys, "env", "use", "Deep Wrok")
    assert code == 1 and "did you mean deep-work?" in err
    code, _, err = run(capsys, "env", "use", "Kitchen")
    assert code == 1 and "no environment called 'Kitchen'" in err and "did you mean" not in err
    run(capsys, "env", "new", "Baking", "--none")
    code, _, err = run(capsys, "env", "use", "Kayaking")      # a different word, not a near miss
    assert code == 1 and "did you mean" not in err
    assert "did you mean baking?" in run(capsys, "env", "use", "bakin")[2]


def test_a_second_environment_with_the_same_title_is_numbered(capsys, home):
    run(capsys, "env", "new", "Cooking", "--none")
    code, out, _ = run(capsys, "env", "new", "Cooking", "--none")
    assert code == 0 and "Made Cooking 2 (cooking-2)" in out
    listing = run(capsys, "env")[1]
    assert "Cooking 2" in listing and listing.count("Cooking") == 2


def test_a_hand_broken_rule_file_is_one_line_not_a_traceback(capsys, home):
    run(capsys, "init")
    (home / "profiles" / "default" / "SEMANTICS.yaml").write_text("environment: [broken", encoding="utf-8")
    code, out, err = run(capsys, "card")
    assert code == 1 and "is not valid YAML" in err and "Traceback" not in err


def test_read_says_each_thing_once(capsys, home):
    code, out, _ = run(capsys, "read", "Please", "delete", "the", "drafts")
    assert out.count('Needs your word before it can "delete"') == 1 and "Needs your word: Needs" not in out


def test_rules_says_when_undone_rules_are_hidden(capsys, home):
    run(capsys, "teach", "Answer in one line")
    run(capsys, "undo", "default.learned-1")
    out = run(capsys, "rules")[1]
    assert "1 undone rule hidden; --all shows it" in out and "default.learned-1" not in out
    assert "default.learned-1" in run(capsys, "rules", "--all")[1]


def test_env_new_lists_what_it_kept(capsys, home):
    out = run(capsys, "env", "new", "Office")[1]
    assert "office.outcome-first:" in out and "semantext toggle ID" in out


def test_serve_on_a_busy_port_is_one_line(capsys, home, monkeypatch):
    def busy(*a, **k):
        raise OSError(10048, "Only one usage of each socket address is normally permitted")
    monkeypatch.setattr("semantext.server.make_server", busy)
    code, out, err = run(capsys, "serve", "--port", "8765")
    assert code == 1 and "already in use? Try --port 8766" in err and "Traceback" not in err


def test_doctor(capsys, home):
    code, out, _ = run(capsys, "doctor")
    assert code == 0 and "fits the 9500-byte hook limit" in out


def test_a_refusal_is_a_message_and_exit_code_1(capsys, home):
    code, out, err = run(capsys, "toggle", "default.nope")
    assert code == 1 and "semantext: no rule 'default.nope'" in err


def test_the_home_option(capsys, tmp_path):
    other = tmp_path / "elsewhere"
    code, out, _ = run(capsys, "--home", str(other), "init")
    assert code == 0 and (other / "profiles" / "default" / "SEMANTICS.yaml").exists()
