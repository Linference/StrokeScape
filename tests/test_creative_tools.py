import io
import json
import zipfile
from concurrent.futures import Future

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import storage
from backend.api import Settings, app
from backend.engine import PAPER, draw_local, paint, schedule


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DATA', tmp_path)
    with TestClient(app) as client:
        yield client


def make_work(tmp_path, budget=240, **options):
    path = tmp_path / 'test.png'
    y, x = np.mgrid[:80, :112]
    Image.fromarray(np.stack((40 + x, 60 + y, 90 + x // 2), axis=-1).astype(np.uint8)).save(path)
    settings = Settings(preset='sketch', budget=budget, duration=15, device='cpu', maxEdge=128, **options).model_dump()
    return path, settings, paint(path, settings, {}, lambda *_: None, lambda: False)


def save_work(path, work):
    import uuid
    import shutil
    task_id = uuid.uuid4().hex
    directory = storage.task_dir(task_id)
    directory.mkdir()
    shutil.copyfile(path, directory / 'input.png')
    (directory / 'work.json').write_text(json.dumps(work), encoding='utf-8')
    storage.create(task_id, '原作品', work['settings'])
    storage.update(task_id, status='done', stats=work['stats'], tags=['测试', '风景'])
    return task_id


def raster(work):
    paper=[int(work['paper'][v:v+2],16) for v in (1,3,5)]
    canvas = np.full((work['height'], work['width'], 3), paper, np.uint8)
    for i, s in enumerate(work['strokes']):
        color = [int(s['c'][v:v+2], 16) for v in (1, 3, 5)]
        draw_local(canvas, s['p'], color, s['w'], s['o'], s.get('b',work['settings'].get('brush','classic')),
                   i, s.get('seed',work['settings']['seed']), s.get('tx',work['settings'].get('texture',1)),
                   s.get('g',work['settings'].get('gaps',1)), s.get('clip'))
    return canvas


def test_refinement_preserves_outside_and_original_brush(tmp_path):
    path, settings, original = make_work(tmp_path, brush='dry', texture=1.4, gaps=1.8)
    before = json.dumps(original)
    refined = paint(path, settings | {'budget': 200, 'brush':'watercolor', 'texture':.3, 'gaps':0}, {},
                    lambda *_: None, lambda: False, base=original, region=[25,20,35,28])
    assert json.dumps(original) == before
    assert len(refined['strokes']) == 440
    assert all(s['clip'] == [25,20,35,28] for s in refined['strokes'][240:])
    left, right = raster(original), raster(refined)
    mask = np.ones(left.shape[:2], bool)
    mask[20:48,25:60] = False
    np.testing.assert_array_equal(left[mask], right[mask])
    assert np.any(left[~mask] != right[~mask])
    assert refined['durationMs'] == 15000
    assert all(a['s']+a['dt'] <= b['s']+1e-7 for a,b in zip(refined['strokes'],refined['strokes'][1:]))


def test_adaptive_stop_reduces_uniform_image_budget(tmp_path):
    path = tmp_path / 'paper.png'
    Image.new('RGB',(64,64),tuple(PAPER)).save(path)
    settings = Settings(budget=4000, maxEdge=128, device='cpu', adaptiveStop=True).model_dump()
    frames=[]
    work=paint(path,settings,{},lambda *_:None,lambda:False,preview=lambda image,count:frames.append((image.copy(),count)))
    assert work['stats']['stoppedEarly']
    assert len(work['strokes']) < 4000
    assert frames and frames[-1][1] == len(work['strokes'])
    assert work['stats']['mae'] == 0
    assert work['durationMs'] == settings['duration']*1000


def test_refinement_preserves_imported_paper_color(tmp_path):
    path, settings, original = make_work(tmp_path)
    original['paper']='#ddeeff'
    refined=paint(path,settings|{'budget':200},{},lambda *_:None,lambda:False,base=original,region=[20,20,20,20])
    assert refined['paper']=='#ddeeff'
    before,after=raster(original),raster(refined)
    np.testing.assert_array_equal(before[:20],after[:20])


def test_storage_migrates_existing_library_without_losing_metadata(tmp_path,monkeypatch):
    import sqlite3
    monkeypatch.setattr(storage,'DATA',tmp_path)
    with sqlite3.connect(tmp_path/'studio.sqlite3') as db:
        db.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,status TEXT,progress REAL,stage TEXT,settings TEXT,stats TEXT,error TEXT,export_state TEXT)")
        db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)",('a'*32,'历史作品','2026-10-22','done',1,'完成','{}','{}',None,'{}'))
    storage.init()
    task=storage.get('a'*32)
    assert task['title']=='历史作品' and task['tags']==[] and task['deleted_at'] is None
    assert len(storage.all_tasks())==1


def test_natural_order_reduces_jump_and_parameters_change_output(tmp_path):
    path, settings, local = make_work(tmp_path,budget=1600,naturalOrder=True)
    global_work=paint(path,settings|{'naturalOrder':False},{},lambda *_:None,lambda:False)
    assert local['stats']['meanJump'] < global_work['stats']['meanJump']*.8
    changed=paint(path,settings|{'brushScale':2,'opacityScale':.4},{},lambda *_:None,lambda:False)
    assert changed['strokes'][0]['w'] == pytest.approx(local['strokes'][0]['w']*2,abs=.02)
    assert changed['strokes'][0]['o'] < local['strokes'][0]['o']


def test_single_layer_schedule_ends_exactly():
    strokes=[{'p':[0,0,3,3],'l':3} for _ in range(200)]
    schedule(strokes,15000)
    assert strokes[0]['s']==0
    assert strokes[-1]['s']+strokes[-1]['dt']==pytest.approx(15000)


def test_renderer_clips_refinement_and_restores_context():
    import shutil
    import subprocess
    node=shutil.which('node')
    if not node:pytest.skip('Node.js needed for renderer check')
    script="""const fs=require('fs'),vm=require('vm');vm.runInThisContext(fs.readFileSync('public/renderer.js','utf8'));
const r=Object.create(StrokeRenderer.prototype);r.brush='classic';r.seed=42;
r.work={settings:{texture:1,gaps:1},strokes:[{p:[1,1,30,30],c:'#123456',w:4,o:.9,b:'pointillism',clip:[10,10,8,9]}]};r.lengths=[[0,Math.hypot(29,29)]];
let calls=[];const ctx={save(){calls.push('save')},restore(){calls.push('restore')},beginPath(){},rect(...v){calls.push(v)},clip(){calls.push('clip')},arc(){},fill(){}};
r.draw(ctx,0);console.log(JSON.stringify(calls));"""
    result=subprocess.run([node,'-e',script],check=True,capture_output=True,text=True)
    assert json.loads(result.stdout)==['save',[10,10,8,9],'clip','restore']


def test_recycle_restore_metadata_project_roundtrip(client,tmp_path):
    path,settings,work=make_work(tmp_path)
    task=save_work(path,work)
    patched=client.patch('/api/tasks/'+task,json={'title':'新的名字','tags':['山水','风景','山水']})
    assert patched.status_code==200
    assert patched.json()['tags']==['山水','风景']
    assert client.patch('/api/tasks/'+task,json={'title':'   ','tags':[]}).status_code==422
    assert client.delete('/api/tasks/'+task+'/permanent').status_code==409
    assert client.delete('/api/tasks/'+task).json()['recoverable']
    assert client.get('/api/tasks').json()==[]
    assert client.get('/api/tasks?trash=true').json()[0]['id']==task
    assert client.get('/api/tasks/'+task+'/work').status_code==404
    assert client.get('/api/tasks/'+task+'/source').status_code==200
    assert client.post('/api/tasks/'+task+'/restore').status_code==200
    archive=client.get('/api/tasks/'+task+'/project')
    assert archive.status_code==200
    result=client.post('/api/projects/import',files={'file':('test.strokescape',archive.content,'application/zip')})
    assert result.status_code==200,result.text
    imported=result.json()
    assert imported['id']!=task and imported['title']=='新的名字' and imported['tags']==['山水','风景']
    again=client.get('/api/tasks/'+imported['id']+'/work').json()
    assert again['strokes']==work['strokes']
    assert client.get('/api/tasks/'+imported['id']+'/html').status_code==200


def test_project_repeated_download_with_windows_read_handle(client,tmp_path):
    path,settings,work=make_work(tmp_path)
    task=save_work(path,work)
    url='/api/tasks/'+task+'/project'
    first=client.get(url)
    archive_path=next(storage.task_dir(task).glob('project-*.strokescape'))
    with archive_path.open('rb') as held:
        assert client.get(url).content==first.content
        assert client.patch('/api/tasks/'+task,json={'title':'另一个名字','tags':['新标签']}).status_code==200
        second=client.get(url)
        assert second.status_code==200
        with zipfile.ZipFile(io.BytesIO(second.content)) as archive:
            assert json.loads(archive.read('manifest.json'))['title']=='另一个名字'
        assert held.read()==first.content


@pytest.mark.parametrize('attack',['path','nan','overlap','clip','zip','version','size'])
def test_project_import_rejects_invalid_archives(client,tmp_path,attack):
    path,settings,work=make_work(tmp_path)
    manifest={'format':'StrokeScape','version':1,'title':'test','tags':[]}
    if attack=='nan':work['strokes'][0]['p'][0]=float('nan')
    if attack=='overlap':work['strokes'][1]['s']=0
    if attack=='clip':work['strokes'][0]['clip']=[-1,0,100,100]
    if attack=='version':manifest['version']=999
    if attack=='size':work['width']=100000
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('manifest.json',json.dumps(manifest))
        z.writestr('work.json',json.dumps(work))
        z.writestr('input.png',path.read_bytes())
        if attack=='path':z.writestr('../outside.txt','malicious')
    data=b'bad zip' if attack=='zip' else stream.getvalue()
    assert client.post('/api/projects/import',files={'file':('test.strokescape',data)}).status_code==422
    assert client.get('/api/tasks').json()==[]


def test_refine_api_snapshots_parent_validates_region_and_budget(client,tmp_path,monkeypatch):
    import backend.api as module
    path,settings,work=make_work(tmp_path)
    task=save_work(path,work)
    class Pool:
        def submit(self,*_):return Future()
        def shutdown(self,**_):pass
    monkeypatch.setattr(module,'pool',Pool())
    monkeypatch.setattr(module,'capabilities',lambda:{'cuda':{'available':False}})
    url='/api/tasks/'+task+'/refine'
    assert client.post(url,json={'region':[-1,0,30,30],'budget':200,'settings':settings}).status_code==422
    response=client.post(url,json={'region':[0,0,30,30],'budget':200,'settings':settings})
    assert response.status_code==200,response.text
    new=response.json()
    assert new['id']!=task and new['tags']==['测试','风景']
    assert (storage.task_dir(new['id'])/'base.json').is_file()
    assert client.delete('/api/tasks/'+new['id']).status_code==409
    storage.update(new['id'],status='cancelled')
    module.futures.pop(new['id']).cancel()
    oversized=dict(work);oversized['strokes']=[work['strokes'][0]]*499900
    (storage.task_dir(task)/'work.json').write_text(json.dumps(oversized),encoding='utf-8')
    assert client.post(url,json={'region':[0,0,30,30],'budget':200,'settings':settings}).status_code==422
