# -*- coding: utf-8 -*-
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    body = """stroke 30 30 60 6
fill 235 200 90
m 60 240
c 100 80 220 80 260 240
c 180 300 120 300 60 240
z
"""
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    path = os.path.join(HERE, "data", "shape.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    print("已生成", path)


if __name__ == "__main__":
    main()
