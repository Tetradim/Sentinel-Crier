import asyncio
import pytest
from crier.relay_maintenance import backup_options, backup_loop

@pytest.mark.parametrize('value',['0','-1','59','invalid'])
def test_invalid_backup_interval_refused(tmp_path,monkeypatch,value):
    monkeypatch.setenv('CRIER_BACKUP_INTERVAL_SECONDS',value)
    with pytest.raises(ValueError): backup_options(tmp_path)

@pytest.mark.parametrize('fail',[False,True])
def test_backup_finishes_and_records_redacted_result_before_shutdown(tmp_path,fail):
    events=[]
    class Ops:
        def record_job(self,name,success): events.append((name,success))
    async def run():
        stop=asyncio.Event()
        loop=asyncio.get_running_loop()
        def create(data,destination,retain):
            loop.call_soon_threadsafe(stop.set)
            if fail: raise ValueError('secret must not appear in results')
        await backup_loop(tmp_path,tmp_path/'backup',60,7,stop,Ops(),create)
    asyncio.run(run())
    assert events==[('backup',not fail)]
