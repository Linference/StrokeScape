import io
import uuid
from concurrent.futures import Future

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import storage
from backend.api import app
from backend.api import Settings


def saved_task(status='done', export_status=None):
    task_id = uuid.uuid4().hex
    directory = storage.task_dir(task_id)
    directory.mkdir()
    storage.create(task_id, 'Delete test', Settings(budget=240).model_dump())
    storage.update(task_id, status=status, stats={'count': 240},
                   export_state={'status': export_status} if export_status else {})
    for name in ('input.png', 'work.json', 'painting.html', 'painting.mp4', 'recording.partial'):
        (directory / name).write_bytes(b'test fixture')
    (directory / 'nested').mkdir()
    (directory / 'nested/cache.bin').write_bytes(b'test cache')
    return task_id, directory


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
    assert Settings(budget=500000, maxEdge=2560).budget == 500000
    assert Settings(budget=200001).budget == 200001
    assert Settings(preset='fine').maxEdge is None
    with pytest.raises(ValidationError):
        Settings(budget=500001)


def test_delete_removes_only_selected_work_and_all_its_files(client):
    selected, directory = saved_task()
    other, other_directory = saved_task()
    sample = (storage.DATA / 'sample.png').read_bytes()
    assert client.delete('/api/tasks/' + selected).json()['recoverable'] is True
    assert directory.exists() and storage.get(selected)['deleted_at']
    response = client.delete('/api/tasks/' + selected + '/permanent')
    assert response.status_code == 200
    assert response.json() == {'id': selected, 'deleted': True}
    assert not directory.exists()
    assert storage.get(selected) is None
    assert [task['id'] for task in client.get('/api/tasks').json()] == [other]
    assert (other_directory / 'painting.mp4').read_bytes() == b'test fixture'
    assert (storage.DATA / 'sample.png').read_bytes() == sample
    for suffix in ('', '/source', '/work', '/html', '/video'):
        assert client.get('/api/tasks/' + selected + suffix).status_code == 404
    assert client.post('/api/tasks/' + selected + '/retry', json={}).status_code == 404
    assert client.post('/api/tasks/' + selected + '/video', json={}).status_code == 404
    assert client.delete('/api/tasks/' + selected).status_code == 404
    assert client.delete('/api/tasks/not-a-uuid').status_code == 404


@pytest.mark.parametrize('status', ['queued', 'running', 'cancelling'])
def test_delete_rejects_active_generation(client, status):
    task, directory = saved_task(status)
    assert client.delete('/api/tasks/' + task).status_code == 409
    assert storage.get(task) is not None
    assert (directory / 'input.png').exists()
    # Mark idle before lifespan cleanup; no worker was started for this fixture.
    storage.update(task, status='cancelled')


@pytest.mark.parametrize('status', ['queued', 'running'])
def test_delete_rejects_active_export(client, status):
    task, directory = saved_task(export_status=status)
    assert client.delete('/api/tasks/' + task).status_code == 409
    assert (directory / 'painting.mp4').exists()
    storage.update(task, export_state={'status': 'cancelled'})


@pytest.mark.parametrize('status', ['failed', 'cancelled', 'interrupted'])
def test_delete_supports_unfinished_idle_works(client, status):
    task, directory = saved_task(status)
    assert client.delete('/api/tasks/' + task).status_code == 200
    assert directory.exists() and storage.get(task)['deleted_at']
    assert client.post('/api/tasks/' + task + '/restore').status_code == 200
    assert storage.get(task)['deleted_at'] is None


def test_delete_rejects_finishing_worker_then_cleans_future(client, monkeypatch):
    from backend.api import futures
    task, directory = saved_task('cancelled')
    future = Future()
    monkeypatch.setitem(futures, task, future)
    assert client.delete('/api/tasks/' + task).status_code == 409
    future.set_result(None)
    assert client.delete('/api/tasks/' + task).status_code == 200
    assert task not in futures and directory.exists()


def test_delete_can_clean_record_with_missing_directory(client):
    task = uuid.uuid4().hex
    storage.create(task, 'Missing files', Settings().model_dump())
    storage.update(task, status='failed')
    assert client.delete('/api/tasks/' + task).status_code == 200
    assert storage.get(task)['deleted_at']


def test_delete_file_error_keeps_metadata_for_retry(client, monkeypatch):
    task, directory = saved_task()
    def locked(_):
        raise PermissionError('File in use')
    storage.trash_task(task)
    monkeypatch.setattr(storage.shutil, 'rmtree', locked)
    response = client.delete('/api/tasks/' + task + '/permanent')
    assert response.status_code == 409
    assert storage.get(task) is not None
    assert (directory / 'input.png').exists()


def test_delete_refuses_resolved_path_outside_data_directory(client, monkeypatch):
    task, directory = saved_task()
    outside = storage.DATA.parent / ('outside-' + uuid.uuid4().hex)
    outside.mkdir()
    (outside / 'keep.txt').write_text('keep', encoding='utf-8')
    storage.trash_task(task)
    monkeypatch.setattr(storage, 'task_dir', lambda _: outside)
    assert client.delete('/api/tasks/' + task + '/permanent').status_code == 409
    assert (outside / 'keep.txt').read_text(encoding='utf-8') == 'keep'
    assert storage.get(task) is not None and directory.exists()
