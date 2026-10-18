"""Publication supports either visibility while protecting published versions."""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from scripts import release


class ReleasePublicationTests(unittest.TestCase):
    def run_publication(self, private, existing=False, mismatch=False, brand='StarBridge'):
        calls = []
        repo = 'AlancoSage/StarBridge'
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / f'{brand}-Windows-1.2.3.zip'
            asset.write_bytes(b'checked release content')
            checksum = hashlib.sha256(asset.read_bytes()).hexdigest()

            def gh(*args, **kwargs):
                calls.append(args)
                if args == ('api', 'repos/' + repo):
                    value = {'full_name': 'someone/other' if mismatch else repo,
                             'private': private, 'archived': False}
                elif args[0] == 'api' and '/contents/' in args[1]:
                    value = {'content': base64.b64encode(b"__version__ = '1.2.3'\n").decode()}
                elif args[0] == 'api' and '/releases/tags/' in args[1]:
                    if not existing:
                        return CompletedProcess(args, 1, '', '')
                    value = {'id': 42, 'draft': False}
                elif args[:2] == ('api', 'repos/' + repo + '/releases'):
                    payload = json.loads(Path(args[args.index('--input') + 1]).read_text('utf-8'))
                    self.assertTrue(payload['draft'])
                    self.assertEqual(payload['target_commitish'], 'a' * 40)
                    self.assertEqual(payload['name'], brand + ' 1.2.3')
                    value = {'id': 42, 'draft': True}
                elif args[:2] == ('api', 'repos/' + repo + '/releases/42'):
                    value = {'assets': [{'name': asset.name, 'size': asset.stat().st_size,
                                         'digest': 'sha256:' + checksum}]}
                else:
                    value = {}
                return CompletedProcess(args, 0, json.dumps(value), '')

            output = io.StringIO()
            with patch.object(release, 'gh', side_effect=gh), contextlib.redirect_stdout(output):
                if existing or mismatch:
                    with self.assertRaises(ValueError):
                        release.publish('1.2.3', [asset], repo, 'a' * 40, 'notes')
                else:
                    release.publish('1.2.3', [asset], repo, 'a' * 40, 'notes')
                    self.assertEqual(json.loads(output.getvalue())['private'], private)
                    self.assertEqual(sum(args[:2] == ('release', 'upload') for args in calls), 1)
                    self.assertTrue(any(args[:2] == ('release', 'edit') and '--draft=false' in args for args in calls))
        return calls

    def test_public_and_private_repositories_publish_checked_drafts(self):
        for private in (False, True):
            with self.subTest(private=private):
                self.run_publication(private)

    def test_release_title_uses_vexbot_and_supports_historical_checkouts(self):
        for brand in ('VexBot', 'Myrinbot', 'AetherBot', 'StarBridge'):
            with self.subTest(brand=brand):
                self.run_publication(False, brand=brand)

    def test_published_versions_cannot_be_overwritten_in_either_visibility(self):
        for private in (False, True):
            with self.subTest(private=private):
                calls = self.run_publication(private, existing=True)
                self.assertFalse(any(args[0] == 'release' or '--method' in args for args in calls))

    def test_repository_mismatch_is_rejected_before_reading_source_or_uploading(self):
        calls = self.run_publication(False, mismatch=True)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
