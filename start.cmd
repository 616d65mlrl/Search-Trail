@echo off
chcp 65001 >nul
rem Search-Trail を起動する（ダブルクリックで動く）。必要なもの: uv と Node.js
cd /d "%~dp0backend"
where uv >nul 2>nul
if errorlevel 1 (
  echo uv が見つかりません。https://docs.astral.sh/uv/ から入れてください
  pause
  exit /b 1
)
uv run tadori start %*
pause
