import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
from PIL import Image
from pydantic import ValidationError
import pytest

from backend.api import Settings
from backend.brushes import BRUSHES, brush_paths
from backend.engine import paint
from backend.exporter import standalone


def test_brush_validation_and_old_settings():
    assert Settings().brush == 'classic'
    for style in BRUSHES:
        assert Settings(brush=style).brush == style
    with pytest.raises(ValidationError):
        Settings(brush='unknown')


@pytest.mark.parametrize('style', BRUSHES)
def test_cpu_and_export_share_seeded_brush_geometry(style):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js needed for shared-renderer parity check')
    points = [10, 20, 23, 13, 37, 18, 48, 6]
    cases = [{'points': points, 'width': 5.7, 'opacity': .79, 'style': style, 'index': index, 'seed': seed, 'texture': texture, 'gaps': gaps}
             for index, seed, texture, gaps in [(0, 42, 1, 1), (12345, 0, .3, 2), (499999, 2147483647, 2, 0)]]
    script = """const fs=require('fs'),vm=require('vm');
vm.runInThisContext(fs.readFileSync('public/renderer.js','utf8'));
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(cases.map(c=>StrokeBrushes.paths(c.points,c.width,c.opacity,c.style,c.index,c.seed,c.texture,c.gaps))));"""
    result = subprocess.run([node, '-e', script], input=json.dumps(cases), text=True,
                            capture_output=True, check=True, cwd=Path(__file__).resolve().parents[1])
    for case, actual in zip(cases, json.loads(result.stdout)):
        expected = brush_paths(**case)
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            assert left['cap'] == right['cap'] and left['keep'] == right['keep']
            np.testing.assert_allclose(left['p'], right['p'], atol=1e-10)
            assert left['w'] == pytest.approx(right['w'])
            assert left['o'] == pytest.approx(right['o'])
            assert left.get('tone') == right.get('tone')
            if 'dots' in right:
                np.testing.assert_allclose(left['dots'], right['dots'], atol=1e-10)


@pytest.mark.parametrize('style', BRUSHES)
def test_style_generation_is_deterministic_and_exported(tmp_path, style):
    y, x = np.mgrid[:70, :96]
    image = np.stack((40 + x, 60 + y, 150 - x), axis=-1).astype(np.uint8)
    path = tmp_path / 'color.png'
    Image.fromarray(image).save(path)
    options = dict(preset='sketch', brush=style, budget=240, duration=15, maxEdge=128, seed=42, device='cpu')
    first = paint(path, options, {}, lambda *_: None, lambda: False)
    second = paint(path, options, {}, lambda *_: None, lambda: False)
    assert first['strokes'] == second['strokes']
    assert len(first['strokes']) == 240
    assert first['settings']['brush'] == style
    assert all(stroke['dt'] > 0 for stroke in first['strokes'])
    if style == 'pencil':
        assert all(stroke['c'][1:3] == stroke['c'][3:5] == stroke['c'][5:7] for stroke in first['strokes'])
    html = standalone(first, 'Brush test')
    assert f'"brush":"{style}"' in html
    assert 'StrokeBrushes' in html


def test_eight_styles_have_distinct_geometry_and_finite_zero_length_paths():
    assert len(BRUSHES) == 8
    signatures = {json.dumps(brush_paths([0, 0, 20, 4, 36, 2], 6, .8, style), sort_keys=True) for style in BRUSHES}
    assert len(signatures) == 8
    for style in BRUSHES:
        for path in brush_paths([2, 2, 2, 2], .6, .9, style):
            assert np.isfinite(path['p']).all()
            if 'dots' in path:
                assert np.isfinite(path['dots']).all()


def test_pointillism_reveals_dots_progressively_without_rerandomizing():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js needed for shared-renderer check')
    script = """const fs=require('fs'),vm=require('vm');
vm.runInThisContext(fs.readFileSync('public/renderer.js','utf8'));
const r=Object.create(StrokeRenderer.prototype);
r.brush='pointillism';r.seed=42;
r.work={strokes:[{p:[0,0,10,0,20,0],c:'#335577',w:3,o:.9}]};r.lengths=[[0,10,20]];
let dots=[];const ctx={beginPath(){},arc(x,y,rad){dots.push([x,y,rad])},fill(){}};
r.draw(ctx,0,.25);const first=dots;dots=[];
r.draw(ctx,0,1);const full=dots;dots=[];
r.draw(ctx,0,.25);
console.log(JSON.stringify({first,full,replay:dots,alpha:ctx.globalAlpha}));"""
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, check=True,
                            cwd=Path(__file__).resolve().parents[1])
    actual = json.loads(result.stdout)
    assert 0 < len(actual['first']) < len(actual['full'])
    assert actual['first'] == actual['replay']
    assert actual['full'][:len(actual['first'])] == actual['first']
    assert actual['alpha'] == 1
