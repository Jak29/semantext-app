"""A time ending in Z is read as UTC on Python 3.10 too. datetime.fromisoformat takes a trailing Z only from 3.11, so
on 3.10 every act of the person's was undecidable and every verdict unfound (fixed in 1.3.0). On 3.11 and later every
other test passes whether the fix is there or not, so here fromisoformat is stood in for by one that refuses a Z as
3.10's does, and the two readers that are handed such times are held to read them anyway."""
from datetime import datetime, timezone

import pytest

from semantext.sources import workverdicts
from semantext.work import span


class Strict310(datetime):
    """datetime as Python 3.10 has it, as far as these readers can tell: fromisoformat refuses a trailing Z."""

    @classmethod
    def fromisoformat(cls, text):
        if isinstance(text, str) and text[-1:] in ("Z", "z"):
            raise ValueError(f"Invalid isoformat string: {text!r}")
        return datetime.fromisoformat(text)


@pytest.fixture
def on_310(monkeypatch):
    monkeypatch.setattr(span, "datetime", Strict310)
    monkeypatch.setattr(workverdicts, "datetime", Strict310)


def test_the_stand_in_refuses_a_z_as_python_3_10_does():
    # The control: a reader that handed the text straight to it would find no time, so the passes below could fail.
    with pytest.raises(ValueError):
        Strict310.fromisoformat("2026-10-24T13:59:00Z")
    assert Strict310.fromisoformat("2026-10-24T13:59:00+00:00") == datetime(2026, 10, 24, 13, 59, tzinfo=timezone.utc)


@pytest.mark.parametrize("text", ["2026-10-24T13:59:00Z", "2026-10-24T13:59:00.123Z", "2026-10-24T13:59:00z"])
def test_a_transcript_time_ending_in_z_is_read_as_utc(on_310, text):   # must pass
    assert span.utc_stamp(text) == "2026-10-24T13:59:00Z"


@pytest.mark.parametrize("text", ["2026-10-24T13:59:00", "not a timeZ", "Z", "", None, "2026-10-24T13:59:00" + "0" * 40])
def test_a_transcript_time_with_no_zone_or_none_at_all_is_no_time(on_310, text):   # must refuse
    assert span.utc_stamp(text) is None


def test_a_verdict_time_ending_in_z_is_read_as_utc(on_310):   # must pass
    assert workverdicts._when("2026-10-24T13:59:00Z") == datetime(2026, 10, 24, 13, 59, tzinfo=timezone.utc)
    assert workverdicts._when("2026-10-24T14:59:00+01:00") == datetime(2026, 10, 24, 13, 59, tzinfo=timezone.utc)


@pytest.mark.parametrize("text", ["not a timeZ", "Z", "", None, 7])
def test_a_verdict_time_that_is_no_time_is_none(on_310, text):   # must refuse
    assert workverdicts._when(text) is None
