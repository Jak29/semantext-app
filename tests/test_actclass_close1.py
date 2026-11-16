"""close1 (the fresh attack on actclass r6, v2-26): each finding's exact inputs must name their acts (must-pass), and
the controls beside them must not (must-refuse).

F1: a QUOTED positional -ArgumentList string that begins with '-' and holds a ':' was dropped as an unknown parameter.
F2: `&` on the right of a PowerShell assignment (`$r = & $deploy`) ended the statement instead of calling.
F3: Start-Process of a POSIX shell (MSYS bash, wsl) with a single-quoted item: the child keeps the quoted run whole.
F5: a group that runs a script by name behind a prefix wrapper (`sudo`), or a gulp/grunt target, named nothing."""
from __future__ import annotations

import pytest

from semantext.actclass import ALL, acts_of_call

PS = "PowerShell"
EVERY = set(ALL)


def _acts(tool, cmd):
    return set(acts_of_call(tool, {"command": cmd}))


F1_PASS = [
    (PS, r"Start-Process git '-C C:\repo push origin main' -Wait", {"push"}),
    (PS, r'Start-Process git "-C C:\repo push origin main" -NoNewWindow -Wait', {"push"}),
    (PS, r"Start-Process git '-c http.proxy=http://proxy:8080 push origin main' -Wait", {"push"}),
    (PS, r"Start-Process git '--git-dir=C:\r\.git push origin main' -Wait", {"push"}),
    (PS, r"Start-Process scp '-i C:\keys\id dist.zip deploy@web01:/var/www/' -Wait", {"publish", "send"}),
    (PS, r"Start-Process powershell '-NoProfile -Command git -C C:\repo push origin main' -Verb RunAs", {"push"}),
    (PS, r"Start-Process wsl '-- git -C C:\repo push origin main'", {"push"}),
    ("Bash", "pwsh -Command \"Start-Process git '-C C:\\repo push origin main' -Wait\"", {"push"}),
    (PS, r"Start-Process git -ArgumentList:'push','origin' -Wait", {"push"}),     # the colon form is still a parameter
]
F1_REFUSE = [
    (PS, r"Start-Process git '-C C:\repo status' -Wait"),
    (PS, r"Start-Process git -ArgumentList 'status' -Wait"),
    (PS, r"Start-Process notepad 'C:\notes.txt'"),
    (PS, r"Start-Process git '-C C:\repo log --oneline' -WorkingDirectory 'C:\repo'"),
]

F2_PASS = [
    r"$deploy = { .\deploy.ps1 -Env prod }; $r = & $deploy",
    r"$deploy = { .\deploy.ps1 -Env prod }; $r = &$deploy",
    r"$out = & $deployScript -Environment prod",
    r"$code = & $tool push origin main; exit $code",
    r"$null = & $uninstaller /S",
    r"$deploy = { .\deploy.ps1 -Env prod }; $r += & $deploy",
    r"$x = & { .\deploy.ps1 }",                                   # a block written after `= &` runs there
]
F2_REFUSE = [
    r"$deploy = { .\deploy.ps1 -Env prod }",
    r"$x = & git status",
    r"$v = $PSVersionTable",
    r"$r = 1; Get-Date",
]

F3_PASS = [
    "Start-Process bash -ArgumentList '-c', \"'git push origin main'\"",
    "Start-Process bash -ArgumentList \"-lc\", \"'git push origin main'\" -Wait",
    "Start-Process wsl -ArgumentList 'bash', '-c', \"'git push origin main'\"",
]
F3_REFUSE = [
    "Start-Process bash -ArgumentList '-c', \"'git status'\"",
    "Start-Process git -ArgumentList \"'status'\"",
]

F5_PASS = [
    "(cd infra && sudo ./deploy.sh prod)",
    "(cd infra && sudo -E nohup ./deploy.sh prod)",     # a valued option as its own word (`nice -n 5`) is a stated limit
    "(cd web && gulp deploy)",
    "(cd web && grunt release)",
    "(cd svc && timeout 900 make deploy)",
    "(cd svc && poetry run python deploy.py)",
    "(cd svc && bundle exec rake deploy)",
]
F5_REFUSE = [
    "(cd web && gulp test)",
    "(cd svc && timeout 900 make test)",
    "(cd svc && poetry run pytest)",
    "(cd svc && bundle exec rake test)",
    "(cd web && sudo npm run lint)",
    "(cd src && sudo python -m pytest)",
]


@pytest.mark.parametrize("tool,cmd,want", F1_PASS)
def test_f1_quoted_positional_with_colon_is_the_argument_list(tool, cmd, want):
    assert want <= _acts(tool, cmd)


@pytest.mark.parametrize("tool,cmd", F1_REFUSE)
def test_f1_controls_name_nothing(tool, cmd):
    assert _acts(tool, cmd) == set()


@pytest.mark.parametrize("cmd", F2_PASS)
def test_f2_call_operator_after_an_assignment_runs(cmd):
    assert _acts(PS, cmd) == EVERY


@pytest.mark.parametrize("cmd", F2_REFUSE)
def test_f2_controls(cmd):
    assert _acts(PS, cmd) == set()


@pytest.mark.parametrize("cmd", F3_PASS)
def test_f3_posix_shell_keeps_single_quoted_run(cmd):
    assert "push" in _acts(PS, cmd)


@pytest.mark.parametrize("cmd", F3_REFUSE)
def test_f3_controls(cmd):
    assert _acts(PS, cmd) == set()


@pytest.mark.parametrize("cmd", F5_PASS)
def test_f5_group_runs_by_name_behind_a_wrapper(cmd):
    assert _acts("Bash", cmd) == EVERY


@pytest.mark.parametrize("cmd", F5_REFUSE)
def test_f5_controls(cmd):
    assert _acts("Bash", cmd) == set()
