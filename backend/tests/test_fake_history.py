"""段階0の完了条件「架空の History ファイルができ、テストが自動で通る」を確かめる。"""

import sqlite3
from datetime import datetime, timezone

import tadori
from tests.fixtures.make_fake_history import (
    CHROME_EPOCH_OFFSET_US,
    VISITS,
    build,
    to_chrome_time,
)


def test_package_imports():
    assert tadori.__doc__


def test_chrome_time_conversion():
    # Unix 時刻 0（1970-01-01 UTC）は、Chrome の時刻では 1601年起点の差の分だけ大きい
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert to_chrome_time(epoch) == CHROME_EPOCH_OFFSET_US


def test_build_creates_chrome_tables(tmp_path):
    path = tmp_path / "History"
    ids = build(path)
    assert len(ids) == len(VISITS)

    con = sqlite3.connect(path)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"urls", "visits", "visit_source", "keyword_search_terms"} <= tables
        assert con.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == len(VISITS)
        # 同期された訪問だけが visit_source に入る
        assert con.execute("SELECT id, source FROM visit_source").fetchall() == [(ids["gs"], 0)]
        # Lens は、新しいタブで開いた Plotly（分岐 C）の開き元になっている
        opener = con.execute("SELECT opener_visit FROM visits WHERE id = ?", (ids["g5"],)).fetchone()[0]
        assert opener == ids["g2"]
        # OCR の調べ物の開始時刻が、06 API 仕様の例（started_at）と一致する
        started = con.execute("SELECT visit_time FROM visits WHERE id = ?", (ids["g0"],)).fetchone()[0]
        assert (started - CHROME_EPOCH_OFFSET_US) // 1000 == 1760270520000
    finally:
        con.close()
