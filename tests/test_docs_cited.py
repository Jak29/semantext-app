"""Every document the package's code cites is in the repository. The code points its readers at docs/*.md for the
contracts it keeps (the plug-in API, the run-record schema, the back-test, the page-module sandbox); a citation of a
file that is not there sends them nowhere, as ECOSYSTEM.md and RUN-RECORD-SCHEMA.md once did. Read from a source
checkout; skipped when the package is installed without its docs."""
import re
from pathlib import Path

import pytest

import semantext

ROOT = Path(semantext.__file__).resolve().parents[1]
CITED = re.compile(r"(?<![\w./-])docs/[\w./-]+?\.md\b")
TEXT = (".py", ".js", ".html", ".css", ".json", ".md", ".txt")
GONE = ("ECOSYSTEM.md", "RUN-RECORD-SCHEMA.md")   # the two contracts once cited and never in the repository


def citations(package: Path) -> dict[str, list[str]]:
    """Each docs/*.md path cited in a text file under `package`, with the files that cite it."""
    out: dict[str, list[str]] = {}
    for p in sorted(package.rglob("*")):
        if p.is_file() and p.suffix in TEXT:
            for m in CITED.finditer(p.read_text(encoding="utf-8", errors="replace")):
                out.setdefault(m.group(0), []).append(p.relative_to(package).as_posix())
    return out


def missing(package: Path, repo: Path) -> dict[str, list[str]]:
    """The cited documents that are not in `repo`, with who cites them."""
    return {doc: who for doc, who in citations(package).items() if not (repo / doc).is_file()}


@pytest.fixture
def checkout():
    if not (ROOT / "docs").is_dir():
        pytest.skip("docs/ is not beside the package (installed from a wheel)")
    return ROOT


def test_every_docs_path_the_package_cites_exists(checkout):
    cited = citations(checkout / "semantext")
    assert "docs/plugin-api.md" in cited and "docs/run-record-schema.md" in cited   # the check has something to see
    assert missing(checkout / "semantext", checkout) == {}


def test_the_two_contracts_once_cited_from_nowhere_are_cited_nowhere(checkout):
    said = [(p.relative_to(checkout).as_posix(), name) for folder in ("semantext", "tests", "docs")
            for p in sorted((checkout / folder).rglob("*")) if p.is_file() and p.suffix in TEXT
            and p.name != Path(__file__).name
            for name in GONE if name in p.read_text(encoding="utf-8", errors="replace")]
    assert said == []


def test_a_citation_of_a_document_that_is_not_there_is_found(tmp_path):
    # The control: a package citing one document that is there and one that is not. The check must name the second,
    # and only it, so the pass above could have failed.
    package, docs = tmp_path / "pkg", tmp_path / "docs"
    package.mkdir()
    docs.mkdir()
    (docs / "here.md").write_text("# here\n", encoding="utf-8")
    (package / "mod.py").write_text('"""See docs/here.md and docs/gone.md."""\n', encoding="utf-8")
    (package / "page.js").write_text("// (docs/gone.md, the second citer)\n", encoding="utf-8")
    assert missing(package, tmp_path) == {"docs/gone.md": ["mod.py", "page.js"]}
    (docs / "gone.md").write_text("# gone no more\n", encoding="utf-8")
    assert missing(package, tmp_path) == {}
