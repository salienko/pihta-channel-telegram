"""Channel tests: rendering, core client contract, screen drawing. No Telegram network."""
import os
import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from core_client import Core, CoreError
from render import chunks, keyboard


class StubMessage:
    """Records what the channel would send to Telegram."""

    def __init__(self, photo=False):
        self.photo = object() if photo else None
        self.sent, self.edits, self.captions = [], [], []

    async def answer(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))

    async def answer_photo(self, file, caption=None, reply_markup=None):
        self.sent.append((caption, reply_markup))

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))

    async def edit_caption(self, caption, reply_markup=None):
        self.captions.append((caption, reply_markup))


class Rendering(unittest.TestCase):
    def test_action_buttons_become_inline(self):
        screen = {'rows': [[{'text': 'Забронировать', 'action': 'begin'}],
                           [{'text': 'Сайт', 'url': 'https://example.test'}]]}
        markup = keyboard(screen)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, 'begin')
        self.assertEqual(markup.inline_keyboard[1][0].url, 'https://example.test')

    def test_contact_screen_asks_for_phone(self):
        markup = keyboard({'rows': [], 'reply_contact': True})
        self.assertTrue(markup.keyboard[0][0].request_contact)

    def test_long_text_is_split(self):
        self.assertEqual(len(chunks('a' * 8000)), 3)

    def test_empty_rows_means_no_markup(self):
        self.assertIsNone(keyboard({'rows': []}))


class CoreContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []

        async def screen(request):
            body = await request.json()
            self.seen.append(('screen', body, request.headers.get('X-Core-Token')))
            return web.json_response({'text': 'меню', 'rows': [], 'notice': 'Готово'})

        async def text(request):
            body = await request.json()
            self.seen.append(('text', body, None))
            return web.json_response({'text': 'шаг', 'rows': []})

        async def contact(request):
            body = await request.json()
            self.seen.append(('contact', body, None))
            return web.json_response({'text': 'гости', 'rows': []})

        async def fail(request):
            return web.json_response({'error': {'code': 'rule_violation', 'message': 'Выберите дату.'}},
                                     status=400)

        app = web.Application()
        app.add_routes([web.post('/api/v1/screen', screen), web.post('/api/v1/text', text),
                        web.post('/api/v1/contact', contact), web.post('/api/v1/fail', fail)])
        self.server = TestServer(app)
        await self.server.start_server()
        self.core = Core(str(self.server.make_url('')).rstrip('/'), 'secret-token')

    async def asyncTearDown(self):
        await self.core.close()
        await self.server.close()

    async def test_screen_sends_platform_and_token(self):
        result = await self.core.screen(530433212, 'begin')
        self.assertEqual(result['text'], 'меню')
        kind, body, token = self.seen[-1]
        self.assertEqual(kind, 'screen')
        self.assertEqual(body['platform'], 'telegram')
        self.assertEqual(body['user_id'], 530433212)
        self.assertEqual(body['action'], 'begin')
        self.assertEqual(token, 'secret-token')

    async def test_text_and_contact_payloads(self):
        await self.core.text(7, 'Иван')
        await self.core.contact(7, '+79812440050')
        self.assertEqual(self.seen[-2][1], {'platform': 'telegram', 'user_id': 7, 'text': 'Иван'})
        self.assertEqual(self.seen[-1][1], {'platform': 'telegram', 'user_id': 7, 'phone': '+79812440050'})

    async def test_rule_error_carries_message(self):
        with self.assertRaises(CoreError) as caught:
            await self.core._post('/api/v1/fail', {})
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.message, 'Выберите дату.')


class Drawing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import bot
        self.bot_module = bot
        self.channel = bot.Channel(bot=None, core=None)

    async def test_text_screen_is_sent(self):
        message = StubMessage()
        await self.channel.show(message, {'text': 'ПИХТА', 'rows': [[{'text': 'Да', 'action': 'home'}]]})
        self.assertEqual(message.sent[0][0], 'ПИХТА')

    async def test_edit_is_preferred(self):
        message = StubMessage()
        await self.channel.show(message, {'text': 'Экран', 'rows': []}, edit=True)
        self.assertEqual(message.edits[0][0], 'Экран')
        self.assertEqual(message.sent, [])

    async def test_long_screen_is_split_into_messages(self):
        message = StubMessage()
        await self.channel.show(message, {'text': 'x' * 8000, 'rows': []})
        self.assertEqual(len(message.sent), 3)

    async def test_banner_goes_as_photo(self):
        message = StubMessage()
        await self.channel.show(message, {'text': 'Экран', 'photo': 'home', 'rows': []})
        self.assertEqual(message.sent[0][0], 'Экран')
