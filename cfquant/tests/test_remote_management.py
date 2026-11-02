"""Remote agent checks: temporary state, no real QMT or service termination."""
import json
import os
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cfquant import remote_management as rm, remote_adapter as adapter, remote_supervisor as supervisor
from cfquant.tests.test_qmt_strategy_web import web_config
from official_site.tests.test_downloads import running_site


@pytest.fixture
def crypto(monkeypatch):
    # Opaque fixture encryption; the actual Windows DPAPI path is tested separately.
    values={}
    def protect(value, entropy):
        token=secrets.token_bytes(32);values[(token,entropy)]=value;return token
    monkeypatch.setattr(rm,'_protect',protect)
    monkeypatch.setattr(rm,'_unprotect',lambda value,entropy:values[(value,entropy)])


@pytest.fixture
def agent(tmp_path, crypto):
    result=rm.RemoteAgent(tmp_path/'web.json')
    result.store.update(enabled=True,api_key='synthetic-key',instance_id='fixture',device_id='fixture-device',
        local_token='synthetic-local-token',site_url='https://cfquant.org',local_url='http://127.0.0.1:1',
        permissions={'queries':True,'service_control':True,'qmt_control':True})
    result.session_id='s1'
    result.cloud=Mock(return_value={'started':True})
    result.local=Mock(return_value={'rows':[{'stock_code':'fixture'}]})
    return result


def task(action='positions', state='queued'):
    return dict(id='test-task',action=action,payload={'binding_id':'binding'},session_id='s1',state=state,expires=9999999999,boot_id='b1')


def test_disabled_is_default_and_never_starts_agent(tmp_path,monkeypatch):
    popen=Mock();monkeypatch.setattr(rm.subprocess,'Popen',popen)
    path=tmp_path/'web.json'
    assert rm.Config(path).read()['enabled'] is False
    assert rm.ensure_agent(path)=={'started':False}
    popen.assert_not_called()


def test_secrets_not_returned_and_config_is_per_deployment(agent):
    text=agent.store.path.read_text()
    assert 'synthetic-key' not in text and 'synthetic-local-token' not in text
    public=rm.local_info(agent.store.web_config)
    assert 'api_key' not in public and 'local_token' not in public
    assert rm.Config(agent.store.web_config.with_name('other.json')).read()['enabled'] is False
    assert agent.store.read()['api_key']=='synthetic-key'


@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI')
def test_windows_dpapi_roundtrip_and_ciphertext(tmp_path):
    pytest.importorskip('win32crypt')
    config=rm.Config(tmp_path/'native.json');config.update(enabled=True,api_key='synthetic-native-secret')
    assert config.read()['api_key']=='synthetic-native-secret'
    assert 'synthetic-native-secret' not in config.path.read_text()


def test_os_lock_excludes_second_agent_and_releases(tmp_path):
    path=tmp_path/'agent.lock'
    with rm.file_lock(path):
        with pytest.raises(rm.RemoteError,match='已有任务'):
            with rm.file_lock(path): pass
    with rm.file_lock(path): pass
    assert path.stat().st_size==1


def test_duplicate_delivery_replays_result_without_querying_again(agent):
    agent.run_task(task())
    agent.run_task(task(state='running'))
    assert agent.local.call_count==1
    assert agent.cloud.call_args.args[1]['state']=='succeeded'


@pytest.mark.parametrize('saved,cloud_state',[('prepared','queued'),('prepared','running'),('started','running'),(None,'running')])
def test_interrupted_task_never_repeats_side_effect(agent,saved,cloud_state):
    if saved: agent.save_task('test-task',saved)
    agent.run_task(task('restart_cfquant',cloud_state))
    agent.local.assert_not_called()
    assert agent.cloud.call_args.args[1]['state']=='outcome_unknown'


def test_lost_result_ack_does_not_repeat_restart(agent):
    agent.service_action=Mock(return_value={'state':'running'})
    def cloud(op, body=None):
        if op.endswith('/result'): raise rm.RemoteError('connection_failed','lost ack')
        return {'started':True}
    agent.cloud=Mock(side_effect=cloud)
    agent.run_task(task('restart_cfquant'))
    agent.run_task(task('restart_cfquant','running'))
    assert agent.service_action.call_count==1
    assert agent.cloud.call_count==3


def test_local_permission_revocation_blocks_execution(agent):
    agent.store.update(permissions={})
    agent.run_task(task())
    agent.local.assert_not_called();agent.cloud.assert_not_called()


def test_snapshot_does_not_claim_service_online_when_agent_is_online(agent):
    agent.local.side_effect=rm.RemoteError('connection_failed','offline')
    snap=agent.snapshot()
    assert snap['service_state']=='unavailable'
    assert snap['capabilities']==['start_cfquant']
    agent.store.update(desired_state='stopped')
    assert agent.snapshot()['service_state']=='stopped'


@pytest.mark.parametrize('value',['http://example.com','https://example.com/evil','https://u:p@example.com','file:///tmp'])
def test_credential_endpoint_requires_https_and_fixed_origin(monkeypatch,value):
    monkeypatch.setenv('CFQUANT_REMOTE_SITE_URL',value)
    with pytest.raises(rm.RemoteError): rm.site_url()


def test_query_filters_secrets_and_refuses_partial_results(web_config,crypto,monkeypatch):
    web,config=web_config
    rm.Config(config.path).update(enabled=True,permissions={'queries':True})
    row=dict(account_key='a',account_id='private-account',account_type='STOCK',bridge_id='bridge')
    monkeypatch.setattr(adapter,'bindings',lambda w:([{'id':'binding'}],{'binding':row}))
    source={'orders':{'ok':True,'data':[{'stock_code':'TEST','order_status':55,'account_id':'private-account','password':'never-upload'}],'checked_at':1}}
    monkeypatch.setattr(web.ACCOUNT_CACHE,'get_market_routed',lambda *a,**k:source)
    body=dict(action='orders',binding_id='binding',boot_id=web.MANAGEMENT_BOOT_ID)
    result=adapter.handle(web,'query',body)
    assert result['rows']==[{'stock_code':'TEST','order_status':55}]
    source['orders']['partial_errors']=['one market failed']
    with pytest.raises(rm.RemoteError,match='QMT 查询失败'): adapter.handle(web,'query',body)


def test_query_dataframe_pagination(web_config,crypto,monkeypatch):
    import pandas as pd
    web,config=web_config
    rm.Config(config.path).update(enabled=True,permissions={'queries':True})
    row=dict(account_key='a',account_id='1',account_type='STOCK',bridge_id='b')
    monkeypatch.setattr(adapter,'bindings',lambda w:([{'id':'binding'}],{'binding':row}))
    monkeypatch.setattr(web.ACCOUNT_CACHE,'get_market_routed',lambda *a,**k:{'positions':{'ok':True,'data':pd.DataFrame([{'stock_code':'A'},{'stock_code':'B'}])}})
    body=dict(action='positions',binding_id='binding',boot_id=web.MANAGEMENT_BOOT_ID,page=2,page_size=1)
    result=adapter.handle(web,'query',body)
    assert result['rows']==[{'stock_code':'B'}] and not result['has_more']


def test_shared_qmt_aliases_are_rejected_before_restart(web_config,crypto,monkeypatch,tmp_path):
    web,config=web_config
    qmt=tmp_path/'QMT'
    config._data['account_configs']={'a':{'account_id':'1001','qmt_dir':str(qmt/'bin.x64')}}
    folder=tmp_path/'registry';monkeypatch.setattr(adapter,'registry_dir',lambda:folder)
    monkeypatch.setattr(adapter,'same_process',lambda identity:True)
    rm.atomic_json(folder/'other.json',{'config':'another-deployment','process':{'pid':123},'qmt_dirs':[adapter.directory_key(qmt/'python')]})
    with pytest.raises(rm.RemoteError,match='共用'): adapter.check_conflicts(web,str(qmt))


def test_supervisor_refuses_changed_pid_before_stopping(agent,monkeypatch):
    agent.store.update(launch={'port':8765})
    local=Mock(return_value={'boot_id':'b1','processes':[{'pid':123}]})
    monkeypatch.setattr(supervisor,'same_process',lambda p:False)
    with pytest.raises(rm.RemoteError,match='进程身份'): supervisor.Supervisor(agent.store,local).execute(task('stop_cfquant'))
    assert [c.args[0] for c in local.call_args_list]==['service-plan']


def test_supervisor_stops_only_recorded_dependencies_and_keeps_agent(agent,monkeypatch):
    agent.store.update(launch={'port':8765})
    identities=[{'pid':p} for p in [111,222]]
    local=Mock(return_value={'boot_id':'b1','processes':identities})
    process=Mock();monkeypatch.setattr(supervisor.psutil,'Process',process)
    monkeypatch.setattr(supervisor,'same_process',lambda p:True)
    manager=supervisor.Supervisor(agent.store,local);manager.wait_exit=Mock()
    assert manager.execute(task('stop_cfquant'))=={'state':'stopped','qmt_preserved':True}
    process.assert_called_once_with(222);process.return_value.terminate.assert_called_once()
    assert agent.store.read()['desired_state']=='stopped'


@pytest.fixture
def local_http(web_config,crypto,monkeypatch):
    web,config=web_config
    config._data['api_key']='synthetic-local-api-key'
    monkeypatch.setattr(web,'MANAGEMENT_READY',True)
    monkeypatch.setattr(web,'binding_status_snapshot',lambda:{'bindings':[]})
    monkeypatch.setattr(adapter,'ensure_agent',lambda path:{'started':False})
    class Handler(web.CfquantWebHandler):
        def log_message(self,*a): pass
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(web,'WEB_BOUND_PORT',http.server_port)
    monkeypatch.setattr(web,'WEB_BOUND_HOST','127.0.0.1')
    def request(path,body=None,headers=None):
        connection=HTTPConnection(*http.server_address,timeout=20)
        values={'Content-Type':'application/json'};values.update(headers or {})
        try:
            connection.request('POST' if body is not None else 'GET',path,body=json.dumps(body) if body is not None else None,headers=values)
            response=connection.getresponse();return response.status,json.loads(response.read().decode('utf-8'))
        finally: connection.close()
    yield SimpleNamespace(web=web,config=config,request=request,url='http://127.0.0.1:'+str(http.server_port))
    http.shutdown();http.server_close();thread.join(5)


def test_agent_endpoint_requires_its_own_token_even_when_web_auth_disabled(local_http):
    s=local_http
    rm.Config(s.config.path).update(enabled=True,local_token='synthetic-agent',instance_id='test',permissions={})
    path='/api/remote-agent/snapshot'
    assert s.request(path)[0]==401
    assert s.request(path,headers={'X-API-Key':'synthetic-local-api-key'})[0]==401
    status,data=s.request(path,headers={'X-CFQuant-Agent-Key':'synthetic-agent'})
    assert status==200 and data['data']['snapshot']['service_state']=='running'
    assert s.request('/api/remote-agent/service-stop',{},headers={'X-CFQuant-Agent-Key':'synthetic-agent'})[1]['code']=='permission_denied'


def test_configuration_rejects_cross_origin(local_http):
    s=local_http
    assert s.request('/api/remote-management',{'enabled':False},headers={'X-API-Key':'synthetic-local-api-key','Origin':'http://localhost:9999'})[0]==400


def test_project_sdk_exposes_remote_configuration_without_secret_persistence():
    from cfquant.management import RuntimeManager
    runtime=RuntimeManager();runtime._request=Mock(return_value={'enabled':True})
    runtime.remote.configure(api_key='synthetic-project-key',permissions={'queries':True})
    args=runtime._request.call_args.args
    assert args[0:2]==('POST','/api/remote-management')
    assert args[2]['api_key']=='synthetic-project-key'
    assert 'synthetic' not in repr(runtime.__dict__)
    runtime._request.reset_mock()
    with pytest.raises(TypeError):
        runtime.remote.configure(account='fixture',password='synthetic')
    runtime._request.assert_not_called()


def test_http_end_to_end_website_key_query_and_control(local_http,running_site,monkeypatch):
    s=running_site;local=local_http
    status,created=s.request(rm.PREFIX+'/instances','POST',token=s.ordinary,body=dict(name='End to end',enrollment_id='website-created',permissions={v:True for v in rm.ACTIONS.values()}))
    assert status==200,created
    monkeypatch.setenv('CFQUANT_REMOTE_SITE_URL',s.url)
    binding=dict(id='binding',name='Fixture',account_masked='***1001',enabled=True,revision='r1',affected_bindings=['binding'])
    row=dict(account_key='a',account_id='private-account',account_type='STOCK',bridge_id='b',qmt_dir='D:/fixture-qmt')
    monkeypatch.setattr(adapter,'bindings',lambda web:([binding],{'binding':row}))
    monkeypatch.setattr(local.web.ACCOUNT_CACHE,'get_market_routed',lambda *a,**k:{'positions':{'ok':True,'data':[{'stock_code':'TEST','volume':100,'account_id':'private-account'}]}})
    status,result=local.request('/api/remote-management',dict(enabled=True,api_key=created['api_key'],permissions={v:True for v in rm.ACTIONS.values()}),headers={'X-API-Key':'synthetic-local-api-key'})
    assert status==200,result
    config=rm.Config(local.config.path).read()
    assert 'password' not in config and 'account' not in config
    assert config['instance_id']==created['instance']['id']
    agent=rm.RemoteAgent(local.config.path)
    assert agent.step()
    iid=config['instance_id'];task_path=rm.PREFIX+'/instances/'+iid+'/tasks'
    def submit(action,payload=None):
        status,data=s.request(task_path,'POST',token=s.ordinary,body=dict(action=action,payload=payload or {},confirm=iid,idempotency_key=secrets.token_hex(16)))
        assert status==200,data
        agent.step();agent.worker.join(10);assert not agent.worker.is_alive()
        return s.request(task_path,token=s.ordinary)[1]['tasks'][0]
    result=submit('positions',{'binding_id':'binding'})
    assert result['state']=='succeeded',result
    assert result['result']['rows']==[{'stock_code':'TEST','volume':100}]
    # Process mutations are substituted, but both HTTP hops and durable delivery are real.
    agent.service_action=Mock(return_value={'state':'running','qmt_preserved':True})
    result=submit('restart_cfquant')
    assert result['state']=='succeeded',result
    agent.service_action.assert_called_once()
    restart=Mock(return_value={'pid':1234})
    monkeypatch.setattr(local.web,'complete_qmt_auto_login',restart)
    monkeypatch.setattr(local.web,'_qmt_auto_login_saved_session',lambda row:{'pid':1234,'state':'logged_in','login_succeeded':True})
    monkeypatch.setattr(adapter,'check_conflicts',lambda *a:None)
    monkeypatch.setattr(adapter,'process_identity',lambda pid:{'pid':pid})
    result=submit('restart_qmt',dict(binding_id='binding',binding_revision='r1',affected_bindings=['binding']))
    assert result['state']=='succeeded',result
    restart.assert_called_once_with({'account_key':'a'})
    assert b'TEST' not in agent.journal.read_bytes()
    local.request('/api/remote-management',{'enabled':False},headers={'X-API-Key':'synthetic-local-api-key'})
    assert agent.step() is False


@pytest.mark.parametrize('body',[{'enabled':True},{'enabled':True,'api_key':'  '},{'enabled':True,'account':'ordinary','password':'synthetic'},{'enabled':True,'api_key':'synthetic-key','password':'synthetic'}])
def test_local_connection_requires_website_key_without_network_or_persistence(local_http,monkeypatch,body):
    network=Mock();monkeypatch.setattr(adapter,'request_json',network)
    _,result=local_http.request('/api/remote-management',body,headers={'X-API-Key':'synthetic-local-api-key'})
    assert result['ok'] is False and result['code']=='api_key_required'
    network.assert_not_called()
    assert not rm.Config(local_http.config.path).path.exists()


def test_existing_key_can_be_reused_and_failed_rotation_keeps_configuration(local_http,monkeypatch):
    web=local_http.web;store=rm.Config(local_http.config.path)
    store.update(enabled=True,api_key='saved-key',instance_id='saved-instance',device_id='device',local_token='token',name='Saved',permissions={'queries':True})
    network=Mock(return_value={'instance':{'id':'saved-instance','name':'Website name','note':'Website note'}})
    monkeypatch.setattr(adapter,'request_json',network)
    adapter.configure(web,{'enabled':True,'permissions':{'queries':False}})
    assert network.call_args.args[0].endswith('/agent/validate')
    assert network.call_args.args[2]['X-CFQuant-Remote-Key']=='saved-key'
    prior=store.read()
    assert prior['name']=='Website name' and prior['permissions']['queries'] is False
    network.side_effect=rm.RemoteError('credential_revoked','invalid key')
    with pytest.raises(rm.RemoteError): adapter.configure(web,{'enabled':True,'api_key':'bad-replacement'})
    assert store.read()==prior


def test_supervisor_real_isolated_process_stop_start_and_restart(agent,tmp_path,monkeypatch):
    """Exercise actual process exits/startup acknowledgments using only a temp fixture service."""
    entry=tmp_path/'fixture_service.py'
    entry.write_text('''import json, os, sys, threading, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import psutil
boot = uuid.uuid4().hex
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self): self.reply()
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.reply()
    def reply(self):
        p=psutil.Process()
        data={'boot_id':boot,'processes':[{'pid':p.pid,'created':p.create_time(),'exe':p.exe(),'args':p.cmdline()}]} if self.path.endswith(('service-plan','service-stop')) else {'instance_id':'fixture','snapshot':{'boot_id':boot,'service_state':'running'}}
        raw=json.dumps({'ok':True,'data':data}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        if self.path.endswith('service-stop'): threading.Thread(target=self.server.shutdown,daemon=True).start()
server=ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1])),Handler)
server.serve_forever();server.server_close()
''',encoding='utf-8')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    launch={'args':[sys.executable,str(entry),str(port)],'env':{},'port':port,'cwd':str(tmp_path),'resources':{}}
    agent.store.update(launch=launch,local_url='http://127.0.0.1:'+str(port))
    actual=[];popen=subprocess.Popen
    def spawn(*args,**kwargs):
        process=popen(*args,**kwargs);actual.append(process);return process
    monkeypatch.setattr(supervisor.subprocess,'Popen',spawn)
    manager=supervisor.Supervisor(agent.store,rm.RemoteAgent.local.__get__(agent))
    monkeypatch.setattr(manager,'check_start_resources',lambda launch:None)
    try:
        started=manager.execute(dict(task('start_cfquant'),boot_id=''))
        assert started['state']=='running' and actual[-1].poll() is None
        restarted=manager.execute(dict(task('restart_cfquant'),boot_id=started['boot_id']))
        assert restarted['boot_id']!=started['boot_id']
        assert actual[0].poll() is not None and actual[1].poll() is None
        assert manager.execute(dict(task('stop_cfquant'),boot_id=restarted['boot_id']))['state']=='stopped'
        assert actual[1].poll() is not None
        assert all(p.args[1]==str(entry) for p in actual)
    finally:
        for process in actual:
            if process.poll() is None: process.terminate()
            process.wait(timeout=10)
