"""概念の抽出（FR-10、04 アルゴリズムの「概念の抽出」）。

| 材料   | 重み | 方法                                                     |
| 検索語 | 1.0  | そのまま1つの概念候補にし、さらに単語に分ける            |
| タイトル | 0.6 | サイト名の部分を消してから単語に分ける                  |
| 本文   | 0.4  | 段階3（ここでは触らない）                                |

英語と識別子（OCR、aiohttp など）は正規表現で、日本語は SudachiPy の名詞で取る。
NFKC 正規化と小文字化をしたうえで、全体で2ページ以上に出る単語だけを概念として残す。
除外語と同義語は、コードの初期値に加えて DB の表（concept_stopwords、concept_synonyms）で手で直せる。
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache

WEIGHTS = {"search": 1.0, "title": 0.6}
MIN_PAGES = 2  # 全体でこの数以上のページに出る単語だけを概念にする

# 概念にしない言葉（正規化した形）
DEFAULT_STOPWORDS = {
    # 日本語
    "とは", "公式", "検索", "日本語", "日本語版", "方法", "やり方", "作り方", "使い方", "一覧", "まとめ",
    "解説", "入門", "記事", "ページ", "サイト", "こと", "もの", "ため", "よう", "これ", "それ",
    # 英語
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "by", "from", "at", "as",
    "is", "are", "be", "it", "its", "this", "that", "what", "how", "why", "you", "your", "all", "new",
    "next", "generation", "introduction", "intro", "docs", "doc", "documentation", "guide", "home",
    "getting", "started", "about", "official",
    # サイトや URL の部品
    "github", "google", "www", "com", "org", "net", "io", "jp", "http", "https", "html",
}

# 言い換えをまとめる表（正規化した形 → まとめ先の正規化した形）
DEFAULT_SYNONYMS = {
    "optical character recognition": "ocr",
    "文字認識": "ocr",
}

TITLE_SEPARATOR = re.compile(r"\s+[-|–—:：]\s+|\s*[｜|]\s*")
# 英語の単語と識別子。途中の + # . _ - は残す（C++、gfx-rs、v1.2 など）
ASCII_WORD = re.compile(r"[0-9A-Za-z](?:[0-9A-Za-z+#._-]*[0-9A-Za-z+#])?")


def normalize(word: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", word).lower().split())


@lru_cache(maxsize=1)
def _tokenizer():
    from sudachipy import Dictionary, SplitMode

    return Dictionary(dict="core").tokenizer(mode=SplitMode.C)


def japanese_nouns(text: str) -> list[str]:
    """日本語の名詞を取り出す。名詞が続くとき、1文字の名詞は隣とくっつける（表＋組 → 表組）。"""
    runs: list[list[str]] = []
    current: list[str] = []
    for m in _tokenizer().tokenize(text):
        pos = m.part_of_speech()
        if pos[0] == "名詞" and pos[1] != "数詞":
            current.append(m.surface())
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    nouns: list[str] = []
    for run in runs:
        merged: list[str] = []
        for s in run:
            if merged and (len(s) == 1 or len(merged[-1]) == 1):
                merged[-1] += s
            else:
                merged.append(s)
        nouns.extend(merged)
    return nouns


def split_words(text: str) -> list[str]:
    """文を単語（表記はそのまま）に分ける。英語・識別子と、日本語の名詞。"""
    text = unicodedata.normalize("NFKC", text)
    words: list[str] = []
    for w in ASCII_WORD.findall(text):
        words.append(w)
        # gfx-rs のようにつながった識別子は、部品も候補にする
        if "-" in w or "_" in w:
            words.extend(p for p in re.split(r"[-_]", w) if p)
    rest = ASCII_WORD.sub(" ", text)
    words.extend(japanese_nouns(rest))
    return words


def site_segments(titles_by_domain: dict[str, list[str]]) -> dict[str, set[str]]:
    """ドメインごとに、サイト名とみなすタイトルの区切り部分（正規化した形）を求める。

    「 - 」「 | 」などで区切った部分のうち、同じドメインの2ページ以上に出てくるものをサイト名とみなす。
    """
    result: dict[str, set[str]] = {}
    for domain, titles in titles_by_domain.items():
        counts: Counter[str] = Counter()
        for title in titles:
            # 区切りのないタイトル（トップページの「Plotly」など）も数える
            counts.update({normalize(s) for s in TITLE_SEPARATOR.split(title) if s.strip()})
        result[domain] = {s for s, n in counts.items() if n >= 2}
    return result


def strip_site_name(title: str, site: set[str]) -> str:
    segments = [s for s in TITLE_SEPARATOR.split(title) if s.strip()]
    kept = [s for s in segments if normalize(s) not in site]
    # 全部がサイト名に見えたら（例: トップページの「Plotly」）、いちばん長い部分を残す
    return " ".join(kept) if kept else max(segments, key=len, default="")


def load_dictionaries(con: sqlite3.Connection) -> tuple[set[str], dict[str, str]]:
    stopwords = DEFAULT_STOPWORDS | {r[0] for r in con.execute("SELECT word_norm FROM concept_stopwords")}
    synonyms = {**DEFAULT_SYNONYMS, **dict(con.execute("SELECT alias_norm, label_norm FROM concept_synonyms"))}
    return stopwords, synonyms


def extract_concepts(con: sqlite3.Connection) -> None:
    """ページごとの概念を、検索語とタイトルから計算し直す。本文（段階3）由来の行は残す。"""
    stopwords, synonyms = load_dictionaries(con)
    phrase_synonyms = {a: l for a, l in synonyms.items() if " " in a}

    # 調べ物に入っているページだけを対象にする（同期・除外の訪問だけのページは使わない）
    pages = con.execute(
        """
        SELECT p.id, p.title, p.domain FROM pages p
        WHERE p.excluded = 0 AND EXISTS (SELECT 1 FROM visits v WHERE v.page_id = p.id AND v.session_id IS NOT NULL)
        """
    ).fetchall()
    terms: dict[int, set[str]] = defaultdict(set)
    for page_id, term in con.execute(
        "SELECT v.page_id, s.term FROM search_terms s JOIN visits v ON v.id = s.visit_id"
    ):
        terms[page_id].add(term)

    titles_by_domain: dict[str, list[str]] = defaultdict(list)
    for _, title, domain in pages:
        if title:
            titles_by_domain[domain].append(title)
    site = site_segments(titles_by_domain)

    # (ページ, 正規化した概念, 材料) → 重み。表示名は、いちばん多く出た表記にする
    found: dict[tuple[int, str, str], float] = {}
    surfaces: dict[str, Counter[str]] = defaultdict(Counter)

    def add(page_id: int, word: str, source: str) -> None:
        norm = normalize(word)
        norm = synonyms.get(norm, norm)
        if len(norm) < 2 or norm in stopwords or norm.replace(".", "").isdigit():
            return
        found[(page_id, norm, source)] = WEIGHTS[source]
        surfaces[norm][word.strip()] += 1

    for page_id, title, domain in pages:
        texts = [(t, "search") for t in terms.get(page_id, ())]
        if title:
            texts.append((strip_site_name(title, site.get(domain, set())), "title"))
        for text, source in texts:
            if source == "search" and " " in normalize(text):
                add(page_id, text, source)  # 検索語は、まるごと1つの概念候補にもする
            for alias, label in phrase_synonyms.items():
                if alias in normalize(text):
                    add(page_id, label, source)
            for word in split_words(text):
                add(page_id, word, source)

    # 全体で2ページ以上に出る単語だけを概念にする
    pages_of: dict[str, set[int]] = defaultdict(set)
    for page_id, norm, _ in found:
        pages_of[norm].add(page_id)
    keep = {norm for norm, ps in pages_of.items() if len(ps) >= MIN_PAGES}

    con.execute("DELETE FROM page_concepts WHERE source IN ('title', 'search')")
    for norm in sorted(keep):
        label = surfaces[norm].most_common(1)[0][0] if surfaces[norm] else norm
        con.execute(
            "INSERT INTO concepts (label, label_norm) VALUES (?, ?)"
            " ON CONFLICT(label_norm) DO UPDATE SET label = excluded.label",
            (label, norm),
        )
    ids = dict(con.execute("SELECT label_norm, id FROM concepts"))
    con.executemany(
        "INSERT INTO page_concepts (page_id, concept_id, source, weight) VALUES (?, ?, ?, ?)",
        [(page_id, ids[norm], source, weight) for (page_id, norm, source), weight in found.items() if norm in keep],
    )
    # どのページにも使われなくなった概念は消す（過去とのつながりは、この後に計算し直す）
    con.execute("DELETE FROM past_links")
    con.execute("DELETE FROM concepts WHERE id NOT IN (SELECT concept_id FROM page_concepts)")
