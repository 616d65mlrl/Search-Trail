"""解析を順番に実行する（04 アルゴリズムの「処理の順番」の手順5以降）。"""

import sqlite3

from tadori.analyze.concepts import extract_concepts
from tadori.analyze.naming import name_sessions
from tadori.analyze.parents import decide_parents
from tadori.analyze.past_links import link_past
from tadori.analyze.sessions import split_sessions


def analyze(con: sqlite3.Connection) -> None:
    decide_parents(con)
    split_sessions(con)
    extract_concepts(con)
    link_past(con)
    name_sessions(con)
