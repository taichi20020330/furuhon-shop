#!/bin/bash
# Mac用：ダブルクリックで inbox の写真を全部切り抜き直します（書名・値段はそのまま）
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "初回セットアップ中（数分かかります）…"
  python3 -m venv .venv && .venv/bin/pip install -q -r tools/requirements.txt || { echo "セットアップに失敗しました。python3 が入っているか確認してください。"; read -n1; exit 1; }
fi
.venv/bin/python tools/process_photos.py --redo "$@"
echo ""; echo "何かキーを押すと閉じます"; read -n1
