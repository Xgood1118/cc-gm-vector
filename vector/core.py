# -*- coding: utf-8 -*-
"""矢量图形骨架。

曲线细分固定 8 段，描边只画中心线，填充直接抛 NotImplementedError。
"""


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
       c x1 y1 x2 y2 x y   三次贝塞尔
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


def bezier(p0, p1, p2, p3, t):
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3 * mt * mt * t
    c = 3 * mt * t * t
    e = t * t * t
    return Point(a * p0.x + b * p1.x + c * p2.x + e * p3.x,
                 a * p0.y + b * p1.y + c * p2.y + e * p3.y)


def flatten_curve(p0, p1, p2, p3, segments=8):
    """把三次贝塞尔拆成折线。固定段数，不随曲线长度变化。"""
    pts = []
    for i in range(segments + 1):
        t = float(i) / segments
        pts.append(bezier(p0, p1, p2, p3, t))
    return pts


def flatten_path(path_obj):
    """把整条路径拆成折线序列。"""
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
            current = [cursor]
        elif kind == "l":
            cursor = seg[1]
            current.append(cursor)
        elif kind == "c":
            pts = flatten_curve(cursor, seg[2], seg[1], seg[3])
            current.extend(pts[1:])
            cursor = seg[3]
        elif kind == "z":
            if len(current) > 1:
                current.append(start)
                polylines.append(current)
            current = []
            cursor = start
    if len(current) > 1:
        polylines.append(current)
    return polylines


def stroke_polyline(img, points, color, width):
    """描边。当前只沿折线打点，宽度被忽略。"""
    for p in points:
        x = int(round(p.x))
        y = int(round(p.y))
        if 0 <= x < img.width and 0 <= y < img.height:
            img.set(x, y, color)


def fill_polygon(img, points, color):
    raise NotImplementedError("多边形填充尚未实现")


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


def save_png(img, path):
    raise NotImplementedError("PNG 编码尚未实现")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="vector")
    ap.add_argument("path")
    ap.add_argument("--width", type=int, default=320)
    ap.add_argument("--height", type=int, default=320)
    ap.add_argument("--out", default="vector.png")
    args = ap.parse_args(argv)
    obj = load_path(args.path)
    img = Image(args.width, args.height)
    polylines = flatten_path(obj)
    style = obj["style"]
    if style["fill"]:
        for pl in polylines:
            fill_polygon(img, pl, style["fill"])
    if style["stroke"]:
        for pl in polylines:
            stroke_polyline(img, pl, style["stroke"]["color"], style["stroke"]["width"])
    save_png(img, args.out)
    print("已输出 %s，折线 %d 条" % (args.out, len(polylines)))
    return 0
