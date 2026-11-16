# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vector.core import Image, Point, bezier, flatten_curve, flatten_path, load_path  # noqa: E402


def test_bezier_endpoints():
    p0, p1, p2, p3 = Point(0, 0), Point(1, 2), Point(3, 2), Point(4, 0)
    a = bezier(p0, p1, p2, p3, 0.0)
    b = bezier(p0, p1, p2, p3, 1.0)
    assert abs(a.x) < 1e-9 and abs(a.y) < 1e-9
    assert abs(b.x - 4) < 1e-9 and abs(b.y) < 1e-9


def test_flatten_count():
    pts = flatten_curve(Point(0, 0), Point(1, 1), Point(2, 1), Point(3, 0))
    assert len(pts) == 9


def test_image_bounds():
    img = Image(5, 4)
    img.set(-1, 0, (0, 0, 0))
    img.set(5, 0, (0, 0, 0))
    assert img.get(0, 0) == (255, 255, 255)


def test_load_path_segments():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "data", "shape.txt")
    if not os.path.exists(path):
        return
    obj = load_path(path)
    assert obj["style"]["stroke"]["width"] == 6.0
    polylines = flatten_path(obj)
    assert len(polylines) == 1
    assert len(polylines[0]) > 10
