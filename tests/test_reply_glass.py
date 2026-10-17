import asyncio
from copy import deepcopy
import hashlib
from io import BytesIO
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from PIL import Image

from starbridge.reply_images import MAX_PNG, RenderError, ReplyRenderer, render_pages


def status(players=None, online=True):
    return {'type': 'server_status', 'updated': 1792223400,
            'servers': [{'id': 'test', 'name': '测试生存服', 'online': online,
                         'players': players or [], 'max_players': 20, 'version': '1.21.11'}]}


class GlassReplyTests(unittest.TestCase):
    def images(self, pages):
        self.assertGreater(len(pages), 0)
        self.assertLessEqual(len(pages), 4)
        for page in pages:
            self.assertLessEqual(len(page), MAX_PNG)
            with Image.open(BytesIO(page)) as image:
                self.assertEqual((image.format, image.mode, image.width), ('PNG', 'RGB', 1080))
                self.assertLessEqual(image.height, 1600)

    def test_original_background_is_embedded_and_legacy_updater_managed(self):
        from starbridge.reply_backdrop import BACKDROP_JPEG, SOURCE_ASSET, SOURCE_SHA256
        from scripts.update_runtime import managed
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(hashlib.sha256((root/SOURCE_ASSET).read_bytes()).hexdigest(), SOURCE_SHA256)
        self.assertTrue(managed('starbridge/reply_backdrop.py'))
        with Image.open(BytesIO(BACKDROP_JPEG)) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertGreaterEqual(image.width, 1080)

    def test_bold_font_is_pinned_and_compatible_with_existing_updater(self):
        from PIL import ImageFont
        from scripts.update_runtime import managed
        from starbridge.reply_bold_font import SHA256, font_data
        data = font_data()
        self.assertEqual(hashlib.sha256(data).hexdigest(), SHA256)
        self.assertEqual(ImageFont.truetype(BytesIO(data), 32).getname(), ('Noto Sans SC', 'Bold'))
        self.assertTrue(managed('starbridge/reply_bold_font.py'))

    def test_status_zero_players_offline_and_empty_servers(self):
        for view in [status(), status(['Steve', '张三']), status(['STALE'], False),
                     {'type': 'server_status', 'updated': 0, 'servers': []}]:
            with self.subTest(view=view):
                before = deepcopy(view)
                self.images(render_pages('状态文字', '在线', view))
                self.assertEqual(view, before)
        self.assertEqual(render_pages('状态文字', '在线', status(['STALE'], False)),
                         render_pages('状态文字', '在线', status([], False)))

    def test_players_continue_on_bounded_pages_and_names_fit(self):
        self.images(render_pages('在线玩家', '在线', status(['Player_'+str(n) for n in range(50)])))
        self.images(render_pages('在线玩家', '状态', status(['很长的玩家名称'*12, 'W'*100])))
        with self.assertRaises(RenderError):
            render_pages('在线玩家', '在线', status(['Player_'+str(n) for n in range(200)]))

    def test_invalid_structured_data_fails_before_sending(self):
        values = [{}, {'type': 'unknown'}, status(['\U0001f600']), status(['line\nbreak']), status(['x'*101])]
        for field, value in [('online', 1), ('players', 'Steve'), ('max_players', -1), ('version', {})]:
            view = status(); view['servers'][0][field] = value; values.append(view)
        for value in [float('nan'), float('inf'), True, -1, 10**30]:
            view = status(); view['updated'] = value; values.append(view)
        for view in values:
            with self.subTest(view=view), self.assertRaises(RenderError):
                render_pages('在线玩家', '在线', view)

class ConcurrentGlassReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_four_page_renders_and_busy_rejection(self):
        renderer = ReplyRenderer()
        view = status(['Player_%03d' % number for number in range(144)])
        view['servers'][0]['max_players'] = 200
        entered, release = threading.Event(), threading.Event()
        lock, count = threading.Lock(), 0

        def gated_render(*args):
            nonlocal count
            with lock:
                count += 1
                if count == 2:
                    entered.set()
            if not release.wait(10):
                raise AssertionError('Concurrent render test gate was not released')
            return render_pages(*args)

        with patch('starbridge.reply_images.render_pages', gated_render):
            tasks = [asyncio.create_task(renderer.render('在线玩家', '在线', view)) for _ in range(2)]
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 10), 'Both renders must enter before checking capacity')
                with self.assertRaises(RenderError):
                    await asyncio.wait_for(renderer.render('在线玩家', '在线', view), timeout=5)
            finally:
                release.set()
                results = await asyncio.gather(*tasks)

        for pages in results:
            self.assertEqual(len(pages), 4)
            for page in pages:
                self.assertLessEqual(len(page), MAX_PNG)
                with Image.open(BytesIO(page)) as image:
                    self.assertEqual((image.format, image.mode, image.width), ('PNG', 'RGB', 1080))
                    self.assertLessEqual(image.height, 1600)
                    image.verify()
        self.assertEqual([hashlib.sha256(page).digest() for page in results[0]],
                         [hashlib.sha256(page).digest() for page in results[1]])


if __name__ == '__main__':
    unittest.main()
