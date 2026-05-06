#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eysk VK Bot - Поиск жилья в Ейске и Должанской
Портирован с Telegram на ВКонтакте
"""

import asyncio
import logging
import random
import hashlib
import json
import aiohttp
from datetime import datetime
import pytz

from vkbottle.bot import Bot, Message
from vkbottle import GroupEventType
from vkbottle.tools import Keyboard, Text, Callback

from config import VK_TOKEN, ADMIN_VK_ID, TARIFFS, PAYMENT_PHONE, USDT_WALLET, WELCOME_TEXT
from database import Database
from sheets_reader import GoogleSheetsReader

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация
db = Database()
sheets = GoogleSheetsReader()
bot = Bot(token=VK_TOKEN)

# Временное хранилище состояния пользователей (в памяти)
user_filters = {}
user_pagination_data = {}
user_search_results = {}
user_writing_to_community = set()  # пользователи в режиме "написать сообществу"

# Константы
PREVIEW_RESULTS_LIMIT = 2
NOTIFICATION_CHECK_INTERVAL_SECONDS = 900
NOTIFICATION_NEW_ITEMS_LIMIT = 3
RESULTS_PER_PAGE = 20


# ─────────────────── Вспомогательные функции ───────────────────

def build_apartment_key(apartment: dict) -> str:
    """Стабильный ключ объявления для дедупликации."""
    key_parts = [
        apartment.get('Населенный_пункт', '').strip(),
        apartment.get('Тип_жилья', '').strip(),
        apartment.get('Расстояние_от_моря_м', '').strip(),
        apartment.get('Гостей_макс', '').strip(),
        apartment.get('Цена_за_сутки', '').strip(),
        apartment.get('Телефон', '').strip(),
        apartment.get('Имя_хозяина', '').strip(),
        apartment.get('VK_ссылка', '').strip(),
        apartment.get('Фото_URL', '').strip(),
    ]
    raw = "|".join(key_parts)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def get_fake_views_count(apartment_key: str) -> int:
    """Стабильный псевдо-случайный счётчик просмотров."""
    rng = random.Random(apartment_key)
    return rng.randint(8, 39)


def is_payment_time() -> bool:
    """Проверяет, доступна ли оплата (11:00–23:00 МСК)."""
    msk_tz = pytz.timezone('Europe/Moscow')
    now_msk = datetime.now(msk_tz)
    return 11 <= now_msk.hour < 23


async def seed_seen_apartments_for_user(user_id: int):
    """Помечает все текущие объявления как уже виденные, чтобы уведомлять только о новых."""
    all_apartments = sheets.read_apartments()
    all_keys = [build_apartment_key(apt) for apt in all_apartments]
    db.add_seen_apartments(user_id, all_keys)


async def get_user_first_name(user_id: int) -> str:
    """Получает имя пользователя ВКонтакте."""
    try:
        users = await bot.api.users.get(user_ids=[user_id])
        return users[0].first_name if users else "Пользователь"
    except Exception:
        return "Пользователь"


# ─────────────────── Сборка клавиатур ───────────────────

def kb_main_menu() -> Keyboard:
    kb = Keyboard(inline=True)
    kb.add(Callback("🔍 Найти жильё через бота", {"a": "search_housing"}))
    kb.row()
    kb.add(Callback("📋 Написать сообществу (администратору)", {"a": "post_announcement"}))
    return kb


def kb_location() -> Keyboard:
    kb = Keyboard(inline=True)
    kb.add(Callback("🏖️ Ейск", {"a": "loc_ейск"}))
    kb.row()
    kb.add(Callback("🌊 Должанская", {"a": "loc_должанская"}))
    return kb


def kb_subscription() -> Keyboard:
    kb = Keyboard(inline=True)
    kb.add(Callback(f"💳 {TARIFFS['1_day']['name']} — {TARIFFS['1_day']['price']}₽", {"a": "buy_1_day"}))
    kb.row()
    kb.add(Callback(f"💳 {TARIFFS['7_days']['name']} — {TARIFFS['7_days']['price']}₽", {"a": "buy_7_days"}))
    kb.row()
    kb.add(Callback(f"💳 {TARIFFS['30_days']['name']} — {TARIFFS['30_days']['price']}₽", {"a": "buy_30_days"}))
    kb.row()
    kb.add(Callback("🔍 Новый поиск", {"a": "new_search"}))
    return kb


def kb_distance() -> Keyboard:
    kb = Keyboard(inline=True)
    kb.add(Callback("🏖️ До 100м", {"a": "dist_0-100"}))
    kb.row()
    kb.add(Callback("🚶 150–500м", {"a": "dist_150-500"}))
    kb.row()
    kb.add(Callback("🚗 500–1000м", {"a": "dist_500-1000"}))
    kb.row()
    kb.add(Callback("🏙️ Более 1000м", {"a": "dist_1000-99999"}))
    kb.row()
    kb.add(Callback("➡️ Не важно", {"a": "dist_any"}))
    kb.row()
    kb.add(Callback("🔙 Назад", {"a": "go_start"}))
    return kb


# ─────────────────── Отправка / редактирование сообщений ───────────────────

async def send_msg(peer_id: int, text: str, keyboard: Keyboard = None, attachment: str = None):
    """Отправить сообщение пользователю."""
    kwargs = {
        "peer_id": peer_id,
        "message": text,
        "random_id": random.randint(0, 2 ** 31),
    }
    if keyboard:
        kwargs["keyboard"] = keyboard.get_json()
    if attachment:
        kwargs["attachment"] = attachment
    await bot.api.messages.send(**kwargs)


async def edit_msg(peer_id: int, cmid: int, text: str, keyboard: Keyboard = None):
    """Отредактировать сообщение бота (только внутри обработчика callback)."""
    kwargs = {
        "peer_id": peer_id,
        "conversation_message_id": cmid,
        "message": text,
    }
    if keyboard:
        kwargs["keyboard"] = keyboard.get_json()
    try:
        await bot.api.messages.edit(**kwargs)
    except Exception as e:
        logger.warning(f"Не удалось отредактировать сообщение (peer={peer_id}, cmid={cmid}): {e}")
        # Если не получилось отредактировать — отправляем новое
        await send_msg(peer_id, text, keyboard)


async def upload_photo(peer_id: int, photo_url: str) -> str | None:
    """Загружает фото по URL в VK и возвращает attachment-строку вида photo{owner}_{id}."""
    try:
        upload_server = await bot.api.photos.get_messages_upload_server(peer_id=peer_id)
        async with aiohttp.ClientSession() as session:
            async with session.get(photo_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                photo_data = await resp.read()

            form = aiohttp.FormData()
            form.add_field("photo", photo_data, filename="photo.jpg", content_type="image/jpeg")

            async with session.post(upload_server.upload_url, data=form) as resp:
                if resp.status != 200:
                    return None
                result = await resp.json(content_type=None)

        saved = await bot.api.photos.save_messages_photo(
            photo=result["photo"],
            server=result["server"],
            hash=result["hash"],
        )
        photo = saved[0]
        return f"photo{photo.owner_id}_{photo.id}"
    except Exception as e:
        logger.error(f"Ошибка загрузки фото {photo_url}: {e}")
        return None


# ─────────────────── Показ объявлений ───────────────────

async def send_apartment(peer_id: int, apt: dict, idx: int,
                         show_contacts: bool = True, show_vk: bool = True):
    """Отправляет одно объявление."""
    text = f"📍 Вариант {idx} ⬇️⬇️⬇️\n\n"

    tip = apt.get('Тип_жилья', 'не указан')
    tip_map = {
        '1-комн': '1-комнатная квартира',
        '2-комн': '2-комнатная квартира',
        '3-комн': '3-комнатная квартира',
        'частный дом': 'Частный дом',
        'гостевой дом': 'Гостевой дом',
    }
    tip = tip_map.get(tip, tip)

    text += f"🏠 {tip}\n"
    text += f"🏖️ {apt.get('Расстояние_от_моря_м', '?')} метров от моря\n"
    text += f"👥 До {apt.get('Гостей_макс', '?')} гостей\n"

    price = apt.get('Цена_за_сутки', '')
    if price and price != 'по запросу':
        text += f"💰 {price}₽/сутки\n"
    else:
        text += "💰 Цена по запросу\n"

    description = apt.get('Описание', '').strip()
    if description:
        text += f"\n📝 {description}\n"

    apt_key = build_apartment_key(apt)
    views_count = get_fake_views_count(apt_key)
    text += f"\n🔥 Этот вариант смотрели {views_count} раз\n"

    if show_contacts:
        text += f"\n📞 {apt.get('Телефон', 'не указан')}\n"
        owner = apt.get('Имя_хозяина', '').strip()
        if owner:
            text += f"👤 {owner}\n"
    else:
        text += "\n🔒 Контакты доступны после активации подписки\n"

    vk_link = apt.get('VK_ссылка', '').strip()
    if show_vk and vk_link and vk_link.startswith('http'):
        text += f"\n🔗 Подробнее: {vk_link}"

    photo_url = apt.get('Фото_URL', '').strip()
    attachment = None
    if photo_url and photo_url.startswith('http'):
        attachment = await upload_photo(peer_id, photo_url)

    await send_msg(peer_id, text, attachment=attachment)


async def show_results_function(peer_id: int, filtered: list, start_index: int = 0,
                                show_contacts: bool = True, show_vk: bool = True):
    """Показывает результаты поиска с пагинацией."""
    total_results = len(filtered)
    end_index = min(start_index + RESULTS_PER_PAGE, total_results)
    current_batch = filtered[start_index:end_index]

    if start_index == 0:
        await send_msg(peer_id, f"✅ Найдено вариантов: {total_results}\n\nСейчас покажу их по очереди:")

    for i, apt in enumerate(current_batch, start_index + 1):
        await send_apartment(peer_id, apt, i, show_contacts, show_vk)

    remaining = total_results - end_index

    if remaining > 0 and show_contacts:
        user_pagination_data[peer_id] = {'filtered': filtered, 'next_index': end_index}
        kb = Keyboard(inline=True)
        kb.add(Callback(f"📋 Показать ещё {remaining}", {"a": "show_more"}))
        kb.row()
        kb.add(Callback("🔔 Подписаться на новые", {"a": "alerts_sub"}))
        kb.row()
        kb.add(Callback("🔍 Новый поиск", {"a": "new_search"}))
        kb.row()
        kb.add(Callback("📋 Написать сообществу (администратору)", {"a": "post_announcement"}))
        await send_msg(peer_id, f"✅ Показано {end_index} из {total_results} вариантов", kb)
    elif show_contacts:
        kb = Keyboard(inline=True)
        kb.add(Callback("🔔 Подписаться на новые", {"a": "alerts_sub"}))
        kb.row()
        kb.add(Callback("🔍 Новый поиск", {"a": "new_search"}))
        kb.row()
        kb.add(Callback("📋 Написать сообществу (администратору)", {"a": "post_announcement"}))
        await send_msg(peer_id, "✅ Все результаты показаны!", kb)


async def show_preview_results_function(peer_id: int, filtered: list):
    """Бесплатный превью — 2 объявления без контактов и ссылок."""
    preview_items = filtered[:PREVIEW_RESULTS_LIMIT]
    if not preview_items:
        return
    await send_msg(
        peer_id,
        f"👀 Бесплатный превью: {len(preview_items)} из {len(filtered)} вариантов\n\n"
        f"Показываю примеры без контактов и без ссылок."
    )
    await show_results_function(peer_id, preview_items, start_index=0,
                                show_contacts=False, show_vk=False)


# ─────────────────── Обработчики команд (текстовые сообщения) ───────────────────

@bot.on.message(text=["/start", "Начать", "начать", "Старт", "старт"])
async def cmd_start(message: Message):
    user_id = message.from_id
    first_name = await get_user_first_name(user_id)
    db.add_user(user_id, None, first_name)

    has_subscription, end_date = db.check_subscription(user_id)
    welcome = WELCOME_TEXT
    if has_subscription:
        welcome += f"\n✅ Подписка активна до {end_date.strftime('%d.%m.%Y %H:%M')}\n"

    user_filters[user_id] = {}
    await send_msg(user_id, welcome, kb_main_menu())


@bot.on.message(text=["/search", "Поиск", "поиск"])
async def cmd_search(message: Message):
    user_id = message.from_id
    user_filters[user_id] = {}
    await send_msg(user_id, "🔍 Давай найдём идеальное жильё!\n\n1️⃣ Выбери населённый пункт:", kb_location())


# ─── Админские команды ───

@bot.on.message(text="/activate <uid> <days>")
async def cmd_activate(message: Message, uid: str, days: str):
    if message.from_id != ADMIN_VK_ID:
        return
    try:
        target_id = int(uid)
        days_int = int(days)
        end_date = db.add_subscription(target_id, days_int, f"{days_int}_days")
        await message.answer(
            f"✅ Подписка активирована!\n"
            f"User VK ID: {target_id}\n"
            f"Дней: {days_int}\n"
            f"До: {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        tariff_name = f"{days_int} " + ("день" if days_int == 1 else "дней")
        try:
            await send_msg(target_id,
                           f"🎉 Подписка активирована!\nТариф: {tariff_name}\n"
                           f"Активна до: {end_date.strftime('%d.%m.%Y %H:%M')}")
            user_filters[target_id] = {}
            await send_msg(target_id,
                           "🔍 Давай найдём жильё для тебя!\n\n1️⃣ Выбери населённый пункт:",
                           kb_location())
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя {target_id}: {e}")
    except (ValueError, TypeError):
        await message.answer("❌ Формат: /activate <vk_user_id> <дни>\nПример: /activate 12345678 7")


@bot.on.message(text="/check <uid>")
async def cmd_check(message: Message, uid: str):
    if message.from_id != ADMIN_VK_ID:
        return
    try:
        target_id = int(uid)
        has_sub, end_date = db.check_subscription(target_id)
        if has_sub:
            await message.answer(f"✅ Подписка активна\nUser VK ID: {target_id}\nДо: {end_date.strftime('%d.%m.%Y %H:%M')}")
        else:
            await message.answer(f"❌ Подписка неактивна\nUser VK ID: {target_id}")
    except (ValueError, TypeError):
        await message.answer("❌ Формат: /check <vk_user_id>")


@bot.on.message(text="/stats")
async def cmd_stats(message: Message):
    if message.from_id != ADMIN_VK_ID:
        return
    stats = db.get_stats()
    text = (
        "📊 Статистика бота\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"✅ Активных подписок: {stats['active_subscriptions']}\n"
        f"⏳ Ожидают оплаты: {stats['pending_payments']}\n"
        f"🔍 Поисков сегодня: {stats['searches_today']}\n"
    )
    await message.answer(text)


@bot.on.message(text="/pending")
async def cmd_pending(message: Message):
    if message.from_id != ADMIN_VK_ID:
        return
    pending = db.get_pending_payments()
    if not pending:
        await message.answer("✅ Нет ожидающих оплат")
        return
    text = "⏳ Ожидающие оплаты:\n\n"
    for req_id, uid, username, first_name, tariff, created_at in pending:
        days = TARIFFS[tariff]['days'] if tariff in TARIFFS else '?'
        text += (
            f"ID заявки: {req_id}\n"
            f"Пользователь: {first_name} (VK ID: {uid})\n"
            f"Тариф: {tariff}\n"
            f"Создано: {created_at}\n"
            f"Активировать: /activate {uid} {days}\n\n"
        )
    await message.answer(text)


# ─────────────────── Catch-all: приём сообщений для администратора ───────────────────

@bot.on.message()
async def handle_free_message(message: Message):
    user_id = message.from_id
    text_lower = (message.text or "").strip().lower()

    # Пропускаем все известные команды — их обработают другие хэндлеры
    known = ["/start", "/search", "/activate", "/check", "/stats", "/pending",
             "начать", "старт", "поиск"]
    if any(text_lower == cmd or text_lower.startswith(cmd + " ") for cmd in known):
        return

    if user_id not in user_writing_to_community:
        return

    user_writing_to_community.discard(user_id)
    # Сообщение уже видно администратору в Управление → Сообщения.
    # Дополнительная пересылка не нужна.

    # Подтверждаем пользователю
    kb = Keyboard(inline=True)
    kb.add(Callback("🏠 В начало", {"a": "go_start"}))
    await send_msg(
        user_id,
        "✅ Ваше сообщение отправлено администратору!\n\nМы ответим вам в ближайшее время.",
        kb
    )


# ─────────────────── Обработчик callback-кнопок ───────────────────

@bot.on.raw_event(GroupEventType.MESSAGE_EVENT, dataclass=dict)
async def handle_callback(event: dict):
    obj = event.get('object', {})
    user_id: int = obj.get('user_id')
    peer_id: int = obj.get('peer_id')
    cmid: int = obj.get('conversation_message_id')
    event_id: str = obj.get('event_id')

    if not user_id or not peer_id or not cmid:
        return

    # Подтверждаем нажатие кнопки (обязательно)
    try:
        await bot.api.messages.send_message_event_answer(
            event_id=event_id,
            user_id=user_id,
            peer_id=peer_id,
        )
    except Exception as e:
        logger.warning(f"Не удалось ответить на callback: {e}")

    # Читаем payload
    raw_payload = obj.get('payload', {})
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            raw_payload = {}
    action: str = raw_payload.get('a', '')

    if not action:
        return

    # ── Выбор города ──
    if action.startswith('loc_'):
        location = action.replace('loc_', '')
        if user_id not in user_filters:
            user_filters[user_id] = {}
        user_filters[user_id]['location'] = location

        if location == 'должанская':
            await edit_msg(peer_id, cmid, "🔍 Ищу все варианты в Должанской...")
            all_apts = sheets.read_apartments()
            filtered = [a for a in all_apts if a.get('Населенный_пункт', '').lower() == 'должанская']
            db.log_search(user_id, user_filters[user_id], len(filtered))

            if not filtered:
                kb = Keyboard(inline=True)
                kb.add(Callback("🔍 Новый поиск", {"a": "new_search"}))
                await send_msg(peer_id, "😔 В Должанской пока нет объявлений.", kb)
                user_filters.pop(user_id, None)
                return

            has_sub, _ = db.check_subscription(user_id)
            if has_sub:
                await show_results_function(peer_id, filtered)
                user_filters.pop(user_id, None)
            else:
                user_search_results[user_id] = filtered
                await show_preview_results_function(peer_id, filtered)
                await send_msg(
                    peer_id,
                    f"✅ Найдено вариантов: {len(filtered)}\n\n"
                    f"Полный доступ к контактам открывается по подписке.\n\nВыбери тариф:",
                    kb_subscription()
                )
        else:
            kb = Keyboard(inline=True)
            kb.add(Callback("🏠 1-комнатная", {"a": "type_1-комн"}))
            kb.row()
            kb.add(Callback("🏡 2-комнатная", {"a": "type_2-комн"}))
            kb.row()
            kb.add(Callback("🏘 3-комнатная", {"a": "type_3-комн"}))
            kb.row()
            kb.add(Callback("🏘️ Частный дом", {"a": "type_частный дом"}))
            kb.row()
            kb.add(Callback("🏨 Гостевой дом", {"a": "type_гостевой дом"}))
            kb.row()
            kb.add(Callback("➡️ Любой тип", {"a": "type_any"}))
            kb.row()
            kb.add(Callback("🔙 Назад", {"a": "go_start"}))
            await edit_msg(peer_id, cmid, "2️⃣ Какой тип жилья тебе нужен?", kb)

    # ── Выбор типа жилья ──
    elif action.startswith('type_'):
        type_choice = action.replace('type_', '')
        if user_id not in user_filters:
            user_filters[user_id] = {}
        if type_choice != 'any':
            user_filters[user_id]['type'] = type_choice

        kb = Keyboard(inline=True)
        kb.add(Callback("👤 1–2 гостя", {"a": "guests_2"}))
        kb.row()
        kb.add(Callback("👥 3–4 гостя", {"a": "guests_4"}))
        kb.row()
        kb.add(Callback("👨‍👩‍👧‍👦 5–6 гостей", {"a": "guests_6"}))
        kb.row()
        kb.add(Callback("🏢 7+ гостей", {"a": "guests_7"}))
        kb.row()
        kb.add(Callback("➡️ Не важно", {"a": "guests_any"}))
        kb.row()
        kb.add(Callback("🔙 Назад", {"a": "go_start"}))
        await edit_msg(peer_id, cmid, "3️⃣ Сколько человек будет отдыхать?", kb)

    # ── Выбор количества гостей ──
    elif action.startswith('guests_'):
        guests_choice = action.replace('guests_', '')
        if user_id not in user_filters:
            user_filters[user_id] = {}
        if guests_choice != 'any':
            user_filters[user_id]['guests'] = int(guests_choice)

        is_guesthouse = user_filters[user_id].get('type') == 'гостевой дом'
        is_many_guests = guests_choice in ['6', '7']

        if is_guesthouse and is_many_guests:
            kb = Keyboard(inline=True)
            kb.add(Callback("✅ Да, подойдёт 2 номера", {"a": "two_rooms_yes"}))
            kb.row()
            kb.add(Callback("❌ Нет, нужен один номер", {"a": "two_rooms_no"}))
            kb.row()
            kb.add(Callback("🔙 Назад", {"a": "go_start"}))
            await edit_msg(peer_id, cmid,
                           "💡 Вам подойдёт 2 номера?\n\n"
                           "Это увеличит шансы найти варианты для большой компании!", kb)
            return

        await edit_msg(peer_id, cmid, "4️⃣ На каком расстоянии от моря?", kb_distance())

    # ── Вопрос про 2 номера ──
    elif action.startswith('two_rooms_'):
        answer = action.replace('two_rooms_', '')
        if user_id not in user_filters:
            user_filters[user_id] = {}
        if answer == 'yes':
            user_filters[user_id]['guests'] = 6
            user_filters[user_id]['two_rooms_mode'] = True
        await edit_msg(peer_id, cmid, "4️⃣ На каком расстоянии от моря?", kb_distance())

    # ── Выбор расстояния (последний вопрос → показ результатов) ──
    elif action.startswith('dist_'):
        dist_choice = action.replace('dist_', '')
        if user_id not in user_filters:
            user_filters[user_id] = {}

        if dist_choice != 'any':
            min_dist, max_dist = dist_choice.split('-')
            user_filters[user_id]['min_distance'] = int(min_dist)
            user_filters[user_id]['max_distance'] = int(max_dist)

        filters = user_filters[user_id]
        has_filters = any([
            filters.get('type'),
            filters.get('guests'),
            filters.get('min_distance'),
            filters.get('max_distance'),
        ])

        if not has_filters:
            kb = Keyboard(inline=True)
            kb.add(Callback("🔍 Новый поиск", {"a": "new_search"}))
            await edit_msg(peer_id, cmid,
                           "🤔 Ты не выбрал ни одного параметра.\n\n"
                           "Выбери хотя бы один фильтр (тип жилья, количество гостей или расстояние).", kb)
            user_filters.pop(user_id, None)
            return

        await edit_msg(peer_id, cmid, "🔍 Ищу подходящие варианты...")

        all_apts = sheets.read_apartments()
        filtered = sheets.filter_apartments(all_apts, user_filters[user_id])
        db.log_search(user_id, user_filters[user_id], len(filtered))

        if not filtered:
            kb = Keyboard(inline=True)
            kb.add(Callback("🔍 Новый поиск", {"a": "new_search"}))
            await send_msg(peer_id, "😔 По твоим критериям ничего не найдено. Попробуй изменить параметры:", kb)
            user_filters.pop(user_id, None)
            return

        has_sub, _ = db.check_subscription(user_id)
        if has_sub:
            await show_results_function(peer_id, filtered)
            user_filters.pop(user_id, None)
        else:
            user_search_results[user_id] = filtered
            await show_preview_results_function(peer_id, filtered)
            await send_msg(
                peer_id,
                f"✅ Найдено вариантов: {len(filtered)}\n\n"
                f"Полный доступ к контактам открывается по подписке.\n\nВыбери тариф:",
                kb_subscription()
            )

    # ── Покупка подписки (выбор тарифа) ──
    elif action.startswith('buy_'):
        tariff_key = action.replace('buy_', '')
        if tariff_key not in TARIFFS:
            return
        tariff = TARIFFS[tariff_key]

        kb = Keyboard(inline=True)
        kb.add(Callback(f"📱 Мобильный — {tariff['price']}₽", {"a": f"pay_card_{tariff_key}"}))
        kb.row()
        kb.add(Callback(f"💵 USDT (BEP-20) — {tariff['price_usdt']} USDT", {"a": f"pay_usdt_{tariff_key}"}))
        kb.row()
        kb.add(Callback("🔙 Назад", {"a": "go_start"}))
        await edit_msg(
            peer_id, cmid,
            f"💰 Оплата подписки: {tariff['name']}\n\n"
            f"Выбери способ оплаты:\n\n"
            f"📱 Мобильный: {tariff['price']}₽\n"
            f"💵 USDT: {tariff['price_usdt']} USDT",
            kb
        )

    # ── Оплата мобильным ──
    elif action.startswith('pay_card_'):
        tariff_key = action.replace('pay_card_', '')
        if tariff_key not in TARIFFS:
            return
        tariff = TARIFFS[tariff_key]

        if not is_payment_time():
            msk_tz = pytz.timezone('Europe/Moscow')
            current_time = datetime.now(msk_tz).strftime('%H:%M')
            kb = Keyboard(inline=True)
            kb.add(Callback("🏠 В начало", {"a": "go_start"}))
            await edit_msg(peer_id, cmid,
                           f"⏰ Оплата временно недоступна\n\n"
                           f"Текущее время МСК: {current_time}\n\n"
                           f"Оплата доступна только с 11:00 до 23:00 МСК\n\nПопробуй позже!", kb)
            return

        request_id = db.add_payment_request(user_id, tariff_key, 'mobile')

        try:
            await send_msg(
                ADMIN_VK_ID,
                f"💰 Новая заявка на оплату!\n\n"
                f"ID заявки: {request_id}\n"
                f"Способ: 📱 Пополнение мобильного\n"
                f"User VK ID: {user_id}\n"
                f"Тариф: {tariff['name']} — {tariff['price']}₽"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления админа: {e}")

        kb = Keyboard(inline=True)
        kb.add(Callback("✅ Я оплатил", {"a": f"paid_card_{request_id}_{tariff_key}"}))
        kb.row()
        kb.add(Callback("🔙 Назад", {"a": "go_start"}))
        await edit_msg(
            peer_id, cmid,
            f"📱 Оплата подписки: {tariff['name']}\n"
            f"Сумма: {tariff['price']}₽\n\n"
            f"💰 Пополните баланс мобильного:\n"
            f"Номер: {PAYMENT_PHONE}\n"
            f"Оператор: Теле2\n\n"
            f"После оплаты нажми кнопку ниже.\n"
            f"Доступ будет активирован в течение 15 минут.\n\n"
            f"⏰ Подписка активируется только с 11:00 до 23:00 МСК",
            kb
        )

    # ── Оплата USDT ──
    elif action.startswith('pay_usdt_'):
        tariff_key = action.replace('pay_usdt_', '')
        if tariff_key not in TARIFFS:
            return
        tariff = TARIFFS[tariff_key]

        request_id = db.add_payment_request(user_id, tariff_key, 'usdt')

        try:
            await send_msg(
                ADMIN_VK_ID,
                f"💰 Новая заявка на оплату!\n\n"
                f"ID заявки: {request_id}\n"
                f"Способ: 💵 USDT (BEP-20)\n"
                f"User VK ID: {user_id}\n"
                f"Тариф: {tariff['name']} — {tariff['price_usdt']} USDT"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления админа: {e}")

        kb = Keyboard(inline=True)
        kb.add(Callback("✅ Я оплатил", {"a": f"paid_usdt_{request_id}_{tariff_key}"}))
        kb.row()
        kb.add(Callback("🔙 Назад", {"a": "go_start"}))
        await edit_msg(
            peer_id, cmid,
            f"💵 Оплата подписки: {tariff['name']}\n"
            f"Сумма: {tariff['price_usdt']} USDT\n\n"
            f"💰 Адрес кошелька USDT (BEP-20):\n"
            f"{USDT_WALLET}\n\n"
            f"⚠️ Отправляйте ТОЛЬКО USDT по сети BEP-20 (Binance Smart Chain)!\n\n"
            f"После оплаты нажми кнопку ниже.\n"
            f"Доступ будет активирован в течение 15 минут.",
            kb
        )

    # ── Подтверждение оплаты от пользователя ──
    elif action.startswith('paid_'):
        try:
            data = action.replace('paid_', '')
            parts = data.split('_')
            payment_method = parts[0]
            request_id = int(parts[1])
            tariff_key = '_'.join(parts[2:])
            if tariff_key not in TARIFFS:
                return
            tariff = TARIFFS[tariff_key]
        except (IndexError, ValueError) as e:
            logger.error(f"Ошибка парсинга paid action '{action}': {e}")
            return

        payment_info = (
            f"📱 Мобильный — {tariff['price']}₽" if payment_method == 'card'
            else f"💵 USDT — {tariff['price_usdt']} USDT"
        )

        try:
            kb = Keyboard(inline=True)
            kb.add(Callback(
                f"✅ Активировать ({tariff['name']})",
                {"a": f"admin_act_{user_id}_{tariff['days']}"}
            ))
            await send_msg(
                ADMIN_VK_ID,
                f"✅ Пользователь подтвердил оплату!\n\n"
                f"ID заявки: {request_id}\n"
                f"Способ: {payment_info}\n"
                f"User VK ID: {user_id}\n"
                f"Тариф: {tariff['name']}\n\n"
                f"Проверь платёж и нажми кнопку ниже:",
                kb
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления админа о подтверждении: {e}")

        kb2 = Keyboard(inline=True)
        kb2.add(Callback("🏠 В начало", {"a": "go_start"}))
        await edit_msg(
            peer_id, cmid,
            "✅ Спасибо! Твоя заявка принята.\n\n"
            "⏳ Ожидай активации подписки (обычно в течение 5–10 минут).\n"
            "Как только доступ будет активирован, я сразу напишу!",
            kb2
        )

    # ── Активация подписки администратором ──
    elif action.startswith('admin_act_'):
        if user_id != ADMIN_VK_ID:
            return
        try:
            parts = action.replace('admin_act_', '').split('_')
            target_user_id = int(parts[0])
            days = int(parts[1])
        except (IndexError, ValueError) as e:
            logger.error(f"Ошибка парсинга admin_act '{action}': {e}")
            return

        end_date = db.add_subscription(target_user_id, days, f"{days}_days")
        await edit_msg(
            peer_id, cmid,
            f"✅ Подписка активирована!\n\n"
            f"User VK ID: {target_user_id}\nДней: {days}\n"
            f"До: {end_date.strftime('%d.%m.%Y %H:%M')}"
        )

        tariff_name = f"{days} " + ("день" if days == 1 else "дней")
        try:
            await send_msg(
                target_user_id,
                f"🎉 Подписка активирована!\nТариф: {tariff_name}\n"
                f"Активна до: {end_date.strftime('%d.%m.%Y %H:%M')}"
            )
            if target_user_id in user_search_results:
                filtered = user_search_results[target_user_id]
                await send_msg(target_user_id, f"🔍 Вот результаты твоего поиска ({len(filtered)} вариантов):")
                await show_results_function(target_user_id, filtered)
                del user_search_results[target_user_id]
                user_filters.pop(target_user_id, None)
            else:
                user_filters[target_user_id] = {}
                await send_msg(
                    target_user_id,
                    "🔍 Давай найдём жильё для тебя!\n\n1️⃣ Выбери населённый пункт:",
                    kb_location()
                )
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя {target_user_id}: {e}")

    # ── Показать ещё ──
    elif action == 'show_more':
        if user_id not in user_pagination_data:
            kb = Keyboard(inline=True)
            kb.add(Callback("🔍 Новый поиск", {"a": "new_search"}))
            await edit_msg(peer_id, cmid, "⚠️ Данные поиска устарели. Начни новый поиск:", kb)
            return
        data = user_pagination_data[user_id]
        filtered = data['filtered']
        next_index = data['next_index']
        await edit_msg(peer_id, cmid, "🔍 Загружаю ещё варианты...")
        await show_results_function(peer_id, filtered, start_index=next_index)
        if len(filtered) - next_index - RESULTS_PER_PAGE <= 0:
            user_pagination_data.pop(user_id, None)

    # ── Подписка на уведомления о новых объявлениях ──
    elif action == 'alerts_sub':
        has_sub, _ = db.check_subscription(user_id)
        if not has_sub:
            kb = Keyboard(inline=True)
            kb.add(Callback("💳 Купить подписку", {"a": "buy_1_day"}))
            await edit_msg(peer_id, cmid, "🔒 Уведомления доступны только при активной подписке.", kb)
            return
        db.set_alert_subscription(user_id, True)
        await seed_seen_apartments_for_user(user_id)
        await edit_msg(peer_id, cmid, "🔔 Готово! Теперь буду присылать новые объявления автоматически.")

    # ── В начало ──
    elif action == 'go_start':
        has_sub, end_date = db.check_subscription(user_id)
        welcome = WELCOME_TEXT
        if has_sub:
            welcome += f"\n✅ Подписка активна до {end_date.strftime('%d.%m.%Y %H:%M')}\n"
        user_filters[user_id] = {}
        await edit_msg(peer_id, cmid, welcome, kb_main_menu())

    # ── Найти жильё через бота ──
    elif action == 'search_housing':
        user_filters[user_id] = {}
        await edit_msg(peer_id, cmid, "🔍 Давай найдём идеальное жильё!\n\n1️⃣ Выбери населённый пункт:", kb_location())

    # ── Написать сообществу ──
    elif action == 'post_announcement':
        user_writing_to_community.add(user_id)
        kb = Keyboard(inline=True)
        kb.add(Callback("🔙 Назад", {"a": "cancel_community_msg"}))
        await edit_msg(
            peer_id, cmid,
            "✍️ Напишите ваше сообщение следующим сообщением.\n\n"
            "Администратор получит его и ответит вам.",
            kb
        )

    # ── Отмена написания сообщества ──
    elif action == 'cancel_community_msg':
        user_writing_to_community.discard(user_id)
        has_sub, end_date = db.check_subscription(user_id)
        welcome = WELCOME_TEXT
        if has_sub:
            welcome += f"\n✅ Подписка активна до {end_date.strftime('%d.%m.%Y %H:%M')}\n"
        user_filters[user_id] = {}
        await edit_msg(peer_id, cmid, welcome, kb_main_menu())

    # ── Новый поиск ──
    elif action == 'new_search':
        user_filters.pop(user_id, None)
        user_filters[user_id] = {}
        await edit_msg(
            peer_id, cmid,
            "🔍 Давай найдём идеальное жильё!\n\n1️⃣ Выбери населённый пункт:",
            kb_location()
        )


# ─────────────────── Фоновая проверка новых объявлений ───────────────────

async def check_new_apartments_job():
    """Проверяет новые объявления и рассылает уведомления подписчикам."""
    user_ids = db.get_alert_subscribers()
    if not user_ids:
        return

    all_apartments = sheets.read_apartments()
    keyed_apartments = {build_apartment_key(apt): apt for apt in all_apartments}
    all_keys = set(keyed_apartments.keys())

    for uid in user_ids:
        has_sub, _ = db.check_subscription(uid)
        if not has_sub:
            db.set_alert_subscription(uid, False)
            continue

        seen_keys = db.get_seen_apartment_keys(uid)
        new_keys = [k for k in all_keys if k not in seen_keys]
        if not new_keys:
            continue

        db.add_seen_apartments(uid, new_keys)
        new_apartments = [keyed_apartments[k] for k in new_keys[:NOTIFICATION_NEW_ITEMS_LIMIT]]

        try:
            await send_msg(uid, f"🆕 Появились новые объявления: {len(new_keys)} шт. Показываю свежие:")
            await show_results_function(uid, new_apartments, show_contacts=True, show_vk=True)
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления user_id={uid}: {e}")


async def notification_loop():
    """Запускает проверку новых объявлений каждые 15 минут."""
    await asyncio.sleep(30)  # Первая проверка через 30 секунд после запуска
    while True:
        try:
            await check_new_apartments_job()
        except Exception as e:
            logger.error(f"Ошибка в notification_loop: {e}")
        await asyncio.sleep(NOTIFICATION_CHECK_INTERVAL_SECONDS)


# ─────────────────── Точка входа ───────────────────

if __name__ == '__main__':
    logger.info("VK Бот запускается...")
    bot.loop_wrapper.add_task(notification_loop())
    bot.run_forever()
