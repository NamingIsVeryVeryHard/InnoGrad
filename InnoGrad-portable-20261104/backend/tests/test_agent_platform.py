import subprocess
import sys
import time
from pathlib import Path
import pytest
from app.agent_client import AgentClient
from app.agent_contracts import AgentExecution, AgentFailure


def client(tmp_path):
    return AgentClient({'base_url': 'http://127.0.0.1:3107', 'lock_root': str(tmp_path)})


def test_agent_slot_times_out_across_processes_then_recovers(tmp_path):
    script = '''
import sys,time
from app.agent_client import AgentClient
from app.agent_contracts import AgentExecution
c=AgentClient({'base_url':'http://localhost:3107','lock_root':sys.argv[1]})
with c._service_slot(AgentExecution(),time.monotonic()+5):
    print('locked',flush=True)
    sys.stdin.readline()
'''
    proc = subprocess.Popen([sys.executable, '-c', script, str(tmp_path)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, cwd=Path(__file__).resolve().parents[1])
    try:
        assert proc.stdout.readline().strip() == 'locked'
        with pytest.raises(AgentFailure, match='AGENT_BUSY'):
            with client(tmp_path)._service_slot(AgentExecution(), time.monotonic()+0.25):
                pytest.fail('another process owns the slot')
        proc.communicate('\n', timeout=5)
        assert proc.returncode == 0
        with client(tmp_path)._service_slot(AgentExecution(), time.monotonic()+2):
            pass
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


def test_agent_slot_is_released_after_business_failure(tmp_path):
    with pytest.raises(RuntimeError):
        with client(tmp_path)._service_slot(AgentExecution(), time.monotonic()+2):
            raise RuntimeError('business failure')
    with client(tmp_path)._service_slot(AgentExecution(), time.monotonic()+2):
        pass


def test_cancelled_queued_agent_does_not_hold_slot(tmp_path):
    with pytest.raises(AgentFailure, match='AGENT_ABORTED'):
        with client(tmp_path)._service_slot(AgentExecution(is_cancelled=lambda: True), time.monotonic()+2):
            pytest.fail('cancelled task must not enter')
    with client(tmp_path)._service_slot(AgentExecution(), time.monotonic()+2):
        pass
