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
import os
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

if __name__ == "__main__":
    print("準備中…（AIの読み込みに1〜2分かかることがあります）", flush=True)

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


DETECT_SIDE = 900   # 本の位置を探すときの作業サイズ（速さのため）


def _clean(mask: np.ndarray) -> np.ndarray:
    k = max(3, int(min(mask.shape) * 0.012)) | 1
    m = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=2)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    return m


def _mask_ai(rgb: np.ndarray, session) -> np.ndarray:
    """AI（rembg）の切り抜き。表紙の絵だけを拾ってしまうことがある。"""
    m = np.array(remove(Image.fromarray(rgb), session=session, only_mask=True))
    return (m > 127).astype(np.uint8) * 255


def _border_colors(lab: np.ndarray) -> np.ndarray:
    h, w = lab.shape[:2]
    b = max(4, int(min(h, w) * 0.03))
    border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                             lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)]).astype(np.float32)
    _, _, centers = cv2.kmeans(border, 3, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0),
                               3, cv2.KMEANS_PP_CENTERS)
    return centers


def _bg_distance(lab: np.ndarray, centers: np.ndarray, l_weight: float) -> np.ndarray:
    wv = np.array([l_weight, 1.0, 1.0], np.float32)
    return np.min(np.stack([np.linalg.norm((lab - c) * wv, axis=-1) for c in centers]), axis=0)


def _mask_border(lab: np.ndarray, centers: np.ndarray, l_weight: float) -> np.ndarray:
    """写真の四辺（＝机や床）の色と違う部分を本とみなす。l_weight を下げると影に強くなる。"""
    dist = _bg_distance(lab, centers, l_weight)
    dist = cv2.normalize(dist, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, m = cv2.threshold(dist, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return m


def _mask_grabcut(rgb: np.ndarray) -> np.ndarray:
    """「四辺は背景、真ん中に本」とだけ教えて境目を探させる。"""
    h, w = rgb.shape[:2]
    scale = 520 / max(h, w)
    small = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    inset = max(3, int(min(sh, sw) * 0.025))
    mask = np.zeros((sh, sw), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(cv2.cvtColor(small, cv2.COLOR_RGB2BGR), mask, (inset, inset, sw - 2 * inset, sh - 2 * inset),
                bgd, fgd, 4, cv2.GC_INIT_WITH_RECT)
    m = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)


def _quads_from_mask(mask: np.ndarray):
    """マスクの大きな塊を、四角形（台形補正用の4点と、回転した長方形）にする。"""
    h, w = mask.shape
    contours, _ = cv2.findContours(_clean(mask), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:2]:
        if cv2.contourArea(c) < 0.06 * h * w:
            continue
        yield from _quads_from_contour(c)


def _quads_from_contour(c):
    area = cv2.contourArea(c)
    peri = cv2.arcLength(c, True)
    for eps in (0.015, 0.025, 0.035, 0.05):
        ap = cv2.approxPolyDP(c, eps * peri, True)
        if len(ap) == 4 and cv2.isContourConvex(ap):
            q = ap.reshape(4, 2).astype(np.float32)
            if cv2.contourArea(q) / area > 0.85:
                yield q, True
            break
    yield cv2.boxPoints(cv2.minAreaRect(c)).astype(np.float32), False


def _quads_from_edges(lab: np.ndarray):
    """輪郭線（エッジ）から四角形を探す。白い本を白い机に置いたときに効く。"""
    h, w = lab.shape[:2]
    L = cv2.GaussianBlur(lab[..., 0].astype(np.uint8), (5, 5), 0)
    med = float(np.median(L))
    edges = cv2.Canny(L, max(5, 0.4 * med), min(255, 1.0 * med + 30))
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
        if cv2.contourArea(c) < 0.06 * h * w:
            continue
        yield from _quads_from_contour(cv2.convexHull(c))


def _score_quad(pts: np.ndarray, grad: np.ndarray, g_ref: float, lab: np.ndarray, centers: np.ndarray) -> dict:
    """その四角形が本の輪郭らしいかを点数にする。
    - 4辺すべてが、写真のなかの「くっきりした境目」に重なっているか（いちばん大事）
    - 四角形のすぐ外側が、机や床の色か（表紙の絵だけを拾うのを防ぐ）
    - 縦横比が本らしいか
    """
    h, w = grad.shape
    q = order_corners(pts)
    area = cv2.contourArea(q)
    frac = area / (h * w)
    if frac < 0.06:
        return {"score": -9}
    center = q.mean(axis=0)
    side_scores, out_d, out_n = [], 0.0, 0
    off = max(3.0, min(h, w) * 0.015)
    for i in range(4):
        p0, p1 = q[i], q[(i + 1) % 4]
        d = p1 - p0
        ln = float(np.linalg.norm(d))
        if ln < 5:
            return {"score": -9}
        n = np.array([-d[1], d[0]]) / ln
        if np.dot((p0 + p1) / 2 - center, n) < 0:
            n = -n                                    # 外向きにそろえる
        vals = []
        for t in np.linspace(0.08, 0.92, 32):
            pt = p0 + d * t
            best = 0.0
            for k in range(-4, 5):
                x, y = int(round(pt[0] + n[0] * k)), int(round(pt[1] + n[1] * k))
                if 0 <= x < w and 0 <= y < h:
                    best = max(best, grad[y, x])
            vals.append(best)
            ox, oy = int(round(pt[0] + n[0] * off)), int(round(pt[1] + n[1] * off))
            if 0 <= ox < w and 0 <= oy < h:
                out_d += float(np.min(np.linalg.norm(centers - lab[oy, ox], axis=1)))
                out_n += 1
        side_scores.append(min(1.0, float(np.median(vals)) / g_ref))
    rw = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    rh = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    aspect = min(rw, rh) / max(rw, rh)
    if out_n >= 20:
        outside = 1.0 - min(1.0, (out_d / out_n) / 28.0)
    else:
        outside = 0.5                                 # 本が写真いっぱい：外側が無い
    score = (2.0 * min(side_scores) + 1.0 * float(np.mean(side_scores)) + 1.5 * outside
             + (0.8 if 0.5 <= aspect <= 0.88 else 0.2 if 0.4 <= aspect <= 0.95 else -0.8)
             + 0.6 * min(frac / 0.5, 1.0) - (0.8 if frac > 0.97 else 0))
    return {"score": score, "edge": min(side_scores), "outside": outside, "frac": frac}


def _snap_quad(q: np.ndarray, grad: np.ndarray) -> np.ndarray:
    """四角形の各辺を、近くにあるいちばんくっきりした境目へ寄せる（角の背景の残りを消す）。"""
    h, w = grad.shape
    q = order_corners(q)
    center = q.mean(axis=0)
    R = max(4, int(min(h, w) * 0.025))
    offs = np.arange(-R, R + 1, 2, dtype=np.float32)
    t = np.linspace(0.06, 0.94, 40, dtype=np.float32)[:, None]
    lines = []
    for i in range(4):
        p0, p1 = q[i], q[(i + 1) % 4]
        d = p1 - p0
        n = np.array([-d[1], d[0]], np.float32) / max(1e-3, float(np.linalg.norm(d)))
        if np.dot((p0 + p1) / 2 - center, n) < 0:
            n = -n
        best, best_pq = -1.0, (p0, p1)
        for a in offs:
            a0 = p0 + n * a
            for b in offs:
                a1 = p1 + n * b
                pts = a0 + (a1 - a0) * t
                xs = np.clip(np.round(pts[:, 0]).astype(int), 0, w - 1)
                ys = np.clip(np.round(pts[:, 1]).astype(int), 0, h - 1)
                v = float(grad[ys, xs].mean()) - 0.002 * (abs(a) + abs(b))   # 動かしすぎない
                if v > best:
                    best, best_pq = v, (a0, a1)
        lines.append(best_pq)

    def inter(l1, l2):
        (x1, y1), (x2, y2) = l1
        (x3, y3), (x4, y4) = l2
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(den) < 1e-6:
            return None
        px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
        py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
        return np.array([px, py], np.float32)

    corners = [inter(lines[(i - 1) % 4], lines[i]) for i in range(4)]
    if any(c is None for c in corners):
        return q
    new = np.array(corners, np.float32)
    # 角が大きく飛んだら（平行線など）寄せるのはやめる
    if np.max(np.linalg.norm(new - q, axis=1)) > 3 * R:
        return q
    return new


def cut_out(img: Image.Image, session, max_side: int) -> tuple[Image.Image, str]:
    """本を見つけて、まっすぐな長方形に切り出す。

    背景色との差・影に強い背景色との差・輪郭線・GrabCut・AI の5通りで四角形の候補を出し、
    「4辺が写真の境目と重なり、外側が机の色で、本らしい縦横比」の候補を採用する。
    どれもダメなら写真をそのまま使う（失敗にはしない）。写真の向きは変えない。
    """
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    full = np.array(img)
    H, W = full.shape[:2]
    sc = DETECT_SIDE / max(H, W)
    small = cv2.resize(full, (int(W * sc), int(H * sc)), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(cv2.GaussianBlur(small, (0, 0), 1.5), cv2.COLOR_RGB2LAB).astype(np.float32)
    centers = _border_colors(lab)
    gx = cv2.Sobel(lab, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lab, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt((gx ** 2 + gy ** 2).sum(axis=2))
    g_ref = max(1e-3, float(np.percentile(grad, 93)))

    sources = (
        ("背景色", lambda: _quads_from_mask(_mask_border(lab, centers, 1.0))),
        ("背景色・影除け", lambda: _quads_from_mask(_mask_border(lab, centers, 0.3))),
        ("輪郭線", lambda: _quads_from_edges(lab)),
        ("GrabCut", lambda: _quads_from_mask(_mask_grabcut(small))),
        ("AI", lambda: _quads_from_mask(_mask_ai(small, session))),
    )
    best = None
    for name, gen in sources:
        try:
            for pts, persp in gen():
                sc_ = _score_quad(pts, grad, g_ref, lab, centers)
                if best is None or sc_["score"] > best["score"]:
                    best = {**sc_, "pts": pts, "persp": persp, "source": name}
        except Exception:
            continue
        if best and best["score"] > 5.2:
            break                                     # 十分きれいに取れたら残りは省略（速さのため）

    if best is None or best["score"] < 3.0:
        return Image.fromarray(full).convert("RGBA"), "見つからず写真をそのまま使用"

    snapped = _snap_quad(best["pts"], grad)
    if _score_quad(snapped, grad, g_ref, lab, centers)["score"] >= best["score"] - 0.15:
        best["pts"], best["persp"] = snapped, True
    tl, tr, br, bl = order_corners(best["pts"] / sc)
    w = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    h = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    M = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]),
                                    np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32))
    rgb = cv2.warpPerspective(full, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    m = max(2, int(min(w, h) * 0.008))               # 端に残った背景を少し落とす
    out = Image.fromarray(rgb[m:h - m, m:w - m]).convert("RGBA")
    if os.environ.get("BOOK_DEBUG"):
        print(f"[score {best['score']:.2f} edge {best['edge']:.2f} out {best['outside']:.2f} frac {best['frac']:.2f}] ", end="")
    return out, ("台形補正" if best["persp"] else "四角に補正") + f"（{best['source']}）"


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
    print(f"写真の撮影日時を確認中（{len(files)}枚）…", flush=True)
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
                    im, how = cut_out(raw, session, max_side=2000)
                if how.startswith("見つからず"):
                    ph.note.append("本の輪郭が取れず写真をそのまま使用")
                ph.isbn = read_isbn(im)
                # 保存サイズに縮めてから持っておく（大量の写真でもメモリを食わない）
                if im.height > args.height:
                    im = im.resize((round(im.width * args.height / im.height), args.height), Image.LANCZOS)
                ph.image = im
                print(f"{how}{'  バーコード ' + ph.isbn if ph.isbn else ''}", flush=True)
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
