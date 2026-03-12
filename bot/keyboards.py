from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.i18n import t


def main_menu_kb(lang: str, owner: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, 'language'), callback_data='menu:language')
    kb.button(text=t(lang, 'edit'), callback_data='menu:edit')
    kb.button(text=t(lang, 'add_token'), callback_data='menu:add')
    kb.button(text=t(lang, 'view_tokens'), callback_data='menu:view')
    kb.button(text=t(lang, 'group_settings'), callback_data='menu:group')
    kb.button(text=t(lang, 'trending'), callback_data='menu:trending')
    kb.button(text=t(lang, 'advert'), callback_data='menu:advert')
    if owner:
        kb.button(text='👑 Owner', callback_data='menu:owner')
    kb.adjust(2, 2, 2, 1, 1 if owner else 0)
    return kb.as_markup()


def language_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='🇺🇸 English', callback_data='lang:en')
    kb.button(text='🇷🇺 Russian', callback_data='lang:ru')
    kb.adjust(2)
    return kb.as_markup()


def source_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for source in ('stonfi', 'dedust', 'blum', 'gaspump'):
        kb.button(text=source.upper(), callback_data=f'source:{source}')
    kb.adjust(2, 2)
    return kb.as_markup()


def token_list_kb(tokens, action: str = 'edit') -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for token in tokens:
        title = token['symbol'] or token['name'] or token['token_address'][:8]
        kb.button(text=f'✏️ {title}', callback_data=f'{action}:{token["token_address"]}')
    kb.button(text='« Return', callback_data='menu:home')
    kb.adjust(1)
    return kb.as_markup()


def edit_token_kb(lang: str, token_address: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='ℹ️ Buy Step', callback_data=f'edit:buy_step:{token_address}')
    kb.button(text='✏️', callback_data=f'editv:buy_step:{token_address}')
    kb.button(text='ℹ️ Min Buy', callback_data=f'edit:min_buy:{token_address}')
    kb.button(text='✏️', callback_data=f'editv:min_buy:{token_address}')
    kb.button(text='ℹ️ Link', callback_data=f'edit:link:{token_address}')
    kb.button(text='✏️', callback_data=f'editv:link:{token_address}')
    kb.button(text='ℹ️ Emoji', callback_data=f'edit:emoji:{token_address}')
    kb.button(text='✏️', callback_data=f'editv:emoji:{token_address}')
    kb.button(text='ℹ️ Media', callback_data=f'edit:media:{token_address}')
    kb.button(text='✏️', callback_data=f'editv:media:{token_address}')
    kb.button(text=t(lang, 'return'), callback_data='menu:home')
    kb.adjust(2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def durations_kb(kind: str, lang: str) -> InlineKeyboardMarkup:
    keys = [('1h', 'hours_1'), ('3h', 'hours_3'), ('6h', 'hours_6'), ('9h', 'hours_9'), ('12h', 'hours_12'), ('24h', 'hours_24')] if kind == 'trending' else [('1d', 'days_1'), ('3d', 'days_3'), ('7d', 'days_7')]
    kb = InlineKeyboardBuilder()
    for value, label in keys:
        kb.button(text=t(lang, label), callback_data=f'duration:{kind}:{value}')
    kb.button(text=t(lang, 'return'), callback_data='menu:home')
    kb.adjust(2 if kind == 'trending' else 3, 2 if kind == 'trending' else 1, 2 if kind == 'trending' else 1, 1)
    return kb.as_markup()


def invoice_kb(amount: float, lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, 'return'), callback_data='menu:home')
    kb.button(text=t(lang, 'refresh'), callback_data='invoice:refresh')
    kb.button(text=t(lang, 'pay_amount', amount=f'{amount:g}'), url='ton://transfer')
    kb.adjust(2, 1)
    return kb.as_markup()


def buy_post_kb(metrics_url: str, secondary_url: str, secondary_text: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='Metrics', url=metrics_url)
    kb.button(text=secondary_text, url=secondary_url)
    kb.adjust(2)
    return kb.as_markup()


def leaderboard_kb(listing_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='Listing', url=listing_url)
    kb.adjust(1)
    return kb.as_markup()
