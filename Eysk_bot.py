#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eysk Telegram Bot - Version 2.0 with Stars and USDT payments
"""

import logging
from datetime import datetime
import hashlib
import random
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, CopyTextButton
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler
)

from config import *
from database import Database
from sheets_reader import GoogleSheetsReader

# РќР°СЃС‚СЂРѕР№РєР° Р»РѕРіРёСЂРѕРІР°РЅРёСЏ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# РРЅРёС†РёР°Р»РёР·Р°С†РёСЏ
db = Database()
sheets = GoogleSheetsReader()  # РўРµРїРµСЂСЊ С‡РёС‚Р°РµС‚ РёР· apartments.xlsx

# Р’СЂРµРјРµРЅРЅРѕРµ С…СЂР°РЅРёР»РёС‰Рµ С„РёР»СЊС‚СЂРѕРІ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ
user_filters = {}

# Р’СЂРµРјРµРЅРЅРѕРµ С…СЂР°РЅРёР»РёС‰Рµ РґР°РЅРЅС‹С… РїР°РіРёРЅР°С†РёРё (РґР»СЏ РєРЅРѕРїРєРё "РџРѕРєР°Р·Р°С‚СЊ РµС‰Рµ")
user_pagination_data = {}

# Р’СЂРµРјРµРЅРЅРѕРµ С…СЂР°РЅРёР»РёС‰Рµ СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ РїРѕРёСЃРєР° (РґР»СЏ РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ Р±РµР· РїРѕРґРїРёСЃРєРё)
user_search_results = {}

# РљРѕРЅСЃС‚Р°РЅС‚С‹ РїСЂРµРІСЊСЋ/СѓРІРµРґРѕРјР»РµРЅРёР№
PREVIEW_RESULTS_LIMIT = 2
NOTIFICATION_CHECK_INTERVAL_SECONDS = 900
NOTIFICATION_NEW_ITEMS_LIMIT = 3


def build_apartment_key(apartment: dict) -> str:
    """РЎС‚СЂРѕРёС‚ СЃС‚Р°Р±РёР»СЊРЅС‹Р№ РєР»СЋС‡ РѕР±СЉСЏРІР»РµРЅРёСЏ РґР»СЏ СѓС‡РµС‚Р° РїСЂРѕСЃРјРѕС‚СЂРѕРІ/СѓРІРµРґРѕРјР»РµРЅРёР№."""
    key_parts = [
        apartment.get('РќР°СЃРµР»РµРЅРЅС‹Р№_РїСѓРЅРєС‚', '').strip(),
        apartment.get('РўРёРї_Р¶РёР»СЊСЏ', '').strip(),
        apartment.get('Р Р°СЃСЃС‚РѕСЏРЅРёРµ_РѕС‚_РјРѕСЂСЏ_Рј', '').strip(),
        apartment.get('Р“РѕСЃС‚РµР№_РјР°РєСЃ', '').strip(),
        apartment.get('Р¦РµРЅР°_Р·Р°_СЃСѓС‚РєРё', '').strip(),
        apartment.get('РўРµР»РµС„РѕРЅ', '').strip(),
        apartment.get('РРјСЏ_С…РѕР·СЏРёРЅР°', '').strip(),
        apartment.get('VK_СЃСЃС‹Р»РєР°', '').strip(),
        apartment.get('Р¤РѕС‚Рѕ_URL', '').strip(),
    ]
    raw = "|".join(key_parts)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def get_fake_views_count(apartment_key: str) -> int:
    """РџСЃРµРІРґРѕ-СЂР°РЅРґРѕРјРЅС‹Р№, РЅРѕ СЃС‚Р°Р±РёР»СЊРЅС‹Р№ СЃС‡РµС‚С‡РёРє РїСЂРѕСЃРјРѕС‚СЂРѕРІ РґР»СЏ РѕР±СЉСЏРІР»РµРЅРёСЏ."""
    rng = random.Random(apartment_key)
    return rng.randint(8, 39)


async def seed_seen_apartments_for_user(user_id: int):
    """Р—Р°РїРѕР»РЅСЏРµС‚ Р±Р°Р·Сѓ С‚РµРєСѓС‰РёРјРё РѕР±СЉСЏРІР»РµРЅРёСЏРјРё, С‡С‚РѕР±С‹ СѓРІРµРґРѕРјР»СЏС‚СЊ С‚РѕР»СЊРєРѕ Рѕ РЅРѕРІС‹С…."""
    all_apartments = sheets.read_apartments()
    all_keys = [build_apartment_key(apt) for apt in all_apartments]
    db.add_seen_apartments(user_id, all_keys)


def is_payment_time():
    """РџСЂРѕРІРµСЂРєР°, РґРѕСЃС‚СѓРїРЅР° Р»Рё РѕРїР»Р°С‚Р° РІ С‚РµРєСѓС‰РµРµ РІСЂРµРјСЏ (11:00-23:00 РњРЎРљ)"""
    msk_tz = pytz.timezone('Europe/Moscow')
    now_msk = datetime.now(msk_tz)
    current_hour = now_msk.hour
    
    # Р’РѕР·РІСЂР°С‰Р°РµРј True РµСЃР»Рё РІСЂРµРјСЏ РјРµР¶РґСѓ 11:00 Рё 23:00 РњРЎРљ
    return 11 <= current_hour < 23


async def safe_answer_callback(query, *args, **kwargs):
    """Р‘РµР·РѕРїР°СЃРЅРѕ РѕС‚РІРµС‡Р°РµС‚ РЅР° callback; РёРіРЅРѕСЂРёСЂСѓРµС‚ РїСЂРѕСЃСЂРѕС‡РµРЅРЅС‹Рµ callback-Р·Р°РїСЂРѕСЃС‹."""
    try:
        await query.answer(*args, **kwargs)
    except BadRequest as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            logger.warning(f"РџСЂРѕРїСѓС‰РµРЅ СѓСЃС‚Р°СЂРµРІС€РёР№ callback: {e}")
            return
        raise


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РєРѕРјР°РЅРґС‹ /start"""
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name)
    
    # РџСЂРѕРІРµСЂСЏРµРј РїРѕРґРїРёСЃРєСѓ РґР»СЏ РёРЅС„РѕСЂРјР°С†РёРё
    has_subscription, end_date = db.check_subscription(user.id)
    
    # РџСЂРёРІРµС‚СЃС‚РІРёРµ
    if has_subscription:
        await update.message.reply_text(
            f"{WELCOME_TEXT}\n\n"
            f"вњ… РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРЅР° РґРѕ {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
    else:
        await update.message.reply_text(WELCOME_TEXT)
    
    # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹ РґР»СЏ РІСЃРµС… РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№
    user_filters[user.id] = {}
    
    # РџР•Р Р’Р«Р™ Р’РћРџР РћРЎ - РІС‹Р±РѕСЂ РЅР°СЃРµР»С‘РЅРЅРѕРіРѕ РїСѓРЅРєС‚Р° (РґР»СЏ РІСЃРµС…)
    keyboard = [
        [InlineKeyboardButton("рџЏ–пёЏ Р•Р№СЃРє", callback_data='location_РµР№СЃРє')],
        [InlineKeyboardButton("рџЊЉ Р”РѕР»Р¶Р°РЅСЃРєР°СЏ", callback_data='location_РґРѕР»Р¶Р°РЅСЃРєР°СЏ')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "рџ”Ќ Р”Р°РІР°Р№ РЅР°Р№РґРµРј РёРґРµР°Р»СЊРЅРѕРµ Р¶РёР»СЊРµ!\n\n"
        "1пёЏвѓЈ Р’С‹Р±РµСЂРё РЅР°СЃРµР»С‘РЅРЅС‹Р№ РїСѓРЅРєС‚:",
        reply_markup=reply_markup
    )


async def buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РїРѕРєСѓРїРєРё РїРѕРґРїРёСЃРєРё - РїРѕРєР°Р·С‹РІР°РµРј РІС‹Р±РѕСЂ СЃРїРѕСЃРѕР±Р° РѕРїР»Р°С‚С‹"""
    query = update.callback_query
    await safe_answer_callback(query)

    tariff_key = query.data.replace('buy_', '')

    # РџСЂРѕРІРµСЂСЏРµРј РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ С‚Р°СЂРёС„Р°
    if tariff_key not in TARIFFS:
        await query.edit_message_text("вќЊ РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ С‚Р°СЂРёС„")
        logger.error(f"РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ tariff_key: {tariff_key}")
        return

    tariff = TARIFFS[tariff_key]

    # РџРѕРєР°Р·С‹РІР°РµРј РІС‹Р±РѕСЂ СЃРїРѕСЃРѕР±Р° РѕРїР»Р°С‚С‹
    keyboard = [
        [InlineKeyboardButton(f"рџ“± РџРѕРїРѕР»РЅРёС‚СЊ Р±Р°Р»Р°РЅСЃ РјРѕР±РёР»СЊРЅРѕРіРѕ - {tariff['price']}в‚Ѕ", callback_data=f'pay_card_{tariff_key}')],
        [InlineKeyboardButton(f"в­ђ Telegram Stars ({tariff['price_stars']} Stars)", callback_data=f'pay_stars_{tariff_key}')],
        [InlineKeyboardButton(f"рџ’µ USDT (BEP-20) - {tariff['price_usdt']} USDT", callback_data=f'pay_usdt_{tariff_key}')],
        [InlineKeyboardButton("рџ”™ РќР°Р·Р°Рґ", callback_data='go_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"рџ’° РћРїР»Р°С‚Р° РїРѕРґРїРёСЃРєРё: {tariff['name']}\n\n"
        f"Р’С‹Р±РµСЂРё СЃРїРѕСЃРѕР± РѕРїР»Р°С‚С‹:\n\n"
        f"рџ“± РњРѕР±РёР»СЊРЅС‹Р№: {tariff['price']}в‚Ѕ\n"
        f"в­ђ Stars: {tariff['price_stars']} Stars\n"
        f"рџ’µ USDT: {tariff['price_usdt']} USDT",
        reply_markup=reply_markup
    )


async def pay_with_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћРїР»Р°С‚Р° РїРѕРїРѕР»РЅРµРЅРёРµРј Р±Р°Р»Р°РЅСЃР° РјРѕР±РёР»СЊРЅРѕРіРѕ"""
    query = update.callback_query
    await safe_answer_callback(query)

    tariff_key = query.data.replace('pay_card_', '')

    # РџСЂРѕРІРµСЂСЏРµРј РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ С‚Р°СЂРёС„Р°
    if tariff_key not in TARIFFS:
        await query.edit_message_text("вќЊ РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ С‚Р°СЂРёС„")
        logger.error(f"РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ tariff_key: {tariff_key}")
        return

    tariff = TARIFFS[tariff_key]

    # РџСЂРѕРІРµСЂСЏРµРј РІСЂРµРјСЏ РїРѕ РњРЎРљ
    if not is_payment_time():
        msk_tz = pytz.timezone('Europe/Moscow')
        now_msk = datetime.now(msk_tz)
        current_time = now_msk.strftime('%H:%M')

        keyboard = [[InlineKeyboardButton("рџЏ  Р’ РЅР°С‡Р°Р»Рѕ", callback_data='go_start')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"вЏ° РћРїР»Р°С‚Р° РІСЂРµРјРµРЅРЅРѕ РЅРµРґРѕСЃС‚СѓРїРЅР°\n\n"
            f"РўРµРєСѓС‰РµРµ РІСЂРµРјСЏ РњРЎРљ: {current_time}\n\n"
            f"РћРїР»Р°С‚Р° Рё Р°РєС‚РёРІР°С†РёСЏ РїРѕРґРїРёСЃРєРё РґРѕСЃС‚СѓРїРЅС‹ С‚РѕР»СЊРєРѕ:\n"
            f"рџ“… РЎ 11:00 РґРѕ 23:00 РїРѕ РњРЎРљ\n\n"
            f"РџРѕРїСЂРѕР±СѓР№ РїРѕР·Р¶Рµ!",
            reply_markup=reply_markup
        )
        return

    # Р”РѕР±Р°РІР»СЏРµРј Р·Р°СЏРІРєСѓ РЅР° РѕРїР»Р°С‚Сѓ
    request_id = db.add_payment_request(query.from_user.id, tariff_key, 'mobile')

    # РЈРІРµРґРѕРјР»СЏРµРј Р°РґРјРёРЅР°
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"рџ’° РќРѕРІР°СЏ Р·Р°СЏРІРєР° РЅР° РѕРїР»Р°С‚Сѓ!\n\n"
                 f"ID Р·Р°СЏРІРєРё: {request_id}\n"
                 f"РЎРїРѕСЃРѕР± РѕРїР»Р°С‚С‹: рџ“± РџРѕРїРѕР»РЅРµРЅРёРµ РјРѕР±РёР»СЊРЅРѕРіРѕ\n"
                 f"РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ: @{query.from_user.username or 'Р±РµР· username'} "
                 f"({query.from_user.first_name})\n"
                 f"User ID: {query.from_user.id}\n"
                 f"РўР°СЂРёС„: {tariff['name']} - {tariff['price']}в‚Ѕ"
        )
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РїСЂРё СѓРІРµРґРѕРјР»РµРЅРёРё Р°РґРјРёРЅР°: {e}")

    # РџРѕРєР°Р·С‹РІР°РµРј СЂРµРєРІРёР·РёС‚С‹
    keyboard = [
        [InlineKeyboardButton("вњ… РЇ РѕРїР»Р°С‚РёР»", callback_data=f'paid_card_{request_id}_{tariff_key}')],
        [InlineKeyboardButton("рџ”™ РќР°Р·Р°Рґ", callback_data='go_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"рџ“± РћРїР»Р°С‚Р° РїРѕРґРїРёСЃРєРё: {tariff['name']}\n"
        f"РЎСѓРјРјР°: {tariff['price']}в‚Ѕ\n\n"
        f"рџ’° РџРѕРїРѕР»РЅРёС‚Рµ Р±Р°Р»Р°РЅСЃ РјРѕР±РёР»СЊРЅРѕРіРѕ:\n"
        f"РќРѕРјРµСЂ: `{PAYMENT_PHONE}`\n"
        f"РћРїРµСЂР°С‚РѕСЂ: РўРµР»Рµ2\n\n"
        f"РџРѕСЃР»Рµ РѕРїР»Р°С‚С‹ РЅР°Р¶РјРё РєРЅРѕРїРєСѓ РЅРёР¶Рµ.\n"
        f"Р”РѕСЃС‚СѓРї Р±СѓРґРµС‚ Р°РєС‚РёРІРёСЂРѕРІР°РЅ РІ С‚РµС‡РµРЅРёРµ 15 РјРёРЅСѓС‚.\n\n"
        f"вЏ° РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂСѓРµС‚СЃСЏ С‚РѕР»СЊРєРѕ СЃ 11:00 РґРѕ 23:00 РїРѕ РњРЎРљ",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def pay_with_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћРїР»Р°С‚Р° С‡РµСЂРµР· Telegram Stars"""
    query = update.callback_query
    await safe_answer_callback(query)

    tariff_key = query.data.replace('pay_stars_', '')

    # РџСЂРѕРІРµСЂСЏРµРј РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ С‚Р°СЂРёС„Р°
    if tariff_key not in TARIFFS:
        await query.edit_message_text("вќЊ РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ С‚Р°СЂРёС„")
        logger.error(f"РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ tariff_key: {tariff_key}")
        return

    tariff = TARIFFS[tariff_key]

    # РЎРѕР·РґР°РµРј РёРЅРІРѕР№СЃ РґР»СЏ РѕРїР»Р°С‚С‹ Stars
    title = f"РџРѕРґРїРёСЃРєР° {tariff['name']}"
    description = f"Р”РѕСЃС‚СѓРї Рє Р±Р°Р·Рµ Р¶РёР»СЊСЏ РІ Р•Р№СЃРєРµ Рё Р”РѕР»Р¶Р°РЅСЃРєРѕР№ РЅР° {tariff['days']} " + ("РґРµРЅСЊ" if tariff['days'] == 1 else "РґРЅРµР№")
    payload = f"subscription_{tariff_key}_{query.from_user.id}"

    # РћС‚РїСЂР°РІР»СЏРµРј РёРЅРІРѕР№СЃ
    try:
        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",  # Р”Р»СЏ Stars РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РїСѓСЃС‚Р°СЏ СЃС‚СЂРѕРєР°
            currency="XTR",  # XTR - РєРѕРґ РІР°Р»СЋС‚С‹ РґР»СЏ Telegram Stars
            prices=[LabeledPrice(label=title, amount=tariff['price_stars'])]
        )

        await query.edit_message_text(
            f"в­ђ РћРїР»Р°С‚Р° С‡РµСЂРµР· Telegram Stars\n\n"
            f"РЎС‡РµС‚ РЅР° РѕРїР»Р°С‚Сѓ РѕС‚РїСЂР°РІР»РµРЅ!\n"
            f"РЎСѓРјРјР°: {tariff['price_stars']} Stars\n\n"
            f"РџРѕСЃР»Рµ СѓСЃРїРµС€РЅРѕР№ РѕРїР»Р°С‚С‹ РїРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂСѓРµС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("рџЏ  Р’ РЅР°С‡Р°Р»Рѕ", callback_data='go_start')
            ]])
        )
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РїСЂРё СЃРѕР·РґР°РЅРёРё РёРЅРІРѕР№СЃР° Stars: {e}")
        await query.edit_message_text(
            f"вќЊ РћС€РёР±РєР° РїСЂРё СЃРѕР·РґР°РЅРёРё СЃС‡РµС‚Р°.\n\n"
            f"РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РїРѕРїСЂРѕР±СѓР№С‚Рµ РґСЂСѓРіРѕР№ СЃРїРѕСЃРѕР± РѕРїР»Р°С‚С‹ РёР»Рё РѕР±СЂР°С‚РёС‚РµСЃСЊ Рє Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("рџЏ  Р’ РЅР°С‡Р°Р»Рѕ", callback_data='go_start')
            ]])
        )


async def pay_with_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћРїР»Р°С‚Р° С‡РµСЂРµР· USDT"""
    query = update.callback_query
    await safe_answer_callback(query)

    tariff_key = query.data.replace('pay_usdt_', '')

    # РџСЂРѕРІРµСЂСЏРµРј РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ С‚Р°СЂРёС„Р°
    if tariff_key not in TARIFFS:
        await query.edit_message_text("вќЊ РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ С‚Р°СЂРёС„")
        logger.error(f"РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ tariff_key: {tariff_key}")
        return

    tariff = TARIFFS[tariff_key]

    # Р”РѕР±Р°РІР»СЏРµРј Р·Р°СЏРІРєСѓ РЅР° РѕРїР»Р°С‚Сѓ
    request_id = db.add_payment_request(query.from_user.id, tariff_key, 'usdt')

    # РЈРІРµРґРѕРјР»СЏРµРј Р°РґРјРёРЅР°
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"рџ’° РќРѕРІР°СЏ Р·Р°СЏРІРєР° РЅР° РѕРїР»Р°С‚Сѓ!\n\n"
                 f"ID Р·Р°СЏРІРєРё: {request_id}\n"
                 f"РЎРїРѕСЃРѕР± РѕРїР»Р°С‚С‹: рџ’µ USDT (BEP-20)\n"
                 f"РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ: @{query.from_user.username or 'Р±РµР· username'} "
                 f"({query.from_user.first_name})\n"
                 f"User ID: {query.from_user.id}\n"
                 f"РўР°СЂРёС„: {tariff['name']} - {tariff['price_usdt']} USDT"
        )
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РїСЂРё СѓРІРµРґРѕРјР»РµРЅРёРё Р°РґРјРёРЅР°: {e}")

    # РџРѕРєР°Р·С‹РІР°РµРј СЂРµРєРІРёР·РёС‚С‹ USDT
    keyboard = [
        [InlineKeyboardButton("рџ“‹ РљРѕРїРёСЂРѕРІР°С‚СЊ Р°РґСЂРµСЃ", copy_text=CopyTextButton(text=USDT_WALLET))],
        [InlineKeyboardButton("вњ… РЇ РѕРїР»Р°С‚РёР»", callback_data=f'paid_usdt_{request_id}_{tariff_key}')],
        [InlineKeyboardButton("рџ”™ РќР°Р·Р°Рґ", callback_data='go_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"рџ’µ РћРїР»Р°С‚Р° РїРѕРґРїРёСЃРєРё: {tariff['name']}\n"
        f"РЎСѓРјРјР°: {tariff['price_usdt']} USDT\n\n"
        f"рџ’° РђРґСЂРµСЃ РєРѕС€РµР»СЊРєР° USDT (BEP-20):\n"
        f"`{USDT_WALLET}`\n\n"
        f"вљ пёЏ Р’РЅРёРјР°РЅРёРµ! РћС‚РїСЂР°РІР»СЏР№С‚Рµ РўРћР›Р¬РљРћ USDT РїРѕ СЃРµС‚Рё BEP-20 (Binance Smart Chain)!\n\n"
        f"РџРѕСЃР»Рµ РѕРїР»Р°С‚С‹ РЅР°Р¶РјРё РєРЅРѕРїРєСѓ РЅРёР¶Рµ.\n"
        f"Р”РѕСЃС‚СѓРї Р±СѓРґРµС‚ Р°РєС‚РёРІРёСЂРѕРІР°РЅ РІ С‚РµС‡РµРЅРёРµ 15 РјРёРЅСѓС‚.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ РѕРїР»Р°С‚С‹ РѕС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ"""
    query = update.callback_query
    await safe_answer_callback(query)

    # Р‘РµР·РѕРїР°СЃРЅС‹Р№ РїР°СЂСЃРёРЅРі callback_data: paid_METHOD_REQUEST_ID_TARIFF_KEY
    try:
        # РЈР±РёСЂР°РµРј РїСЂРµС„РёРєСЃ 'paid_'
        data = query.data.replace('paid_', '')
        parts = data.split('_')

        # РћРїСЂРµРґРµР»СЏРµРј РјРµС‚РѕРґ РѕРїР»Р°С‚С‹
        payment_method = parts[0]  # card РёР»Рё usdt
        request_id = int(parts[1])
        tariff_key = '_'.join(parts[2:])  # РЎРѕРµРґРёРЅСЏРµРј РІСЃРµ С‡Р°СЃС‚Рё РїРѕСЃР»Рµ request_id: '1_day'

        # РџСЂРѕРІРµСЂСЏРµРј РєРѕСЂСЂРµРєС‚РЅРѕСЃС‚СЊ С‚Р°СЂРёС„Р°
        if tariff_key not in TARIFFS:
            await safe_answer_callback(query, "вќЊ РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ С‚Р°СЂРёС„", show_alert=True)
            logger.error(f"РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ tariff_key РІ payment_confirmation: {tariff_key}")
            return

        tariff = TARIFFS[tariff_key]
    except (IndexError, ValueError) as e:
        logger.error(f"РћС€РёР±РєР° РїР°СЂСЃРёРЅРіР° callback_data РІ payment_confirmation: {query.data}, {e}")
        await safe_answer_callback(query, "вќЊ РќРµРєРѕСЂСЂРµРєС‚РЅС‹Рµ РґР°РЅРЅС‹Рµ", show_alert=True)
        return
    
    user_id = query.from_user.id

    # РћРїСЂРµРґРµР»СЏРµРј СЃРѕРѕР±С‰РµРЅРёРµ РІ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё РѕС‚ РјРµС‚РѕРґР° РѕРїР»Р°С‚С‹
    payment_info = ""
    if payment_method == 'card':
        payment_info = f"рџ“± РњРѕР±РёР»СЊРЅС‹Р№ - {tariff['price']}в‚Ѕ"
    elif payment_method == 'usdt':
        payment_info = f"рџ’µ USDT - {tariff['price_usdt']} USDT"

    # РЈРІРµРґРѕРјР»СЏРµРј Р°РґРјРёРЅР° СЃ РєРЅРѕРїРєРѕР№ Р°РєС‚РёРІР°С†РёРё
    try:
        keyboard = [[
            InlineKeyboardButton(
                f"вњ… РђРєС‚РёРІРёСЂРѕРІР°С‚СЊ ({tariff['name']})",
                callback_data=f'admin_activate_{user_id}_{tariff["days"]}'
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"вњ… РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РїРѕРґС‚РІРµСЂРґРёР» РѕРїР»Р°С‚Сѓ!\n\n"
                 f"ID Р·Р°СЏРІРєРё: {request_id}\n"
                 f"РЎРїРѕСЃРѕР± РѕРїР»Р°С‚С‹: {payment_info}\n"
                 f"РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ: @{query.from_user.username or 'Р±РµР· username'} "
                 f"({query.from_user.first_name})\n"
                 f"User ID: {user_id}\n"
                 f"РўР°СЂРёС„: {tariff['name']}\n\n"
                 f"РџСЂРѕРІРµСЂСЊ РїР»Р°С‚РµР¶ Рё РЅР°Р¶РјРё РєРЅРѕРїРєСѓ РЅРёР¶Рµ:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РїСЂРё СѓРІРµРґРѕРјР»РµРЅРёРё Р°РґРјРёРЅР° Рѕ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРё: {e}")
    
    await query.edit_message_text(
        "вњ… РЎРїР°СЃРёР±Рѕ! РўРІРѕСЏ Р·Р°СЏРІРєР° РїСЂРёРЅСЏС‚Р°.\n\n"
        "вЏі РћР¶РёРґР°Р№ Р°РєС‚РёРІР°С†РёРё РїРѕРґРїРёСЃРєРё (РѕР±С‹С‡РЅРѕ РІ С‚РµС‡РµРЅРёРµ 5-10 РјРёРЅСѓС‚).\n"
        "РљР°Рє С‚РѕР»СЊРєРѕ РґРѕСЃС‚СѓРї Р±СѓРґРµС‚ Р°РєС‚РёРІРёСЂРѕРІР°РЅ, СЏ СЃСЂР°Р·Сѓ С‚РµР±Рµ РЅР°РїРёС€Сѓ!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("рџЏ  Р’ РЅР°С‡Р°Р»Рѕ", callback_data='go_start')
        ]])
    )
    
    # Р—Р°РїР»Р°РЅРёСЂРѕРІР°С‚СЊ РЅР°РїРѕРјРёРЅР°РЅРёРµ С‡РµСЂРµР· 1 С‡Р°СЃ
    context.job_queue.run_once(
        send_payment_reminder,
        3600,  # 3600 СЃРµРєСѓРЅРґ = 1 С‡Р°СЃ
        data={'user_id': user_id, 'request_id': request_id},
        name=f'reminder_{user_id}_{request_id}'
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ РїР»Р°С‚РµР¶Р° Stars РїРµСЂРµРґ РѕРїР»Р°С‚РѕР№"""
    query = update.pre_checkout_query
    # Р’СЃРµРіРґР° РїРѕРґС‚РІРµСЂР¶РґР°РµРј РїР»Р°С‚РµР¶
    await safe_answer_callback(query, ok=True)


async def successful_payment_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћР±СЂР°Р±РѕС‚РєР° СѓСЃРїРµС€РЅРѕР№ РѕРїР»Р°С‚С‹ С‡РµСЂРµР· Stars"""
    payment = update.message.successful_payment
    user_id = update.effective_user.id

    # РџР°СЂСЃРёРј payload: subscription_TARIFF_KEY_USER_ID
    try:
        payload_parts = payment.invoice_payload.split('_')
        tariff_key = '_'.join(payload_parts[1:-1])  # РџРѕР»СѓС‡Р°РµРј tariff_key (РЅР°РїСЂРёРјРµСЂ, "1_day")

        if tariff_key not in TARIFFS:
            logger.error(f"РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ tariff_key РёР· payload: {tariff_key}")
            await update.message.reply_text("вќЊ РћС€РёР±РєР° РѕР±СЂР°Р±РѕС‚РєРё РїР»Р°С‚РµР¶Р°. РћР±СЂР°С‚РёС‚РµСЃСЊ Рє Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ.")
            return

        tariff = TARIFFS[tariff_key]

        # РђРєС‚РёРІРёСЂСѓРµРј РїРѕРґРїРёСЃРєСѓ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё
        end_date = db.add_subscription(user_id, tariff['days'], tariff_key)

        # РЈРІРµРґРѕРјР»СЏРµРј Р°РґРјРёРЅР° РѕР± СѓСЃРїРµС€РЅРѕР№ РѕРїР»Р°С‚Рµ Stars
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"в­ђ РЈСЃРїРµС€РЅР°СЏ РѕРїР»Р°С‚Р° С‡РµСЂРµР· Stars!\n\n"
                     f"РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ: @{update.effective_user.username or 'Р±РµР· username'} "
                     f"({update.effective_user.first_name})\n"
                     f"User ID: {user_id}\n"
                     f"РўР°СЂРёС„: {tariff['name']}\n"
                     f"РЎСѓРјРјР°: {tariff['price_stars']} Stars\n"
                     f"РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂРѕРІР°РЅР° РґРѕ: {end_date.strftime('%d.%m.%Y %H:%M')}"
            )
        except Exception as e:
            logger.error(f"РћС€РёР±РєР° РїСЂРё СѓРІРµРґРѕРјР»РµРЅРёРё Р°РґРјРёРЅР° РѕР± РѕРїР»Р°С‚Рµ Stars: {e}")

        # РЈРІРµРґРѕРјР»СЏРµРј РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ
        await update.message.reply_text(
            f"рџЋ‰ РћРїР»Р°С‚Р° СѓСЃРїРµС€РЅР°!\n\n"
            f"вњ… РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂРѕРІР°РЅР°!\n"
            f"РўР°СЂРёС„: {tariff['name']}\n"
            f"РђРєС‚РёРІРЅР° РґРѕ: {end_date.strftime('%d.%m.%Y %H:%M')}"
        )

        # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё СЃРѕС…СЂР°РЅРµРЅРЅС‹Рµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР°
        if user_id in user_search_results:
            # Р•СЃС‚СЊ СЃРѕС…СЂР°РЅРµРЅРЅС‹Рµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ - РїРѕРєР°Р·С‹РІР°РµРј РёС…
            filtered = user_search_results[user_id]

            await context.bot.send_message(
                chat_id=user_id,
                text=f"рџ”Ќ Р’РѕС‚ СЂРµР·СѓР»СЊС‚Р°С‚С‹ С‚РІРѕРµРіРѕ РїРѕРёСЃРєР° ({len(filtered)} РІР°СЂРёР°РЅС‚РѕРІ):"
            )

            await show_results_function(context, user_id, filtered)

            # РћС‡РёС‰Р°РµРј СЃРѕС…СЂР°РЅРµРЅРЅС‹Рµ СЂРµР·СѓР»СЊС‚Р°С‚С‹
            del user_search_results[user_id]

            # РћС‡РёС‰Р°РµРј С„РёР»СЊС‚СЂС‹
            if user_id in user_filters:
                del user_filters[user_id]
        else:
            # РќРµС‚ СЃРѕС…СЂР°РЅРµРЅРЅС‹С… СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ - РЅР°С‡РёРЅР°РµРј РЅРѕРІС‹Р№ РїРѕРёСЃРє
            user_filters[user_id] = {}

            keyboard = [
                [InlineKeyboardButton("рџЏ–пёЏ Р•Р№СЃРє", callback_data='location_РµР№СЃРє')],
                [InlineKeyboardButton("рџЊЉ Р”РѕР»Р¶Р°РЅСЃРєР°СЏ", callback_data='location_РґРѕР»Р¶Р°РЅСЃРєР°СЏ')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=user_id,
                text="рџ”Ќ Р”Р°РІР°Р№ РЅР°Р№РґРµРј Р¶РёР»СЊРµ РґР»СЏ С‚РµР±СЏ!\n\n1пёЏвѓЈ Р’С‹Р±РµСЂРё РЅР°СЃРµР»С‘РЅРЅС‹Р№ РїСѓРЅРєС‚:",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"РћС€РёР±РєР° РїСЂРё РѕР±СЂР°Р±РѕС‚РєРµ СѓСЃРїРµС€РЅРѕР№ РѕРїР»Р°С‚С‹ Stars: {e}")
        await update.message.reply_text(
            "вќЊ РџСЂРѕРёР·РѕС€Р»Р° РѕС€РёР±РєР° РїСЂРё Р°РєС‚РёРІР°С†РёРё РїРѕРґРїРёСЃРєРё.\n"
            "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РѕР±СЂР°С‚РёС‚РµСЃСЊ Рє Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ."
        )


async def send_payment_reminder(context: ContextTypes.DEFAULT_TYPE):
    """РћС‚РїСЂР°РІРєР° РЅР°РїРѕРјРёРЅР°РЅРёСЏ РµСЃР»Рё РїРѕРґРїРёСЃРєР° РЅРµ Р°РєС‚РёРІРёСЂРѕРІР°РЅР° С‡РµСЂРµР· 1 С‡Р°СЃ"""
    job_data = context.job.data
    user_id = job_data['user_id']
    request_id = job_data['request_id']

    # РџСЂРѕРІРµСЂСЏРµРј, Р°РєС‚РёРІРёСЂРѕРІР°РЅР° Р»Рё РїРѕРґРїРёСЃРєР°
    has_subscription, end_date = db.check_subscription(user_id)

    if not has_subscription:
        # РџРѕРґРїРёСЃРєР° РЅРµ Р°РєС‚РёРІРёСЂРѕРІР°РЅР° - РѕС‚РїСЂР°РІР»СЏРµРј РЅР°РїРѕРјРёРЅР°РЅРёРµ
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"вЏ° РџСЂРѕС€РµР» 1 С‡Р°СЃ СЃ РјРѕРјРµРЅС‚Р° РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ РѕРїР»Р°С‚С‹.\n\n"
                     f"Р•СЃР»Рё РІР°С€Р° РїРѕРґРїРёСЃРєР° РїРѕ РєР°РєРёРј-С‚Рѕ РїСЂРёС‡РёРЅР°Рј РЅРµ Р°РєС‚РёРІРёСЂРѕРІР°РЅР°, "
                     f"РїРѕР¶Р°Р»СѓР№СЃС‚Р°, РѕР±СЂР°С‚РёС‚РµСЃСЊ Рє Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂСѓ:\n"
                     f"рџ‘¤ https://t.me/Den_Shev_007\n\n"
                     f"рџ“Ћ РџСЂРёРєСЂРµРїРёС‚Рµ С‡РµРє РѕР± РѕРїР»Р°С‚Рµ.\n\n"
                     f"РЎРїР°СЃРёР±Рѕ Р·Р° РїРѕРЅРёРјР°РЅРёРµ! рџ™Џ"
            )
        except Exception as e:
            logger.error(f"РћС€РёР±РєР° РїСЂРё РѕС‚РїСЂР°РІРєРµ РЅР°РїРѕРјРёРЅР°РЅРёСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ {user_id}: {e}")


async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РќР°С‡Р°Р»Рѕ РїРѕРёСЃРєР° Р¶РёР»СЊСЏ"""
    user_id = update.effective_user.id
    
    # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹ РґР»СЏ РІСЃРµС…
    user_filters[user_id] = {}
    
    # РџР•Р Р’Р«Р™ Р’РћРџР РћРЎ - РІС‹Р±РѕСЂ РЅР°СЃРµР»С‘РЅРЅРѕРіРѕ РїСѓРЅРєС‚Р°
    keyboard = [
        [InlineKeyboardButton("рџЏ–пёЏ Р•Р№СЃРє", callback_data='location_РµР№СЃРє')],
        [InlineKeyboardButton("рџЊЉ Р”РѕР»Р¶Р°РЅСЃРєР°СЏ", callback_data='location_РґРѕР»Р¶Р°РЅСЃРєР°СЏ')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "рџ”Ќ Р”Р°РІР°Р№ РЅР°Р№РґРµРј РёРґРµР°Р»СЊРЅРѕРµ Р¶РёР»СЊРµ!\n\n"
        "1пёЏвѓЈ Р’С‹Р±РµСЂРё РЅР°СЃРµР»С‘РЅРЅС‹Р№ РїСѓРЅРєС‚:",
        reply_markup=reply_markup
    )


async def show_results_function(
    context,
    user_id,
    filtered,
    start_index=0,
    show_contacts=True,
    show_vk=True
):
    """Р’СЃРїРѕРјРѕРіР°С‚РµР»СЊРЅР°СЏ С„СѓРЅРєС†РёСЏ РґР»СЏ РїРѕРєР°Р·Р° СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ СЃ РїР°РіРёРЅР°С†РёРµР№"""
    
    RESULTS_PER_PAGE = 20  # РџРѕРєР°Р·С‹РІР°РµРј РїРѕ 20 Р·Р° СЂР°Р·
    
    total_results = len(filtered)
    end_index = min(start_index + RESULTS_PER_PAGE, total_results)
    current_batch = filtered[start_index:end_index]
    
    # РџРµСЂРІРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ С‚РѕР»СЊРєРѕ РїСЂРё start_index = 0
    if start_index == 0:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"вњ… РќР°Р№РґРµРЅРѕ РІР°СЂРёР°РЅС‚РѕРІ: {total_results}\n\n"
                 f"РЎРµР№С‡Р°СЃ РїРѕРєР°Р¶Сѓ РёС… РїРѕ РѕС‡РµСЂРµРґРё:"
        )
    
    for i, apt in enumerate(current_batch, start_index + 1):
        # Р—Р°РіРѕР»РѕРІРѕРє
        text = f"рџ“Ќ Р’Р°СЂРёР°РЅС‚ {i} в¬‡пёЏв¬‡пёЏв¬‡пёЏ\n\n"
        
        # РћСЃРЅРѕРІРЅР°СЏ РёРЅС„РѕСЂРјР°С†РёСЏ
        tip = apt.get('РўРёРї_Р¶РёР»СЊСЏ', 'РЅРµ СѓРєР°Р·Р°РЅ')
        if tip == '1-РєРѕРјРЅ':
            tip = '1-РєРѕРјРЅР°С‚РЅР°СЏ РєРІР°СЂС‚РёСЂР°'
        elif tip == '2-РєРѕРјРЅ':
            tip = '2-РєРѕРјРЅР°С‚РЅР°СЏ РєРІР°СЂС‚РёСЂР°'
        elif tip == '3-РєРѕРјРЅ':
            tip = '3-РєРѕРјРЅР°С‚РЅР°СЏ РєРІР°СЂС‚РёСЂР°'
        elif tip == 'С‡Р°СЃС‚РЅС‹Р№ РґРѕРј':
            tip = 'Р§Р°СЃС‚РЅС‹Р№ РґРѕРј'
        elif tip == 'РіРѕСЃС‚РµРІРѕР№ РґРѕРј':
            tip = 'Р“РѕСЃС‚РµРІРѕР№ РґРѕРј'
        
        text += f"рџЏ  {tip}\n"
        text += f"рџЏ–пёЏ {apt.get('Р Р°СЃСЃС‚РѕСЏРЅРёРµ_РѕС‚_РјРѕСЂСЏ_Рј', '?')} РјРµС‚СЂРѕРІ РѕС‚ РјРѕСЂСЏ\n"
        text += f"рџ‘Ґ Р”Рѕ {apt.get('Р“РѕСЃС‚РµР№_РјР°РєСЃ', '?')} РіРѕСЃС‚РµР№\n"
        
        # Р¦РµРЅР°
        price = apt.get('Р¦РµРЅР°_Р·Р°_СЃСѓС‚РєРё', '')
        if price and price != 'РїРѕ Р·Р°РїСЂРѕСЃСѓ':
            text += f"рџ’° {price}в‚Ѕ/СЃСѓС‚РєРё\n"
        else:
            text += f"рџ’° Р¦РµРЅР° РїРѕ Р·Р°РїСЂРѕСЃСѓ\n"
        
        # РћРїРёСЃР°РЅРёРµ (РµСЃР»Рё РµСЃС‚СЊ)
        description = apt.get('РћРїРёСЃР°РЅРёРµ', '').strip()
        if description:
            text += f"\nрџ“ќ {description}\n"
        
        # Р”РѕР±Р°РІР»СЏРµРј "Р°Р¶РёРѕС‚Р°Р¶РЅС‹Р№" СЃС‡РµС‚С‡РёРє РїСЂРѕСЃРјРѕС‚СЂРѕРІ
        apt_key = build_apartment_key(apt)
        views_count = get_fake_views_count(apt_key)
        text += f"\nрџ”Ґ Р­С‚РѕС‚ РІР°СЂРёР°РЅС‚ СЃРјРѕС‚СЂРµР»Рё {views_count} СЂР°Р·\n"

        if show_contacts:
            # РљРѕРЅС‚Р°РєС‚С‹ - СЃРЅР°С‡Р°Р»Р° С‚РµР»РµС„РѕРЅ
            text += f"\nрџ“ћ {apt.get('РўРµР»РµС„РѕРЅ', 'РЅРµ СѓРєР°Р·Р°РЅ')}\n"

            # РџРѕС‚РѕРј РёРјСЏ С…РѕР·СЏРёРЅР° (РµСЃР»Рё РµСЃС‚СЊ)
            owner = apt.get('РРјСЏ_С…РѕР·СЏРёРЅР°', '').strip()
            if owner:
                text += f"рџ‘¤ {owner}\n"
        else:
            text += "\nрџ”’ РљРѕРЅС‚Р°РєС‚С‹ РґРѕСЃС‚СѓРїРЅС‹ РїРѕСЃР»Рµ Р°РєС‚РёРІР°С†РёРё РїРѕРґРїРёСЃРєРё\n"

        # VK СЃСЃС‹Р»РєР° СЃ РєСЂР°СЃРёРІС‹Рј С‚РµРєСЃС‚РѕРј
        vk_link = apt.get('VK_СЃСЃС‹Р»РєР°', '').strip()
        if show_vk and vk_link and vk_link.startswith('http'):
            text += f"\nрџ”— РџРѕРґСЂРѕР±РЅРµРµ Р·РґРµСЃСЊ: {vk_link}"

        # Р•СЃР»Рё РµСЃС‚СЊ С„РѕС‚Рѕ
        photo_url = apt.get('Р¤РѕС‚Рѕ_URL', '').strip()
        if photo_url and photo_url.startswith('http'):
            try:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo_url,
                    caption=text
                )
            except Exception as e:
                logger.error(f"РћС€РёР±РєР° РїСЂРё РѕС‚РїСЂР°РІРєРµ С„РѕС‚Рѕ: {e}")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text
                )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=text
            )
    
    # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё РµС‰Рµ СЂРµР·СѓР»СЊС‚Р°С‚С‹
    remaining = total_results - end_index
    
    if remaining > 0 and show_contacts:
        # Р•СЃС‚СЊ РµС‰Рµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ - РїРѕРєР°Р·С‹РІР°РµРј РєРЅРѕРїРєСѓ "РџРѕРєР°Р·Р°С‚СЊ РµС‰Рµ"
        # РЎРѕС…СЂР°РЅСЏРµРј РґР°РЅРЅС‹Рµ РґР»СЏ СЃР»РµРґСѓСЋС‰РµР№ РїРѕСЂС†РёРё
        user_pagination_data[user_id] = {
            'filtered': filtered,
            'next_index': end_index
        }
        
        keyboard = [
            [InlineKeyboardButton(f"рџ“‹ РџРѕРєР°Р·Р°С‚СЊ РµС‰Рµ {remaining}", callback_data='show_more')],
            [InlineKeyboardButton("рџ”” РџРѕРґРїРёСЃР°С‚СЊСЃСЏ РЅР° РЅРѕРІС‹Рµ", callback_data='alerts_subscribe')],
            [InlineKeyboardButton("рџ”Ќ РќРѕРІС‹Р№ РїРѕРёСЃРє", callback_data='new_search')]
        ]
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"вњ… РџРѕРєР°Р·Р°РЅРѕ {end_index} РёР· {total_results} РІР°СЂРёР°РЅС‚РѕРІ",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif show_contacts:
        # Р’СЃРµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРєР°Р·Р°РЅС‹
        await context.bot.send_message(
            chat_id=user_id,
            text="вњ… Р’СЃРµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРєР°Р·Р°РЅС‹!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("рџ”” РџРѕРґРїРёСЃР°С‚СЊСЃСЏ РЅР° РЅРѕРІС‹Рµ", callback_data='alerts_subscribe')
            ], [
                InlineKeyboardButton("рџ”Ќ РќРѕРІС‹Р№ РїРѕРёСЃРє", callback_data='new_search')
            ]])
        )


async def show_preview_results_function(context, user_id, filtered):
    """РџРѕРєР°Р·С‹РІР°РµС‚ Р±РµСЃРїР»Р°С‚РЅС‹Р№ РїСЂРµРІСЊСЋ: РґРѕ 2 РІР°СЂРёР°РЅС‚РѕРІ Р±РµР· РєРѕРЅС‚Р°РєС‚РѕРІ Рё Р±РµР· VK."""
    preview_items = filtered[:PREVIEW_RESULTS_LIMIT]

    if not preview_items:
        return

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"рџ‘Ђ Р‘РµСЃРїР»Р°С‚РЅС‹Р№ РїСЂРµРІСЊСЋ: {len(preview_items)} РёР· {len(filtered)} РІР°СЂРёР°РЅС‚РѕРІ\n\n"
            f"РџРѕРєР°Р·С‹РІР°СЋ РїСЂРёРјРµСЂС‹ Р±РµР· РєРѕРЅС‚Р°РєС‚РѕРІ Рё Р±РµР· СЃСЃС‹Р»РѕРє."
        )
    )

    await show_results_function(
        context,
        user_id,
        preview_items,
        start_index=0,
        show_contacts=False,
        show_vk=False
    )


async def subscribe_alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Р’РєР»СЋС‡Р°РµС‚ СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ РЅРѕРІС‹С… РѕР±СЉСЏРІР»РµРЅРёСЏС…."""
    query = update.callback_query
    await safe_answer_callback(query)
    user_id = query.from_user.id

    has_subscription, _ = db.check_subscription(user_id)
    if not has_subscription:
        await query.edit_message_text(
            "рџ”’ РЈРІРµРґРѕРјР»РµРЅРёСЏ Рѕ РЅРѕРІС‹С… РІР°СЂРёР°РЅС‚Р°С… РґРѕСЃС‚СѓРїРЅС‹ С‚РѕР»СЊРєРѕ РїСЂРё Р°РєС‚РёРІРЅРѕР№ РїРѕРґРїРёСЃРєРµ.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("рџ’і РљСѓРїРёС‚СЊ РїРѕРґРїРёСЃРєСѓ", callback_data='buy_1_day')]])
        )
        return

    db.set_alert_subscription(user_id, True)
    await seed_seen_apartments_for_user(user_id)

    await query.edit_message_text(
        "рџ”” Р“РѕС‚РѕРІРѕ! РўРµРїРµСЂСЊ Р±СѓРґСѓ РїСЂРёСЃС‹Р»Р°С‚СЊ РЅРѕРІС‹Рµ РѕР±СЉСЏРІР»РµРЅРёСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё."
    )


async def check_new_apartments_job(context: ContextTypes.DEFAULT_TYPE):
    """РџРµСЂРёРѕРґРёС‡РµСЃРєРё РїСЂРѕРІРµСЂСЏРµС‚ РЅРѕРІС‹Рµ РѕР±СЉСЏРІР»РµРЅРёСЏ Рё СЂР°СЃСЃС‹Р»Р°РµС‚ СѓРІРµРґРѕРјР»РµРЅРёСЏ РїРѕРґРїРёСЃС‡РёРєР°Рј."""
    user_ids = db.get_alert_subscribers()
    if not user_ids:
        return

    all_apartments = sheets.read_apartments()
    keyed_apartments = {build_apartment_key(apt): apt for apt in all_apartments}
    all_keys = set(keyed_apartments.keys())

    for user_id in user_ids:
        has_subscription, _ = db.check_subscription(user_id)
        if not has_subscription:
            db.set_alert_subscription(user_id, False)
            continue

        seen_keys = db.get_seen_apartment_keys(user_id)
        new_keys = [key for key in all_keys if key not in seen_keys]
        if not new_keys:
            continue

        db.add_seen_apartments(user_id, new_keys)
        new_apartments = [keyed_apartments[key] for key in new_keys[:NOTIFICATION_NEW_ITEMS_LIMIT]]

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"рџ†• РџРѕСЏРІРёР»РёСЃСЊ РЅРѕРІС‹Рµ РѕР±СЉСЏРІР»РµРЅРёСЏ: {len(new_keys)} С€С‚. РџРѕРєР°Р·С‹РІР°СЋ СЃРІРµР¶РёРµ:"
            )
            await show_results_function(context, user_id, new_apartments, show_contacts=True, show_vk=True)
        except Exception as e:
            logger.error(f"РћС€РёР±РєР° РѕС‚РїСЂР°РІРєРё СѓРІРµРґРѕРјР»РµРЅРёСЏ Рѕ РЅРѕРІС‹С… РѕР±СЉСЏРІР»РµРЅРёСЏС… РґР»СЏ user_id={user_id}: {e}")


async def select_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Р’С‹Р±РѕСЂ РЅР°СЃРµР»С‘РЅРЅРѕРіРѕ РїСѓРЅРєС‚Р°"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user_id = query.from_user.id
    location = query.data.replace('location_', '')
    
    # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹ РµСЃР»Рё РёС… РЅРµС‚
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    # РЎРѕС…СЂР°РЅСЏРµРј РІС‹Р±РѕСЂ
    user_filters[user_id]['location'] = location
    
    # Р•СЃР»Рё РІС‹Р±СЂР°РЅР° Р”РѕР»Р¶Р°РЅСЃРєР°СЏ - СЃСЂР°Р·Сѓ РїРѕРєР°Р·С‹РІР°РµРј РІСЃРµ РѕР±СЉСЏРІР»РµРЅРёСЏ
    if location == 'РґРѕР»Р¶Р°РЅСЃРєР°СЏ':
        await query.edit_message_text("рџ”Ќ РС‰Сѓ РІСЃРµ РІР°СЂРёР°РЅС‚С‹ РІ Р”РѕР»Р¶Р°РЅСЃРєРѕР№...")
        
        # РџРѕР»СѓС‡Р°РµРј РІСЃРµ РѕР±СЉСЏРІР»РµРЅРёСЏ Р”РѕР»Р¶Р°РЅСЃРєРѕР№
        all_apartments = sheets.read_apartments()
        filtered = [apt for apt in all_apartments if apt.get('РќР°СЃРµР»РµРЅРЅС‹Р№_РїСѓРЅРєС‚', '').lower() == 'РґРѕР»Р¶Р°РЅСЃРєР°СЏ']
        
        # Р›РѕРіРёСЂСѓРµРј РїРѕРёСЃРє
        db.log_search(user_id, user_filters[user_id], len(filtered))
        
        if not filtered:
            await context.bot.send_message(
                chat_id=user_id,
                text="рџ” Рљ СЃРѕР¶Р°Р»РµРЅРёСЋ, РІ Р”РѕР»Р¶Р°РЅСЃРєРѕР№ РїРѕРєР° РЅРµС‚ РѕР±СЉСЏРІР»РµРЅРёР№.\n\n"
                     "РџРѕРїСЂРѕР±СѓР№ РїРѕРёСЃРєР°С‚СЊ РІ Р•Р№СЃРєРµ:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("рџ”Ќ РќРѕРІС‹Р№ РїРѕРёСЃРє", callback_data='new_search')
                ]])
            )
            if user_id in user_filters:
                del user_filters[user_id]
            return
        
        # РџСЂРѕРІРµСЂСЏРµРј РїРѕРґРїРёСЃРєСѓ
        has_subscription, end_date = db.check_subscription(user_id)
        
        if has_subscription:
            # Р•СЃР»Рё РµСЃС‚СЊ РїРѕРґРїРёСЃРєР° - РїРѕРєР°Р·С‹РІР°РµРј СЂРµР·СѓР»СЊС‚Р°С‚С‹
            await show_results_function(context, user_id, filtered)
            
            # РћС‡РёС‰Р°РµРј С„РёР»СЊС‚СЂС‹
            if user_id in user_filters:
                del user_filters[user_id]
        else:
            # Р•СЃР»Рё РЅРµС‚ РїРѕРґРїРёСЃРєРё - РїРѕРєР°Р·С‹РІР°РµРј РєРѕР»РёС‡РµСЃС‚РІРѕ Рё РїСЂРµРґР»Р°РіР°РµРј РѕРїР»Р°С‚РёС‚СЊ
            # РЎРѕС…СЂР°РЅСЏРµРј СЂРµР·СѓР»СЊС‚Р°С‚С‹ РґР»СЏ РїРѕРєР°Р·Р° РїРѕСЃР»Рµ РѕРїР»Р°С‚С‹
            user_search_results[user_id] = filtered

            # Р‘РµСЃРїР»Р°С‚РЅС‹Р№ РїСЂРµРІСЊСЋ (Р±РµР· РєРѕРЅС‚Р°РєС‚РѕРІ Рё VK)
            await show_preview_results_function(context, user_id, filtered)
            
            keyboard = [
                [InlineKeyboardButton(f"рџ’і {TARIFFS['1_day']['name']} - {TARIFFS['1_day']['price']}в‚Ѕ",
                                     callback_data='buy_1_day')],
                [InlineKeyboardButton(f"рџ’і {TARIFFS['7_days']['name']} - {TARIFFS['7_days']['price']}в‚Ѕ",
                                     callback_data='buy_7_days')],
                [InlineKeyboardButton(f"рџ’і {TARIFFS['30_days']['name']} - {TARIFFS['30_days']['price']}в‚Ѕ",
                                     callback_data='buy_30_days')],
                [InlineKeyboardButton("рџ”Ќ РќРѕРІС‹Р№ РїРѕРёСЃРє", callback_data='new_search')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=user_id,
                text=f"вњ… РќР°Р№РґРµРЅРѕ РІР°СЂРёР°РЅС‚РѕРІ: {len(filtered)}\n\n"
                     f"РџРѕР»РЅС‹Р№ РґРѕСЃС‚СѓРї Рє РєРѕРЅС‚Р°РєС‚Р°Рј Рё РІСЃРµРј РѕР±СЉСЏРІР»РµРЅРёСЏРј РѕС‚РєСЂС‹РІР°РµС‚СЃСЏ РїРѕ РїРѕРґРїРёСЃРєРµ.\n\n"
                     f"Р’С‹Р±РµСЂРё С‚Р°СЂРёС„:",
                reply_markup=reply_markup
            )

            # РќР• РѕС‡РёС‰Р°РµРј С„РёР»СЊС‚СЂС‹ - РѕРЅРё РјРѕРіСѓС‚ РїСЂРёРіРѕРґРёС‚СЊСЃСЏ

    # Р•СЃР»Рё РІС‹Р±СЂР°РЅ Р•Р№СЃРє - Р·Р°РґР°С‘Рј РІРѕРїСЂРѕСЃС‹
    else:
        keyboard = [
            [InlineKeyboardButton("рџЏ  1-РєРѕРјРЅР°С‚РЅР°СЏ", callback_data='type_1-РєРѕРјРЅ')],
            [InlineKeyboardButton("рџЏЎ 2-РєРѕРјРЅР°С‚РЅР°СЏ", callback_data='type_2-РєРѕРјРЅ')],
            [InlineKeyboardButton("рџЏ 3-РєРѕРјРЅР°С‚РЅР°СЏ", callback_data='type_3-РєРѕРјРЅ')],
            [InlineKeyboardButton("рџЏпёЏ Р§Р°СЃС‚РЅС‹Р№ РґРѕРј", callback_data='type_С‡Р°СЃС‚РЅС‹Р№ РґРѕРј')],
            [InlineKeyboardButton("рџЏЁ Р“РѕСЃС‚РµРІРѕР№ РґРѕРј", callback_data='type_РіРѕСЃС‚РµРІРѕР№ РґРѕРј')],
            [InlineKeyboardButton("вћЎпёЏ Р›СЋР±РѕР№ С‚РёРї", callback_data='type_any')],
            [InlineKeyboardButton("рџ”™ РќР°Р·Р°Рґ", callback_data='go_start')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "2пёЏвѓЈ РљР°РєРѕР№ С‚РёРї Р¶РёР»СЊСЏ С‚РµР±Рµ РЅСѓР¶РµРЅ?",
            reply_markup=reply_markup
        )
    
    


async def select_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Р’С‹Р±РѕСЂ С‚РёРїР° Р¶РёР»СЊСЏ"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user_id = query.from_user.id
    type_choice = query.data.replace('type_', '')
    
    # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹ РµСЃР»Рё РёС… РЅРµС‚
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    if type_choice != 'any':
        user_filters[user_id]['type'] = type_choice
    
    # Р’РѕРїСЂРѕСЃ Рѕ РєРѕР»РёС‡РµСЃС‚РІРµ РіРѕСЃС‚РµР№
    keyboard = [
        [InlineKeyboardButton("рџ‘¤ 1-2 РіРѕСЃС‚СЏ", callback_data='guests_2')],
        [InlineKeyboardButton("рџ‘Ґ 3-4 РіРѕСЃС‚СЏ", callback_data='guests_4')],
        [InlineKeyboardButton("рџ‘ЁвЂЌрџ‘©вЂЌрџ‘§вЂЌрџ‘¦ 5-6 РіРѕСЃС‚РµР№", callback_data='guests_6')],
        [InlineKeyboardButton("рџЏў 7+ РіРѕСЃС‚РµР№", callback_data='guests_7')],
        [InlineKeyboardButton("вћЎпёЏ РќРµ РІР°Р¶РЅРѕ", callback_data='guests_any')],
        [InlineKeyboardButton("рџ”™ РќР°Р·Р°Рґ", callback_data='go_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "3пёЏвѓЈ РЎРєРѕР»СЊРєРѕ С‡РµР»РѕРІРµРє Р±СѓРґРµС‚ РѕС‚РґС‹С…Р°С‚СЊ?",
        reply_markup=reply_markup
    )


async def select_guests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Р’С‹Р±РѕСЂ РєРѕР»РёС‡РµСЃС‚РІР° РіРѕСЃС‚РµР№"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user_id = query.from_user.id
    guests_choice = query.data.replace('guests_', '')
    
    # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹ РµСЃР»Рё РёС… РЅРµС‚
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    if guests_choice != 'any':
        user_filters[user_id]['guests'] = int(guests_choice)
    
    # РџР РћР’Р•Р РљРђ: Р•СЃР»Рё РіРѕСЃС‚РµРІРѕР№ РґРѕРј + 5-6 РёР»Рё 7+ РіРѕСЃС‚РµР№ в†’ СЃРїСЂР°С€РёРІР°РµРј РїСЂРѕ 2 РЅРѕРјРµСЂР°
    is_guesthouse = user_filters[user_id].get('type') == 'РіРѕСЃС‚РµРІРѕР№ РґРѕРј'
    is_many_guests = guests_choice in ['6', '7']  # 5-6 РіРѕСЃС‚РµР№ РёР»Рё 7+
    
    if is_guesthouse and is_many_guests:
        # Р—Р°РґР°С‘Рј РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹Р№ РІРѕРїСЂРѕСЃ РїСЂРѕ 2 РЅРѕРјРµСЂР°
        keyboard = [
            [InlineKeyboardButton("вњ… Р”Р°, РїРѕРґРѕР№РґРµС‚ 2 РЅРѕРјРµСЂР°", callback_data='two_rooms_yes')],
            [InlineKeyboardButton("вќЊ РќРµС‚, РЅСѓР¶РµРЅ РѕРґРёРЅ РЅРѕРјРµСЂ", callback_data='two_rooms_no')],
            [InlineKeyboardButton("рџ”™ РќР°Р·Р°Рґ", callback_data='go_start')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "рџ’Ў Р’Р°Рј РїРѕРґРѕР№РґРµС‚ 2 РЅРѕРјРµСЂР°?\n\n"
            "Р­С‚Рѕ СѓРІРµР»РёС‡РёС‚ С€Р°РЅСЃС‹ РЅР°Р№С‚Рё РІР°СЂРёР°РЅС‚С‹ РґР»СЏ Р±РѕР»СЊС€РѕР№ РєРѕРјРїР°РЅРёРё!",
            reply_markup=reply_markup
        )
        return
    
    # РћР±С‹С‡РЅС‹Р№ РІРѕРїСЂРѕСЃ Рѕ СЂР°СЃСЃС‚РѕСЏРЅРёРё РѕС‚ РјРѕСЂСЏ
    keyboard = [
        [InlineKeyboardButton("рџЏ–пёЏ Р”Рѕ 100Рј", callback_data='dist_0-100')],
        [InlineKeyboardButton("рџљ¶ 150-500Рј", callback_data='dist_150-500')],
        [InlineKeyboardButton("рџљ— 500-1000Рј", callback_data='dist_500-1000')],
        [InlineKeyboardButton("рџЏ™пёЏ Р‘РѕР»РµРµ 1000Рј", callback_data='dist_1000-99999')],
        [InlineKeyboardButton("вћЎпёЏ РќРµ РІР°Р¶РЅРѕ", callback_data='dist_any')],
        [InlineKeyboardButton("рџ”™ РќР°Р·Р°Рґ", callback_data='go_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "4пёЏвѓЈ РќР° РєР°РєРѕРј СЂР°СЃСЃС‚РѕСЏРЅРёРё РѕС‚ РјРѕСЂСЏ?",
        reply_markup=reply_markup
    )


async def select_two_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћР±СЂР°Р±РѕС‚РєР° РѕС‚РІРµС‚Р° РЅР° РІРѕРїСЂРѕСЃ РїСЂРѕ 2 РЅРѕРјРµСЂР°"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user_id = query.from_user.id
    answer = query.data.replace('two_rooms_', '')
    
    # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹ РµСЃР»Рё РёС… РЅРµС‚
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    # Р•СЃР»Рё Р”Рђ - РјРµРЅСЏРµРј С„РёР»СЊС‚СЂ РЅР° 3-6 С‡РµР»РѕРІРµРє
    if answer == 'yes':
        user_filters[user_id]['guests'] = 6  # РС‰РµРј РЅРѕРјРµСЂР° РґРѕ 6 С‡РµР»РѕРІРµРє
        user_filters[user_id]['two_rooms_mode'] = True  # Р¤Р»Р°Рі С‡С‚Рѕ РёС‰РµРј 2 РЅРѕРјРµСЂР°
    # Р•СЃР»Рё РќР•Рў - РѕСЃС‚Р°РІР»СЏРµРј РєР°Рє РµСЃС‚СЊ (5-6 РёР»Рё 7+)
    
    # РџРµСЂРµС…РѕРґРёРј Рє РІРѕРїСЂРѕСЃСѓ Рѕ СЂР°СЃСЃС‚РѕСЏРЅРёРё
    keyboard = [
        [InlineKeyboardButton("рџЏ–пёЏ Р”Рѕ 100Рј", callback_data='dist_0-100')],
        [InlineKeyboardButton("рџљ¶ 150-500Рј", callback_data='dist_150-500')],
        [InlineKeyboardButton("рџљ— 500-1000Рј", callback_data='dist_500-1000')],
        [InlineKeyboardButton("рџЏ™пёЏ Р‘РѕР»РµРµ 1000Рј", callback_data='dist_1000-99999')],
        [InlineKeyboardButton("вћЎпёЏ РќРµ РІР°Р¶РЅРѕ", callback_data='dist_any')],
        [InlineKeyboardButton("рџ”™ РќР°Р·Р°Рґ", callback_data='go_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "4пёЏвѓЈ РќР° РєР°РєРѕРј СЂР°СЃСЃС‚РѕСЏРЅРёРё РѕС‚ РјРѕСЂСЏ?",
        reply_markup=reply_markup
    )


async def select_distance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Р’С‹Р±РѕСЂ СЂР°СЃСЃС‚РѕСЏРЅРёСЏ РѕС‚ РјРѕСЂСЏ - РџРћРЎР›Р•Р”РќРР™ РІРѕРїСЂРѕСЃ, Р·Р°С‚РµРј РїРѕРєР°Р· СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user_id = query.from_user.id
    dist_choice = query.data.replace('dist_', '')
    
    # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹ РµСЃР»Рё РёС… РЅРµС‚
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    # РџР°СЂСЃРёРј РґРёР°РїР°Р·РѕРЅ (РЅР°РїСЂРёРјРµСЂ "150-500" РёР»Рё "0-100")
    if dist_choice != 'any':
        min_dist, max_dist = dist_choice.split('-')
        user_filters[user_id]['min_distance'] = int(min_dist)
        user_filters[user_id]['max_distance'] = int(max_dist)
    
    # РџР РћР’Р•Р РљРђ: РµСЃР»Рё РЅРµ РІС‹Р±СЂР°РЅ РЅРё РѕРґРёРЅ С„РёР»СЊС‚СЂ РєСЂРѕРјРµ РіРѕСЂРѕРґР° в†’ РїСЂРѕСЃРёРј СѓС‚РѕС‡РЅРёС‚СЊ
    filters = user_filters[user_id]
    has_filters = any([
        filters.get('type'),           # С‚РёРї Р¶РёР»СЊСЏ
        filters.get('guests'),         # РєРѕР»РёС‡РµСЃС‚РІРѕ РіРѕСЃС‚РµР№
        filters.get('min_distance'),   # СЂР°СЃСЃС‚РѕСЏРЅРёРµ РѕС‚ РјРѕСЂСЏ
        filters.get('max_distance')
    ])
    
    if not has_filters:
        await query.edit_message_text(
            "рџ¤” Р’С‹ РЅРµ РІС‹Р±СЂР°Р»Рё РЅРё РѕРґРёРЅ РїР°СЂР°РјРµС‚СЂ РїРѕРёСЃРєР°.\n\n"
            "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РІС‹Р±РµСЂРёС‚Рµ С…РѕС‚СЏ Р±С‹ РѕРґРёРЅ РёР· С„РёР»СЊС‚СЂРѕРІ "
            "(С‚РёРї Р¶РёР»СЊСЏ, РєРѕР»РёС‡РµСЃС‚РІРѕ РіРѕСЃС‚РµР№ РёР»Рё СЂР°СЃСЃС‚РѕСЏРЅРёРµ РґРѕ РјРѕСЂСЏ), "
            "С‡С‚РѕР±С‹ СЏ РјРѕРі РЅР°Р№С‚Рё РґР»СЏ РІР°СЃ РїРѕРґС…РѕРґСЏС‰РёРµ РІР°СЂРёР°РЅС‚С‹!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("рџ”Ќ РќРѕРІС‹Р№ РїРѕРёСЃРє", callback_data='new_search')
            ]])
        )
        # РћС‡РёС‰Р°РµРј С„РёР»СЊС‚СЂС‹
        if user_id in user_filters:
            del user_filters[user_id]
        return
    
    # РџРѕРєР°Р·С‹РІР°РµРј СЂРµР·СѓР»СЊС‚Р°С‚С‹
    await query.edit_message_text("рџ”Ќ РС‰Сѓ РїРѕРґС…РѕРґСЏС‰РёРµ РІР°СЂРёР°РЅС‚С‹...")
    
    # РџРѕР»СѓС‡Р°РµРј РѕР±СЉСЏРІР»РµРЅРёСЏ РёР· С‚Р°Р±Р»РёС†С‹
    all_apartments = sheets.read_apartments()
    
    # Р¤РёР»СЊС‚СЂСѓРµРј
    filtered = sheets.filter_apartments(all_apartments, user_filters[user_id])
    
    # Р›РѕРіРёСЂСѓРµРј РїРѕРёСЃРє
    db.log_search(user_id, user_filters[user_id], len(filtered))
    
    if not filtered:
        await context.bot.send_message(
            chat_id=user_id,
            text="рџ” Рљ СЃРѕР¶Р°Р»РµРЅРёСЋ, РїРѕ С‚РІРѕРёРј РєСЂРёС‚РµСЂРёСЏРј РЅРёС‡РµРіРѕ РЅРµ РЅР°Р№РґРµРЅРѕ.\n\n"
                 "РџРѕРїСЂРѕР±СѓР№ РёР·РјРµРЅРёС‚СЊ РїР°СЂР°РјРµС‚СЂС‹ РїРѕРёСЃРєР°:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("рџ”Ќ РќРѕРІС‹Р№ РїРѕРёСЃРє", callback_data='new_search')
            ]])
        )
        # РћС‡РёС‰Р°РµРј С„РёР»СЊС‚СЂС‹
        if user_id in user_filters:
            del user_filters[user_id]
        return
    
    # РџСЂРѕРІРµСЂСЏРµРј РїРѕРґРїРёСЃРєСѓ
    has_subscription, end_date = db.check_subscription(user_id)
    
    if has_subscription:
        # Р•СЃР»Рё РµСЃС‚СЊ РїРѕРґРїРёСЃРєР° - РїРѕРєР°Р·С‹РІР°РµРј СЂРµР·СѓР»СЊС‚Р°С‚С‹
        await show_results_function(context, user_id, filtered)
        
        # РћС‡РёС‰Р°РµРј С„РёР»СЊС‚СЂС‹
        if user_id in user_filters:
            del user_filters[user_id]
    else:
        # Р•СЃР»Рё РЅРµС‚ РїРѕРґРїРёСЃРєРё - РїРѕРєР°Р·С‹РІР°РµРј РєРѕР»РёС‡РµСЃС‚РІРѕ Рё РїСЂРµРґР»Р°РіР°РµРј РѕРїР»Р°С‚РёС‚СЊ
        # РЎРѕС…СЂР°РЅСЏРµРј СЂРµР·СѓР»СЊС‚Р°С‚С‹ РґР»СЏ РїРѕРєР°Р·Р° РїРѕСЃР»Рµ РѕРїР»Р°С‚С‹
        user_search_results[user_id] = filtered

        # Р‘РµСЃРїР»Р°С‚РЅС‹Р№ РїСЂРµРІСЊСЋ (Р±РµР· РєРѕРЅС‚Р°РєС‚РѕРІ Рё VK)
        await show_preview_results_function(context, user_id, filtered)
        
        keyboard = [
            [InlineKeyboardButton(f"рџ’і {TARIFFS['1_day']['name']} - {TARIFFS['1_day']['price']}в‚Ѕ",
                                 callback_data='buy_1_day')],
            [InlineKeyboardButton(f"рџ’і {TARIFFS['7_days']['name']} - {TARIFFS['7_days']['price']}в‚Ѕ",
                                 callback_data='buy_7_days')],
            [InlineKeyboardButton(f"рџ’і {TARIFFS['30_days']['name']} - {TARIFFS['30_days']['price']}в‚Ѕ",
                                 callback_data='buy_30_days')],
            [InlineKeyboardButton("рџ”Ќ РќРѕРІС‹Р№ РїРѕРёСЃРє", callback_data='new_search')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=user_id,
            text=f"вњ… РќР°Р№РґРµРЅРѕ РІР°СЂРёР°РЅС‚РѕРІ: {len(filtered)}\n\n"
                 f"РџРѕР»РЅС‹Р№ РґРѕСЃС‚СѓРї Рє РєРѕРЅС‚Р°РєС‚Р°Рј Рё РІСЃРµРј РѕР±СЉСЏРІР»РµРЅРёСЏРј РѕС‚РєСЂС‹РІР°РµС‚СЃСЏ РїРѕ РїРѕРґРїРёСЃРєРµ.\n\n"
                 f"Р’С‹Р±РµСЂРё С‚Р°СЂРёС„:",
            reply_markup=reply_markup
        )

        # РќР• РѕС‡РёС‰Р°РµРј С„РёР»СЊС‚СЂС‹ - РѕРЅРё РјРѕРіСѓС‚ РїСЂРёРіРѕРґРёС‚СЊСЃСЏ


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћС‚РјРµРЅР° РїРѕРёСЃРєР°"""
    user_id = update.effective_user.id
    if user_id in user_filters:
        del user_filters[user_id]
    
    await update.message.reply_text(
        "вќЊ РџРѕРёСЃРє РѕС‚РјРµРЅРµРЅ.\n\n"
        "Р”Р»СЏ РЅРѕРІРѕРіРѕ РїРѕРёСЃРєР° РёСЃРїРѕР»СЊР·СѓР№ /search"
    )
    


# === РђР”РњРРќРЎРљРР• РљРћРњРђРќР”Р« ===

async def admin_activate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РєРЅРѕРїРєРё Р°РєС‚РёРІР°С†РёРё РїРѕРґРїРёСЃРєРё Р°РґРјРёРЅРѕРј"""
    query = update.callback_query
    
    # РџСЂРѕРІРµСЂРєР° С‡С‚Рѕ СЌС‚Рѕ Р°РґРјРёРЅ
    if query.from_user.id != ADMIN_ID:
        await safe_answer_callback(query, "в›” РўРѕР»СЊРєРѕ РґР»СЏ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР°", show_alert=True)
        return
    
    await safe_answer_callback(query)
    
    # Р‘РµР·РѕРїР°СЃРЅС‹Р№ РїР°СЂСЃРёРЅРі РґР°РЅРЅС‹С…: admin_activate_USER_ID_DAYS
    try:
        parts = query.data.replace('admin_activate_', '').split('_')
        user_id = int(parts[0])
        days = int(parts[1])
    except (IndexError, ValueError) as e:
        logger.error(f"РћС€РёР±РєР° РїР°СЂСЃРёРЅРіР° admin callback_data: {query.data}, {e}")
        await safe_answer_callback(query, "вќЊ РќРµРєРѕСЂСЂРµРєС‚РЅС‹Рµ РґР°РЅРЅС‹Рµ", show_alert=True)
        return
    
    try:
        # РђРєС‚РёРІРёСЂСѓРµРј РїРѕРґРїРёСЃРєСѓ
        end_date = db.add_subscription(user_id, days, f"{days}_days")
        
        # РћС‚РјРµРЅСЏРµРј Р·Р°РїР»Р°РЅРёСЂРѕРІР°РЅРЅРѕРµ РЅР°РїРѕРјРёРЅР°РЅРёРµ РµСЃР»Рё РѕРЅРѕ РµСЃС‚СЊ
        # РС‰РµРј РІСЃРµ Р·Р°РґР°С‡Рё Рё РѕС‚РјРµРЅСЏРµРј С‚Рµ, РєРѕС‚РѕСЂС‹Рµ РѕС‚РЅРѕСЃСЏС‚СЃСЏ Рє СЌС‚РѕРјСѓ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ
        all_jobs = context.job_queue.jobs()
        for job in all_jobs:
            if job.name and job.name.startswith(f'reminder_{user_id}_'):
                job.schedule_removal()
        
        # РћР±РЅРѕРІР»СЏРµРј СЃРѕРѕР±С‰РµРЅРёРµ Р°РґРјРёРЅСѓ
        await query.edit_message_text(
            f"вњ… РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂРѕРІР°РЅР°!\n\n"
            f"User ID: {user_id}\n"
            f"Р”РЅРµР№: {days}\n"
            f"Р”Рѕ: {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        
        # РЈРІРµРґРѕРјР»СЏРµРј РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ
        try:
            tariff_name = f"{days} " + ("РґРµРЅСЊ" if days == 1 else "РґРЅРµР№")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"рџЋ‰ РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂРѕРІР°РЅР°!\n\n"
                     f"РўР°СЂРёС„: {tariff_name}\n"
                     f"РђРєС‚РёРІРЅР° РґРѕ: {end_date.strftime('%d.%m.%Y %H:%M')}"
            )
            
            # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё СЃРѕС…СЂР°РЅРµРЅРЅС‹Рµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРёСЃРєР°
            if user_id in user_search_results:
                # Р•СЃС‚СЊ СЃРѕС…СЂР°РЅРµРЅРЅС‹Рµ СЂРµР·СѓР»СЊС‚Р°С‚С‹ - РїРѕРєР°Р·С‹РІР°РµРј РёС…
                filtered = user_search_results[user_id]
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"рџ”Ќ Р’РѕС‚ СЂРµР·СѓР»СЊС‚Р°С‚С‹ С‚РІРѕРµРіРѕ РїРѕРёСЃРєР° ({len(filtered)} РІР°СЂРёР°РЅС‚РѕРІ):"
                )
                
                await show_results_function(context, user_id, filtered)
                
                # РћС‡РёС‰Р°РµРј СЃРѕС…СЂР°РЅРµРЅРЅС‹Рµ СЂРµР·СѓР»СЊС‚Р°С‚С‹
                del user_search_results[user_id]
                
                # РћС‡РёС‰Р°РµРј С„РёР»СЊС‚СЂС‹
                if user_id in user_filters:
                    del user_filters[user_id]
            else:
                # РќРµС‚ СЃРѕС…СЂР°РЅРµРЅРЅС‹С… СЂРµР·СѓР»СЊС‚Р°С‚РѕРІ - РЅР°С‡РёРЅР°РµРј РЅРѕРІС‹Р№ РїРѕРёСЃРє
                # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹
                user_filters[user_id] = {}
                
                # Р—Р°РїСѓСЃРєР°РµРј РїРѕРёСЃРє Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё
                keyboard = [
                    [InlineKeyboardButton("рџЏ–пёЏ Р•Р№СЃРє", callback_data='location_РµР№СЃРє')],
                    [InlineKeyboardButton("рџЊЉ Р”РѕР»Р¶Р°РЅСЃРєР°СЏ", callback_data='location_РґРѕР»Р¶Р°РЅСЃРєР°СЏ')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text="рџ”Ќ Р”Р°РІР°Р№ РЅР°Р№РґРµРј Р¶РёР»СЊРµ РґР»СЏ С‚РµР±СЏ!\n\n1пёЏвѓЈ Р’С‹Р±РµСЂРё РЅР°СЃРµР»С‘РЅРЅС‹Р№ РїСѓРЅРєС‚:",
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"РћС€РёР±РєР° РїСЂРё СѓРІРµРґРѕРјР»РµРЅРёРё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РѕР± Р°РєС‚РёРІР°С†РёРё: {e}")
            
    except Exception as e:
        await query.edit_message_text(
            f"вќЊ РћС€РёР±РєР° РїСЂРё Р°РєС‚РёРІР°С†РёРё: {e}"
        )


async def activate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РђРєС‚РёРІР°С†РёСЏ РїРѕРґРїРёСЃРєРё РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ (С‚РѕР»СЊРєРѕ РґР»СЏ Р°РґРјРёРЅР°)"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(context.args[0])
        days = int(context.args[1])
        
        end_date = db.add_subscription(user_id, days, f"{days}_days")
        
        # РћС‚РјРµРЅСЏРµРј Р·Р°РїР»Р°РЅРёСЂРѕРІР°РЅРЅРѕРµ РЅР°РїРѕРјРёРЅР°РЅРёРµ РµСЃР»Рё РѕРЅРѕ РµСЃС‚СЊ
        all_jobs = context.job_queue.jobs()
        for job in all_jobs:
            if job.name and job.name.startswith(f'reminder_{user_id}_'):
                job.schedule_removal()
        
        await update.message.reply_text(
            f"вњ… РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂРѕРІР°РЅР°!\n\n"
            f"User ID: {user_id}\n"
            f"Р”РЅРµР№: {days}\n"
            f"Р”Рѕ: {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        
        # РЈРІРµРґРѕРјР»СЏРµРј РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ Рё СЃСЂР°Р·Сѓ Р·Р°РїСѓСЃРєР°РµРј РїРѕРёСЃРє
        try:
            tariff_name = f"{days} " + ("РґРµРЅСЊ" if days == 1 else "РґРЅРµР№")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"рџЋ‰ РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРёСЂРѕРІР°РЅР°!\n\n"
                     f"РўР°СЂРёС„: {tariff_name}\n"
                     f"РђРєС‚РёРІРЅР° РґРѕ: {end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                     f"рџ”Ќ Р”Р°РІР°Р№ РЅР°Р№РґРµРј Р¶РёР»СЊРµ РґР»СЏ С‚РµР±СЏ!"
            )
            
            # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹
            user_filters[user_id] = {}
            
            # Р—Р°РїСѓСЃРєР°РµРј РїРѕРёСЃРє Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё - РџР•Р Р’Р«Р™ Р’РћРџР РћРЎ Рѕ РЅР°СЃРµР»С‘РЅРЅРѕРј РїСѓРЅРєС‚Рµ
            keyboard = [
                [InlineKeyboardButton("рџЏ–пёЏ Р•Р№СЃРє", callback_data='location_РµР№СЃРє')],
                [InlineKeyboardButton("рџЊЉ Р”РѕР»Р¶Р°РЅСЃРєР°СЏ", callback_data='location_РґРѕР»Р¶Р°РЅСЃРєР°СЏ')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=user_id,
                text="1пёЏвѓЈ Р’С‹Р±РµСЂРё РЅР°СЃРµР»С‘РЅРЅС‹Р№ РїСѓРЅРєС‚:",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"РћС€РёР±РєР° РїСЂРё СѓРІРµРґРѕРјР»РµРЅРёРё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РѕР± Р°РєС‚РёРІР°С†РёРё: {e}")
            
    except (IndexError, ValueError):
        await update.message.reply_text(
            "вќЊ РќРµРІРµСЂРЅС‹Р№ С„РѕСЂРјР°С‚ РєРѕРјР°РЅРґС‹\n\n"
            "РСЃРїРѕР»СЊР·СѓР№: /activate <user_id> <РґРЅРё>\n"
            "РџСЂРёРјРµСЂ: /activate 123456789 7"
        )


async def check_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РџСЂРѕРІРµСЂРєР° СЃС‚Р°С‚СѓСЃР° РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ (С‚РѕР»СЊРєРѕ РґР»СЏ Р°РґРјРёРЅР°)"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(context.args[0])
        has_sub, end_date = db.check_subscription(user_id)
        
        if has_sub:
            await update.message.reply_text(
                f"вњ… РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРЅР°\n\n"
                f"User ID: {user_id}\n"
                f"Р”Рѕ: {end_date.strftime('%d.%m.%Y %H:%M')}"
            )
        else:
            await update.message.reply_text(
                f"вќЊ РџРѕРґРїРёСЃРєР° РЅРµР°РєС‚РёРІРЅР°\n\n"
                f"User ID: {user_id}"
            )
    except (IndexError, ValueError):
        await update.message.reply_text(
            "вќЊ РќРµРІРµСЂРЅС‹Р№ С„РѕСЂРјР°С‚\n\n"
            "РСЃРїРѕР»СЊР·СѓР№: /check <user_id>"
        )


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РџРѕРєР°Р· СЃС‚Р°С‚РёСЃС‚РёРєРё (С‚РѕР»СЊРєРѕ РґР»СЏ Р°РґРјРёРЅР°)"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    stats = db.get_stats()
    
    text = "рџ“Љ РЎС‚Р°С‚РёСЃС‚РёРєР° Р±РѕС‚Р°\n\n"
    text += f"рџ‘Ґ Р’СЃРµРіРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№: {stats['total_users']}\n"
    text += f"вњ… РђРєС‚РёРІРЅС‹С… РїРѕРґРїРёСЃРѕРє: {stats['active_subscriptions']}\n"
    text += f"вЏі РћР¶РёРґР°СЋС‚ РѕРїР»Р°С‚С‹: {stats['pending_payments']}\n"
    text += f"рџ”Ќ РџРѕРёСЃРєРѕРІ СЃРµРіРѕРґРЅСЏ: {stats['searches_today']}\n"
    
    await update.message.reply_text(text)


async def show_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РџРѕРєР°Р· РѕР¶РёРґР°СЋС‰РёС… РѕРїР»Р°С‚ (С‚РѕР»СЊРєРѕ РґР»СЏ Р°РґРјРёРЅР°)"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    pending = db.get_pending_payments()
    
    if not pending:
        await update.message.reply_text("вњ… РќРµС‚ РѕР¶РёРґР°СЋС‰РёС… РѕРїР»Р°С‚")
        return
    
    text = "вЏі РћР¶РёРґР°СЋС‰РёРµ РѕРїР»Р°С‚С‹:\n\n"
    for req_id, user_id, username, first_name, tariff, created_at in pending:
        text += f"ID: {req_id}\n"
        text += f"User: @{username or 'РЅРµС‚'} ({first_name})\n"
        text += f"User ID: {user_id}\n"
        text += f"РўР°СЂРёС„: {tariff}\n"
        text += f"РЎРѕР·РґР°РЅРѕ: {created_at}\n"
        text += f"РђРєС‚РёРІРёСЂРѕРІР°С‚СЊ: /activate {user_id} {TARIFFS[tariff]['days']}\n\n"
    
    await update.message.reply_text(text)


async def show_more_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РєРЅРѕРїРєРё 'РџРѕРєР°Р·Р°С‚СЊ РµС‰Рµ'"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user_id = query.from_user.id
    
    # РџРѕР»СѓС‡Р°РµРј СЃРѕС…СЂР°РЅРµРЅРЅС‹Рµ РґР°РЅРЅС‹Рµ
    if user_id not in user_pagination_data:
        await query.edit_message_text(
            "вљ пёЏ Р”Р°РЅРЅС‹Рµ РїРѕРёСЃРєР° СѓСЃС‚Р°СЂРµР»Рё. РќР°С‡РЅРёС‚Рµ РЅРѕРІС‹Р№ РїРѕРёСЃРє:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("рџ”Ќ РќРѕРІС‹Р№ РїРѕРёСЃРє", callback_data='new_search')
            ]])
        )
        return
    
    data = user_pagination_data[user_id]
    filtered = data['filtered']
    next_index = data['next_index']
    
    await query.edit_message_text("рџ”Ќ Р—Р°РіСЂСѓР¶Р°СЋ РµС‰Рµ РІР°СЂРёР°РЅС‚С‹...")
    
    # РџРѕРєР°Р·С‹РІР°РµРј СЃР»РµРґСѓСЋС‰СѓСЋ РїРѕСЂС†РёСЋ
    await show_results_function(context, user_id, filtered, start_index=next_index)
    
    # РћС‡РёС‰Р°РµРј РґР°РЅРЅС‹Рµ РїР°РіРёРЅР°С†РёРё РµСЃР»Рё РІСЃРµ РїРѕРєР°Р·Р°РЅРѕ
    remaining = len(filtered) - next_index - RESULTS_PER_PAGE
    if remaining <= 0:
        if user_id in user_pagination_data:
            del user_pagination_data[user_id]


async def go_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РєРЅРѕРїРєРё 'Р’ РЅР°С‡Р°Р»Рѕ'"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user_id = query.from_user.id
    user = query.from_user
    
    # РџСЂРѕРІРµСЂСЏРµРј РїРѕРґРїРёСЃРєСѓ РґР»СЏ РёРЅС„РѕСЂРјР°С†РёРё
    has_subscription, end_date = db.check_subscription(user_id)
    
    # РџСЂРёРІРµС‚СЃС‚РІРёРµ
    if has_subscription:
        await query.edit_message_text(
            f"{WELCOME_TEXT}\n\n"
            f"вњ… РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРЅР° РґРѕ {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
    else:
        await query.edit_message_text(WELCOME_TEXT)
    
    # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј С„РёР»СЊС‚СЂС‹ РґР»СЏ РІСЃРµС…
    user_filters[user_id] = {}
    
    # РџРѕРєР°Р·С‹РІР°РµРј РІС‹Р±РѕСЂ РЅР°СЃРµР»С‘РЅРЅРѕРіРѕ РїСѓРЅРєС‚Р°
    keyboard = [
        [InlineKeyboardButton("рџЏ–пёЏ Р•Р№СЃРє", callback_data='location_РµР№СЃРє')],
        [InlineKeyboardButton("рџЊЉ Р”РѕР»Р¶Р°РЅСЃРєР°СЏ", callback_data='location_РґРѕР»Р¶Р°РЅСЃРєР°СЏ')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=user_id,
        text="рџ”Ќ Р”Р°РІР°Р№ РЅР°Р№РґРµРј РёРґРµР°Р»СЊРЅРѕРµ Р¶РёР»СЊРµ!\n\n"
             "1пёЏвѓЈ Р’С‹Р±РµСЂРё РЅР°СЃРµР»С‘РЅРЅС‹Р№ РїСѓРЅРєС‚:",
        reply_markup=reply_markup
    )


async def new_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """РћР±СЂР°Р±РѕС‚С‡РёРє РєРЅРѕРїРєРё 'РќРѕРІС‹Р№ РїРѕРёСЃРє'"""
    query = update.callback_query
    await safe_answer_callback(query)
    
    user_id = query.from_user.id
    
    # РћС‡РёС‰Р°РµРј СЃС‚Р°СЂС‹Рµ С„РёР»СЊС‚СЂС‹ РµСЃР»Рё РµСЃС‚СЊ
    if user_id in user_filters:
        del user_filters[user_id]
    
    # РРЅРёС†РёР°Р»РёР·РёСЂСѓРµРј РЅРѕРІС‹Рµ С„РёР»СЊС‚СЂС‹
    user_filters[user_id] = {}
    
    # РџРѕРєР°Р·С‹РІР°РµРј РІС‹Р±РѕСЂ РЅР°СЃРµР»С‘РЅРЅРѕРіРѕ РїСѓРЅРєС‚Р°
    keyboard = [
        [InlineKeyboardButton("рџЏ–пёЏ Р•Р№СЃРє", callback_data='location_РµР№СЃРє')],
        [InlineKeyboardButton("рџЊЉ Р”РѕР»Р¶Р°РЅСЃРєР°СЏ", callback_data='location_РґРѕР»Р¶Р°РЅСЃРєР°СЏ')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "рџ”Ќ Р”Р°РІР°Р№ РЅР°Р№РґРµРј РёРґРµР°Р»СЊРЅРѕРµ Р¶РёР»СЊРµ!\n\n"
        "1пёЏвѓЈ Р’С‹Р±РµСЂРё РЅР°СЃРµР»С‘РЅРЅС‹Р№ РїСѓРЅРєС‚:",
        reply_markup=reply_markup
    )


# РљРѕРЅСЃС‚Р°РЅС‚Р° РґР»СЏ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЏ РІ show_more_handler
RESULTS_PER_PAGE = 20


def main():
    """Р—Р°РїСѓСЃРє Р±РѕС‚Р°"""
    # РЎРѕР·РґР°РµРј РїСЂРёР»РѕР¶РµРЅРёРµ
    application = Application.builder().token(BOT_TOKEN).build()

    # Р РµРіРёСЃС‚СЂРёСЂСѓРµРј РѕР±СЂР°Р±РѕС‚С‡РёРєРё
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('search', search_start))
    application.add_handler(CommandHandler('cancel', cancel))

    # РћР±СЂР°Р±РѕС‚С‡РёРєРё РѕРїР»Р°С‚С‹ Stars
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_stars))

    # РћР±СЂР°Р±РѕС‚С‡РёРєРё РєРЅРѕРїРѕРє (callback queries)
    application.add_handler(CallbackQueryHandler(buy_subscription, pattern='^buy_'))
    application.add_handler(CallbackQueryHandler(pay_with_card, pattern='^pay_card_'))
    application.add_handler(CallbackQueryHandler(pay_with_stars, pattern='^pay_stars_'))
    application.add_handler(CallbackQueryHandler(pay_with_usdt, pattern='^pay_usdt_'))
    application.add_handler(CallbackQueryHandler(payment_confirmation, pattern='^paid_'))
    application.add_handler(CallbackQueryHandler(admin_activate_handler, pattern='^admin_activate_'))
    application.add_handler(CallbackQueryHandler(select_location, pattern='^location_'))
    application.add_handler(CallbackQueryHandler(select_type, pattern='^type_'))
    application.add_handler(CallbackQueryHandler(select_guests, pattern='^guests_'))
    application.add_handler(CallbackQueryHandler(select_two_rooms, pattern='^two_rooms_'))
    application.add_handler(CallbackQueryHandler(select_distance, pattern='^dist_'))
    application.add_handler(CallbackQueryHandler(go_start_handler, pattern='^go_start$'))
    application.add_handler(CallbackQueryHandler(new_search_handler, pattern='^new_search$'))
    application.add_handler(CallbackQueryHandler(show_more_handler, pattern='^show_more$'))
    application.add_handler(CallbackQueryHandler(subscribe_alerts_handler, pattern='^alerts_subscribe$'))

    # РђРґРјРёРЅСЃРєРёРµ РєРѕРјР°РЅРґС‹
    application.add_handler(CommandHandler('activate', activate_user))
    application.add_handler(CommandHandler('check', check_user))
    application.add_handler(CommandHandler('stats', show_stats))
    application.add_handler(CommandHandler('pending', show_pending))

    # Р¤РѕРЅРѕРІР°СЏ РїСЂРѕРІРµСЂРєР° РЅРѕРІС‹С… РѕР±СЉСЏРІР»РµРЅРёР№ РґР»СЏ РїРѕРґРїРёСЃС‡РёРєРѕРІ СѓРІРµРґРѕРјР»РµРЅРёР№
    if application.job_queue:
        application.job_queue.run_repeating(
            check_new_apartments_job,
            interval=NOTIFICATION_CHECK_INTERVAL_SECONDS,
            first=30,
            name='new_apartments_checker'
        )
    else:
        logger.warning(
            "JobQueue РЅРµРґРѕСЃС‚СѓРїРµРЅ. РЈСЃС‚Р°РЅРѕРІРёС‚Рµ Р·Р°РІРёСЃРёРјРѕСЃС‚Рё: "
            "pip install \"python-telegram-bot[job-queue]==21.7\""
        )

    # Р—Р°РїСѓСЃРєР°РµРј Р±РѕС‚Р°
    logger.info("Р‘РѕС‚ Р·Р°РїСѓС‰РµРЅ!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

