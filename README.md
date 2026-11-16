# 矢量描边与填充

骨架能解析路径、能按固定 8 段拆分贝塞尔，但画不出可用的图形。

## 已知缺口

- `flatten_curve` 无论曲线多长都只拆 8 段，长曲线明显折线化，短曲线过度细分。
- `stroke_polyline` 忽略线宽，只在中心线上打单像素，放大后是一条细线。
- 折线拐角处没有连接处理，宽线会断开。
- `fill_polygon` 抛 NotImplementedError。
- `save_png` 抛 NotImplementedError。
- 没有抗锯齿，斜边全是硬锯齿。

## 运行

```
python gen_samples.py
python -m vector.cli data/shape.txt --width 320 --height 320 --out vector.png
python -m pytest tests -q
```

`shape.txt` 是一条由两段三次贝塞尔组成的闭合叶片，带 6 像素描边和填充色。
