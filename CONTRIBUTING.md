# Contributing

Thank you for helping. Semantext is small on purpose: the rules belong to the user, the files are plain, and nothing
leaves the machine. Changes that keep it that way are welcome.

## Setup

```bash
git clone https://github.com/Jak29/semantext-app.git
cd semantext-app
pip install -e ".[test]"
python -m pytest
```

You need Python 3.10 or newer. The whole suite takes about 22 minutes on one of GitHub's Linux runners. CI runs it on
Linux, Windows and macOS, for Python 3.10 to 3.14; while the repository is private, a push runs Linux and two Windows
versions, and the rest waits for a tag or a run by hand (see the comment at the top of `.github/workflows/ci.yml`).
Six tests whose time bounds a hosted runner misses carry the `timing` mark: CI reports them and does not require
them, and `python -m pytest` runs them with the rest. `tests/test_ci_runs_every_test.py` lists them and refuses the
mark on any other test.

## How the tests are written

- **In pairs.** For each behaviour there is a test that it works (must pass) and a test that what should be refused is
  refused (must refuse). For example, the editor must save a valid edit, and must refuse broken YAML, a changed
  environment id, a rule without an id or a statement, and duplicate ids.
- **A guard ships with a test that fails without it.** When you add a check, such as a refusal, a limit or a header,
  add a test for it. Then remove the check, and confirm the test fails. The existing guards were checked this way.
- **No test touches your real files.** The `home` fixture in `tests/conftest.py` points `SEMANTEXT_HOME`, `HOME` and
  `USERPROFILE` at a temporary folder. Use it, or the `store` fixture, in any test that reads or writes.
- **No test opens a network connection.**

## Rule files and examples

- **The schema:** rule files are YAML, as described in [docs/rule-files.md](docs/rule-files.md).
- **No null values:** the shipped files in `semantext/data/` contain none, and a test checks this. Keep `examples/` the
  same: write every field you use with a value, and leave out the fields you do not use.
- **Statements:** write each one as an instruction to the assistant, one idea each, in plain words.

## Commits and pull requests

- A commit message describes the change: what changed and why, in a sentence or two.
- Keep a pull request to one change, with its tests.
- When behaviour a user can see changes, update README.md or `docs/`. Add a line under `[Unreleased]` in CHANGELOG.md.

## Security

Please report security problems privately, as described in [SECURITY.md](SECURITY.md), not in a public issue.

## License

By contributing, you agree that your contributions are licensed under the MIT License (see [LICENSE](LICENSE)).
