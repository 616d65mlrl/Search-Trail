"""コマンドの入口。

- `tadori start`: 画面を（必要なら）組み立て、画面と API を 127.0.0.1:8765 で配り、ブラウザを開く。ふだんはこれだけ
- `tadori serve`: API だけを起動する（開発用。画面は別に `npm run dev` で動かす）

閲覧履歴はファイルに保存しない。サーバーを起動したら、画面で History ファイルを選んで取り込む。
サーバーを止めると、取り込んだ履歴と解析結果はすべて消える。
"""

import argparse
import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8765  # 06 API 仕様
# 履歴は個人情報なので、自分の PC からだけ接続できるようにする（NFR-02）
HOST = "127.0.0.1"

# backend/tadori/cli.py から見たリポジトリの場所
REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
DIST = FRONTEND / "dist"
# これらが組み立て済みの画面より新しければ、組み立て直す
FRONTEND_SOURCES = ("src", "index.html", "package.json", "package-lock.json", "vite.config.ts")


def _newest_mtime(paths: list[Path]) -> float:
    newest = 0.0
    for p in paths:
        if p.is_dir():
            newest = max([newest, *(f.stat().st_mtime for f in p.rglob("*") if f.is_file())])
        elif p.is_file():
            newest = max(newest, p.stat().st_mtime)
    return newest


def needs_install(frontend: Path = FRONTEND) -> bool:
    """部品（node_modules）が無いか、package-lock.json のほうが新しければ入れ直す。"""
    marker = frontend / "node_modules" / ".package-lock.json"
    lock = frontend / "package-lock.json"
    return not marker.is_file() or (lock.is_file() and lock.stat().st_mtime > marker.stat().st_mtime)


def needs_build(frontend: Path = FRONTEND) -> bool:
    """組み立て済みの画面が無いか、元のファイルのほうが新しければ組み立て直す。"""
    built = frontend / "dist" / "index.html"
    if not built.is_file():
        return True
    return _newest_mtime([frontend / name for name in FRONTEND_SOURCES]) > built.stat().st_mtime


def _npm(*args: str) -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("Node.js（npm）が見つかりません。https://nodejs.org/ から入れてください（画面を組み立てるのに使います）")
    print(f"npm {' '.join(args)} を実行しています…")
    subprocess.run([npm, *args], cwd=FRONTEND, check=True)


def prepare_frontend() -> None:
    if needs_install():
        _npm("ci")
    if needs_build():
        _npm("run", "build")


def _run(port: int, static_dir: Path | None, open_browser: bool) -> None:
    import uvicorn

    from tadori.api.app import create_app

    url = f"http://{HOST}:{port}/"
    print(f"{url} で開いています（止めるときは Ctrl+C）" if static_dir else f"{url}docs で API の説明を見られます")
    print("履歴はメモリの中にだけ置きます。画面で History ファイルを選んで取り込んでください")
    if open_browser:
        # サーバーが待ち受けを始めるのを少し待ってから開く
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(static_dir=static_dir), host=HOST, port=port, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser(prog="tadori")
    sub = parser.add_subparsers(dest="command", required=True)
    p_start = sub.add_parser("start", help="画面と API を起動し、ブラウザを開く（ふだんはこれ）")
    p_start.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"ポート番号（省略時は {DEFAULT_PORT}）")
    p_start.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    p_serve = sub.add_parser("serve", help=f"API だけを {HOST} で起動する（開発用）")
    p_serve.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"ポート番号（省略時は {DEFAULT_PORT}）")
    args = parser.parse_args()

    if args.command == "start":
        prepare_frontend()
        _run(args.port, DIST, open_browser=not args.no_browser)
    elif args.command == "serve":
        _run(args.port, None, open_browser=False)
