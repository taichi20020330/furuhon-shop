@echo off
rem Windows用：ダブルクリックで inbox の写真をまとめて処理します
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist .venv (
  echo 初回セットアップ中（数分かかります）...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\pip install -q -r tools\requirements.txt
)
.venv\Scripts\python tools\process_photos.py %*
pause
