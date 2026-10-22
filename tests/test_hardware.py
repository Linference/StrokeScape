import sys
from types import SimpleNamespace

from backend import hardware


def test_cuda_loader_error_is_actionable_and_preserves_detail(monkeypatch):
    message = 'Failed to load nvrtc64_130_0.dll: module not found'

    def broken_runtime():
        raise RuntimeError(message)

    monkeypatch.setattr(hardware.importlib.util, 'find_spec', lambda name: object())
    monkeypatch.setitem(sys.modules, 'cupy', SimpleNamespace(is_available=broken_runtime))
    result = hardware.detect_cuda()
    assert result['available'] is False
    assert result['errorDetail'] == message
    assert result['errorType'] == 'RuntimeError'
    assert '重启' in result['hint']
    assert result['reason'] == 'CUDA 运行组件加载失败'
