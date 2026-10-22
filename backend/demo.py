"""An original procedural landscape used as the bundled, offline sample."""
from pathlib import Path
import math

import numpy as np
from PIL import Image, ImageDraw


def create_sample(destination: Path):
    width, height = 1000, 760
    rng = np.random.default_rng(19)
    top, bottom = np.array([231, 221, 194]), np.array([239, 227, 202])
    t = np.linspace(0, 1, height)[:, None, None]
    pixels = np.broadcast_to(top * (1 - t) + bottom * t, (height, width, 3)).copy()
    pixels += rng.normal(0, 1.7, (height, width, 1))
    image = Image.fromarray(np.uint8(np.clip(pixels, 0, 255)))
    draw = ImageDraw.Draw(image)
    draw.ellipse((689, 78, 802, 191), fill=(203, 133, 88))
    # Mountain ridges are deliberately irregular rather than copied imagery.
    ridges = [
        (310, 74, (158, 181, 168), 0.1),
        (381, 115, (112, 155, 148), 1.7),
        (473, 104, (67, 123, 119), 3.4),
        (607, 90, (36, 85, 80), 4.7),
    ]
    for layer, (baseline, amplitude, color, phase) in enumerate(ridges):
        points = []
        for x in range(-20, width + 21, 7):
            y = baseline + amplitude * math.sin(x / (155 - layer * 18) + phase)
            y += amplitude * 0.18 * math.sin(x / 34 + phase) + rng.normal(0, 2)
            points.append((x, y))
        draw.polygon(points + [(width + 20, height), (-20, height)], fill=color)
        if layer in (1, 2):
            for offset in range(20, 65, 13):
                draw.line([(x, y + offset) for x, y in points], fill=tuple(min(255, c + 8) for c in color), width=1)
    # A winding light river through the foreground.
    draw.polygon([(554, 442), (570, 450), (542, 487), (589, 533), (563, 561),
                  (454, 598), (429, 621), (515, 655), (724, 701), (838, 760),
                  (493, 760), (344, 705), (310, 656), (352, 604), (491, 553),
                  (534, 531), (505, 493)], fill=(188, 205, 185))
    for y in range(600, 760, 14):
        x = 320 + int((y - 600) * 1.3)
        draw.line((x + 35, y, x + 110 + (y - 600) // 4, y), fill=(216, 220, 196), width=2)
    # Small pines make useful directional features for the painter.
    for x, y, scale in [(86, 658, 1.4), (155, 693, 1), (902, 604, 1.5), (825, 579, .85), (255, 591, .6), (751, 536, .5)]:
        draw.line((x, y - 80 * scale, x, y + 8 * scale), fill=(26, 63, 58), width=max(2, int(4 * scale)))
        for branch in range(6):
            cy = y - 70 * scale + branch * 12 * scale
            spread = (10 + branch * 5) * scale
            draw.line((x - spread, cy + 12 * scale, x, cy, x + spread, cy + 12 * scale), fill=(29, 68, 61), width=max(2, int(5 * scale)))
    # Solitary cabin, used as a small-detail subject.
    draw.rectangle((660, 518, 701, 549), fill=(218, 192, 145))
    draw.polygon([(651, 521), (681, 499), (709, 521)], fill=(94, 78, 62))
    draw.rectangle((679, 531, 688, 549), fill=(70, 81, 66))
    draw.line((0, 748, 1000, 748), fill=(34, 77, 69), width=24)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
