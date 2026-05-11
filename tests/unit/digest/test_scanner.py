from agentic_trader.digest.scanner import (
    DigestEntry,
    DigestPayload,
    rank_entries,
)


def _entry(symbol: str, pct: float, class_pct: str = "narrow", class_stat: str = "moderate") -> DigestEntry:
    return DigestEntry(
        symbol=symbol,
        width_pct=pct,
        class_pct=class_pct,
        class_stat=class_stat,
        stat_was_fallback=False,
    )


def test_rank_entries_sorted_ascending_by_width_pct():
    entries = [_entry("B", 0.4), _entry("A", 0.1), _entry("C", 0.7)]
    out = rank_entries(entries, top_n=5)
    assert [e.symbol for e in out] == ["A", "B", "C"]


def test_rank_entries_truncates_to_top_n():
    entries = [_entry(f"S{i}", i * 0.1) for i in range(10)]
    out = rank_entries(entries, top_n=5)
    assert len(out) == 5
    assert [e.symbol for e in out] == ["S0", "S1", "S2", "S3", "S4"]


def test_rank_entries_stable_on_ties():
    entries = [_entry("A", 0.5), _entry("B", 0.5), _entry("C", 0.5)]
    out = rank_entries(entries, top_n=5)
    assert [e.symbol for e in out] == ["A", "B", "C"]


def test_digest_payload_holds_metadata():
    payload = DigestPayload(
        tf="D",
        mode="final",
        entries=[_entry("A", 0.1)],
    )
    assert payload.tf == "D"
    assert payload.mode == "final"
    assert len(payload.entries) == 1
