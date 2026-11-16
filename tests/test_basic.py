# -*- coding: utf-8 -*-
import hashlib
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vector.core import (  # noqa: E402
    Image, Point, bezier, fill_polygon, flatten_curve, flatten_path,
    load_path, save_png, stroke_polyline,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHAPE = os.path.join(ROOT, "data", "shape.txt")


def _sample_curve(p0, p1, p2, p3, n=4000):
    return [bezier(p0, p1, p2, p3, i / float(n)) for i in range(n + 1)]


def _point_polyline_distance(pt, poly):
    best = float("inf")
    for i in range(len(poly) - 1):
        a, b = poly[i], poly[i + 1]
        dx = b.x - a.x
        dy = b.y - a.y
        dd = dx * dx + dy * dy
        if dd <= 1e-18:
            d = math.hypot(pt.x - a.x, pt.y - a.y)
        else:
            t = ((pt.x - a.x) * dx + (pt.y - a.y) * dy) / dd
            t = max(0.0, min(1.0, t))
            d = math.hypot(pt.x - (a.x + t * dx), pt.y - (a.y + t * dy))
        if d < best:
            best = d
    return best


def _polyline_curve_distance(poly, curve):
    """折线各点到真实曲线的最大偏差（双向 Hausdorff 的一半）。"""
    best = 0.0
    for pt in poly:
        d = _point_polyline_distance(pt, curve)
        if d > best:
            best = d
    return best


# ---------------------------------------------------------------------------
# 解析与基础接口
# ---------------------------------------------------------------------------

def test_bezier_endpoints():
    p0, p1, p2, p3 = Point(0, 0), Point(1, 2), Point(3, 2), Point(4, 0)
    a = bezier(p0, p1, p2, p3, 0.0)
    b = bezier(p0, p1, p2, p3, 1.0)
    assert abs(a.x) < 1e-9 and abs(a.y) < 1e-9
    assert abs(b.x - 4) < 1e-9 and abs(b.y - 0) < 1e-9


def test_flatten_explicit_segments():
    pts = flatten_curve(Point(0, 0), Point(1, 1), Point(2, 1), Point(3, 0), segments=8)
    assert len(pts) == 9


def test_image_bounds():
    img = Image(5, 4)
    img.set(-1, 0, (0, 0, 0))
    img.set(5, 0, (0, 0, 0))
    assert img.get(0, 0) == (255, 255, 255)


def test_load_path_segments():
    obj = load_path(SHAPE)
    assert obj["style"]["stroke"]["width"] == 6.0
    polylines = flatten_path(obj)
    assert len(polylines) == 1
    assert len(polylines[0]) > 10
    # 闭合路径首尾点重合
    first, last = polylines[0][0], polylines[0][-1]
    assert abs(first.x - last.x) < 1e-9 and abs(first.y - last.y) < 1e-9


# ---------------------------------------------------------------------------
# 1. 曲线细分：密度随曲率变化，偏差上界 < 1 像素
# ---------------------------------------------------------------------------

def test_flatten_error_under_one_pixel():
    cases = [
        # 长而平缓
        (Point(0, 0), Point(100, 0), Point(200, 0), Point(300, 0)),
        # 长且弯曲
        (Point(0, 0), Point(400, 300), Point(-100, 300), Point(300, 0)),
        # 急转弯
        (Point(0, 0), Point(200, 0), Point(0, 1), Point(1, 1)),
        # 高曲率小回环
        (Point(0, 0), Point(100, 100), Point(-100, 100), Point(0, 0)),
    ]
    for p0, p1, p2, p3 in cases:
        curve = _sample_curve(p0, p1, p2, p3)
        poly = flatten_curve(p0, p1, p2, p3)
        # 曲线到折线的距离
        forward = max(_point_polyline_distance(q, poly) for q in curve)
        assert forward <= 1.0, "曲线到折线偏差 %.3f 超过 1 像素" % forward
        # 折线到曲线的距离（防止折线偏离）
        backward = _polyline_curve_distance(poly, curve)
        assert backward <= 1.0, "折线到曲线偏差 %.3f 超过 1 像素" % backward


def test_flatten_density_follows_curvature():
    # 同样弦长的两段曲线，曲率大的一段应得到更多点。
    flat = flatten_curve(Point(0, 0), Point(100, 2), Point(200, 2), Point(300, 0))
    bent = flatten_curve(Point(0, 0), Point(100, 200), Point(200, -200), Point(300, 0))
    assert len(bent) > len(flat)
    # 长曲线点数多于短曲线（同形状按比例放大）
    short = flatten_curve(Point(0, 0), Point(10, 10), Point(20, 10), Point(30, 0))
    long_ = flatten_curve(Point(0, 0), Point(100, 100), Point(200, 100), Point(300, 0))
    assert len(long_) > len(short)


def test_flatten_tolerance_is_respected():
    p0, p1, p2, p3 = Point(0, 0), Point(300, 200), Point(-50, 200), Point(250, 0)
    curve = _sample_curve(p0, p1, p2, p3)
    poly = flatten_curve(p0, p1, p2, p3, tolerance=0.05)
    forward = max(_point_polyline_distance(q, poly) for q in curve)
    assert forward <= 0.05 + 1e-9


# ---------------------------------------------------------------------------
# 2. 描边
# ---------------------------------------------------------------------------

def _stroke_count(width):
    img = Image(120, 120)
    pts = [Point(20, 60), Point(60, 20), Point(100, 60)]
    stroke_polyline(img, pts, (0, 0, 0), width)
    return sum(1 for px in img.pixels if px != (255, 255, 255))


def test_stroke_width_takes_effect():
    counts = [_stroke_count(w) for w in (1, 2, 4, 8, 12, 16, 20)]
    assert all(c > 0 for c in counts)
    # 宽度单调增大时覆盖像素数严格增加（1..20 都成立）
    for a, b in zip(counts, counts[1:]):
        assert b > a, "线宽增大但覆盖像素没有增加: %r" % (counts,)
    # 面积大致与线宽成正比：width=20 的覆盖应 >= width=1 的 10 倍
    assert counts[-1] >= counts[0] * 10


def test_stroke_corners_connected():
    # L 形拐角处不能断开：拐角附近一条法向扫描线上必须有连续覆盖。
    img = Image(80, 80)
    pts = [Point(20, 20), Point(60, 20), Point(60, 60)]
    stroke_polyline(img, pts, (0, 0, 0), 10)
    # 拐角外角 (60+5, 20-5) 附近必须有像素被覆盖，说明连接被填充。
    covered = 0
    for y in range(10, 31):
        for x in range(50, 71):
            if img.get(x, y) != (255, 255, 255):
                covered += 1
    assert covered > 0
    # 两条线段沿线（中心线上下 2 像素处）都必须连续覆盖，不能有洞。
    for x in range(20, 61):
        assert img.get(x, 18) != (255, 255, 255), (x, 18)
        assert img.get(x, 22) != (255, 255, 255), (x, 22)
    for y in range(20, 61):
        assert img.get(58, y) != (255, 255, 255), (58, y)
        assert img.get(62, y) != (255, 255, 255), (62, y)
    # 拐角处是对称的圆角覆盖：外角方向也要有像素。
    for k in range(8):
        ang = math.pi * 0.5 * k / 7.0  # 0..90 度
        x = int(round(60 + 4.0 * math.sin(ang)))
        y = int(round(20 - 4.0 * math.cos(ang)))
        assert img.get(x, y) != (255, 255, 255), (x, y, ang)


def test_stroke_no_spikes():
    # 尖刺会表现为远离折线（超出胶囊外接范围）的覆盖像素。
    # 只要像素有任何一个角落在胶囊内就会被覆盖，所以像素中心距折线的
    # 最大距离是半宽 + 半个像素对角线 = width/2 + sqrt(2)/2。
    img = Image(120, 120)
    pts = [Point(20, 90), Point(60, 20), Point(100, 90)]
    width = 8
    stroke_polyline(img, pts, (0, 0, 0), width)
    limit = width / 2.0 + math.sqrt(2.0) / 2.0 + 1e-9
    for y in range(img.height):
        for x in range(img.width):
            if img.get(x, y) != (255, 255, 255):
                d = _point_polyline_distance(Point(x + 0.5, y + 0.5), pts)
                assert d <= limit, (x, y, d)


def test_closed_path_seam_smooth():
    # 闭合路径：首尾重合，接缝处的描边覆盖必须与普通顶点一致，无缺口。
    obj = load_path(SHAPE)
    poly = flatten_path(obj)[0]
    img = Image(320, 320)
    stroke_polyline(img, poly, (0, 0, 0), 6)
    first = poly[0]
    # 围绕起点一整圈都有覆盖（半径 1.5 内）
    covered_dirs = 0
    for k in range(16):
        ang = 2.0 * math.pi * k / 16.0
        x = int(round(first.x + 1.5 * math.cos(ang)))
        y = int(round(first.y + 1.5 * math.sin(ang)))
        if 0 <= x < 320 and 0 <= y < 320 and img.get(x, y) != (255, 255, 255):
            covered_dirs += 1
    assert covered_dirs >= 12


# ---------------------------------------------------------------------------
# 3. 填充
# ---------------------------------------------------------------------------

def test_fill_non_empty():
    img = Image(100, 100)
    square = [Point(10, 10), Point(90, 10), Point(90, 90), Point(10, 90), Point(10, 10)]
    touched = fill_polygon(img, square, (255, 0, 0))
    assert touched > 0
    assert img.get(50, 50) == (255, 0, 0)


def test_fill_even_odd():
    # 两个相互重叠的方形：重叠区按奇偶规则被判为外部（白）。
    a = [Point(10, 10), Point(60, 10), Point(60, 60), Point(10, 60), Point(10, 10)]
    b = [Point(40, 40), Point(90, 40), Point(90, 90), Point(40, 90), Point(40, 40)]
    img = Image(100, 100)
    fill_polygon(img, a + b, (0, 0, 255))
    assert img.get(25, 25) == (0, 0, 255)   # 只在 a 内
    assert img.get(75, 75) == (0, 0, 255)   # 只在 b 内
    assert img.get(50, 50) == (255, 255, 255)  # 重叠 -> 外部


def test_fill_curve_non_empty():
    obj = load_path(SHAPE)
    poly = flatten_path(obj)[0]
    img = Image(320, 320)
    touched = fill_polygon(img, poly, (235, 200, 90))
    assert touched > 5000
    assert img.get(160, 200) == (235, 200, 90)


def test_fill_stroke_no_gap():
    # 填充后描边，边界两侧都不能有白色缝隙。
    obj = load_path(SHAPE)
    poly = flatten_path(obj)[0]
    img = Image(320, 320)
    fill_polygon(img, poly, (235, 200, 90))
    stroke_polyline(img, poly, (30, 30, 60), 6)
    # 沿每条折线段的内部法向两侧各取 1 像素，应都不是纯白。
    for i in range(0, len(poly) - 1, 7):
        a, b = poly[i], poly[i + 1]
        dx, dy = b.x - a.x, b.y - a.y
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            continue
        nx, ny = -dy / ln, dx / ln
        mx, my = (a.x + b.x) / 2.0, (a.y + b.y) / 2.0
        for sign in (-1.0, 1.0):
            x = int(round(mx + sign * 0.5 * nx))
            y = int(round(my + sign * 0.5 * ny))
            if 0 <= x < 320 and 0 <= y < 320:
                assert img.get(x, y) != (255, 255, 255), (x, y)


# ---------------------------------------------------------------------------
# 4. 抗锯齿
# ---------------------------------------------------------------------------

def test_antialiasing_has_gray_edges():
    img = Image(120, 120)
    pts = [Point(10, 100), Point(110, 10)]
    stroke_polyline(img, pts, (0, 0, 0), 4)
    gray = 0
    for px in img.pixels:
        if px != (255, 255, 255) and px != (0, 0, 0):
            gray += 1
    assert gray > 20, "斜线边缘没有灰度过渡"


def test_fill_antialiasing_consistent_with_geometry():
    # 斜边 y = x + 0.25 穿过像素：覆盖率应随斜边在像素内的位置平滑变化，
    # 且数值与「像素内位于斜边上方的面积」一致。
    img = Image(40, 40)
    # 用一个大三角形，斜边固定为 y = x + 0.25（不是整像素对齐的 45 度线）
    poly = [Point(-0.0, 0.25), Point(40.0, 40.25), Point(40.0, 0.25), Point(-0.0, 0.25)]
    fill_polygon(img, poly, (0, 0, 0), supersample=32)
    # 斜边下方的像素：跨 (i, i+1) 的那一列有一个部分覆盖像素。
    partial = 0
    for i in range(1, 38):
        px = img.get(i, i)
        if 0 < px[0] < 255:
            partial += 1
    assert partial >= 30, "斜边覆盖率没有形成连续过渡带: %d" % partial
    # 覆盖率与几何位置一致：斜边在像素内的位置每列平移 1 像素，
    # 该列的分界像素覆盖率应基本相同（几何是平移不变的）。
    vals = [img.get(i, i)[0] for i in range(5, 30)]
    assert max(vals) - min(vals) <= 2, vals
    # 深在内部与深在外部的像素分别是全黑与全白。
    assert img.get(20, 30)[0] == 255  # 斜边下方（外部）
    assert img.get(20, 10)[0] == 0    # 斜边上方（内部）


def test_coverage_matches_half_plane_area():
    # 水平边界 y=10.5 的矩形：第 10 行像素覆盖率刚好 0.5。
    img = Image(20, 20)
    poly = [Point(2, 10.5), Point(18, 10.5), Point(18, 18), Point(2, 18), Point(2, 10.5)]
    fill_polygon(img, poly, (0, 0, 0), supersample=16)
    v = img.get(10, 10)[0]
    assert abs(v - 128) <= 3, v
    assert img.get(10, 11) == (0, 0, 0)


def test_stroke_coverage_matches_geometry():
    # 竖直线 x=10.3、宽 4 -> 带宽 [8.3, 12.3]。
    # 像素 8 覆盖 0.7，像素 9/10/11 全覆盖，像素 12 覆盖 0.3。
    img = Image(24, 24)
    stroke_polyline(img, [Point(10.3, 2), Point(10.3, 22)], (0, 0, 0), 4, supersample=32)
    # 边缘像素覆盖率与几何面积一致（容差 3/255）。
    assert abs(img.get(8, 12)[0] - 77) <= 3   # 覆盖 0.7 -> 白剩 0.3
    assert abs(img.get(12, 12)[0] - 179) <= 3  # 覆盖 0.3 -> 白剩 0.7
    assert [img.get(x, 12)[0] for x in range(9, 12)] == [0, 0, 0]
    assert img.get(7, 12) == (255, 255, 255)
    assert img.get(13, 12) == (255, 255, 255)


def test_stroke_coverage_moves_with_subpixel_position():
    # 线在像素内平移时，跨越边缘的像素覆盖率必须连续、线性地变化。
    # 宽 2 的竖线 x=px，左边缘在 px-1；取 px in (9.1, 9.9) 让该边缘始终
    # 落在像素 8 内部。
    vals = []
    for px in (9.1, 9.3, 9.5, 9.7, 9.9):
        img = Image(24, 24)
        stroke_polyline(img, [Point(px, 2), Point(px, 22)], (0, 0, 0), 2, supersample=32)
        vals.append(img.get(8, 12)[0])
    # 覆盖率从 0.9 线性降到 0.1 -> 白色分量从 ~26 升到 ~230，步长约 51。
    assert vals == sorted(vals), vals
    for a, b in zip(vals, vals[1:]):
        assert abs((b - a) - 51) <= 7, (vals, a, b)
    assert abs(vals[0] - 26) <= 4 and abs(vals[-1] - 230) <= 4, vals

    # 跨过像素边界时也要连续：px 从 9.9 到 10.1，覆盖率从 0.1 到 0，
    # 左边缘 9.1 落在像素 9 里，覆盖率 0.9 -> 白剩 0.1。
    img = Image(24, 24)
    stroke_polyline(img, [Point(10.1, 2), Point(10.1, 22)], (0, 0, 0), 2, supersample=32)
    assert img.get(8, 12) == (255, 255, 255)
    assert abs(img.get(9, 12)[0] - 26) <= 4


def test_stroke_area_conserved_across_widths():
    # 水平线段覆盖面积应约等于 width*length + 两端半圆。
    for width in (1, 2, 5, 12, 20):
        img = Image(80, 80)
        stroke_polyline(img, [Point(15, 40), Point(65, 40)], (0, 0, 0), width, supersample=16)
        area = sum((255 - p[0]) / 255.0 for p in img.pixels)
        expected = width * 50 + math.pi * (width / 2.0) ** 2
        assert abs(area - expected) / expected < 0.01, (width, area, expected)


# ---------------------------------------------------------------------------
# 5. 出图：尺寸、背景、确定性
# ---------------------------------------------------------------------------

def _png_size(data):
    # IHDR 位于签名(8) + 长度(4) + 类型(4) 之后
    import struct
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def test_png_size_and_background(tmp_path):
    obj = load_path(SHAPE)
    img = Image(137, 91)
    out = str(tmp_path / "a.png")
    save_png(img, out)
    data = open(out, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert _png_size(data) == (137, 91)


def test_render_is_byte_identical(tmp_path):
    obj = load_path(SHAPE)
    outs = []
    for name in ("one.png", "two.png"):
        p = str(tmp_path / name)
        # 与 CLI 相同的流程
        from vector.core import render
        img, _ = render(obj, 320, 320)
        save_png(img, p)
        outs.append(open(p, "rb").read())
    assert hashlib.sha256(outs[0]).hexdigest() == hashlib.sha256(outs[1]).hexdigest()
    assert outs[0] == outs[1]
