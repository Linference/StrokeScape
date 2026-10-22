import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import storage
from backend.api import app
from backend.api import Settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DATA', tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def test_empty_history_sample_and_missing_files(client):
    assert client.get('/api/health').json()['name'] == '绘序成境'
    assert client.get('/api/tasks').json() == []
    sample = client.get('/api/sample')
    assert sample.status_code == 200
    assert sample.headers['content-type'] == 'image/png'
    assert client.get('/api/tasks/not-a-uuid/source').status_code == 404
    assert client.get('/api/tasks/' + 'a' * 32 + '/work').status_code == 404


def test_reject_invalid_upload_and_settings(client):
    assert client.post('/api/tasks', files={'file': ('fake.png', b'not an image', 'image/png')}).status_code == 422
    assert client.post('/api/tasks', files={'file': ('fake.png', b'x', 'image/png')}, data={'options': '{"duration":0}'}).status_code == 422
    stream = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(stream, 'PNG')
    assert client.post('/api/tasks', files={'file': ('tiny.png', stream.getvalue(), 'image/png')}).status_code == 422


def test_external_sites_cannot_submit_local_tasks(client):
    assert client.post('/api/tasks/sample', json={}, headers={'Origin': 'https://example.com'}).status_code == 403
    assert client.get('/api/health', headers={'Host': 'example.com'}).status_code == 403


def test_large_budget_validation():
    from pydantic import ValidationError
    assert Settings(budget=200000, maxEdge=2560).budget == 200000
    assert Settings(preset='fine').maxEdge is None
    with pytest.raises(ValidationError):
        Settings(budget=200001)
