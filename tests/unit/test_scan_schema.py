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
    await repo.close()
