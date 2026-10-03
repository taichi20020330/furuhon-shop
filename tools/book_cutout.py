"""
本の写真から、本だけをまっすぐな長方形で切り出す（AIを使わない自前の処理）。

前提（これを手がかりにしている）
  1. 本は長方形である
  2. 本の形をしている（縦横比がだいたい 0.55〜0.85）
  3. 縦向きに写っている（縦の方が長い）
  4. 写真の四辺は机や床（＝背景）で、本は写真の中ほどにある

やっていること
  1. 写真の四辺の色を「背景の色」として覚え、背景と違う部分を探す（しきい値を何通りか試す）
  2. 写真の中の「くっきりした境目（輪郭線）」からも四角形を探す
  3. 出てきた四角形の候補すべてに点数を付けて、いちばん本らしいものを選ぶ
       - 4辺すべてが、くっきりした境目に重なっているか
       - すぐ外側が背景の色か（表紙のイラストだけを拾った候補はここで落ちる）
       - 縦長で、本らしい縦横比か
       - 大きいか（本の中のイラストより、本そのものの方が大きい）
  4. 選んだ四角形の各辺を、近くのいちばんくっきりした境目に寄せる
  5. 4つの角を引き伸ばして、まっすぐな長方形にする（斜めから撮っても台形が直る）
"""
from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image, ImageOps

WORK = 900                     # 本を探すときの作業サイズ(px)。大きいほど正確で遅い
ASPECT_MIN, ASPECT_MAX = 0.50, 0.88   # 本の縦横比（横÷縦）の許容範囲
GOOD_ENOUGH = 5.4              # この点数を超えたら、残りの探し方は省略する
MIN_SCORE = 3.0                # これ未満なら「見つからず」
NEAR = 1.2                     # 最高点からこの差までの候補は「同じくらい本らしい」とみなす


# ------------------------------------------------------------ 小道具

def order_corners(pts: np.ndarray) -> np.ndarray:
    """4点を 左上・右上・右下・左下 の順に並べる。"""
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], np.float32)


def _clean(mask: np.ndarray) -> np.ndarray:
    k = max(3, int(min(mask.shape) * 0.012)) | 1
    m = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=2)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))


def _border_colors(lab: np.ndarray) -> np.ndarray:
    """写真の四辺の色を3色に代表させる（木目や影があっても背景を覚えられるように）。"""
    h, w = lab.shape[:2]
    b = max(4, int(min(h, w) * 0.03))
    border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                             lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)]).astype(np.float32)
    _, _, centers = cv2.kmeans(border, 3, None,
                               (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0),
                               3, cv2.KMEANS_PP_CENTERS)
    return centers


def _bg_distance(lab: np.ndarray, centers: np.ndarray, l_weight: float) -> np.ndarray:
    wv = np.array([l_weight, 1.0, 1.0], np.float32)
    return np.min(np.stack([np.linalg.norm((lab - c) * wv, axis=-1) for c in centers]), axis=0)


# ------------------------------------------------------------ 候補の四角形を出す

def _quads_from_contour(c):
    area = cv2.contourArea(c)
    if area <= 0:
        return
    peri = cv2.arcLength(c, True)
    for eps in (0.012, 0.02, 0.03, 0.045):
        ap = cv2.approxPolyDP(c, eps * peri, True)
        if len(ap) == 4 and cv2.isContourConvex(ap):
            q = ap.reshape(4, 2).astype(np.float32)
            if cv2.contourArea(q) / area > 0.85:
                yield q
            break
    yield cv2.boxPoints(cv2.minAreaRect(c)).astype(np.float32)


def _quads_from_mask(mask: np.ndarray):
    h, w = mask.shape
    contours, _ = cv2.findContours(_clean(mask), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:3]:
        if cv2.contourArea(c) >= 0.05 * h * w:
            yield from _quads_from_contour(c)
            yield from _quads_from_contour(cv2.convexHull(c))


def _masks_from_color(lab: np.ndarray, centers: np.ndarray):
    """背景色との差。しきい値と「明るさをどれだけ気にするか」を何通りか試す。"""
    for l_weight in (1.0, 0.35):          # 0.35 は影や照明ムラに強い
        d = _bg_distance(lab, centers, l_weight)
        d8 = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        otsu, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        for t in (otsu, otsu * 0.6, otsu * 0.35):   # 低いしきい値ほど、背景に近い色の本も拾える
            yield (d8 > max(4, t)).astype(np.uint8) * 255


def _quads_from_edges(lab: np.ndarray):
    """輪郭線から。白い本を白い机に置いたときなど、色の差が小さいときに効く。"""
    h, w = lab.shape[:2]
    L = cv2.GaussianBlur(lab[..., 0].astype(np.uint8), (5, 5), 0)
    med = float(np.median(L))
    for lo, hi in ((0.66 * med, 1.33 * med), (0.25 * med, 0.6 * med + 20)):
        edges = cv2.Canny(L, max(5, lo), min(255, max(lo + 10, hi)))
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=lambda c: cv2.contourArea(cv2.convexHull(c)), reverse=True)[:8]:
            hull = cv2.convexHull(c)
            if cv2.contourArea(hull) >= 0.05 * h * w:
                yield from _quads_from_contour(hull)


def _mask_grabcut(rgb: np.ndarray) -> np.ndarray:
    """「四辺は背景、真ん中に本」とだけ教えて境目を探させる（OpenCV 標準の手法）。"""
    h, w = rgb.shape[:2]
    scale = 480 / max(h, w)
    small = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    inset = max(3, int(min(sh, sw) * 0.025))
    mask = np.zeros((sh, sw), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(cv2.cvtColor(small, cv2.COLOR_RGB2BGR), mask,
                (inset, inset, sw - 2 * inset, sh - 2 * inset), bgd, fgd, 4, cv2.GC_INIT_WITH_RECT)
    m = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)


# ------------------------------------------------------------ 点数を付ける

def _shape(q: np.ndarray):
    rw = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    rh = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    return rw, rh


def score_quad(pts, grad, g_ref, lab, centers, noise=1.0) -> dict:
    h, w = grad.shape
    q = order_corners(pts)
    area = cv2.contourArea(q)
    frac = area / (h * w)
    if frac < 0.05 or not cv2.isContourConvex(q.reshape(-1, 1, 2)):
        return {"score": -9.0}
    rw, rh = _shape(q)
    aspect = rw / max(rh, 1e-3)                 # 横÷縦。縦長なら 1 未満

    center = q.mean(axis=0)
    off = max(3.0, min(h, w) * 0.015)
    side, out_d, out_n = [], 0.0, 0
    for i in range(4):
        p0, p1 = q[i], q[(i + 1) % 4]
        d = p1 - p0
        ln = float(np.linalg.norm(d))
        if ln < 8:
            return {"score": -9.0}
        n = np.array([-d[1], d[0]], np.float32) / ln
        if np.dot((p0 + p1) / 2 - center, n) < 0:
            n = -n                                # 外向きにそろえる
        vals = []
        for t in np.linspace(0.06, 0.94, 32):
            pt = p0 + d * t
            ks = np.arange(-4, 5)
            xs = np.clip(np.round(pt[0] + n[0] * ks).astype(int), 0, w - 1)
            ys = np.clip(np.round(pt[1] + n[1] * ks).astype(int), 0, h - 1)
            vals.append(float(grad[ys, xs].max()))
            ox, oy = int(round(pt[0] + n[0] * off)), int(round(pt[1] + n[1] * off))
            if 0 <= ox < w and 0 <= oy < h:
                out_d += float(np.min(np.linalg.norm(centers - lab[oy, ox], axis=1)))
                out_n += 1
        vals = np.array(vals)
        # 辺が「途切れず続く境目」か：机の細かい模様（ノイズ）よりはっきり強い点の割合
        cont = float(np.mean(vals > max(4.0 * noise, 3.0)))
        side.append(0.6 * cont + 0.4 * min(1.0, float(np.median(vals)) / g_ref))

    outside = 1.0 - min(1.0, (out_d / out_n) / 28.0) if out_n >= 20 else 0.5
    if ASPECT_MIN <= aspect <= ASPECT_MAX:
        shape_pt = 1.0
    elif 0.42 <= aspect <= 0.95:
        shape_pt = 0.3
    elif aspect > 1.0:
        shape_pt = -2.0                           # 横長は本ではない（縦向き前提）
    else:
        shape_pt = -0.8
    score = (2.0 * min(side) + 1.0 * float(np.mean(side)) + 1.5 * outside + shape_pt
             + 1.0 * min(frac / 0.45, 1.0) - (0.8 if frac > 0.97 else 0.0))
    return {"score": score, "edge": min(side), "outside": outside, "aspect": aspect, "frac": frac}


# ------------------------------------------------------------ 辺を境目に寄せる

def snap_quad(q: np.ndarray, grad: np.ndarray) -> np.ndarray:
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
                v = float(grad[ys, xs].mean()) - 0.002 * (abs(a) + abs(b))
                if v > best:
                    best, best_pq = v, (a0, a1)
        lines.append(best_pq)

    def inter(l1, l2):
        (x1, y1), (x2, y2) = l1
        (x3, y3), (x4, y4) = l2
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(den) < 1e-6:
            return None
        a, b = x1 * y2 - y1 * x2, x3 * y4 - y3 * x4
        return np.array([(a * (x3 - x4) - (x1 - x2) * b) / den, (a * (y3 - y4) - (y1 - y2) * b) / den], np.float32)

    corners = [inter(lines[(i - 1) % 4], lines[i]) for i in range(4)]
    if any(c is None for c in corners):
        return q
    new = np.array(corners, np.float32)
    return q if np.max(np.linalg.norm(new - q, axis=1)) > 3 * R else new


# ------------------------------------------------------------ 本体

def find_book(rgb: np.ndarray) -> dict | None:
    """作業サイズの画像から、本の4隅（作業サイズの座標）と点数を返す。"""
    lab = cv2.cvtColor(cv2.GaussianBlur(rgb, (0, 0), 1.5), cv2.COLOR_RGB2LAB).astype(np.float32)
    centers = _border_colors(lab)
    gx = cv2.Sobel(lab, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lab, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt((gx ** 2 + gy ** 2).sum(axis=2))
    g_ref = max(1e-3, float(np.percentile(grad, 93)))
    bw = max(4, int(min(grad.shape) * 0.03))
    noise = float(np.median(np.concatenate([grad[:bw].ravel(), grad[-bw:].ravel(),
                                            grad[:, :bw].ravel(), grad[:, -bw:].ravel()])))

    sources = (
        ("背景色", lambda: (q for m in _masks_from_color(lab, centers) for q in _quads_from_mask(m))),
        ("輪郭線", lambda: _quads_from_edges(lab)),
        ("GrabCut", lambda: _quads_from_mask(_mask_grabcut(rgb))),
    )
    cands = []
    for name, gen in sources:
        try:
            for pts in gen():
                s = score_quad(pts, grad, g_ref, lab, centers, noise)
                if s["score"] > 0:
                    cands.append({**s, "pts": order_corners(pts), "source": name})
        except cv2.error:
            continue
        if cands and max(c["score"] for c in cands) > GOOD_ENOUGH and max(c["frac"] for c in cands if c["score"] > GOOD_ENOUGH - NEAR) > 0.25:
            break
    if not cands:
        return None
    # 本の中のイラストや文字の囲みも「きれいな四角」に見えるので、
    # 点数が近い候補どうしなら、外側（大きい方）の四角を選ぶ
    top = max(c["score"] for c in cands)
    near = [c for c in cands if c["score"] >= top - NEAR and c["edge"] >= 0.3
            and ASPECT_MIN - 0.05 <= c["aspect"] <= ASPECT_MAX + 0.05]
    best = max(near, key=lambda c: c["frac"]) if near else max(cands, key=lambda c: c["score"])
    snapped = snap_quad(best["pts"], grad)
    s2 = score_quad(snapped, grad, g_ref, lab, centers, noise)
    if s2["score"] >= best["score"] - 0.15:
        best.update(s2, pts=snapped)
    return best


def cut_out(img: Image.Image, max_side: int = 2000) -> tuple[Image.Image, str, bool]:
    """写真から本を切り出す。戻り値：(画像, 説明, 見つかったか)。
    見つからなければ写真をそのまま返す（向きは変えない）。"""
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    full = np.array(img)
    H, W = full.shape[:2]
    sc = WORK / max(H, W)
    small = cv2.resize(full, (int(W * sc), int(H * sc)), interpolation=cv2.INTER_AREA)

    best = find_book(small)
    if os.environ.get("BOOK_DEBUG") and best:
        print(f"[点数 {best['score']:.2f} 輪郭 {best.get('edge', 0):.2f} 外側 {best.get('outside', 0):.2f} "
              f"縦横 {best.get('aspect', 0):.2f} 面積 {best.get('frac', 0):.2f}] ", end="")
    if best is None or best["score"] < MIN_SCORE:
        return Image.fromarray(full).convert("RGBA"), "本が見つからず写真をそのまま使用", False

    tl, tr, br, bl = order_corners(best["pts"] / sc)
    w = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    h = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    M = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]),
                                    np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32))
    out = cv2.warpPerspective(full, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    m = max(2, int(min(w, h) * 0.006))            # 端に残った背景をほんの少し落とす
    out = out[m:h - m, m:w - m]
    return Image.fromarray(out).convert("RGBA"), f"切り抜き（{best['source']}）", True


def debug_overlay(img: Image.Image, path: str) -> None:
    """どこを本と判断したかを、元写真に緑の枠で描いて保存する（確認用）。"""
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((WORK, WORK))
    rgb = np.array(img)
    best = find_book(rgb)
    if best is not None:
        cv2.polylines(rgb, [best["pts"].astype(np.int32).reshape(-1, 1, 2)], True, (0, 200, 0), 4)
        cv2.putText(rgb, f"{best['score']:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 200, 0), 2)
    Image.fromarray(rgb).save(path)
