from spotiflac_autoresume.ui import parse_break_events

REAL = ("all requested Tidal qualities failed: failed to get download URL: This is normal and not a bug. "
        "The server is taking a scheduled short break. Please try again in about 120 minute(s).")


def test_real_message_gives_120_minutes():
    assert [m for _, m in parse_break_events(REAL)] == [120]


def test_block_with_several_breaks_counts_each_with_its_own_minutes():
    block = REAL + "\n[02:10] other noise\n" + REAL.replace("120", "30")
    assert [m for _, m in parse_break_events(block)] == [120, 30]


def test_message_without_number_yields_none():
    assert [m for _, m in parse_break_events("server is taking a scheduled short break.")] == [None]


def test_unrelated_errors_are_ignored():
    assert parse_break_events("Amazon API returned status 409") == []
    assert parse_break_events("track not found for query: Zz Michael Veli") == []


def test_case_insensitive_and_custom_pattern():
    assert len(parse_break_events("SCHEDULED SHORT BREAK ... in about 5 minutes")) == 1
    assert len(parse_break_events("maintenance window, about 7 minutes", pattern="maintenance window")) == 1
