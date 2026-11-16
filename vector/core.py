# -*- coding: utf-8 -*-
"""矢量图形渲染器。

流水线：

1. ``load_path`` 解析路径文件；
2. ``flatten_path`` 按曲率自适应把贝塞尔拆成折线，几何偏差有严格上界；
3. ``fill_polygon`` 用子扫描线精确覆盖率做抗锯齿填充，奇偶规则；
4. ``stroke_polyline`` 用「到折线的距离场」做抗锯齿描边，拐角为圆角连接；
5. ``save_png`` 手工编码 24 位 PNG，输出逐字节确定。

只使用 Python 标准库。所有栅格化都在子像素坐标下进行：像素 ``(x, y)``
覆盖区域 ``[x, x+1) x [y, y+1)``，像素中心为 ``(x + 0.5, y + 0.5)``。
"""

import math
import os
import struct
import zlib

# 填充覆盖率采样密度（每个方向）。8 -> 每像素 64 个子样本。
SUPERSAMPLE = 8

# 折线逼近贝塞尔的默认最大允许偏差（像素）。远小于 1 像素，留足余量。
DEFAULT_FLATTEN_TOLERANCE = 0.25

# 自适应细分的递归深度上限（防止退化曲线爆炸）。
_MAX_SUBDIVISION_DEPTH = 24


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

class Point(object):
    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)

    def __repr__(self):
        return "Point(%.2f, %.2f)" % (self.x, self.y)


def load_path(path):
    """读取路径文件。

       m x y        移动到
       l x y        直线到
       c x1 y1 x2 y2 x y   三次贝塞尔（两个控制点 + 终点）
       z            闭合
       stroke r g b width
       fill r g b
    """
    segs = []
    style = {"stroke": None, "fill": None}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            tag = parts[0]
            nums = [float(x) for x in parts[1:]]
            if tag == "m":
                segs.append(("m", Point(nums[0], nums[1]), None, None))
            elif tag == "l":
                segs.append(("l", Point(nums[0], nums[1]), None, None))
            elif tag == "c":
                segs.append(("c", Point(nums[2], nums[3]),
                             Point(nums[0], nums[1]), Point(nums[4], nums[5])))
            elif tag == "z":
                segs.append(("z", None, None, None))
            elif tag == "stroke":
                style["stroke"] = {"color": (int(nums[0]), int(nums[1]), int(nums[2])),
                                   "width": nums[3]}
            elif tag == "fill":
                style["fill"] = (int(nums[0]), int(nums[1]), int(nums[2]))
            else:
                raise ValueError("未知行: %s" % line)
    return {"segments": segs, "style": style}


# ---------------------------------------------------------------------------
# 贝塞尔曲线
# ---------------------------------------------------------------------------

def bezier(p0, p1, p2, p3, t):
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3 * mt * mt * t
    c = 3 * mt * t * t
    e = t * t * t
    return Point(a * p0.x + b * p1.x + c * p2.x + e * p3.x,
                 a * p0.y + b * p1.y + c * p2.y + e * p3.y)


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _point_segment_distance(px, py, ax, ay, bx, by):
    """点 (px, py) 到线段 a-b 的最短距离。"""
    dx = bx - ax
    dy = by - ay
    dd = dx * dx + dy * dy
    if dd <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / dd
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def curve_chord_bound(p0, p1, p2, p3):
    """曲线到首尾弦的最大距离的严格上界。

    三次贝塞尔曲线是控制点的凸组合，而「点到线段的距离」是凸函数，
    因此曲线上任意点距弦的距离 <= max(d(p1), d(p2))（d(p0)=d(p3)=0）。
    返回该上界。
    """
    d1 = _point_segment_distance(p1.x, p1.y, p0.x, p0.y, p3.x, p3.y)
    d2 = _point_segment_distance(p2.x, p2.y, p0.x, p0.y, p3.x, p3.y)
    return max(d1, d2)


def _subdivide(p0, p1, p2, p3, tolerance, out, depth):
    """de Casteljau 二分；每个子段都满足偏差上界 <= tolerance。

    偏差上界随局部曲率增长，所以急转弯处细分自然更密；
    弦长较长的平缓段也不会被过度拆分。
    """
    if depth >= _MAX_SUBDIVISION_DEPTH or curve_chord_bound(p0, p1, p2, p3) <= tolerance:
        out.append(Point(p3.x, p3.y))
        return

    ax = 0.5 * (p0.x + p1.x)
    ay = 0.5 * (p0.y + p1.y)
    bx = 0.5 * (p1.x + p2.x)
    by = 0.5 * (p1.y + p2.y)
    cx = 0.5 * (p2.x + p3.x)
    cy = 0.5 * (p2.y + p3.y)

    dx = 0.5 * (ax + bx)
    dy = 0.5 * (ay + by)
    ex = 0.5 * (bx + cx)
    ey = 0.5 * (by + cy)

    mx = 0.5 * (dx + ex)
    my = 0.5 * (dy + ey)

    _subdivide(p0, Point(ax, ay), Point(dx, dy), Point(mx, my), tolerance, out, depth + 1)
    _subdivide(Point(mx, my), Point(ex, ey), Point(cx, cy), p3, tolerance, out, depth + 1)


def flatten_curve(p0, p1, p2, p3, segments=None, tolerance=None):
    """把三次贝塞尔拆成折线。

    ``segments`` 给定时按固定段数均分（保留旧接口的显式用法）。
    否则按曲率自适应细分，保证折线到真实曲线的最大偏差
    ``<= tolerance``（默认 0.25 像素）。返回点列从 ``p0`` 到 ``p3``，
    两端点精确。
    """
    if segments is not None:
        n = max(1, int(segments))
        pts = []
        for i in range(n + 1):
            pts.append(bezier(p0, p1, p2, p3, float(i) / n))
        pts[0] = Point(p0.x, p0.y)
        pts[-1] = Point(p3.x, p3.y)
        return pts

    if tolerance is None:
        tolerance = DEFAULT_FLATTEN_TOLERANCE
    tolerance = float(tolerance)
    if tolerance <= 0.0:
        tolerance = 1e-6

    out = [Point(p0.x, p0.y)]
    _subdivide(p0, p1, p2, p3, tolerance, out, 0)
    return out


def flatten_path(path_obj, tolerance=None):
    """把整条路径拆成折线序列。

    每个子路径一条折线；闭合路径的首尾点是同一个坐标，供描边接缝使用。
    """
    if tolerance is None:
        tolerance = DEFAULT_FLATTEN_TOLERANCE
    polylines = []
    current = []
    cursor = Point(0, 0)
    start = Point(0, 0)
    for seg in path_obj["segments"]:
        kind = seg[0]
        if kind == "m":
            if len(current) > 1:
                polylines.append(current)
            cursor = seg[1]
            start = cursor
            current = [Point(cursor.x, cursor.y)]
        elif kind == "l":
            cursor = seg[1]
            current.append(Point(cursor.x, cursor.y))
        elif kind == "c":
            pts = flatten_curve(cursor, seg[2], seg[1], seg[3], tolerance=tolerance)
            current.extend(pts[1:])
            cursor = seg[3]
        elif kind == "z":
            if len(current) > 1:
                current.append(Point(start.x, start.y))
                polylines.append(current)
            current = []
            cursor = start
    if len(current) > 1:
        polylines.append(current)
    return polylines


# ---------------------------------------------------------------------------
# 像素混合
# ---------------------------------------------------------------------------

def _blend(pixels, index, color, coverage):
    """按覆盖率把纯色混到不透明目标像素上。"""
    if coverage <= 0.0:
        return
    if coverage > 1.0:
        coverage = 1.0
    if coverage >= 1.0:
        pixels[index] = (int(color[0]), int(color[1]), int(color[2]))
        return
    dst = pixels[index]
    inv = 1.0 - coverage
    pixels[index] = (
        int(round(color[0] * coverage + dst[0] * inv)),
        int(round(color[1] * coverage + dst[1] * inv)),
        int(round(color[2] * coverage + dst[2] * inv)),
    )


def _supersample(supersample):
    try:
        s = int(supersample)
    except (TypeError, ValueError):
        s = SUPERSAMPLE
    return s if s >= 1 else 1


# ---------------------------------------------------------------------------
# 填充
# ---------------------------------------------------------------------------

def fill_polygon(img, points, color, supersample=None):
    """按奇偶规则填充多边形，抗锯齿。

    对每个像素行取 ``S`` 条子扫描线，在每条子扫描线上求出所有交点并成对
    取内部区间；子扫描线与像素格的横向重叠即该像素在该子行上的精确覆盖率。
    最终覆盖率 = 各子行覆盖率之和 / S。

    奇偶规则天然把自交区域交替判为内外。返回被填充触及的像素数。
    """
    if len(points) < 3:
        return 0

    S = _supersample(supersample)
    inv = 1.0 / S

    pts = [(p.x, p.y) for p in points]
    if pts[0] != pts[-1]:
        pts.append(pts[0])

    # 边表：只保留非水平边，统一成 (y_min, y_max, x_at_ymin, slope=dx/dy)。
    edges = []
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if y0 == y1:
            continue
        if y0 < y1:
            edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0)))
        else:
            edges.append((y1, y0, x1, (x0 - x1) / (y0 - y1)))
    if not edges:
        return 0

    ys = [p[1] for p in pts]
    xs = [p[0] for p in pts]
    y_lo = max(0, int(math.floor(min(ys))))
    y_hi = min(img.height - 1, int(math.floor(max(ys))))
    x_lo = max(0, int(math.floor(min(xs))))
    x_hi = min(img.width - 1, int(math.floor(max(xs))))
    if y_lo > y_hi or x_lo > x_hi:
        return 0

    touched = 0
    offsets = [(i + 0.5) * inv for i in range(S)]

    for py in range(y_lo, y_hi + 1):
        acc = {}
        for off in offsets:
            y = py + off
            crossings = []
            for y_min, y_max, x_at_min, slope in edges:
                if y_min <= y < y_max:
                    crossings.append(x_at_min + (y - y_min) * slope)
            if len(crossings) < 2:
                continue
            crossings.sort()
            for k in range(0, len(crossings) - 1, 2):
                _accumulate_span(acc, crossings[k], crossings[k + 1], inv, x_lo, x_hi)

        base = py * img.width
        for px in sorted(acc):
            cov = acc[px]
            if cov > 0.0:
                _blend(img.pixels, base + px, color, cov)
                touched += 1
    return touched


# ---------------------------------------------------------------------------
# 描边
# ---------------------------------------------------------------------------

def _stadium_span(ax, ay, bx, by, half, y):
    """水平直线 y 与「线段 a-b 外扩 half」的胶囊区域的 x 区间。

    胶囊是凸集，水平直线与凸集的交集必为单一区间；胶囊又是两个圆盘与
    一个旋转矩形的并集，三者互相接触，所以区间 = 各部分区间的最左/最右。
    """
    lo = None
    hi = None

    for cx, cy in ((ax, ay), (bx, by)):
        d = y - cy
        if d * d <= half * half:
            r = math.sqrt(half * half - d * d)
            if lo is None or cx - r < lo:
                lo = cx - r
            if hi is None or cx + r > hi:
                hi = cx + r

    dx = bx - ax
    dy = by - ay
    length = math.hypot(dx, dy)
    if length > 1e-12:
        nx = -dy / length
        ny = dx / length
        corners = ((ax + half * nx, ay + half * ny),
                   (bx + half * nx, by + half * ny),
                   (bx - half * nx, by - half * ny),
                   (ax - half * nx, ay - half * ny))
        xs = []
        for i in range(4):
            x0, y0 = corners[i]
            x1, y1 = corners[(i + 1) % 4]
            if y0 == y1:
                if y == y0:
                    xs.append(x0)
                    xs.append(x1)
            elif (y0 - y) * (y1 - y) <= 0.0:
                t = (y - y0) / (y1 - y0)
                xs.append(x0 + t * (x1 - x0))
        if xs:
            rlo = min(xs)
            rhi = max(xs)
            if lo is None or rlo < lo:
                lo = rlo
            if hi is None or rhi > hi:
                hi = rhi

    if lo is None or hi is None:
        return None
    return (lo, hi)


def _union_spans(spans):
    """把若干 x 区间合并成不相交区间（胶囊之间的并集）。"""
    spans.sort()
    merged = []
    for lo, hi in spans:
        if hi <= lo:
            continue
        if merged and lo <= merged[-1][1]:
            if hi > merged[-1][1]:
                merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return merged


def _accumulate_span(acc, lo, hi, weight, x_lo, x_hi):
    """把水平区间 [lo, hi) 与像素格的横向重叠按 weight 累加到 acc。"""
    if hi <= lo:
        return
    pa = int(math.floor(lo))
    pb = int(math.floor(hi))
    if pa < x_lo:
        pa = x_lo
    if pb > x_hi:
        pb = x_hi
    if pa > pb:
        return
    for px in range(pa, pb + 1):
        left = lo if lo > px else px
        right = px + 1
        hi_c = hi if hi < right else right
        if hi_c > left:
            w = (hi_c - left) * weight
            if px in acc:
                acc[px] += w
            else:
                acc[px] = w


def stroke_polyline(img, points, color, width, supersample=None):
    """抗锯齿描边折线，``width`` 为线宽（像素）。

    每个线段外扩 ``width/2`` 形成胶囊（圆角），全部胶囊取并集：
    拐角处相邻胶囊必然重叠，不会断开；并集不会超出胶囊范围，不会出现
    尖刺。闭合路径首尾共享端点，接缝与普通关节完全相同。

    覆盖率在 x 方向解析计算（区间与像素格的重叠长度），y 方向用 S 条子扫描
    线平均，因此不仅是灰度过渡，覆盖率数值与几何面积一致。

    返回被描边触及（覆盖率 > 0）的像素数。
    """
    if len(points) < 2 or width is None:
        return 0
    half = float(width) * 0.5
    if half <= 0.0:
        return 0

    S = _supersample(supersample)
    weight = 1.0 / S
    offsets = [(i + 0.5) * weight for i in range(S)]

    segs = []
    y_min = float("inf")
    y_max = float("-inf")
    for i in range(len(points) - 1):
        p = points[i]
        q = points[i + 1]
        segs.append((p.x, p.y, q.x, q.y))
        seg_min = min(p.y, q.y) - half
        seg_max = max(p.y, q.y) + half
        if seg_min < y_min:
            y_min = seg_min
        if seg_max > y_max:
            y_max = seg_max
    if not segs:
        return 0

    y_lo = max(0, int(math.floor(y_min)))
    y_hi = min(img.height - 1, int(math.floor(y_max)))

    touched = 0
    for py in range(y_lo, y_hi + 1):
        acc = {}
        for off in offsets:
            y = py + off
            spans = []
            for ax, ay, bx, by in segs:
                if y < min(ay, by) - half or y > max(ay, by) + half:
                    continue
                span = _stadium_span(ax, ay, bx, by, half, y)
                if span is not None:
                    spans.append(span)
            for lo, hi in _union_spans(spans):
                _accumulate_span(acc, lo, hi, weight, 0, img.width - 1)

        base = py * img.width
        for px in sorted(acc):
            cov = acc[px]
            if cov > 0.0:
                _blend(img.pixels, base + px, color, cov)
                touched += 1
    return touched


# ---------------------------------------------------------------------------
# 图像与 PNG
# ---------------------------------------------------------------------------

class Image(object):
    def __init__(self, width, height, background=(255, 255, 255)):
        self.width = int(width)
        self.height = int(height)
        self.pixels = [background for _ in range(self.width * self.height)]

    def set(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y * self.width + x] = color

    def get(self, x, y):
        return self.pixels[y * self.width + x]


def _png_chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def save_png(img, path):
    """写出 24 位 RGB PNG。

    固定 filter=None、固定 zlib 压缩级别，不写入时间戳等元数据，
    因此同样的像素内容总是产生逐字节相同的文件。
    """
    width = img.width
    height = img.height
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # 每行 filter type 0 (None)
        base = y * width
        for x in range(width):
            r, g, b = img.pixels[base + x]
            raw.append(int(r) & 0xFF)
            raw.append(int(g) & 0xFF)
            raw.append(int(b) & 0xFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    body = (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _png_chunk(b"IEND", b""))
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "wb") as f:
        f.write(body)
    return len(body)


def render(path_obj, width, height):
    """按路径对象的样式渲染成 Image。填充在前、描边在后。"""
    img = Image(width, height)
    polylines = flatten_path(path_obj)
    style = path_obj["style"]
    if style["fill"]:
        for pl in polylines:
            fill_polygon(img, pl, style["fill"])
    if style["stroke"]:
        for pl in polylines:
            stroke_polyline(img, pl, style["stroke"]["color"], style["stroke"]["width"])
    return img, polylines


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="vector")
    ap.add_argument("path")
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--height", type=int, default=320)
    ap.add_argument("--out", default="vector.png")
    args = ap.parse_args(argv)
    obj = load_path(args.path)
    img, polylines = render(obj, args.width, args.height)
    save_png(img, args.out)
    print("已输出 %s，折线 %d 条" % (args.out, len(polylines)))
    return 0
