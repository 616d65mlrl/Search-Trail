"""概念の抽出（FR-10）のテスト。"""

import sqlite3
from contextlib import closing

import pytest

from tadori.analyze.concepts import (
    extract_concepts,
    japanese_nouns,
    site_segments,
    split_words,
    strip_site_name,
)
from tadori.db.connection import connect
from tadori.ingest.importer import import_history
from tests.fixtures.make_fake_history import build


@pytest.fixture
def db(tmp_path):
    history = tmp_path / "chrome" / "History"
    history.parent.mkdir()
    build(history)
    db = tmp_path / "tadori.db"
    import_history(history, db)
    return db


def _concepts(db) -> dict[str, set[str]]:
    """概念の表示名 → その概念を持つページのタイトル。"""
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            "SELECT c.label, p.title FROM concepts c JOIN page_concepts pc ON pc.concept_id = c.id"
            " JOIN pages p ON p.id = pc.page_id"
        ).fetchall()
    result: dict[str, set[str]] = {}
    for label, title in rows:
        result.setdefault(label, set()).add(title)
    return result


def test_japanese_nouns_merge_single_characters():
    # 辞書に無い「表組」は「表」「組」に分かれるので、1文字の名詞は隣とくっつける
    assert japanese_nouns("で表組ビューアを作る") == ["表組", "ビューア"]
    assert japanese_nouns("辞書とは？") == ["辞書"]
    assert japanese_nouns("変数と代入") == ["変数", "代入"]


def test_split_words():
    assert split_words("書類をOCR化する") == ["OCR", "書類"]
    # つながった識別子は、部品も候補にする
    assert split_words("aio-libs/aiohttp") == ["aio-libs", "aio", "libs", "aiohttp"]
    # 全角の英数字も半角として扱う
    assert split_words("Ｐｙｔｈｏｎ") == ["Python"]


def test_site_name_is_removed_from_titles():
    titles = {
        "www.google.com": ["python 辞書 - Google 検索", "OCR 作り方 - Google 検索"],
        "docs.python.jp": [
            "辞書とは？ - The Python Programming Language 日本語版",
            "変数と代入 - The Python Programming Language 日本語版",
        ],
        "plotly.io": ["Plotly", "What is Plotly? - Plotly"],
    }
    site = site_segments(titles)
    assert site["www.google.com"] == {"google 検索"}
    assert strip_site_name("辞書とは？ - The Python Programming Language 日本語版", site["docs.python.jp"]) == "辞書とは？"
    assert strip_site_name("What is Plotly? - Plotly", site["plotly.io"]) == "What is Plotly?"
    # 全部がサイト名に見えるときは残す
    assert strip_site_name("Plotly", site["plotly.io"]) == "Plotly"


def test_concepts_from_fake_history(db):
    concepts = _concepts(db)
    assert set(concepts) == {"python", "Plotly", "表組", "辞書", "aiohttp", "websocket", "Dash", "OCR"}
    # 検索語とタイトルの両方から取れる
    assert concepts["OCR"] == {"OCR 作り方 - Google 検索", "書類をOCR化する"}
    assert concepts["辞書"] == {"python 辞書 - Google 検索", "辞書とは？ - The Python Programming Language 日本語版"}
    # サイト名（GitHub、Google 検索）や除外語（作り方）は概念にならない
    assert not {"GitHub", "github", "Google", "作り方", "検索"} & set(concepts)


def test_weights_by_source(db):
    with closing(sqlite3.connect(db)) as con:
        rows = con.execute(
            "SELECT pc.source, pc.weight FROM page_concepts pc JOIN concepts c ON c.id = pc.concept_id"
            " JOIN pages p ON p.id = pc.page_id WHERE c.label = 'OCR' AND p.url_norm = 'search:ocr 作り方'"
        ).fetchall()
    assert sorted(rows) == [("search", 1.0), ("title", 0.6)]


def test_stopwords_and_synonyms_can_be_edited(db):
    with closing(connect(db)) as con:
        con.execute("INSERT INTO concept_stopwords (word_norm) VALUES ('plotly')")
        con.execute("INSERT INTO concept_synonyms (alias_norm, label_norm) VALUES ('aiohttp', 'websocket')")
        extract_concepts(con)
        con.commit()
    concepts = _concepts(db)
    assert "Plotly" not in concepts
    assert "aiohttp" not in concepts
    # aiohttp のページも websocket にまとまる
    assert len(concepts["websocket"]) == 4  # websocket の2ページと aiohttp の2ページ


def test_body_concepts_are_kept(db):
    """本文（段階3）由来の概念は、計算し直しても消さない。"""
    with closing(connect(db)) as con:
        concept_id = con.execute("SELECT id FROM concepts WHERE label_norm = 'python'").fetchone()[0]
        page_id = con.execute("SELECT id FROM pages WHERE url_norm = 'https://plotly.io/'").fetchone()[0]
        con.execute("INSERT INTO page_concepts VALUES (?, ?, 'body', 0.4)", (page_id, concept_id))
        extract_concepts(con)
        con.commit()
        assert con.execute("SELECT COUNT(*) FROM page_concepts WHERE source = 'body'").fetchone()[0] == 1
