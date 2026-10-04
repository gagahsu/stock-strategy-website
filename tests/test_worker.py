import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from backend import api, worker
from backend.db import Base, put


def test_worker_activity_uses_live_lock_not_leftover_file(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    (tmp_path/'data').mkdir()
    assert worker.active() is False
    path=tmp_path/'data'/'bulk.lock'
    path.write_bytes(b'0')
    with path.open('r+b') as handle:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert worker.active() is True
    assert worker.active() is False


def test_status_does_not_claim_dead_worker_is_cooling_down(tmp_path, monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'worker.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    monkeypatch.setattr(api,'Session',isolated)
    monkeypatch.setattr(worker,'active',lambda:False)
    with isolated.begin() as s:put(s,'bulk','latest',{'status':'cooldown','done':73,'total':2576})
    status=TestClient(api.app).get('/api/status').json()['bulk']
    assert status['status']=='interrupted' and status['active'] is False
    assert status['done']==73


def test_bulk_start_does_not_spawn_duplicate_worker(tmp_path, monkeypatch):
    (tmp_path/'data').mkdir()
    monkeypatch.setattr(api,'ROOT',tmp_path)
    monkeypatch.setattr(worker,'active',lambda:True)
    def forbidden(*args,**kwargs):raise AssertionError('must not spawn')
    monkeypatch.setattr('subprocess.Popen',forbidden)
    response=TestClient(api.app).post('/api/bulk/start')
    assert response.status_code==200 and response.json()['status']=='already_running'
