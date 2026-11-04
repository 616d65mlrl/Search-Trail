-- 解析用データベースのテーブル定義（03 データ設計）。ふだんはメモリの中だけに作る。
-- IF NOT EXISTS をつけ、取り込みのたびに実行しても安全にしている。
CREATE TABLE IF NOT EXISTS pages (
  id INTEGER PRIMARY KEY,
  url_norm TEXT NOT NULL UNIQUE,
  title TEXT,
  domain TEXT NOT NULL,
  excluded INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY,
  started_at INTEGER NOT NULL,          -- Unix ミリ秒
  ended_at INTEGER NOT NULL,
  root_visit_id INTEGER,
  name TEXT,
  name_is_manual INTEGER NOT NULL DEFAULT 0,
  color_index INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS visits (
  id INTEGER PRIMARY KEY,
  chrome_visit_id INTEGER NOT NULL UNIQUE,
  page_id INTEGER NOT NULL REFERENCES pages(id),
  visited_at INTEGER NOT NULL,          -- Unix ミリ秒（UTC）
  duration_ms INTEGER NOT NULL DEFAULT 0,
  transition_core INTEGER NOT NULL,
  transition_flags INTEGER NOT NULL,
  chrome_from_visit INTEGER,
  chrome_opener_visit INTEGER,
  parent_visit_id INTEGER REFERENCES visits(id),
  parent_reason TEXT,                   -- from_visit / opener / search / time
  session_id INTEGER REFERENCES sessions(id),
  synced INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS search_terms (
  visit_id INTEGER NOT NULL REFERENCES visits(id),
  term TEXT NOT NULL,
  term_norm TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS concepts (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL,
  label_norm TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS page_concepts (
  page_id INTEGER NOT NULL REFERENCES pages(id),
  concept_id INTEGER NOT NULL REFERENCES concepts(id),
  source TEXT NOT NULL,                 -- title / search / body
  weight REAL NOT NULL,
  PRIMARY KEY (page_id, concept_id, source)
);
-- 過去とのつながり。concept_id が NULL のものは「同じページを別の調べ物で開いた」つながり
CREATE TABLE IF NOT EXISTS past_links (
  id INTEGER PRIMARY KEY,
  new_visit_id INTEGER NOT NULL REFERENCES visits(id),
  old_visit_id INTEGER NOT NULL REFERENCES visits(id),
  concept_id INTEGER REFERENCES concepts(id),
  score REAL NOT NULL
);
-- 概念にしない言葉（除外語）。コードの初期値に足して、手で直せる
CREATE TABLE IF NOT EXISTS concept_stopwords (
  word_norm TEXT PRIMARY KEY
);
-- 言い換えをまとめる表（例: optical character recognition → ocr）。コードの初期値に足して、手で直せる
CREATE TABLE IF NOT EXISTS concept_synonyms (
  alias_norm TEXT PRIMARY KEY,
  label_norm TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exclusions (
  id INTEGER PRIMARY KEY,
  pattern TEXT NOT NULL                 -- 例: *.bank.example, mail.google.com
);
-- 取り込まなかった訪問（hidden、埋め込み、ブラウザ内部のページ、転送の途中）。
-- 来た元をさかのぼる手がかりだけを残し、URL やタイトルは保存しない
CREATE TABLE IF NOT EXISTS skipped_visits (
  chrome_visit_id INTEGER PRIMARY KEY,
  chrome_from_visit INTEGER,
  chrome_opener_visit INTEGER,
  reason TEXT NOT NULL                  -- hidden / subframe / internal / redirect
);
CREATE TABLE IF NOT EXISTS import_runs (
  id INTEGER PRIMARY KEY,
  started_at INTEGER NOT NULL,          -- History の場所は残さない
  last_chrome_visit_id INTEGER NOT NULL,
  added_visits INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS visits_time ON visits(visited_at);
CREATE INDEX IF NOT EXISTS visits_session ON visits(session_id);
