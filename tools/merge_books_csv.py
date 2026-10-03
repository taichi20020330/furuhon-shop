"""git のマージ（リベース）で data/books.csv がぶつかったときに、両方の変更を残して1つにまとめる。

使い方（ぶつかった状態のフォルダで）:
    git show :2:data/books.csv > /tmp/up.csv      # 先に GitHub にあった側
    git show :3:data/books.csv > /tmp/mine.csv    # 手元で直していた側
    python3 tools/merge_books_csv.py /tmp/up.csv /tmp/mine.csv data/books.csv

ルール: 行は up（GitHub側）にあるものを残す。列の値は、mine（手元）に値が入っていればそちらを優先、
空なら up の値を使う。mine にしかない行は取り込まず、一覧だけ表示する。
"""
import csv
import sys

up_path, mine_path, out_path = sys.argv[1:4]
read = lambda p: list(csv.DictReader(open(p, encoding="utf-8-sig", newline="")))
rd = csv.DictReader(open(up_path, encoding="utf-8-sig", newline=""))
fields = rd.fieldnames
up = list(rd)
mine = {r["id"]: r for r in read(mine_path)}
changed = 0
for r in up:
    m = mine.get(r["id"])
    if not m:
        continue
    for k in fields:
        if k in ("id", "front", "back"):          # 画像のパスは up（作り直した側）を使う
            continue
        v = (m.get(k) or "").strip()
        if v and v != r.get(k, ""):
            r[k] = v
            changed += 1
only_mine = [i for i in mine if i not in {r["id"] for r in up}]
with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(up)
print(f"{len(up)}行を書き出しました（手元の値で {changed} か所を上書き）")
if only_mine:
    print(f"手元にだけあった行 {len(only_mine)} 件は取り込んでいません:", ", ".join(only_mine[:20]))
