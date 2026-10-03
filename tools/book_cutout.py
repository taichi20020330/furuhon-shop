"""
本の写真から、本だけをまっすぐな長方形で切り出す（AIを使わない自前の処理・第2版）。

前提
  1. 本は長方形（斜めから撮れば台形に写る）
  2. 本らしい縦横比（横÷縦 がだいたい 0.5〜0.88）で、縦向きに写っている
  3. 写真の四辺は机や床で、本は写真の中ほどにある

第1版との違い：「見切れ」（本の端が切れてしまう）を出さないことを最優先にした。
  - 本の内側にある四角（イラストの枠、文字の囲み、帯）を本と取り違えないよう、
    本の形（マスク）を求めて、それを「すべて含む」四角を作る
  - 各辺は「近くでいちばん外側の、はっきりした境目」に合わせる
    （前は一番くっきりした境目に合わせていたので、内側の線に吸い寄せられていた）
  - 切り出すときは外側に少し余裕を取り、背景色の残りを内側から削る
    （削る量には上限があるので、本の中に食い込まない）
  - 本が写真の端で切れている、輪郭がはっきりしない、などは警告として知らせる

流れ
  A. 背景色との差・GrabCut・輪郭線から「本の形」の候補を出す（穴は埋める）
  B. 各候補を「すべて含む四角」に当てはめ、辺が境目に乗っているか・外側が机の色か・
     本らしい比率か、で採点して選ぶ
  C. 辺を外側の境目に寄せる
  D. 外側に余裕を付けて台形補正し、背景の残りを上限付きで削る
"""
from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image, ImageOps

DEBUG = bool(os.environ.get('BOOK_DEBUG2'))
WORK = 900                      # 本を探すときの作業サイズ(px)
ASPECT_MIN, ASPECT_MAX = 0.50, 0.88   # 本の縦横比（横÷縦）
GOOD_ENOUGH = 5.4               # この点数を超えたら、残りの探し方は省略
MIN_SCORE = 3.0                 # これ未満なら「見つからず」
NEAR = 1.2                      # 最高点からこの差までは「同じくらい本らしい」
PAD = 0.03                      # 切り出すとき外側に取る余裕（辺の長さに対する割合）
MAX_TRIM = PAD + 0.012          # 背景の残りを削る量の上限（これ以上は本に食い込まない）


# ------------------------------------------------------------ 小道具

def order_corners(pts) -> np.ndarray:
    """4点を 左上・右上・右下・左下 の順に並べる。"""
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], np.float32)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """本の中の白い部分（文字や余白）が穴になっていても、本全体を塗りつぶす。"""
    p = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = p.copy()
    cv2.floodFill(ff, np.zeros((p.shape[0] + 2, p.shape[1] + 2), np.uint8), (0, 0), 255)
    holes = cv2.bitwise_not(ff)[1:-1, 1:-1]
    return cv2.bitwise_or(mask, holes)


def _clean(mask: np.ndarray) -> np.ndarray:
    k = max(3, int(min(mask.shape) * 0.012)) | 1
    m = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=2)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    return _fill_holes(m)


def _border_colors(lab: np.ndarray) -> np.ndarray:
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


# ------------------------------------------------------------ A. 本の形（マスク）を出す

def _masks_from_color(lab, centers):
    """背景色との差。しきい値と「明るさをどれだけ気にするか」を何通りか試す。"""
    for l_weight in (1.0, 0.35):          # 0.35 は影や照明ムラに強い
        d = _bg_distance(lab, centers, l_weight)
        d8 = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        otsu, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        for t in (otsu, otsu * 0.6, otsu * 0.35):
            yield (d8 > max(4, t)).astype(np.uint8) * 255


def _mask_grabcut(rgb: np.ndarray) -> np.ndarray:
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


def _edge_shapes(lab: np.ndarray):
    """輪郭線から。色の差が小さいとき（白い本を白い机に置くなど）に効く。塗りつぶした形を返す。"""
    h, w = lab.shape[:2]
    L = cv2.GaussianBlur(lab[..., 0].astype(np.uint8), (5, 5), 0)
    med = float(np.median(L))
    for lo, hi in ((0.66 * med, 1.33 * med), (0.25 * med, 0.6 * med + 20)):
        edges = cv2.Canny(L, max(5, lo), min(255, max(lo + 10, hi)))
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=lambda c: cv2.contourArea(cv2.convexHull(c)), reverse=True)[:6]:
            hull = cv2.convexHull(c)
            if cv2.contourArea(hull) >= 0.05 * h * w:
                m = np.zeros((h, w), np.uint8)
                cv2.fillConvexPoly(m, hull, 255)
                yield m


def _hulls(mask: np.ndarray, min_frac: float = 0.05):
    h, w = mask.shape
    contours, _ = cv2.findContours(_clean(mask), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:2]:
        if cv2.contourArea(c) >= min_frac * h * w:
            yield cv2.convexHull(c)


# ------------------------------------------------------------ B. 「すべて含む」四角に当てはめる

def _densify(hull: np.ndarray, step: float = 2.0) -> np.ndarray:
    pts = hull.reshape(-1, 2).astype(np.float32)
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        n = max(1, int(np.linalg.norm(b - a) / step))
        out.append(a + (b - a) * (np.arange(n)[:, None] / n))
    return np.concatenate(out).astype(np.float32)


def _line_intersect(l1, l2):
    (x1, y1), (x2, y2) = l1
    (x3, y3), (x4, y4) = l2
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-6:
        return None
    a, b = x1 * y2 - y1 * x2, x3 * y4 - y3 * x4
    return np.array([(a * (x3 - x4) - (x1 - x2) * b) / den, (a * (y3 - y4) - (y1 - y2) * b) / den], np.float32)


def fit_enclosing_quad(hull: np.ndarray) -> np.ndarray:
    """本の形（凸包）に4本の直線を当てはめ、凸包がすべて中に収まるまで外へ広げた四角形を返す。
    斜めから撮った台形も、そのままの形で捉える。"""
    dense = _densify(hull)
    box = order_corners(cv2.boxPoints(cv2.minAreaRect(dense)))
    centroid = dense.mean(axis=0)

    # 各点を、いちばん近い箱の辺に割り当てる（角のそばは除く）
    seg_d, assign, near_end = [], None, None
    for i in range(4):
        a, b = box[i], box[(i + 1) % 4]
        ab = b - a
        t = np.clip(((dense - a) @ ab) / max(1e-6, float(ab @ ab)), 0, 1)
        proj = a + t[:, None] * ab
        seg_d.append(np.linalg.norm(dense - proj, axis=1))
    seg_d = np.stack(seg_d)
    assign = seg_d.argmin(axis=0)

    lines = []
    for i in range(4):
        a, b = box[i], box[(i + 1) % 4]
        ab = b - a
        t = ((dense - a) @ ab) / max(1e-6, float(ab @ ab))
        sel = dense[(assign == i) & (t > 0.1) & (t < 0.9)]
        if len(sel) >= 8:
            vx, vy, x0, y0 = cv2.fitLine(sel, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
            p0 = np.array([x0, y0], np.float32)
            d = np.array([vx, vy], np.float32)
        else:
            p0, d = a, ab / max(1e-6, float(np.linalg.norm(ab)))
        n = np.array([-d[1], d[0]], np.float32)
        if np.dot(p0 - centroid, n) < 0:
            n = -n                                         # 外向き
        # 凸包の点がすべて中に入るまで、直線を外へずらす
        over = float(np.max((dense - p0) @ n))
        if over > 0:
            p0 = p0 + n * over
        lines.append((p0 - d * 1000, p0 + d * 1000))

    corners = [_line_intersect(lines[(i - 1) % 4], lines[i]) for i in range(4)]
    if any(c is None for c in corners):
        return box
    q = order_corners(corners)
    # 当てはめが暴れたら（交点が遠すぎる）、素直な長方形に戻す
    if cv2.contourArea(q) > 1.5 * cv2.contourArea(box) or cv2.contourArea(q) < 0.5 * cv2.contourArea(box):
        return box
    return q


def score_quad(pts, grad, g_ref, lab, centers, noise) -> dict:
    h, w = grad.shape
    q = order_corners(pts)
    area = cv2.contourArea(q)
    frac = area / (h * w)
    if frac < 0.05 or not cv2.isContourConvex(q.reshape(-1, 1, 2)):
        return {"score": -9.0}
    rw = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    rh = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    aspect = rw / max(rh, 1e-3)

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
            n = -n
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
        cont = float(np.mean(vals > max(4.0 * noise, 3.0)))       # 辺が途切れず続く境目か
        side.append(0.6 * cont + 0.4 * min(1.0, float(np.median(vals)) / g_ref))

    outside = 1.0 - min(1.0, (out_d / out_n) / 28.0) if out_n >= 20 else 0.5
    if ASPECT_MIN <= aspect <= ASPECT_MAX:
        shape_pt = 1.0
    elif 0.42 <= aspect <= 0.95:
        shape_pt = 0.3
    elif aspect > 1.0:
        shape_pt = -2.0                      # 横長は本ではない
    else:
        shape_pt = -0.8
    score = (2.0 * min(side) + 1.0 * float(np.mean(side)) + 1.5 * outside + shape_pt
             + 1.0 * min(frac / 0.45, 1.0) - (0.8 if frac > 0.97 else 0.0))
    return {"score": score, "edge": min(side), "outside": outside, "aspect": aspect, "frac": frac}


# ------------------------------------------------------------ C. 辺を外側の境目に寄せる

def snap_quad(q: np.ndarray, grad: np.ndarray, noise: float) -> np.ndarray:
    """各辺を平行に動かして、近くにある「はっきりした境目」のうち、いちばん外側のものに合わせる。
    （いちばんくっきりした線ではなく、いちばん外側の線。内側のイラストの枠に吸い寄せられない）"""
    h, w = grad.shape
    q = order_corners(q)
    center = q.mean(axis=0)
    R = max(5, int(min(h, w) * 0.022))
    offs = np.arange(-R, 3 * R + 1)
    t = np.linspace(0.08, 0.92, 48, dtype=np.float32)[:, None]
    new_lines = []
    for i in range(4):
        p0, p1 = q[i], q[(i + 1) % 4]
        d = p1 - p0
        n = np.array([-d[1], d[0]], np.float32) / max(1e-3, float(np.linalg.norm(d)))
        if np.dot((p0 + p1) / 2 - center, n) < 0:
            n = -n
        strength = np.zeros(len(offs), np.float32)
        for k, a in enumerate(offs):
            pts = (p0 + n * a) + d * t
            best = np.zeros(len(t), np.float32)
            for j in (-1, 0, 1):
                xs = np.clip(np.round(pts[:, 0] + n[0] * j).astype(int), 0, w - 1)
                ys = np.clip(np.round(pts[:, 1] + n[1] * j).astype(int), 0, h - 1)
                best = np.maximum(best, grad[ys, xs])
            strength[k] = float(np.median(best))             # 辺全体で見て強い線だけを拾う
        win = (offs >= -R) & (offs <= R)
        far = offs > R + 6
        bg_s = float(np.median(strength[far])) if far.any() else noise
        peak = float(strength[win].max())
        need = max(0.55 * peak, 1.8 * bg_s, 1.5 * noise)
        chosen = 0
        if peak >= need:
            cand = [int(a) for k, a in enumerate(offs)
                    if win[k] and strength[k] >= need
                    and strength[k] >= strength[max(0, k - 1)] and strength[k] >= strength[min(len(offs) - 1, k + 1)]]
            if cand:
                chosen = max(cand)                            # いちばん外側
            else:
                chosen = int(offs[win][int(np.argmax(strength[win]))])
        new_lines.append((p0 + n * chosen, p1 + n * chosen))
    corners = [_line_intersect(new_lines[(i - 1) % 4], new_lines[i]) for i in range(4)]
    if any(c is None for c in corners):
        return q
    new = order_corners(corners)
    return q if np.max(np.linalg.norm(new - q, axis=1)) > 4 * R else new


STRAIGHT_DEG = 7.0       # これ以下の傾きなら補正しない


def max_tilt_deg(q: np.ndarray) -> float:
    """四角形の辺が、水平・垂直からどれだけ傾いているか（度、最大値）。"""
    q = order_corners(q)
    worst = 0.0
    for i in range(4):
        d = q[(i + 1) % 4] - q[i]
        ang = abs(np.degrees(np.arctan2(d[1], d[0]))) % 90
        worst = max(worst, min(ang, 90 - ang))
    return float(worst)


def shape_ok(q: np.ndarray) -> bool:
    """本の輪郭として無理のない四角形か（角が直角に近く、向かい合う辺の長さが極端に違わない）。"""
    q = order_corners(q)
    L = [float(np.linalg.norm(q[(i + 1) % 4] - q[i])) for i in range(4)]
    if min(L) < 1e-3:
        return False
    if not (0.55 <= L[0] / L[2] <= 1.8 and 0.55 <= L[1] / L[3] <= 1.8):
        return False
    for i in range(4):
        a, b = q[i - 1] - q[i], q[(i + 1) % 4] - q[i]
        cosv = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
        if not (-0.42 <= cosv <= 0.42):          # 約65〜115度
            return False
    return True


def tighten_quad(q: np.ndarray, grad: np.ndarray, lab: np.ndarray, noise: float) -> np.ndarray:
    """四角形が机の面（背景の余り）まで含んでしまっているとき、各辺を内側のはっきりした境目まで寄せる。
    辺は平行移動だけでなく少し傾けて探す（写真の遠近で、向かい合う辺が平行にならないため）。
    寄せるのは「辺の上は弱い線・内側にくっきり長い線・間の帯が外側の色に近い」ときだけ。"""
    h, w = grad.shape
    q = order_corners(q)
    center = q.mean(axis=0)
    t = np.linspace(0.08, 0.92, 48, dtype=np.float32)[:, None]
    span = int(0.25 * min(h, w))
    angles = np.deg2rad(np.arange(-14, 14.1, 2.0))
    lines = []
    for i in range(4):
        p0, p1 = q[i], q[(i + 1) % 4]
        d = p1 - p0
        L = float(np.linalg.norm(d))
        n = np.array([-d[1], d[0]], np.float32) / max(1e-3, L)
        if np.dot((p0 + p1) / 2 - center, n) < 0:
            n = -n
        mid = (p0 + p1) / 2

        def frame(a, th):
            c, s_ = np.cos(th), np.sin(th)
            dr = np.array([c * d[0] - s_ * d[1], s_ * d[0] + c * d[1]], np.float32)
            nr = np.array([c * n[0] - s_ * n[1], s_ * n[0] + c * n[1]], np.float32)
            return mid - n * a, dr, nr

        def line_strength(a, th):
            m, dr, nr = frame(a, th)
            pts = m + dr * (t - 0.5)
            best = np.zeros(len(t), np.float32)
            for j in (-1, 0, 1):
                xs = np.clip(np.round(pts[:, 0] + nr[0] * j).astype(int), 0, w - 1)
                ys = np.clip(np.round(pts[:, 1] + nr[1] * j).astype(int), 0, h - 1)
                best = np.maximum(best, grad[ys, xs])
            return float(np.percentile(best, 25))      # 辺の大部分で強い線だけ

        offs = np.arange(0, span + 1)
        st = np.array([[line_strength(a, th) for a in offs] for th in angles])   # [角度, 位置]
        th0 = len(angles) // 2
        here = float(st[th0, :4].max())
        inner = st[:, 4:]
        peak = float(inner.max()) if inner.size else 0.0
        chosen = None
        if DEBUG:
            print('side', i, 'here', round(here, 1), 'peak', round(peak, 1), 'noise', round(noise, 1))
        if peak >= 1.7 * max(here, noise * 0.9) and peak >= 2.0 * noise:
            cands = []
            for ti in range(len(angles)):
                for a in offs[4:]:
                    v = st[ti, a]
                    if v >= 0.6 * peak and v >= st[ti, a - 1] and v >= st[ti, min(len(offs) - 1, a + 1)]:
                        cands.append((int(a), -float(v), ti))
            if cands:
                a, _, ti = min(cands)                   # いちばん外側（同じなら強い方）
                if a >= 6:
                    m, dr, nr = frame(a, angles[ti])

                    def band(a0, a1):
                        ps = []
                        for u in np.linspace(0.15, 0.85, 12):
                            for aa in np.linspace(a0, a1, 4):
                                x, y = (mid - n * aa) + (dr * (u - 0.5)) if False else (m + dr * (u - 0.5) + nr * (a - aa))
                                xi, yi = int(round(x)), int(round(y))
                                if 0 <= xi < w and 0 <= yi < h:
                                    ps.append(lab[yi, xi])
                        return np.median(np.array(ps), axis=0) if len(ps) >= 8 else None
                    strip = band(a - 2, 2)       # 元の辺と新しい線の間
                    inside = band(-2, -10)       # 新しい線の内側
                    outside = None
                    po = np.array([mid + n * 9])
                    ps = []
                    for u in np.linspace(-0.4, 0.4, 12):
                        for k in (5, 9, 13):
                            x, y = mid + d * u + n * k
                            xi, yi = int(round(x)), int(round(y))
                            if 0 <= xi < w and 0 <= yi < h:
                                ps.append(lab[yi, xi])
                    if len(ps) >= 8:
                        outside = np.median(np.array(ps), axis=0)
                    good = strip is not None and inside is not None
                    if good and outside is not None:
                        good = np.linalg.norm(strip - outside) < 0.7 * np.linalg.norm(strip - inside)
                    if good:
                        chosen = (m, dr)
        if chosen is None:
            lines.append((p0, p1))
        else:
            m, dr = chosen
            lines.append((m - dr / 2, m + dr / 2))
    corners = [_line_intersect(lines[(i - 1) % 4], lines[i]) for i in range(4)]
    if any(c is None for c in corners):
        return q
    return order_corners(corners)


# ------------------------------------------------------------ 本を探す

def find_book(rgb: np.ndarray) -> dict | None:
    """作業サイズの画像から、本の4隅（作業サイズの座標）・点数・警告を返す。"""
    h, w = rgb.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(rgb, (0, 0), 1.5), cv2.COLOR_RGB2LAB).astype(np.float32)
    centers = _border_colors(lab)
    gx = cv2.Sobel(lab, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(lab, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.sqrt((gx ** 2 + gy ** 2).sum(axis=2))
    g_ref = max(1e-3, float(np.percentile(grad, 93)))
    bw = max(4, int(min(h, w) * 0.03))
    noise = float(np.median(np.concatenate([grad[:bw].ravel(), grad[-bw:].ravel(),
                                            grad[:, :bw].ravel(), grad[:, -bw:].ravel()])))

    sources = (
        ("背景色", lambda: (hl for m in _masks_from_color(lab, centers) for hl in _hulls(m))),
        ("輪郭線", lambda: (hl for m in _edge_shapes(lab) for hl in _hulls(m))),
        ("GrabCut", lambda: _hulls(_mask_grabcut(rgb))),
    )
    cands = []
    for name, gen in sources:
        try:
            for hull in gen():
                q = fit_enclosing_quad(hull)
                s = score_quad(q, grad, g_ref, lab, centers, noise)
                if s["score"] > 0 and shape_ok(q):
                    cands.append({**s, "pts": q, "source": name, "hull": hull})
        except cv2.error:
            continue
        good = [c for c in cands if c["score"] > GOOD_ENOUGH - NEAR]
        if cands and max(c["score"] for c in cands) > GOOD_ENOUGH and good and max(c["frac"] for c in good) > 0.25:
            break
    if not cands:
        return None
    top = max(c["score"] for c in cands)
    # 本の色が机に近いと、辺の境目は弱くなる。そこで境目の強さは条件にせず、
    # 「外側が机の色」で本らしい比率の候補なら、大きい方を選ぶ（切れるより余るほうがまし）
    near = [c for c in cands if c["score"] >= top - NEAR and c["outside"] >= 0.5
            and ASPECT_MIN - 0.05 <= c["aspect"] <= ASPECT_MAX + 0.05]
    best = max(near, key=lambda c: c["frac"]) if near else max(cands, key=lambda c: c["score"])

    tight = tighten_quad(best["pts"], grad, lab, noise)
    if np.max(np.linalg.norm(tight - order_corners(best["pts"]), axis=1)) > 3:
        st = score_quad(tight, grad, g_ref, lab, centers, noise)
        if shape_ok(tight) and st["score"] >= best["score"] - 0.3 and ASPECT_MIN - 0.05 <= st["aspect"] <= ASPECT_MAX + 0.05:
            best.update(st, pts=tight)
    snapped = snap_quad(best["pts"], grad, noise)
    s2 = score_quad(snapped, grad, g_ref, lab, centers, noise)
    if s2["score"] >= best["score"] - 0.3:
        best.update(s2, pts=snapped)

    # 警告：本が写真の端で切れていないか
    q = best["pts"]
    m = max(3, int(min(h, w) * 0.01))
    out_of_frame = int((q[:, 0] < m).sum() + (q[:, 0] > w - 1 - m).sum() + (q[:, 1] < m).sum() + (q[:, 1] > h - 1 - m).sum())
    best["clipped"] = out_of_frame >= 2
    best["centers"] = centers
    return best


# ------------------------------------------------------------ D. 切り出し

def _expand(q: np.ndarray, pad: float) -> np.ndarray:
    """四角形を各辺の外側へ、辺の長さ×pad だけ広げる。"""
    q = order_corners(q)
    center = q.mean(axis=0)
    lines = []
    for i in range(4):
        p0, p1 = q[i], q[(i + 1) % 4]
        d = p1 - p0
        ln = float(np.linalg.norm(d))
        n = np.array([-d[1], d[0]], np.float32) / max(1e-3, ln)
        if np.dot((p0 + p1) / 2 - center, n) < 0:
            n = -n
        # 辺に直交する向きの長さを基準にする
        other = np.linalg.norm(q[(i + 2) % 4] - q[(i + 1) % 4]) if i % 2 == 0 else np.linalg.norm(q[(i + 1) % 4] - q[i])
        lines.append((p0 + n * pad * ln, p1 + n * pad * ln))
    corners = [_line_intersect(lines[(i - 1) % 4], lines[i]) for i in range(4)]
    return q if any(c is None for c in corners) else order_corners(corners)


def _warp(full: np.ndarray, q: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = order_corners(q)
    w = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    h = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    M = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl], np.float32),
                                    np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32))
    return cv2.warpPerspective(full, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _trim_background(rect: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """余裕を付けて切り出した画像から、机の色が続いている外周だけを削る。削る量には上限がある。"""
    h, w = rect.shape[:2]
    sc = 300 / max(h, w)
    small = cv2.resize(rect, (max(8, int(w * sc)), max(8, int(h * sc))), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(cv2.GaussianBlur(small, (0, 0), 1.0), cv2.COLOR_RGB2LAB).astype(np.float32)
    dist = _bg_distance(lab, centers, 0.6)
    book = dist > 14.0                                     # 机の色から十分離れている＝本
    sh, sw = book.shape
    rows, cols = book.mean(axis=1), book.mean(axis=0)

    def first(v, maxcut):
        cut = int(maxcut)
        for i in range(0, cut + 1):
            if v[i] >= 0.6:
                return i
        return None

    mx, my = int(MAX_TRIM * sw / (1 + 2 * PAD)), int(MAX_TRIM * sh / (1 + 2 * PAD))
    top, bottom = first(rows, my), first(rows[::-1], my)
    left, right = first(cols, mx), first(cols[::-1], mx)
    if None in (top, bottom, left, right):
        # 机の色が見分けられない（白い本を白い机に置いたなど）。余裕分をそのまま内側に戻す
        k = PAD / (1 + 2 * PAD)
        top = bottom = int(round(k * sh)); left = right = int(round(k * sw))
    t, b = int(top / sc), int(bottom / sc)
    l, r = int(left / sc), int(right / sc)
    return rect[t:h - b if b else h, l:w - r if r else w]


def cut_out(img: Image.Image, max_side: int = 2000) -> tuple[Image.Image, str, bool, str]:
    """写真から本を切り出す。戻り値：(画像, 説明, 見つかったか, 警告)。
    見つからなければ写真をそのまま返す（向きは変えない）。"""
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    full = np.array(img)
    note = ""

    def look(arr):
        H, W = arr.shape[:2]
        sc = WORK / max(H, W)
        small = cv2.resize(arr, (int(W * sc), int(H * sc)), interpolation=cv2.INTER_AREA)
        return sc, find_book(small)

    def valid(b):
        return (b is not None and b["score"] >= MIN_SCORE
                and ASPECT_MIN - 0.05 <= b["aspect"] <= ASPECT_MAX + 0.05)

    sc, best = look(full)
    if not valid(best):
        # 本が横倒しに写っているのかもしれない。縦向きで見つからないときだけ、回した向きも試す
        # （これまでの写真では、横倒しはどれも「本の上が右」＝左に90度回すと正しい向きだったので、左回しを優先）
        tries = []
        for k, label in ((1, "左に90度回転"), (-1, "右に90度回転")):
            arr = np.rot90(full, k).copy()
            sc2, b2 = look(arr)
            if valid(b2):
                tries.append((b2["score"], arr, sc2, b2, label))
                break                      # 左回しで本が見つかれば、それを採用（向きの取り違えを避ける）
        if tries:
            _, arr, sc2, b2, label = max(tries, key=lambda x: x[0])
            if best is None or b2["score"] > best["score"] + 0.5:
                full, sc, best, note = arr, sc2, b2, "横倒しの写真を" + label
    if os.environ.get("BOOK_DEBUG") and best:
        print(f"[点数 {best['score']:.2f} 輪郭 {best.get('edge', 0):.2f} 外側 {best.get('outside', 0):.2f} "
              f"縦横 {best.get('aspect', 0):.2f} 面積 {best.get('frac', 0):.2f}] ", end="")
    if best is None or best["score"] < MIN_SCORE:
        return Image.fromarray(full).convert("RGBA"), "本が見つからず写真をそのまま使用", False, ""

    q = order_corners(best["pts"] / sc)
    tilt = max_tilt_deg(q)
    if tilt <= STRAIGHT_DEG or not shape_ok(q):
        # ほぼまっすぐに写っている本は、ゆがませず四角く切り出すだけにする
        # （台形補正をかけると、検出が少しずれただけで画像が斜めにゆがむため）
        H, W = full.shape[:2]
        e = order_corners(_expand(q, PAD))
        x0, x1 = int(max(0, np.floor(e[:, 0].min()))), int(min(W, np.ceil(e[:, 0].max())))
        y0, y1 = int(max(0, np.floor(e[:, 1].min()))), int(min(H, np.ceil(e[:, 1].max())))
        rect = full[y0:y1, x0:x1]
        note = (note + "・" if note else "") + "補正なし"
    else:
        rect = _warp(full, _expand(q, PAD))
        note = (note + "・" if note else "") + f"傾き{tilt:.0f}度を補正"
    rect = _trim_background(rect, best["centers"])
    warn = ""
    if best["clipped"]:
        warn = "本が写真の端で切れている可能性（撮り直し推奨）"
    elif best["score"] < 4.2:
        warn = "輪郭があまりはっきりしない（切り抜きを目で確認）"
    how = f"切り抜き（{best['source']}）" + (f"・{note}" if note else "")
    return Image.fromarray(rect).convert("RGBA"), how, True, warn


def debug_overlay(img: Image.Image, path: str) -> None:
    """どこを本と判断したかを、元写真に緑の枠で描いて保存する（確認用）。"""
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((WORK, WORK))
    rgb = np.array(img)
    best = find_book(rgb)
    if best is not None:
        color = (0, 200, 0) if best["score"] >= MIN_SCORE and not best["clipped"] else (230, 120, 0)
        cv2.polylines(rgb, [best["pts"].astype(np.int32).reshape(-1, 1, 2)], True, color, 4)
        cv2.putText(rgb, f"{best['score']:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
    Image.fromarray(rgb).save(path)
