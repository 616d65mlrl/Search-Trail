"""`tadori start` の下準備（画面の部品を入れるか、組み立て直すか）のテスト。"""

import os

from tadori.cli import needs_build, needs_install


def _touch(path, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_needs_install(tmp_path):
    _touch(tmp_path / "package-lock.json", 100)
    assert needs_install(tmp_path)  # node_modules が無い
    _touch(tmp_path / "node_modules" / ".package-lock.json", 200)
    assert not needs_install(tmp_path)
    _touch(tmp_path / "package-lock.json", 300)  # 部品の一覧が変わった
    assert needs_install(tmp_path)


def test_needs_build(tmp_path):
    _touch(tmp_path / "src" / "App.vue", 100)
    assert needs_build(tmp_path)  # まだ組み立てていない
    _touch(tmp_path / "dist" / "index.html", 200)
    assert not needs_build(tmp_path)
    _touch(tmp_path / "src" / "components" / "GraphView.vue", 300)  # 元のファイルを直した
    assert needs_build(tmp_path)
