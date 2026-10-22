import json

import numpy as np
import pytest
from PIL import Image

from backend.engine import Cancelled, PAPER, PRESETS, PRESET_EDGES, draw_local, paint, schedule
from backend.exporter import standalone


@pytest.fixture
def image_path(tmp_path):
    y, x = np.mgrid[:80, :112]
    rgb = np.stack((40 + x, 60 + y, 90 + x // 2), axis=-1).astype(np.uint8)
    path = tmp_path / 'source.png'
    Image.fromarray(rgb).save(path)
    return path


def settings():
    return {'preset': 'sketch', 'budget': 240, 'duration': 15, 'device': 'cpu', 'seed': 42, 'maxEdge': 128}


def test_serial_budget_determinism_and_quality(image_path):
    outputs = [paint(image_path, settings(), {}, lambda *args: None, lambda: False) for _ in range(2)]
    first, second = outputs
    assert len(first['strokes']) == 240
    assert first['strokes'] == second['strokes']
    assert sum(first['layers']) == 240
    assert first['strokes'][0]['s'] == 0
    assert abs(first['durationMs'] - 15000) < 0.1
    for before, after in zip(first['strokes'], first['strokes'][1:]):
        assert before['s'] + before['dt'] <= after['s'] + 1e-7
        if before['l'] != after['l']:
            assert after['s'] - before['s'] - before['dt'] == pytest.approx(200)
    original = np.asarray(Image.open(image_path)).astype(np.float32)
    canvas = np.full(original.shape, PAPER, np.uint8)
    blank_error = np.abs(canvas.astype(np.float32) - original).mean()
    for stroke in first['strokes']:
        color = [int(stroke['c'][i:i + 2], 16) for i in (1, 3, 5)]
        draw_local(canvas, stroke['p'], color, stroke['w'], stroke['o'])
    assert np.abs(canvas.astype(np.float32) - original).mean() < blank_error * 0.5


def test_cancel_before_stroke_loop(image_path):
    with pytest.raises(Cancelled):
        paint(image_path, settings(), {}, lambda *args: None, lambda: True)


def test_auto_without_cuda_keeps_cpu_functional(image_path):
    opts = settings() | {'device': 'auto'}
    result = paint(image_path, opts, {'available': False, 'reason': 'not installed'}, lambda *args: None, lambda: False)
    assert result['stats']['backend'] == 'cpu'
    assert result['stats']['fallback'] == 'not installed'


@pytest.mark.parametrize('budget', [200000, 500000])
def test_large_budget_schedule_stays_positive_serial_and_exact(budget):
    per_layer = budget // 4
    strokes = [{'p': [1, 1, 1.01 + index % 7, 2], 'l': min(3, index // per_layer)} for index in range(budget)]
    counts = schedule(strokes, 15000)
    assert counts == [per_layer] * 4
    assert all(stroke['dt'] > 0 for stroke in strokes)
    assert strokes[-1]['s'] + strokes[-1]['dt'] == pytest.approx(15000, abs=1e-6)
    for previous, current in zip(strokes, strokes[1:]):
        assert previous['s'] + previous['dt'] <= current['s'] + 1e-7


def test_high_density_presets_and_incremental_feedback(image_path):
    assert PRESETS == {'sketch': 18000, 'standard': 60000, 'fine': 150000}
    assert PRESET_EDGES['fine'] == 1920
    output = paint(image_path, settings() | {'maxEdge': None}, {}, lambda *args: None, lambda: False)
    assert output['settings']['maxEdge'] == 960
    assert output['settings']['budget'] == 240
    assert output['stats']['analysisSeconds'] >= 0


def test_standalone_has_no_remote_dependencies_or_script_injection(image_path):
    result = paint(image_path, settings(), {}, lambda *args: None, lambda: False)
    result['settings']['adversarial'] = '</script><script>alert(1)</script>'
    document = standalone(result, '<img src=x onerror=alert(1)>')
    assert '<script>alert(1)</script>' not in document
    assert '<img src=x onerror=alert(1)>' not in document
    assert '\\u003c/script>' in document
    assert 'https://' not in document
    assert 'class StrokeRenderer' in document
    assert 'requestAnimationFrame' in document
