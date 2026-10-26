"""Render a core screen with Telegram primitives. No business rules here."""
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove)

MAX_TEXT = 3500


def keyboard(screen):
    """Inline keyboard from screen rows; None when the screen asks for a contact."""
    if screen.get('reply_contact'):
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='📱 Поделиться номером', request_contact=True)],
                                             [KeyboardButton(text='🏠 Главное меню')]],
                                   resize_keyboard=True, one_time_keyboard=True)
    rows = screen.get('rows') or []
    if not rows:
        return None
    built = []
    for row in rows:
        line = []
        for button in row:
            if button.get('url'):
                line.append(InlineKeyboardButton(text=button['text'], url=button['url']))
            else:
                line.append(InlineKeyboardButton(text=button['text'], callback_data=button['action']))
        built.append(line)
    return InlineKeyboardMarkup(inline_keyboard=built)


def chunks(text, size=MAX_TEXT):
    text = text or ''
    return [text[i:i + size] for i in range(0, len(text), size)] or ['']


def plain_keyboard(screen):
    """Keyboard for the reply-contact case; inline keyboard otherwise."""
    markup = keyboard(screen)
    return markup


def drop_reply_keyboard():
    return ReplyKeyboardRemove()
