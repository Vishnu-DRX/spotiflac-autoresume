from spotiflac_autoresume.ui import log_rows, parse_break_events, parse_break_rows

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


# The Debug Logs page renders '[ time ] [ level ] message' as separate text nodes (captured from the live app).
PAGE = ["Debug Logs", "[", "11:30:02", "]", "[", "success", "]", "downloaded: Paradise - Bazzi",
        "[", "11:30:06", "]", "[", "error", "]", "Tidal error: Error: all requested Tidal qualities failed: "
        "failed to get download URL: This is normal and not a bug. The server is taking a scheduled short "
        "break. Please try again in about 120 minute(s).",
        "[", "11:30:06", "]", "[", "info", "]", "servers on a scheduled break. pausing downloads."]


def test_log_rows_groups_time_level_message():
    rows = log_rows(PAGE)
    assert rows[0] == ("11:30:02", "success", "downloaded: Paradise - Bazzi")
    assert len(rows) == 3 and rows[1][1] == "error"


def test_break_rows_carry_timestamp_minutes_and_a_stable_key():
    ev = parse_break_rows(log_rows(PAGE))
    assert len(ev) == 1                      # the 'servers on a scheduled break' line is not the pattern
    assert ev[0]["time"] == "11:30:06" and ev[0]["minutes"] == 120
    assert ev[0]["key"] == parse_break_rows(log_rows(PAGE))[0]["key"]
