"""No test reads, lists or writes the person's real files. Every test runs with its home pointed into a temporary
folder (conftest.away_from_the_real_home), and an audit hook set for the whole run (conftest._audit) records any file
opened, folder listed or name changed under the real user home, outside the temporary folder, this checkout and
Python's own folders. The last test of the run fails if anything was recorded, naming the test and the path.

What it watches: this test process only (a test's child process is not audited), and the audit events Python raises
for opening a file, listing or making a folder, renaming, removing and linking; a plain stat is not one of them."""
import os

import conftest


def test_a_read_of_the_real_home_is_caught(tmp_path):   # must refuse: the check could fail
    before = len(conftest.TOUCHED)
    probe = os.path.join(conftest.REAL_HOME, ".semantext-audit-probe-never-made")   # never there: nothing is read
    try:
        open(probe, "rb").close()
    except OSError:
        pass
    caught = conftest.TOUCHED[before:]
    del conftest.TOUCHED[before:]   # the control's own touch is not the run's
    assert [(e, p) for _, e, p in caught] == [("open", os.path.normcase(probe))]
    assert caught[0][0].endswith("test_a_read_of_the_real_home_is_caught")


def test_a_touch_of_the_temporary_folder_or_this_checkout_is_not_caught(tmp_path):   # must pass
    before = len(conftest.TOUCHED)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    os.listdir(conftest.ROOT)
    assert conftest.TOUCHED[before:] == []
    assert conftest.real_home_touch("open", (os.path.join(conftest.REAL_HOME, "notes.txt"),)) is not None
    assert conftest.real_home_touch("open", (str(tmp_path / "x.txt"),)) is None


def test_every_path_of_an_event_is_looked_at(tmp_path):   # must refuse a destination in the real home
    inside = os.path.join(conftest.REAL_HOME, "renamed-here-never-made")
    for event in ("os.rename", "os.link", "os.symlink", "shutil.copyfile"):
        assert conftest.real_home_touch(event, (str(tmp_path / "a"), inside, -1, -1)) == os.path.normcase(inside)
        assert conftest.real_home_touch(event, (str(tmp_path / "a"), str(tmp_path / "b"), -1, -1)) is None   # pass
    assert conftest.real_home_touch("os.rename", (3, inside)) == os.path.normcase(inside)   # a descriptor skipped


def test_no_test_of_the_run_touched_the_real_user_home():   # runs last (conftest.pytest_collection_modifyitems)
    assert conftest.TOUCHED == [], "\n".join(f"{t}: {e} {p}" for t, e, p in conftest.TOUCHED[:20])
