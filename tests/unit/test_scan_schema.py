from agentic_trader.data.repository import Repository


async def _table_names(repo: Repository) -> set[str]:
    cur = await repo._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    rows = await cur.fetchall()
    return {r[0] for r in rows}


async def test_scanner_tables_created(tmp_path):
    repo = Repository(db_path=tmp_path / "scan.db")
    await repo.connect()
    await repo.init_schema()
    names = await _table_names(repo)
    assert {"touches", "scan_alerts", "scan_notif_log"} <= names
    # legacy tables remain (archived, not dropped)
    assert {"signals_log", "pivots_cache"} <= names
    # touches must carry every TouchEvent field that is persisted, incl. zone_kind
    cur = await repo._db.execute("PRAGMA table_info(touches)")
    cols = {r[1] for r in await cur.fetchall()}
    assert {
        "symbol", "timeframe", "zone_kind", "tag", "zone_low", "zone_high",
        "side", "direction", "bar_time", "seen_at", "expires_at",
    } <= cols
    await repo.close()
