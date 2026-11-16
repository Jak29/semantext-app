"""The act reader's part of the 1.8.0 attacks (F1-F4, F6, G1-G9 and the reviews). DECISION for 1.8.0: there is NO
dry-run, help-page or -WhatIf exemption. Four attacks in a row found a spelling the exemption let through; it was new in
1.8.0, and 1.7.0 named every one of those calls. A call holding such a word is named as its act and asked about. What
stays from the rounds: fetching runners keep their download, read-sounding tool names with their joiners and the MCP
split, and the group rules for scripts and targets run by name."""
import pytest

from semantext import actclass

ALL = set(actclass.ALL)


def acts(cmd):
    return set(actclass.acts_of_call("Bash", {"command": cmd}))


def ps(cmd):
    return set(actclass.acts_of_call("PowerShell", {"command": cmd}))


def tool(name):
    return set(actclass.acts_of_call(name, {"x": 1}))


# ---- no exemption: what used to be "must stay no act" is now named --------------------------------------------------
FORMER_CONTROLS = [
    (acts, "git push --dry-run origin main", "push"), (acts, "git push -n origin main", "push"),
    (acts, "git push --help", "push"), (acts, "git push -h", "push"), (acts, "git help push", "push"),
    (acts, "git -C repo help push", "push"), (acts, "git push origin main --dry-run", "push"),
    (acts, "git push --dry-run=true origin main", "push"), (acts, "sudo git push --dry-run origin main", "push"),
    (acts, "npm publish --dry-run", "publish"), (acts, "npm --dry-run publish", "publish"),
    (acts, "npm publish --help", "publish"), (acts, "npm help publish", "publish"),
    (acts, "npm publish --dry-run true", "publish"), (acts, "kubectl delete pod x --dry-run=client", "delete"),
    (acts, "kubectl delete pod x --dry-run=server", "delete"), (acts, "kubectl help delete pod x", "delete"),
    (acts, "gh release create v1 --help", "publish"), (acts, "aws s3 rm s3://b/k --dryrun", "delete"),
    (acts, "aws s3 rm s3://b/k --dryrun --recursive", "delete"), (acts, "aws s3 rm s3://b/k help", "delete"),
    (acts, "git clean -n", "delete"), (acts, "git clean -fdn", "delete"), (acts, "git worktree prune -n", "delete"),
    (acts, "make -n clean", "delete"), (acts, "cargo publish --allow-dirty --dry-run", "publish"),
    (acts, "git push --force --dry-run", "push"), (acts, "git push -f -n", "push"),
    (acts, "apt-get -s install x", "download"), (acts, "npx semantic-release --dry-run", "download"),
    (ps, "Remove-Item x -Recurse -WhatIf", "delete"), (ps, "Remove-Item -Path x -Recurse -Force -WhatIf", "delete"),
    (ps, "Remove-Item x -wi", "delete"), (ps, "Remove-Item x -WhatIf:$true", "delete"),
    (ps, "Publish-Module -Name M -NuGetApiKey k -WhatIf", "publish"), (ps, "& Remove-Item x -WhatIf", "delete"),
    (ps, "Remove-AzResourceGroup -Name g -WhatIf", "delete"),
]


@pytest.mark.parametrize("read,cmd,act", FORMER_CONTROLS)
def test_a_dry_run_a_help_page_and_whatif_are_named(read, cmd, act):
    assert act in read(cmd)


@pytest.mark.parametrize("cmd", ["rsync -avz --delete --dry-run src dst", "rsync -avz --delete --dry-run src host:dst",
                                 "rsync -avn src/ host:dst/", "rsync -a --dry-run x host:/y",
                                 "rsync -rltHP --delete-after -n src host:dst", "robocopy a b /MIR /L",
                                 "robocopy a \\\\srv\\share /L"])
def test_a_dry_run_is_read_as_the_command_without_it(cmd):
    # what rsync (robocopy) is named without the dry-run word, it is named with it; and it is named
    plain = " ".join(w for w in cmd.split() if w not in ("--dry-run", "-n", "/L"))
    plain = plain.replace("-avn", "-av")
    assert acts(cmd) == acts(plain) and acts(cmd), (cmd, acts(cmd), plain, acts(plain))


# ---- every must-name case of the attacks stays named -------------------------------------------------------------------
MUST_NAME = [
    # F1
    ("git push -o --dry-run origin main", "push"), ("git push -o --help origin main", "push"),
    ("git commit -m x && git push -o --help", "push"), ("curl -d --help https://x", "send"),
    ("gh release create v1 --notes --dry-run", "publish"), ("gh pr merge 3 --body --dry-run", "publish"),
    ("npm publish --tag --dry-run", "publish"), ("kubectl delete pod x -l --dry-run", "delete"),
    ("mail -s --help a@b.c", "send"), ("git send-email --subject --dry-run 0001.patch", "send"),
    ("git push --push-option --dry-run origin main", "push"), ("git push --repo --help", "push"),
    ("curl --data --dry-run https://x -X POST", "send"), ("npm publish --otp --help", "publish"),
    ("gh release create v1 -n --help", "publish"), ("aws s3 rm s3://b/k --exclude --dryrun", "delete"),
    ("rsync -av --exclude --dry-run src host:dst", "send"), ("git push -o --dry-run=x origin main", "push"),
    ("terraform apply -var --help", "publish"), ("git push origin main -- --help", "push"),
    ("git push origin main -- --dry-run", "push"), ("git push -o -n origin main", "push"),
    ("curl -d -help https://x", "send"),
    # F2
    ("git push --dry-run --no-dry-run origin main", "push"), ("git push -n --no-dry-run origin main", "push"),
    ("npm publish --dry-run --no-dry-run", "publish"), ("npm publish --dry-run false", "publish"),
    ("npm publish --dry-run=0", "publish"), ("npm publish --dry-run=", "publish"),
    ("npm publish --dry-run=false", "publish"), ("kubectl delete pod x --dry-run=none", "delete"),
    ('npm publish --dry-run ""', "publish"),
    # G1, G2
    ("git push -on origin main", "push"), ("git push -fon origin main", "push"),
    ("git push -o=--dry-run origin main", "push"), ("git push -o=-n origin main", "push"),
    ("git clean -fden", "delete"), ("git clean -fdxen", "delete"),
    ("npm --dry-run publish --no-dry-run", "publish"), ("npm --dry-run --no-dry-run publish", "publish"),
    ("npm --tag x --dry-run publish --no-dry-run", "publish"),
    # the review of e4de611: a QUOTED word that starts with `-`
    ('git push "--force" --dry-run origin main', "push"), ("git push '--force' -n origin main", "push"),
    ('npm publish "--tag" --dry-run', "publish"), ('kubectl delete pod x "-l" --dry-run=client', "delete"),
]


@pytest.mark.parametrize("cmd,act", MUST_NAME)
def test_every_must_name_case_is_named(cmd, act):
    assert act in acts(cmd)


@pytest.mark.parametrize("cmd,act", [
    ("git push -o -WhatIf origin main", "push"), ("npm publish -WhatIf", "publish"), ("curl -d -WhatIf https://x", "send"),
    ("Remove-Item x -Recurse -WhatIf:$false", "delete"), ("Remove-Item x -WhatIf -WhatIf:$false", "delete"),
    ("Publish-Site -WhatIf", "publish"), (".\\Remove-Old.ps1 -WhatIf", "delete"),
    ("& .\\Publish-Thing.ps1 -WhatIf", "publish"), ("Remove-Item C:\\x --% -WhatIf", "delete"),
    ("Set-Alias Remove-Item .\\wipe.ps1; Remove-Item C:\\x -WhatIf", "delete"),
    ("Set-Alias Send-MailMessage .\\blast.ps1; Send-MailMessage -To a@b.c -WhatIf", "send"),
    ("function Remove-Item { node wipe.js }; Remove-Item C:\\x -WhatIf", "delete"),
])
def test_whatif_is_named_in_powershell(cmd, act):
    assert act in ps(cmd)


def test_whatif_is_named_in_a_cmd_tool_and_in_bash():
    assert "delete" in set(actclass.acts_of_call("cmd", {"command": "Remove-Item C:\\x -WhatIf"}))
    assert "delete" in acts("Remove-Item x -WhatIf")


# ---- the law: adding a dry-run, help or -WhatIf word never removes an act ----------------------------------------------
LAW_BASH = [
    "git push origin main", "git push --force origin main", "git push -u origin feat", "git clean -fdx", "git rm file",
    "git branch -D feat", "git tag -d v1", "git reset --hard HEAD~1", "git clone https://x/y.git", "git fetch origin",
    "git pull", "git send-email 0001.patch", "npm publish", "npm publish --tag beta", "npm install lodash", "npm ci",
    "yarn add x", "pnpm add x", "cargo publish", "twine upload dist/x.whl", "gh release create v1", "gh pr merge 3",
    "gh repo delete o/r --yes", "kubectl delete pod x", "kubectl apply -f k.yaml", "helm uninstall api",
    "helm upgrade --install api ./chart", "terraform apply", "terraform destroy", "docker push me/img", "docker rm c1",
    "docker pull alpine", "podman push img", "aws s3 rm s3://b/k", "aws s3 cp f s3://b/k", "aws s3 sync ./d s3://b",
    "rsync -avz --delete src host:dst", "rsync -av src host:dst", "scp f host:/x", "curl -X POST https://x",
    "curl -d a=1 https://x", "wget https://x/f", "mail -s hi a@b.c", "rm -rf build", "rmdir d", "make clean",
    "pip install x", "brew install x", "apt-get install x", "wrangler deploy", "vercel deploy --prod",
    "netlify deploy --prod", "firebase deploy", "fly deploy", "npx some-pkg", "pnpm dlx some-pkg",
    "rclone sync a r:b", "gsutil rsync -r a gs://b", "dotnet nuget push x.nupkg", "gem push x.gem", "poetry publish",
    "robocopy a b /MIR", "git push origin :feat", "npm unpublish x", "gh api --method DELETE repos/a/b",
]
LAW_PS = ["Remove-Item x -Recurse", "Remove-Item -Path x", "Publish-Module -Name M", "Send-MailMessage -To a@b.c",
          "Invoke-WebRequest https://x -OutFile f", "Install-Module x", "git push origin main", "npm publish"]
SPELLINGS = ["--dry-run", "--dryrun", "-n", "--dry-run=client", "--dry-run=true", "--dry-run=server", "--help", "-h",
             "-help", "/?", "help", "-WhatIf", "-wi", "-WhatIf:$true", "--what-if", "--whatif", "--simulate", "--noop",
             '"--dry-run"', "'--help'", '"-n"', "--just-print", "--recon", "--no-dry-run", "--dry-run=false"]


def _with(cmd, word, pos):
    ws = cmd.split()
    pos = {"after-program": 1, "middle": max(1, len(ws) // 2), "end": len(ws)}[pos]
    return " ".join(ws[:pos] + [word] + ws[pos:])


def test_the_law_a_dry_run_or_help_word_never_removes_an_act():
    cases = [(acts, c) for c in LAW_BASH] + [(ps, c) for c in LAW_PS]
    named = [(r, c, r(c)) for r, c in cases if r(c)]
    assert len(named) >= 60, len(named)
    bad = []
    for read, cmd, base in named:
        for word in SPELLINGS:
            for pos in ("after-program", "middle", "end"):
                line = _with(cmd, word, pos)
                got = read(line)
                if not base <= got:
                    bad.append((line, sorted(base), sorted(got)))
    assert bad == [], bad[:20]


# ---- fetching runners, tool names, groups (kept from the rounds) ------------------------------------------------------
FETCH = [
    "npx some-pkg --help", "npx -y some-pkg --dry-run", "npx dotenv -- git push --dry-run",
    "npx dotenv -- npm publish --dry-run", "npx --package=evil-pkg tsc", "npx -p evil-pkg@latest tsc",
    "npx --package evil-pkg tsc", "npx tsc@latest", "npx eslint@9 .", "npx tsc@5 --noEmit", "bunx tsc", "pnpx tsc",
    "bunx some-pkg --help", "uvx ruff --help", "(cd web && npx turbo run deploy)",
    "pnpm dlx some-pkg --help", "pnpm dlx some-pkg --dry-run", "yarn dlx some-pkg --help", "yarn dlx -p evil tsc --help",
    "npm x some-pkg --dry-run", "npm exec some-pkg --help", "pipx run some-pkg --help", "uv tool run some-pkg --help",
    "npx @scope/tsc", "npx @evil/eslint .", "npx @acme/jest", "npx -y tsc", "npx --yes tsc", "npx TSC",
    "npx --ignore-existing tsc", "npx --prefer-online tsc",
]


@pytest.mark.parametrize("cmd", FETCH)
def test_a_fetching_runner_keeps_its_download(cmd):
    assert "download" in acts(cmd)


def test_the_inner_command_of_a_runner_is_read():
    assert acts("npx dotenv -- git push origin main") >= {"download", "push"}
    assert acts("npx dotenv -- git push --dry-run") >= {"download", "push"}


@pytest.mark.parametrize("cmd", ["npx tsc", "npx tsc --noEmit", "npx eslint .", "(cd web && npm test)",
                                 "(cd docs && make html)", "(cd web && poetry run pytest)", "(cd web && py -m pytest)",
                                 "(cd x && make build)", "(cd web && turbo run build)", "git status", "git --version"])
def test_controls_that_are_no_act(cmd):
    assert acts(cmd) == set()


NAMES = [
    ("search_and_purchase", "pay"), ("find_and_purchase_item", "pay"), ("mcp__a__view_and_order", "pay"),
    ("check_and_install_updates", "download"), ("mcp__a__search_and_install", "download"),
    ("view_and_release", "publish"), ("mcp__a__query_and_message", "send"), ("mcp__a__count_then_mail", "send"),
    ("get_and_sms", "send"), ("read_and_slack", "send"), ("search_then_purchase", "pay"), ("find_or_order", "pay"),
    ("list_plus_install", "download"), ("searchAndOrder", "pay"), ("mcp__a__purchase_check", "pay"),
    ("install_and_check", "download"), ("mcp__get_tools__purchase", "pay"),
    ("mcp__a__purchase__list", "pay"), ("mcp__shop__buy__get", "pay"), ("mcp__x__send__search", "send"),
    ("mcp__a__install__check", "download"), ("mcp__a__order__get", "pay"), ("mcp__shop__list__orders", "pay"),
    ("mcp__a__get__release", "publish"),
    ("find2purchase", "pay"), ("find_to_purchase", "pay"), ("search_for_install", "download"),
    ("check_with_install", "download"), ("view_with_release", "publish"), ("lookup_via_message", "send"),
    ("search+purchase", "pay"), ("search&purchase", "pay"), ("find_&_purchase", "pay"),
]


@pytest.mark.parametrize("name,act", NAMES)
def test_a_name_that_joins_a_read_to_an_act_is_the_act(name, act):
    assert act in tool(name)


@pytest.mark.parametrize("name", ["list_orders", "get_channel_history", "slack_get_channel_history", "search_threads",
                                  "mcp__shop__get_order", "list_charges", "get_release", "list_releases",
                                  "search_messages", "get_install_status", "view_order_history",
                                  "mcp__slack__get_channel_history", "mcp__4300d8d1__chat_message_search",
                                  "order_lookup", "mcp__slack__search_messages", "mcp__a__list__items",
                                  "search_for_messages", "get_orders_for_customer"])
def test_read_sounding_names_stay_reads(name):
    assert tool(name) == set()


GROUPS = [
    "(cd web && poetry run deploy)", "(cd web && pipenv run deploy)", "(cd web && hatch run deploy)",
    "(cd web && pdm run deploy)", "(cd infra && make --file=release.mk build)", "(cd infra && make -f x.mk)",
    "(cd web && make --eval='all: ; ./ship' all)", "(cd web && py -m deploy)", "(cd web && xargs make deploy)",
    "(cd web && npx turbo run deploy)", "(cd web && turbo run deploy)", "(cd infra && just --justfile=x.just build)",
    "(cd web && uv run deploy)", "{ cd web; uv run deploy; }", "(cd web && uv run ./deploy.py)",
    "(cd web && bunx turbo run deploy)", "(cd web && npm exec turbo run deploy)", "(cd web && poetry -C web run deploy)",
    "(cd web && poetry --directory web run deploy)", "(cd web && hatch -e prod run deploy)",
]


@pytest.mark.parametrize("cmd", GROUPS)
def test_run_by_name_in_a_group_is_every_act(cmd):
    assert acts(cmd) == ALL


@pytest.mark.parametrize("cmd", ["(cd web && deploy)", "(cd infra && make)", "(cd infra && just)", "(cd infra && task)"])
def test_left_what_names_nothing(cmd):
    # the stated limits: a program on PATH the reader does not know, run by its bare name, and a task runner given no
    # target (its default target, which no word names; A20 pins `(cd a && make)` as everyday) are not counted
    assert acts(cmd) == set()
