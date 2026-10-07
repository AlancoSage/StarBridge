from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid
import zipfile

from scripts import update_runtime as runtime
from starbridge.updates import extract_package, https_url, Updates
from starbridge.registration import RegistrationError


def package(base, version='0.6.1', main='pass', extra=None):
    folder=base/'package';folder.mkdir(parents=True,exist_ok=True)
    files={'starbridge/__init__.py':'__version__='+repr(version)+'\n','starbridge/__main__.py':main,
           'starbridge/app.py':'# isolated fixture\n','requirements.lock.txt':'# no dependencies\n'} | (extra or {})
    for name,content in files.items():runtime.atomic(runtime.safe(folder,name),content.encode())
    manifest={'format':'starbridge-update-v1','protocol':1,'version':version,'files':{name:runtime.sha(folder/name) for name in files}}
    runtime.write_json(folder/'update.json',manifest);return folder,manifest


class UpdatePackageTests(unittest.TestCase):
    def test_safe_archive_paths_hashes_case_collisions_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);folder,manifest=package(base)
            def archive(extra=None,alter=None):
                output=io.BytesIO()
                with zipfile.ZipFile(output,'w') as z:
                    for path in folder.rglob('*'):
                        if path.is_file():z.writestr('StarBridge/'+path.relative_to(folder).as_posix(),alter.get(path.relative_to(folder).as_posix(),path.read_bytes()) if alter else path.read_bytes())
                    for name,value in (extra or {}).items():z.writestr(name,value)
                output.seek(0);return output
            self.assertEqual(extract_package(archive(),base/'valid')['version'],'0.6.1')
            cases=[{'StarBridge/../escape.py':'bad'},{'StarBridge/starbridge/APP.py':'collision'},{'StarBridge/config.toml':'secret'}, {'StarBridge/.runtime/hack.py':'bad'}]
            for index,extra in enumerate(cases):
                with self.subTest(extra=extra),self.assertRaises(ValueError):extract_package(archive(extra),base/('invalid'+str(index)))
            with self.assertRaises(ValueError):extract_package(archive(alter={'starbridge/app.py':b'changed'}),base/'tampered')
            runtime.atomic(folder/'starbridge/__init__.py',b"__version__='0.6.2'\n");manifest['files']['starbridge/__init__.py']=runtime.sha(folder/'starbridge/__init__.py');runtime.write_json(folder/'update.json',manifest)
            with self.assertRaises(ValueError):extract_package(archive(),base/'wrong-version')
            self.assertFalse((base/'escape.py').exists())

    def test_update_urls_and_protected_bootstrap(self):
        for value in ('http://example.com/file','https://user:pass@example.com/update.json','https://example.com/#a',None):
            with self.assertRaises(RegistrationError):https_url(value)
        self.assertEqual(https_url('https://example.com/update.json'),'https://example.com/update.json')
        self.assertFalse(runtime.managed('scripts/update_runtime.py'))


class OfflineUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.config=self.root/'config.toml'
        self.config.write_text('[app]\ndatabase="data/test.db"\n',encoding='utf-8')
        self.db=self.root/'data/test.db';self.db.parent.mkdir()
        with closing(sqlite3.connect(self.db)) as db, db:db.execute('CREATE TABLE sample(value TEXT)');db.execute("INSERT INTO sample VALUES('before')")
        runtime.atomic(self.root/'starbridge/__init__.py',b"__version__='0.6.0'\n")
        runtime.atomic(self.root/'starbridge/old.py',b'# removed during upgrade\n')
        runtime.atomic(self.root/'scripts/update_runtime.py',Path(runtime.__file__).read_bytes())

    def tearDown(self):self.tmp.cleanup()

    def prepare(self, main='pass'):
        rid=uuid.uuid4().hex;stage=runtime.folder(self.root,rid);stage.mkdir(parents=True)
        package(stage,main=main)
        job={'id':rid,'phase':'pending','mode':'update','version':'0.6.1','previous_version':'0.6.0','created':time.time(),'previous_runtime':'','safety_backup':'test'}
        runtime.write_json(stage/'job-metadata.json',job);runtime.write_json(runtime.job_path(self.root),job);return job

    def sample(self):
        with closing(sqlite3.connect(self.db)) as db, db:return db.execute('SELECT value FROM sample').fetchone()[0]

    def test_switch_and_user_requested_rollback_restore_code_and_data(self):
        job=self.prepare();applied=runtime.apply_pending(self.root,self.config)
        self.assertEqual(applied['phase'],'applied');self.assertFalse((self.root/'starbridge/old.py').exists())
        self.assertEqual((self.root/'scripts/update_runtime.py').read_bytes(),Path(runtime.__file__).read_bytes())
        runtime.finish(self.root,applied)
        with closing(sqlite3.connect(self.db)) as db, db:db.execute("UPDATE sample SET value='after'")
        rollback_id=uuid.uuid4().hex;stage=runtime.folder(self.root,rollback_id);stage.mkdir()
        rollback={'id':rollback_id,'source':job['id'],'mode':'rollback','phase':'pending','version':'0.6.0','previous_version':'0.6.1','created':time.time(),'previous_runtime':'','safety_backup':'test'}
        runtime.write_json(stage/'job-metadata.json',rollback);runtime.write_json(runtime.job_path(self.root),rollback)
        done=runtime.apply_pending(self.root,self.config);self.assertEqual(self.sample(),'before');self.assertTrue((self.root/'starbridge/old.py').exists())
        runtime.finish(self.root,done);self.assertFalse(runtime.job_path(self.root).exists())
        self.assertEqual(runtime.read_json(self.root/'.runtime/updates/history.json')[-1]['mode'],'rollback')

    def test_interrupted_switch_is_recovered_before_next_start(self):
        job=self.prepare();runtime.apply_pending(self.root,self.config)
        with closing(sqlite3.connect(self.db)) as db, db:db.execute("UPDATE sample SET value='incomplete'")
        self.assertIsNone(runtime.apply_pending(self.root,self.config));self.assertEqual(self.sample(),'before')
        self.assertIn('0.6.0',(self.root/'starbridge/__init__.py').read_text())
        self.assertEqual(runtime.read_json(self.root/'.runtime/updates/history.json')[-1]['status'],'rolled_back')

    def test_write_failure_restores_old_code_and_allows_restart(self):
        job=self.prepare();original=runtime.atomic
        failed=False
        def fail_once(path,content):
            nonlocal failed
            if path==self.root/'starbridge/app.py' and not failed:failed=True;raise OSError('disk failure')
            return original(path,content)
        with patch.object(runtime,'atomic',side_effect=fail_once):self.assertIsNone(runtime.apply_pending(self.root,self.config))
        self.assertTrue((self.root/'starbridge/old.py').exists());self.assertEqual(self.sample(),'before');self.assertFalse(runtime.job_path(self.root).exists())

    def test_empty_old_runtime_uses_base_python_not_new_environment(self):
        job=self.prepare();rid=uuid.uuid4().hex;runtime.write_json(self.root/'.runtime/updates/runtime.json',{'stage':rid})
        self.assertEqual(runtime.runtime_python(self.root,{'id':uuid.uuid4().hex,'source':job['id'],'mode':'rollback'}),sys.executable)

    def test_second_supervisor_cannot_modify_a_live_installation(self):
        handle=runtime.supervisor_lock(self.root)
        try:
            with self.assertRaises(OSError):runtime.supervisor_lock(self.root)
        finally:handle.close()
        runtime.supervisor_lock(self.root).close()

    def test_supervisor_confirms_success_and_recovers_failed_boot_on_windows(self):
        # A tiny stdlib-only service exercises real process creation, ready nonces and Windows job cleanup.
        ready_main='''import os,json,pathlib,sys
root=pathlib.Path.cwd()
p=root/'.runtime/updates/ready.json'
p.write_text(json.dumps({'pid':os.getpid(),'nonce':os.environ['STARBRIDGE_READY_NONCE']}))
import time;time.sleep(.4)
'''
        runtime.atomic(self.root/'starbridge/__main__.py',ready_main.encode())
        helper=Path(runtime.__file__).resolve()
        invoke='from scripts.update_runtime import supervise; import sys; raise SystemExit(supervise(sys.argv[1],sys.argv[2]))'
        env=os.environ|{'PYTHONPATH':str(helper.parent.parent)}
        for fail in (False,True):
            if not (self.root/'starbridge/__main__.py').exists():runtime.atomic(self.root/'starbridge/__main__.py',ready_main.encode())
            job=self.prepare('raise RuntimeError("startup failure")' if fail else ready_main)
            process=subprocess.run([sys.executable,'-c',invoke,str(self.config),str(self.root)],cwd=self.root,env=env,capture_output=True,timeout=20)
            self.assertEqual(process.returncode,0,process.stderr.decode(errors='replace'))
            history=runtime.read_json(self.root/'.runtime/updates/history.json')[-1]
            self.assertEqual(history['status'],'rolled_back' if fail else 'success',process.stderr.decode(errors='replace'))
            self.assertFalse(runtime.job_path(self.root).exists())


if __name__=='__main__':unittest.main()
