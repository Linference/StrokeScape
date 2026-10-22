"""Deterministic procedural brush geometry, mirrored in public/renderer.js."""
from __future__ import annotations

import math

BRUSHES = ('classic', 'pencil', 'marker', 'dry', 'watercolor', 'oil', 'pointillism', 'colored_pencil')


def brush_paths(points, width, opacity, style='classic', index=0, seed=42, texture=1.0, gaps=1.0):
    if style not in BRUSHES:
        raise ValueError('Unknown brush style')
    if style == 'classic':
        return [{'p': points, 'w': width, 'o': opacity, 'cap': 'round', 'keep': None}]
    state = (int(seed) ^ (((index + 1) * 0x9E3779B1) & 0xFFFFFFFF)) & 0xFFFFFFFF

    def random():
        nonlocal state
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        return state / 4294967296

    count = len(points) // 2
    normals = []
    for vertex in range(count):
        before, after = max(0, vertex - 1), min(count - 1, vertex + 1)
        dx = points[after * 2] - points[before * 2]
        dy = points[after * 2 + 1] - points[before * 2 + 1]
        length = max(math.hypot(dx, dy), 1e-6)
        normals.append((-dy / length, dx / length))
    if style == 'pointillism':
        lengths = [0.0]
        for vertex in range(1, count):
            lengths.append(lengths[-1] + math.hypot(points[vertex * 2] - points[vertex * 2 - 2],
                                                    points[vertex * 2 + 1] - points[vertex * 2 - 1]))
        total = lengths[-1]
        dot_count = max(2, min(32, math.ceil(total / max(0.75, width * 0.72)) + 1))
        dots = []
        segment = 1
        for dot in range(dot_count):
            t = dot / (dot_count - 1)
            distance = total * t
            while segment < count - 1 and lengths[segment] < distance:
                segment += 1
            part = (distance - lengths[segment - 1]) / max(1e-6, lengths[segment] - lengths[segment - 1])
            offset = (random() - 0.5) * width * 0.9 * texture
            nx, ny = normals[segment - 1]
            x = points[segment * 2 - 2] + (points[segment * 2] - points[segment * 2 - 2]) * part + nx * offset
            y = points[segment * 2 - 1] + (points[segment * 2 + 1] - points[segment * 2 - 1]) * part + ny * offset
            dots.append([x, y, max(0.22, width * (0.17 + random() * 0.17)), t])
        return [{'p': points, 'w': width, 'o': opacity, 'cap': 'round', 'keep': None, 'dots': dots}]
    paths = []
    passes = 3 if style in ('pencil', 'marker') else 5
    for lane in range(passes):
        tone = None
        if style == 'marker':
            offset = 0 if lane == 0 else (-0.4 if lane == 1 else 0.4)
            thickness = width if lane == 0 else width * 0.13
            alpha = opacity if lane == 0 else opacity * 0.22
            cap = 'butt'
        elif style in ('pencil', 'colored_pencil'):
            offset = (lane - (1 if style == 'pencil' else 2)) * (0.27 if style == 'pencil' else 0.17)
            thickness = max(0.22, width * ((0.13 if style == 'pencil' else 0.08) + random() * 0.12))
            alpha = opacity * (0.58 + random() * 0.32)
            cap = 'round'
        elif style == 'watercolor':
            offset = 0 if lane < 3 else (-0.4 if lane == 3 else 0.4)
            thickness = width * ([1.35, 1.05, 0.78][lane] if lane < 3 else 0.09)
            alpha = opacity * ([0.12, 0.22, 0.34][lane] if lane < 3 else 0.12)
            cap = 'round'
        elif style == 'oil':
            offset = 0 if lane == 0 else (lane - 2.5) * 0.2
            thickness = width * (1.05 if lane == 0 else 0.055 + random() * 0.04)
            alpha = opacity * (0.97 if lane == 0 else 0.35 + random() * 0.35)
            cap = 'round'
            tone = 0 if lane == 0 else (0.16 if lane % 2 else -0.12)
        else:
            offset = (lane - 2) * 0.19
            thickness = max(0.22, width * (0.08 + random() * 0.09))
            alpha = opacity * (0.7 + random() * 0.3)
            cap = 'butt'
        shifted = []
        for vertex, (nx, ny) in enumerate(normals):
            jitter = 0 if style == 'marker' else (random() - 0.5) * (0.04 if style == 'oil' else 0.12)
            displacement = (offset + jitter) * width * texture
            shifted.extend((points[vertex * 2] + nx * displacement,
                            points[vertex * 2 + 1] + ny * displacement))
        keep = ([random() > (0.13 if style in ('pencil', 'colored_pencil') else 0.24) * gaps
                 for _ in range(count - 1)] if style in ('pencil', 'colored_pencil', 'dry') else None)
        if keep is not None and not any(keep):
            keep[len(keep) // 2] = True
        path = {'p': shifted, 'w': thickness, 'o': alpha, 'cap': cap, 'keep': keep}
        if tone is not None:
            path['tone'] = tone
        paths.append(path)
    return paths
