"""The website must build and run after copying it out of the Bot workspace."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import urlopen
from urllib.error import HTTPError
import zipfile
import importlib.util
from http.server import ThreadingHTTPServer


class IndependentWebsiteTests(unittest.TestCase):
    def test_copied_project_builds_and_serves_without_bot_files(self):
        source=Path(__file__).resolve().parent.parent/'starbridge-website'
        with tempfile.TemporaryDirectory() as directory:
            project=Path(directory)/'website'
            shutil.copytree(source,project,ignore=shutil.ignore_patterns('dist','__pycache__','.local'))
            original=(project/'config.json').read_bytes()
            result=subprocess.run([sys.executable,str(project/'build.py'),'--api-base','https://bridge.example.com/api/v1'],cwd=project,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            with zipfile.ZipFile(project/'dist/Myrinbot-website.zip') as archive:
                self.assertEqual(json.loads(archive.read('config.json')),{'apiBase':'https://bridge.example.com/api/v1'})
                for name in ('serve.py','build.py','start.ps1','LICENSE','docs/account-api.md','sdk/starbridge.js'):
                    self.assertIn(name,archive.namelist())
                self.assertEqual(archive.read('LICENSE'), (source.parent/'LICENSE').read_bytes())
                self.assertFalse(any(name.endswith(('.db','.toml','.log')) or '__pycache__' in name for name in archive.namelist()))
            self.assertEqual((project/'config.json').read_bytes(),original)
            spec=importlib.util.spec_from_file_location('independent_site',project/'serve.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            server=ThreadingHTTPServer(('127.0.0.1',0),module.handler('http://127.0.0.1:8088/api/v1'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url='http://127.0.0.1:'+str(server.server_port)
            try:
                with urlopen(url+'/config.json',timeout=5) as response:
                    self.assertEqual(json.load(response),{'apiBase':'http://127.0.0.1:8088/api/v1'})
                    self.assertEqual(response.headers['Cache-Control'],'no-cache')
                with urlopen(url+'/',timeout=5) as response:self.assertIn(b'site.js',response.read())
                for path in ('/serve.py','/../config.toml','/sdk/../../config.json','/docs/'):
                    with self.subTest(path=path),self.assertRaises(HTTPError) as error:urlopen(url+path,timeout=5)
                    self.assertEqual(error.exception.code,404)
                    error.exception.close()
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
