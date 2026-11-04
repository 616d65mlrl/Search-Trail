"""取り込まない訪問の判定と、除外リストとの照合（FR-16、04 アルゴリズムの手順2）。

- 取り込まない訪問（hidden、埋め込み、ブラウザ内部のページ）は visits に入れず、
  来た元をさかのぼる手がかりだけを skipped_visits に残す。
- 除外リストに合うページは消さずに pages.excluded=1 にする。リストから外せば元に戻る。
"""

from __future__ import annotations

import sqlite3
from fnmatch import fnmatchcase
from urllib.parse import urlsplit

from tadori.ingest.chrome import ChromeVisit

AUTO_SUBFRAME = 3
MANUAL_SUBFRAME = 4

# 転送の印（03 データ設計の「transition の扱い」）
CHAIN_START = 0x10000000
CHAIN_END = 0x20000000
REDIRECT_MASK = 0xC0000000  # CLIENT_REDIRECT | SERVER_REDIRECT

# ブラウザ内部のページや、ページとして意味のない URL のスキーム
INTERNAL_SCHEMES = {
    "about", "blob", "chrome", "chrome-extension", "chrome-native", "chrome-search",
    "chrome-untrusted", "data", "devtools", "edge", "filesystem", "javascript", "view-source",
}


def skip_reason(v: ChromeVisit) -> str | None:
    """取り込まない訪問なら理由（hidden / subframe / internal / redirect）を、取り込むなら None を返す。"""
    if v.transition & 0xFF in (AUTO_SUBFRAME, MANUAL_SUBFRAME):
        return "subframe"
    # 転送の連なりは最後（CHAIN_END）だけを残す。途中の訪問を skipped_visits に回すと、
    # 最後の訪問の来た元をさかのぼるとき、連なりの最初の訪問の来た元に自然にたどり着く。
    # 印が何もない訪問（古い Chrome など）は、連なりの途中とはみなさない
    if not v.transition & CHAIN_END and v.transition & (CHAIN_START | REDIRECT_MASK):
        return "redirect"
    if urlsplit(v.url).scheme.lower() in INTERNAL_SCHEMES:
        return "internal"
    if v.hidden:
        return "hidden"
    return None


def matches_exclusion(pattern: str, domain: str, url_norm: str) -> bool:
    """除外リストの1行がページに一致するか。

    `/` を含まなければドメインとして比べる（`*.bank.example` は bank.example 自身にも一致）。
    `/` を含めば「ドメイン/パス」として比べる（例: `example.com/private/*`）。
    """
    p = pattern.strip().lower()
    if not p:
        return False
    if "/" in p:
        target = url_norm.split("://", 1)[-1].lower()
        return fnmatchcase(target, p.split("://", 1)[-1])
    if p.startswith("*."):
        base = p[2:]
        return domain == base or domain.endswith("." + base)
    return fnmatchcase(domain, p)


def refresh_page_exclusions(con: sqlite3.Connection) -> None:
    """除外リストに合わせて、すべてのページの excluded を付け直す。"""
    patterns = [r[0] for r in con.execute("SELECT pattern FROM exclusions")]
    pages = con.execute("SELECT id, domain, url_norm, excluded FROM pages").fetchall()
    for page_id, domain, url_norm, excluded in pages:
        hit = int(any(matches_exclusion(p, domain, url_norm) for p in patterns))
        if hit != excluded:
            con.execute("UPDATE pages SET excluded = ? WHERE id = ?", (hit, page_id))
