from datetime import UTC, datetime

from agentic_trader.digest.render import render_digest
from agentic_trader.digest.scanner import DigestEntry, DigestPayload


def _payload(mode="final"):
    entries = [
        DigestEntry(
            symbol="GBPUSD", width_pct=0.14,
            class_pct="narrow", class_stat="narrow", stat_was_fallback=False,
        ),
        DigestEntry(
            symbol="EURUSD", width_pct=0.18,
            class_pct="narrow", class_stat="moderate", stat_was_fallback=False,
        ),
        DigestEntry(
            symbol="XAUUSD", width_pct=0.21,
            class_pct="narrow", class_stat="narrow", stat_was_fallback=True,
        ),
        DigestEntry(
            symbol="DJ30", width_pct=0.33,
            class_pct="moderate", class_stat="moderate", stat_was_fallback=False,
        ),
        DigestEntry(
            symbol="NAS100", width_pct=0.44,
            class_pct="moderate", class_stat="wide", stat_was_fallback=False,
        ),
    ]
    return DigestPayload(tf="D", mode=mode, entries=entries)


def test_render_final_header_contains_tf_and_final_flag():
    now = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
    text = render_digest(_payload("final"), now=now)
    assert "Daily" in text
    assert "final" in text
    assert "2026-05-12 00:00 UTC" in text


def test_render_preview_header_contains_preview_marker():
    now = datetime(2026, 5, 11, 16, 0, tzinfo=UTC)
    text = render_digest(_payload("preview"), now=now)
    assert "preview" in text


def test_render_lists_top_entries_with_widths_and_classes():
    text = render_digest(_payload("final"), now=datetime(2026, 5, 12, 0, 0, tzinfo=UTC))
    assert "GBPUSD" in text
    assert "0.14%" in text
    assert "narrow / narrow" in text


def test_render_fallback_uses_em_dash():
    text = render_digest(_payload("final"), now=datetime(2026, 5, 12, 0, 0, tzinfo=UTC))
    # XAUUSD entry has stat_was_fallback=True
    assert "narrow / —" in text


def test_render_handles_empty_entries():
    payload = DigestPayload(tf="D", mode="final", entries=[])
    text = render_digest(payload, now=datetime(2026, 5, 12, 0, 0, tzinfo=UTC))
    assert "Daily" in text
    # Should not raise; a short "no symbols" line is acceptable
    assert "no symbols" in text.lower() or "empty" in text.lower() or "—" in text
