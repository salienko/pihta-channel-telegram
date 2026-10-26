"""Thin Telegram channel: receive update, ask the core, draw the screen."""
import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiohttp import web

from core_client import Core, CoreError
from render import chunks, drop_reply_keyboard, keyboard

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
log = logging.getLogger('channel.telegram')

ASSETS = Path(__file__).with_name('assets')
PHOTO_CAPTION_LIMIT = 1000


class Channel:
    def __init__(self, bot, core):
        self.bot, self.core = bot, core
        self.locks = {}

    def lock(self, user_id):
        return self.locks.setdefault(user_id, asyncio.Lock())

    async def show(self, message, screen, edit=False):
        """Draw one screen. Editing is preferred: the guest keeps a single message."""
        markup = keyboard(screen)
        text = screen.get('text') or ''
        photo = screen.get('photo')
        file = ASSETS / f'{photo}.jpg' if photo else None
        if edit:
            try:
                if message.photo and (not file or not file.exists()):
                    await message.edit_caption(caption=text, reply_markup=markup)
                    return
                if message.photo and file and file.exists():
                    from aiogram.types import InputMediaPhoto
                    await message.edit_media(InputMediaPhoto(media=FSInputFile(file), caption=text),
                                             reply_markup=markup)
                    return
                if not file or not file.exists():
                    await message.edit_text(text, reply_markup=markup)
                    return
            except TelegramBadRequest as error:
                reason = str(error).lower()
                if 'message is not modified' in reason:
                    return
                if not any(part in reason for part in ('message to edit not found', "message can't be edited",
                                                       'message is too long')):
                    raise
        if file and file.exists() and len(text) <= PHOTO_CAPTION_LIMIT:
            await message.answer_photo(FSInputFile(file), caption=text, reply_markup=markup)
            return
        parts = chunks(text)
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            await message.answer(part, reply_markup=markup if last else None)

    async def handle_error(self, message, error):
        if isinstance(error, CoreError) and error.status == 400:
            await message.answer(error.message)
            return
        log.error('core failure: %s', error)
        await message.answer('Сервис обновляется. Попробуйте через минуту.')


def build(bot, core):
    channel = Channel(bot, core)
    dp = Dispatcher()

    @dp.message(F.contact)
    async def on_contact(message: Message):
        async with channel.lock(message.from_user.id):
            try:
                screen = await core.contact(message.from_user.id, message.contact.phone_number)
            except Exception as error:
                await channel.handle_error(message, error)
                return
            await message.answer('Номер получен.', reply_markup=drop_reply_keyboard())
            await channel.show(message, screen)

    @dp.message(F.text)
    async def on_text(message: Message):
        async with channel.lock(message.from_user.id):
            try:
                screen = await core.text(message.from_user.id, message.text)
            except Exception as error:
                await channel.handle_error(message, error)
                return
            if screen.get('notice'):
                await message.answer(screen['notice'])
            await channel.show(message, screen)

    @dp.callback_query()
    async def on_callback(call: CallbackQuery):
        async with channel.lock(call.from_user.id):
            try:
                screen = await core.screen(call.from_user.id, call.data)
            except Exception as error:
                await call.answer()
                await channel.handle_error(call.message, error)
                return
            await call.answer(screen.get('notice') or None)
            if screen.get('nothing'):
                return
            await channel.show(call.message, screen, edit=True)

    return dp


async def health_server(port):
    app = web.Application()

    async def health(request):
        return web.json_response({'status': 'ok', 'service': 'pihta-channel-telegram'})

    app.add_routes([web.get('/health', health)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', port).start()
    log.info('health listener on 0.0.0.0:%s', port)


async def main():
    token = os.getenv('BOT_TOKEN', '').strip()
    core_url = os.getenv('CORE_URL', '').strip()
    core_token = os.getenv('CORE_API_TOKEN', '').strip()
    if not token or not core_url or not core_token:
        raise SystemExit('BOT_TOKEN, CORE_URL and CORE_API_TOKEN are required')
    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    core = Core(core_url, core_token)
    dp = build(bot, core)
    port = os.getenv('PORT', '').strip()
    if port:
        await health_server(int(port))
    log.info('release=%s core=%s polling started', os.getenv('RELEASE', 'dev'), core_url)
    try:
        await dp.start_polling(bot, allowed_updates=['message', 'callback_query'])
    finally:
        await core.close()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        log.error('startup failed: %s: %s', type(error).__name__, str(error)[:300])
        raise
