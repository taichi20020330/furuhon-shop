"""写真のまとまりから本を作る中核処理（Firebase に依存しないので、手元でもテストできる）。
tools/process_photos.py と tools/book_cutout.py を使う（デプロイ時に functions/ へコピーされる）。"""
from __future__ import annotations

import gc
import time
from pathlib import Path

from PIL import Image

import process_photos as pp
from book_cutout import cut_out

HEIGHT = 900


def run_batch(items, existing_ids, save_book, on_progress=None, lookup=True):
    """items: [(Path, 撮影時刻 or None, 元の名前)]。save_book(bid, front_img, back_img, info, warns) を1冊ごとに呼ぶ。
    戻り値: (作った冊数, 失敗した写真の名前のリスト)"""
    photos_in = []
    for path, taken, name in items:
        photos_in.append((taken if taken else pp.taken_time(path), name, path))
    photos_in.sort(key=lambda t: (t[0], t[1]))

    ids = set(existing_ids)
    made, failed = 0, []
    buf: list[pp.Photo] = []

    def emit(front: pp.Photo, back):
        nonlocal made
        isbn = (back.isbn if back else "") or front.isbn
        bid = pp.new_id(isbn or f"b-{int(front.taken)}", ids)
        ids.add(bid)
        info = {}
        if isbn and lookup:
            try:
                info = pp.lookup(isbn)
            except Exception:
                info = {}
            time.sleep(0.2)
        warns = []
        if not back:
            warns.append("表の写真なし" if front.isbn else "裏の写真なし")
        if not isbn:
            warns.append("ISBNが読めませんでした")
        elif not info.get("title"):
            warns.append("書誌情報が見つかりませんでした")
        for ph in (front, back):
            if ph and ph.note:
                warns += ph.note
        save_book(bid, front.image, back.image if back else None, {"isbn": isbn, **info}, warns)
        made += 1
        for ph in (front, back):
            if ph:
                ph.image = None

    def drain(final):
        while True:
            d = pp.decide(buf, final)
            if d is None:
                return
            front, back, used = d
            del buf[:used]
            emit(front, back)

    for n, (taken, name, path) in enumerate(photos_in, 1):
        ph = pp.Photo(Path(path), taken)
        try:
            with Image.open(path) as raw:
                im, how, found, warn = cut_out(raw, max_side=2000)
            if not found:
                ph.note.append("本の輪郭が取れず写真をそのまま使用")
            elif warn:
                ph.note.append(warn)
            ph.isbn = pp.read_isbn(im)
            if im.height > HEIGHT:
                im = im.resize((round(im.width * HEIGHT / im.height), HEIGHT), Image.LANCZOS)
            ph.image = im
        except Exception:
            failed.append(name)
            if on_progress:
                on_progress(n, len(photos_in), made)
            continue
        buf.append(ph)
        drain(False)
        gc.collect()
        if on_progress:
            on_progress(n, len(photos_in), made)
    drain(True)
    return made, failed
