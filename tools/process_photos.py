#!/usr/bin/env python3
"""
本の写真をまとめて背景透過し、表・裏をセットにして books.csv に登録するツール。

使い方（リポジトリのフォルダで）:
    python tools/process_photos.py

1. inbox/ に写真を入れる（1冊につき「表 → 裏」の順で撮る）
2. このコマンドを実行する
3. images/ に <id>-front.webp と <id>-back.webp ができ、data/books.csv に行が追加される
4. 処理済みの元写真は inbox/_done/ に移る

仕組み:
- 背景の切り抜きは rembg（AIの背景除去）で行い、本の四隅を見つけて
  台形のゆがみを真っすぐに直します（真上から撮っていなくても長方形に整う）。
- 裏表紙のバーコード（978…）を読み取って ISBN を取り、
  openBD → 国立国会図書館サーチ → Google Books の順に書名・著者・出版社を調べます。
- Cコード（例 C0232）が分かればカテゴリと判型（文庫・新書・単行本）も自動で入れます。
- バーコードがある方を「裏」と判断するので、撮る順番が多少前後しても大丈夫です。
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image, ImageOps

try:  # iPhone の HEIC 写真に対応
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

import cv2
import zxingcpp
from rembg import new_session, remove

ROOT = Path(__file__).resolve().parent.parent
EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"}
FIELDS = ["id", "isbn", "title", "author", "publisher", "label", "category",
          "format", "price", "condition", "sold", "front", "back", "sample"]

# Cコード下2桁（内容）の十の位 → カテゴリ名。好みで書き換えてください。
CCODE_CATEGORY = {
    "0": "総記", "1": "哲学・宗教", "2": "歴史・地理", "3": "社会科学", "4": "自然科学",
    "5": "工学", "6": "産業", "7": "芸術・暮らし", "8": "語学", "9": "文学",
}
# より細かく分けたいものだけ上書き
CCODE_DETAIL = {
    "31": "法・政治", "32": "法・政治", "36": "社会学", "39": "社会学",
    "11": "心理学", "33": "経済・経営", "34": "経済・経営", "37": "教育",
    "21": "歴史", "22": "歴史", "23": "歴史", "79": "マンガ",
}
# Cコードが無いときは国立国会図書館の分類（NDC）の上2桁で分ける
NDC_DETAIL = {
    "31": "法・政治", "32": "法・政治", "33": "経済・経営", "36": "社会学", "38": "社会学",
    "37": "教育", "14": "心理学", "20": "歴史", "21": "歴史", "22": "歴史", "23": "歴史", "28": "歴史",
    "72": "芸術・暮らし", "59": "芸術・暮らし", "91": "文学",
}
# Cコード2桁目（発行形態）→ サイトの判型
CCODE_FORMAT = {"0": "tanko", "1": "bunko", "2": "shinsho"}


# ---------------------------------------------------------------- 画像処理

@dataclass
class Photo:
    path: Path
    taken: float
    image: Image.Image | None = None   # 切り抜き後
    isbn: str = ""
    warped: bool = False
    note: list[str] = field(default_factory=list)


def taken_time(path: Path) -> float:
    """撮影日時（EXIF）。無ければファイルの更新日時。"""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)
            if raw:
                return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:
        pass
    return path.stat().st_mtime


def order_corners(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32)


def cut_out(img: Image.Image, session, max_side: int) -> tuple[Image.Image, bool]:
    """背景を消し、本が四角く見つかればゆがみを直した長方形で返す。"""
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)

    mask = np.array(remove(img, session=session, only_mask=True, post_process_mask=True))
    _, binm = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
    binm = cv2.morphologyEx(binm, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    contours, _ = cv2.findContours(binm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise RuntimeError("本が見つかりませんでした")
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < 0.05 * mask.size:
        raise RuntimeError("本が小さすぎるか、見つかりませんでした")

    # 四隅を探す：輪郭を多角形に近似して4点になれば台形補正
    quad = None
    peri = cv2.arcLength(c, True)
    for eps in (0.01, 0.02, 0.03, 0.04, 0.05):
        approx = cv2.approxPolyDP(c, eps * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            quad = approx.reshape(4, 2).astype(np.float32)
            break
    if quad is not None and cv2.contourArea(quad) / area > 0.92:
        tl, tr, br, bl = order_corners(quad)
        w = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
        h = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
        M = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]),
                                        np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32))
        rgb = cv2.warpPerspective(np.array(img), M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        # 端の1%を落として背景の残りを消す
        m = max(2, int(min(w, h) * 0.008))
        out = Image.fromarray(rgb[m:h - m, m:w - m]).convert("RGBA")
        return out, True

    # 四角にならない（帯付き・角が折れている等）ときは、AIの切り抜きをそのまま使う
    rgba = img.convert("RGBA")
    rgba.putalpha(Image.fromarray(mask))
    x, y, w, h = cv2.boundingRect(c)
    return rgba.crop((x, y, x + w, y + h)), False


def make_portrait(im: Image.Image) -> tuple[Image.Image, bool]:
    if im.width > im.height * 1.05:
        return im.rotate(90, expand=True), True
    return im, False


def read_isbn(im: Image.Image) -> str:
    """裏表紙のバーコードから ISBN-13 を読む。"""
    rgb = im.convert("RGB")
    for scale in (1.0, 1.6, 0.6):
        target = rgb if scale == 1.0 else rgb.resize((int(rgb.width * scale), int(rgb.height * scale)), Image.LANCZOS)
        for angle in (0, 180, 90, 270):
            probe = target if angle == 0 else target.rotate(angle, expand=True)
            for r in zxingcpp.read_barcodes(probe):
                t = re.sub(r"\D", "", r.text)
                if len(t) == 13 and t[:3] in ("978", "979") and isbn13_ok(t):
                    return t
    return ""


def isbn13_ok(t: str) -> bool:
    s = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(t[:12]))
    return (10 - s % 10) % 10 == int(t[12])


def save_webp(im: Image.Image, path: Path, height: int) -> None:
    if im.height > height:
        im = im.resize((round(im.width * height / im.height), height), Image.LANCZOS)
    im.save(path, "WEBP", quality=82, method=6)


# ---------------------------------------------------------------- 書誌情報

def http_get(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "furuhon-shop/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def clean_author(a: str) -> str:
    """「長谷部,恭男,1956-」のような表記を「長谷部恭男」に整える。"""
    names = []
    for part in re.split(r"[\s　]+", a or ""):
        part = re.sub(r",?\d{4}-?(\d{4})?$", "", part)
        part = re.sub(r"[／/]?(著|編著|編|訳|監修|作|文|絵)$", "", part)
        part = part.replace(",", "").replace("，", "").strip()
        if part:
            names.append(part)
    return "、".join(names)


def lookup_openbd(isbn: str) -> dict:
    data = json.loads(http_get(f"https://api.openbd.jp/v1/get?isbn={isbn}"))
    if not data or not data[0]:
        return {}
    d = data[0]
    s = d.get("summary", {})
    info = {"title": s.get("title", ""), "author": clean_author(s.get("author", "")),
            "publisher": s.get("publisher", ""), "label": s.get("series", "")}
    try:  # Cコード
        for subj in d["onix"]["DescriptiveDetail"].get("Subject", []):
            if subj.get("SubjectSchemeIdentifier") == "78":
                info["ccode"] = subj.get("SubjectCode", "")
    except (KeyError, TypeError):
        pass
    return info if info["title"] else {}


def lookup_ndl(isbn: str) -> dict:
    xml = http_get(f"https://ndlsearch.ndl.go.jp/api/opensearch?isbn={isbn}&cnt=1")
    ns = {"dc": "http://purl.org/dc/elements/1.1/", "dcndl": "http://ndl.go.jp/dcndl/terms/"}
    item = ET.fromstring(xml).find("channel/item")
    if item is None:
        return {}
    g = lambda tag: (item.findtext(tag, default="", namespaces=ns) or "").strip()
    info = {"title": g("dc:title"), "author": clean_author(g("dc:creator") or g("author")),
            "publisher": g("dc:publisher"), "label": g("dcndl:seriesTitle")}
    xsi = "{http://www.w3.org/2001/XMLSchema-instance}type"
    for subj in item.findall("dc:subject", ns):
        if "NDC" in (subj.get(xsi) or "") and re.match(r"\d{3}", subj.text or ""):
            info["ndc"] = subj.text.strip()
            break
    return info


def lookup_google(isbn: str) -> dict:
    data = json.loads(http_get(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"))
    if not data.get("items"):
        return {}
    v = data["items"][0]["volumeInfo"]
    title = v.get("title", "") + (" " + v["subtitle"] if v.get("subtitle") else "")
    return {"title": title, "author": "、".join(v.get("authors", [])), "publisher": v.get("publisher", "")}


def lookup(isbn: str) -> dict:
    found: dict = {}
    for fn in (lookup_openbd, lookup_ndl, lookup_google):
        try:
            info = fn(isbn)
        except Exception:
            continue
        for k, v in info.items():
            if v and not found.get(k):
                found[k] = v
        if found.get("title") and found.get("publisher") and found.get("author"):
            break
    cc = re.sub(r"\D", "", found.pop("ccode", ""))
    ndc = found.pop("ndc", "")
    if len(cc) == 4:
        found["category"] = CCODE_DETAIL.get(cc[2:], CCODE_CATEGORY.get(cc[2], ""))
        found["format"] = CCODE_FORMAT.get(cc[1], "")
    elif ndc:
        found["category"] = NDC_DETAIL.get(ndc[:2], CCODE_CATEGORY.get(ndc[0], ""))
    if not found.get("format"):
        label = found.get("label", "")
        found["format"] = "shinsho" if "新書" in label else "bunko" if "文庫" in label else ""
    return found



# ---------------------------------------------------------------- CSV

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    tmp.replace(path)


def new_id(isbn: str, taken: set[str]) -> str:
    base = isbn or datetime.now().strftime("b%y%m%d%H%M%S")
    cand, n = base, 2
    while cand in taken:
        cand, n = f"{base}-{n}", n + 1
    return cand


# ---------------------------------------------------------------- メイン

def decide(buf: list[Photo], final: bool):
    """先頭から1冊ぶんを決める。(表, 裏, 使った枚数) か、もう1枚見ないと決められなければ None。

    基本は「表 → 裏」の順。バーコードがある方を裏とみなし、裏を目印に組を作るので、
    途中で1枚失敗したり撮り忘れたりしても、その後の組がずれません。
    """
    if not buf:
        return None
    a = buf[0]
    if len(buf) == 1:
        return (a, None, 1) if final else None
    b = buf[1]
    c = buf[2] if len(buf) > 2 else None
    if not a.isbn and b.isbn:                 # 表 → 裏（ふつう）
        return a, b, 2
    if a.isbn and b.isbn:                     # 裏が2枚続いた：a の表は撮れていない
        return a, None, 1
    if c is None and not final:               # ここから先は3枚目を見て決める
        return None
    if not a.isbn and not b.isbn:
        if c is not None and c.isbn:          # b は次の本(c)の表。a は裏なしの1冊
            return a, None, 1
        return a, b, 2                        # バーコードのない古い本：表 → 裏
    # a にバーコード、b に無い
    if c is not None and c.isbn:              # b は次の本の表。a は表なしの1冊
        return a, None, 1
    return b, a, 2                            # 裏 → 表 の順で撮った


def main() -> int:
    ap = argparse.ArgumentParser(description="本の写真をまとめて背景透過して登録します")
    ap.add_argument("--inbox", default=str(ROOT / "inbox"))
    ap.add_argument("--images", default=str(ROOT / "images"))
    ap.add_argument("--csv", default=str(ROOT / "data" / "books.csv"))
    ap.add_argument("--model", default="isnet-general-use", help="rembg のモデル名（軽くしたいときは u2netp）")
    ap.add_argument("--height", type=int, default=900, help="保存する画像の高さ(px)")
    ap.add_argument("--no-lookup", action="store_true", help="書誌情報をネットで調べない")
    ap.add_argument("--keep", action="store_true", help="処理済みの写真を _done に移さない")
    args = ap.parse_args()

    inbox, images, csv_path = Path(args.inbox), Path(args.images), Path(args.csv)
    files = [p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in EXTS and not p.name.startswith(".")]
    if not files:
        print(f"写真がありません：{inbox} に入れてから実行してください。")
        return 0
    files.sort(key=lambda f: (taken_time(f), f.name))
    images.mkdir(parents=True, exist_ok=True)
    done_dir = inbox / "_done"
    fail_dir = inbox / "_failed"

    print(f"{len(files)}枚の写真を処理します（初回はAIモデルのダウンロードで少し待ちます）", flush=True)
    print("途中で止めても、そこまでの本は保存されます。もう一度実行すると続きから処理します。\n", flush=True)
    session = new_session(args.model)

    rows = read_csv(csv_path)
    ids = {r.get("id", "") for r in rows}
    added: list[tuple[dict, list[str]]] = []

    def emit(front: Photo, back: Photo | None) -> None:
        """1冊ぶんを保存し、CSVにすぐ書き込み、元写真を _done へ移す。"""
        isbn = (back.isbn if back else "") or front.isbn
        info = {}
        if isbn and not args.no_lookup:
            info = lookup(isbn)
            time.sleep(0.3)
        bid = new_id(isbn or f"b-{front.path.stem}", ids)
        ids.add(bid)
        save_webp(front.image, images / f"{bid}-front.webp", args.height)
        bpath = ""
        if back:
            save_webp(back.image, images / f"{bid}-back.webp", args.height)
            bpath = f"images/{bid}-back.webp"
        row = {"id": bid, "isbn": isbn, "front": f"images/{bid}-front.webp", "back": bpath,
               "price": "", "sold": "", "sample": "", "condition": "", **info}
        rows.append(row)
        write_csv(csv_path, rows)      # 1冊ごとに保存（途中で止まっても失われない）

        warn = []
        if not back:
            warn.append("表の写真なし（裏表紙を表に使用）" if front.isbn else "裏の写真なし")
        if not isbn:
            warn.append("ISBNが読めず書名は空欄")
        elif not row.get("title"):
            warn.append("書誌情報が見つからず空欄")
        for ph in (front, back):
            if ph and ph.note:
                warn += ph.note
        added.append((row, warn))
        print(f"      → 登録 {bid}  {row.get('title') or '（書名未入力）'}" + (f"   ※{'・'.join(warn)}" if warn else ""), flush=True)

        if not args.keep:
            done_dir.mkdir(exist_ok=True)
            for ph in (front, back):
                if ph:
                    shutil.move(str(ph.path), done_dir / ph.path.name)
        for ph in (front, back):       # メモリを空ける
            if ph:
                ph.image = None

    buf: list[Photo] = []

    def drain(final: bool) -> None:
        while True:
            d = decide(buf, final)
            if d is None:
                return
            front, back, used = d
            del buf[:used]
            emit(front, back)

    try:
        for n, p in enumerate(files, 1):
            print(f"  [{n}/{len(files)}] {p.name}  ", end="", flush=True)
            ph = Photo(p, taken_time(p))
            try:
                with Image.open(p) as raw:
                    im, ph.warped = cut_out(raw, session, max_side=2000)
                im, rotated = make_portrait(im)
                if rotated:
                    ph.note.append("横向きだったので回転")
                ph.isbn = read_isbn(im)
                # 保存サイズに縮めてから持っておく（大量の写真でもメモリを食わない）
                if im.height > args.height:
                    im = im.resize((round(im.width * args.height / im.height), args.height), Image.LANCZOS)
                ph.image = im
                print(f"{'台形補正' if ph.warped else '切り抜き'}{'  バーコード ' + ph.isbn if ph.isbn else ''}", flush=True)
            except Exception as e:
                print(f"失敗：{e} → inbox/_failed へ", flush=True)
                fail_dir.mkdir(exist_ok=True)
                shutil.move(str(p), fail_dir / p.name)
                continue
            buf.append(ph)
            drain(final=False)
            gc.collect()
        drain(final=True)
    except KeyboardInterrupt:
        print("\n\n中断しました。ここまでの本は保存済みです。未処理の写真は inbox に残っています。")

    print(f"\n{len(added)}冊を data/books.csv に追加しました。")
    warned = [(r, w) for r, w in added if w]
    if warned:
        print("確認が必要な本：")
        for r, w in warned:
            print(f"  {r['id']}  {r.get('title') or '（書名未入力）'}   ※{'・'.join(w)}")
    print("\n次は data/books.csv を開いて、price（値段）と category を入れてください。"
          "\n値段が空の本はサイトに出ません。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
