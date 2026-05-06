#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eysk VK Bot - Поиск жилья в Ейске и Должанской
"""

import json
import time
import random
import hashlib
import logging
import threading
import requests
from datetime import datetime
import pytz

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType

from config import VK_TOKEN, ADMIN_VK_ID, TARIFFS, PAYMENT_PHONE, USDT_WALLET, WELCOME_TEXT
from database import Database
from sheets_reader import GoogleSheetsReader

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()
sheets = GoogleSheetsReader()

vk_session = vk_api.VkApi(token=VK_TOKEN)
vk = vk_session.get_api()

group_info = vk.groups.getById()
GROUP_ID = group_info[0]['id']
longpoll = VkBotLongPoll(vk_session, GROUP_ID)

user_filters = {}
user_pagination_data = {}
user_search_results = {}
user_writing_to_community = set()

PREVIEW_RESULTS_LIMIT = 2
NOTIFICATION_CHECK_INTERVAL_SECONDS = 900
NOTIFICATION_NEW_ITEMS_LIMIT = 3
RESULTS_PER_PAGE = 20


# ─────────────────── Вспомогательные функции ───────────────────

def build_apartment_key(apartment: dict) -> str:
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
    return hashlib.sha256("|".join(key_parts).encode('utf-8')).hexdigest()


def get_fake_views_count(apartment_key: str) -> int:
    return random.Random(apartment_key).randint(8, 39)


def is_payment_time() -> bool:
    now_msk = datetime.now(pytz.timezone('Europe/Moscow'))
    return 11 <= now_msk.hour < 23


def seed_seen_apartments_for_user(user_id: int):
    all_apartments = sheets.read_apartments()
    db.add_seen_apartments(user_id, [build_apartment_key(apt) for apt in all_apartments])


def get_user_first_name(user_id: int) -> str:
    try:
        users = vk.users.get(user_ids=[user_id])
        return users[0]['first_name'] if users else "Пользователь"
    except Exception:
        return "Пользователь"


# ─────────────────── Клавиатуры ───────────────────

def make_keyboard(rows: list) -> str:
    buttons = []
    for row in rows:
        buttons.append([{
            "action": {
                "type": "callback",
                "label": label,
                "payload": json.dumps(payload, ensure_ascii=False)
            },
            "color": "primary"
        } for label, payload in row])
    return json.dumps({"inline": True, "buttons": buttons}, ensure_ascii=False)


def kb_main_menu() -> str:
    return make_keyboard([
        [("🔍 Найти жильё через бота", {"a": "search_housing"})],
        [("📋 Написать сообществу (администратору)", {"a": "post_announcement"})],
    ])


def kb_location() -> str:
    return make_keyboard([
        [("🏖️ Ейск", {"a": "loc_ейск"})],
        [("🌊 Должанская", {"a": "loc_должанская"})],
    ])


def kb_subscription() -> str:
    return make_keyboard([
        [(f"💳 {TARIFFS['1_day']['name']} — {TARIFFS['1_day']['price']}₽", {"a": "buy_1_day"})],
        [(f"💳 {TARIFFS['7_days']['name']} — {TARIFFS['7_days']['price']}₽", {"a": "buy_7_days"})],
        [(f"💳 {TARIFFS['30_days']['name']} — {TARIFFS['30_days']['price']}₽", {"a": "buy_30_days"})],
        [("🔍 Новый поиск", {"a": "new_search"})],
    ])


def kb_distance() -> str:
    return make_keyboard([
        [("🏖️ До 100м", {"a": "dist_0-100"}), ("🚶 150–500м", {"a": "dist_150-500"})],
        [("🚗 500–1000м", {"a": "dist_500-1000"}), ("🏙️ Более 1000м", {"a": "dist_1000-99999"})],
        [("➡️ Не важно", {"a": "dist_any"}), ("🔙 Назад", {"a": "go_start"})],
    ])


# ─────────────────── Отправка / редактирование ───────────────────

def send_msg(peer_id: int, text: str, keyboard: str = None, attachment: str = None):
    kwargs = {
        "peer_id": peer_id,
        "message": text,
        "random_id": random.randint(0, 2 ** 31),
    }
    if keyboard:
        kwargs["keyboard"] = keyboard
    if attachment:
        kwargs["attachment"] = attachment
    try:
        vk.messages.send(**kwargs)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения peer={peer_id}: {e}")


def edit_msg(peer_id: int, cmid: int, text: str, keyboard: str = None):
    kwargs = {
        "peer_id": peer_id,
        "conversation_message_id": cmid,
        "message": text,
    }
    if keyboard:
        kwargs["keyboard"] = keyboard
    try:
        vk.messages.edit(**kwargs)
    except Exception as e:
        logger.warning(f"Не удалось отредактировать peer={peer_id} cmid={cmid}: {e}")
        send_msg(peer_id, text, keyboard)


def upload_photo(peer_id: int, photo_url: str) -> str | None:
    try:
        upload_server = vk.photos.getMessagesUploadServer(peer_id=peer_id)
        resp = requests.get(photo_url, timeout=10)
        if resp.status_code != 200:
            return None
        upload_resp = requests.post(
            upload_server['upload_url'],
            files={'photo': ('photo.jpg', resp.content, 'image/jpeg')}
        )
        result = upload_resp.json()
        saved = vk.photos.saveMessagesPhoto(
            photo=result['photo'],
            server=result['server'],
            hash=result['hash']
        )
        photo = saved[0]
        return f"photo{photo['owner_id']}_{photo['id']}"
    except Exception as e:
        logger.error(f"Ошибка загрузки фото {photo_url}: {e}")
        return None


# ─────────────────── Показ объявлений ───────────────────

def send_apartment(peer_id: int, apt: dict, idx: int,
                   show_contacts: bool = True, show_vk: bool = True):
    text = f"📍 Вариант {idx} ⬇️⬇️⬇️\n\n"

    tip = apt.get('Тип_жилья', 'не указан')
    tip_map = {
        '1-комн': '1-комнатная квартира',
        '2-комн': '2-комнатная квартира',
        '3-комн': '3-комнатная квартира',
        'частный дом': 'Частный дом',
        'гостевой дом': 'Гостевой дом',
    }
    text += f"🏠 {tip_map.get(tip, tip)}\n"
    text += f"🏖️ {apt.get('Расстояние_от_моря_м', '?')} метров от моря\n"
    text += f"👥 До {apt.get('Гостей_макс', '?')} гостей\n"

    price = apt.get('Цена_за_сутки', '')
    text += f"💰 {price}₽/сутки\n" if price and price != 'по запросу' else "💰 Цена по запросу\n"

    description = apt.get('Описание', '').strip()
    if description:
        text += f"\n📝 {description}\n"

    apt_key = build_apartment_key(apt)
    text += f"\n🔥 Этот вариант смотрели {get_fake_views_count(apt_key)} раз\n"

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
    attachment = upload_photo(peer_id, photo_url) if photo_url and photo_url.startswith('http') else None

    send_msg(peer_id, text, attachment=attachment)


def show_results(peer_id: int, filtered: list, start_index: int = 0,
                 show_contacts: bool = True, show_vk: bool = True):
    total = len(filtered)
    end_index = min(start_index + RESULTS_PER_PAGE, total)

    if start_index == 0:
        send_msg(peer_id, f"✅ Найдено вариантов: {total}\n\nСейчас покажу их по очереди:")

    for i, apt in enumerate(filtered[start_index:end_index], start_index + 1):
        send_apartment(peer_id, apt, i, show_contacts, show_vk)

    remaining = total - end_index
    if remaining > 0 and show_contacts:
        user_pagination_data[peer_id] = {'filtered': filtered, 'next_index': end_index}
        kb = make_keyboard([
            [(f"📋 Показать ещё {remaining}", {"a": "show_more"})],
            [("🔔 Подписаться на новые", {"a": "alerts_sub"})],
            [("🔍 Новый поиск", {"a": "new_search"})],
            [("📋 Написать сообществу (администратору)", {"a": "post_announcement"})],
        ])
        send_msg(peer_id, f"✅ Показано {end_index} из {total} вариантов", kb)
    elif show_contacts:
        kb = make_keyboard([
            [("🔔 Подписаться на новые", {"a": "alerts_sub"})],
            [("🔍 Новый поиск", {"a": "new_search"})],
            [("📋 Написать сообществу (администратору)", {"a": "post_announcement"})],
        ])
        send_msg(peer_id, "✅ Все результаты показаны!", kb)


def show_preview(peer_id: int, filtered: list):
    preview = filtered[:PREVIEW_RESULTS_LIMIT]
    if not preview:
        return
    send_msg(
        peer_id,
        f"👀 Бесплатный превью: {len(preview)} из {len(filtered)} вариантов\n\n"
        f"Показываю примеры без контактов и без ссылок."
    )
    show_results(peer_id, preview, start_index=0, show_contacts=False, show_vk=False)


# ─────────────────── Текстовые команды ───────────────────

def cmd_start(user_id: int):
    first_name = get_user_first_name(user_id)
    db.add_user(user_id, None, first_name)
    has_sub, end_date = db.check_subscription(user_id)
    welcome = WELCOME_TEXT
    if has_sub:
        welcome += f"\n✅ Подписка активна до {end_date.strftime('%d.%m.%Y %H:%M')}\n"
    user_filters[user_id] = {}
    send_msg(user_id, welcome, kb_main_menu())


def cmd_search(user_id: int):
    user_filters[user_id] = {}
    send_msg(user_id, "🔍 Давай найдём идеальное жильё!\n\n1️⃣ Выбери населённый пункт:", kb_location())


def cmd_activate(user_id: int, text: str):
    if user_id != ADMIN_VK_ID:
        return
    parts = text.split()
    if len(parts) != 3:
        send_msg(user_id, "❌ Формат: /activate <vk_user_id> <дни>\nПример: /activate 12345678 7")
        return
    try:
        target_id, days = int(parts[1]), int(parts[2])
        end_date = db.add_subscription(target_id, days, f"{days}_days")
        send_msg(
            user_id,
            f"✅ Подписка активирована!\nUser VK ID: {target_id}\nДней: {days}\n"
            f"До: {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        tariff_name = f"{days} " + ("день" if days == 1 else "дней")
        try:
            send_msg(
                target_id,
                f"🎉 Подписка активирована!\nТариф: {tariff_name}\n"
                f"Активна до: {end_date.strftime('%d.%m.%Y %H:%M')}"
            )
            user_filters[target_id] = {}
            send_msg(target_id, "🔍 Давай найдём жильё!\n\n1️⃣ Выбери населённый пункт:", kb_location())
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя {target_id}: {e}")
    except (ValueError, TypeError):
        send_msg(user_id, "❌ Формат: /activate <vk_user_id> <дни>\nПример: /activate 12345678 7")


def cmd_check(user_id: int, text: str):
    if user_id != ADMIN_VK_ID:
        return
    parts = text.split()
    if len(parts) != 2:
        send_msg(user_id, "❌ Формат: /check <vk_user_id>")
        return
    try:
        target_id = int(parts[1])
        has_sub, end_date = db.check_subscription(target_id)
        if has_sub:
            send_msg(user_id, f"✅ Подписка активна\nUser VK ID: {target_id}\nДо: {end_date.strftime('%d.%m.%Y %H:%M')}")
        else:
            send_msg(user_id, f"❌ Подписка неактивна\nUser VK ID: {target_id}")
    except (ValueError, TypeError):
        send_msg(user_id, "❌ Формат: /check <vk_user_id>")


def cmd_stats(user_id: int):
    if user_id != ADMIN_VK_ID:
        return
    s = db.get_stats()
    send_msg(
        user_id,
        f"📊 Статистика бота\n\n"
        f"👥 Всего пользователей: {s['total_users']}\n"
        f"✅ Активных подписок: {s['active_subscriptions']}\n"
        f"⏳ Ожидают оплаты: {s['pending_payments']}\n"
        f"🔍 Поисков сегодня: {s['searches_today']}\n"
    )


def cmd_pending(user_id: int):
    if user_id != ADMIN_VK_ID:
        return
    pending = db.get_pending_payments()
    if not pending:
        send_msg(user_id, "✅ Нет ожидающих оплат")
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
    send_msg(user_id, text)


def handle_free_message(user_id: int):
    if user_id not in user_writing_to_community:
        return
    user_writing_to_community.discard(user_id)
    kb = make_keyboard([[("🏠 В начало", {"a": "go_start"})]])
    send_msg(
        user_id,
        "✅ Ваше сообщение отправлено администратору!\n\nМы ответим вам в ближайшее время.",
        kb
    )


# ─────────────────── Обработка callback-кнопок ───────────────────

def process_action(user_id: int, peer_id: int, cmid: int, action: str):
    # ── Выбор города ──
    if action.startswith('loc_'):
        location = action.replace('loc_', '')
        user_filters.setdefault(user_id, {})['location'] = location

        if location == 'должанская':
            edit_msg(peer_id, cmid, "🔍 Ищу все варианты в Должанской...")
            all_apts = sheets.read_apartments()
            filtered = [a for a in all_apts if a.get('Населенный_пункт', '').lower() == 'должанская']
            db.log_search(user_id, user_filters[user_id], len(filtered))

            if not filtered:
                send_msg(peer_id, "😔 В Должанской пока нет объявлений.",
                         make_keyboard([[("🔍 Новый поиск", {"a": "new_search"})]]))
                user_filters.pop(user_id, None)
                return

            has_sub, _ = db.check_subscription(user_id)
            if has_sub:
                show_results(peer_id, filtered)
                user_filters.pop(user_id, None)
            else:
                user_search_results[user_id] = filtered
                show_preview(peer_id, filtered)
                send_msg(
                    peer_id,
                    f"✅ Найдено вариантов: {len(filtered)}\n\n"
                    f"Полный доступ к контактам открывается по подписке.\n\nВыбери тариф:",
                    kb_subscription()
                )
        else:
            kb = make_keyboard([
                [("🏠 1-комнатная", {"a": "type_1-комн"}), ("🏡 2-комнатная", {"a": "type_2-комн"})],
                [("🏘 3-комнатная", {"a": "type_3-комн"})],
                [("🏘️ Частный дом", {"a": "type_частный дом"}), ("🏨 Гостевой дом", {"a": "type_гостевой дом"})],
                [("➡️ Любой тип", {"a": "type_any"})],
                [("🔙 Назад", {"a": "go_start"})],
            ])
            edit_msg(peer_id, cmid, "2️⃣ Какой тип жилья тебе нужен?", kb)

    # ── Выбор типа жилья ──
    elif action.startswith('type_'):
        type_choice = action.replace('type_', '')
        user_filters.setdefault(user_id, {})
        if type_choice != 'any':
            user_filters[user_id]['type'] = type_choice
        kb = make_keyboard([
            [("👤 1–2 гостя", {"a": "guests_2"}), ("👥 3–4 гостя", {"a": "guests_4"})],
            [("👨‍👩‍👧‍👦 5–6 гостей", {"a": "guests_6"}), ("🏢 7+ гостей", {"a": "guests_7"})],
            [("➡️ Не важно", {"a": "guests_any"}), ("🔙 Назад", {"a": "go_start"})],
        ])
        edit_msg(peer_id, cmid, "3️⃣ Сколько человек будет отдыхать?", kb)

    # ── Выбор количества гостей ──
    elif action.startswith('guests_'):
        guests_choice = action.replace('guests_', '')
        user_filters.setdefault(user_id, {})
        if guests_choice != 'any':
            user_filters[user_id]['guests'] = int(guests_choice)

        is_guesthouse = user_filters[user_id].get('type') == 'гостевой дом'
        if is_guesthouse and guests_choice in ['6', '7']:
            kb = make_keyboard([
                [("✅ Да, подойдёт 2 номера", {"a": "two_rooms_yes"})],
                [("❌ Нет, нужен один номер", {"a": "two_rooms_no"})],
                [("🔙 Назад", {"a": "go_start"})],
            ])
            edit_msg(peer_id, cmid,
                     "💡 Вам подойдёт 2 номера?\n\n"
                     "Это увеличит шансы найти варианты для большой компании!", kb)
            return

        edit_msg(peer_id, cmid, "4️⃣ На каком расстоянии от моря?", kb_distance())

    # ── Вопрос про 2 номера ──
    elif action.startswith('two_rooms_'):
        user_filters.setdefault(user_id, {})
        if action == 'two_rooms_yes':
            user_filters[user_id]['guests'] = 6
            user_filters[user_id]['two_rooms_mode'] = True
        edit_msg(peer_id, cmid, "4️⃣ На каком расстоянии от моря?", kb_distance())

    # ── Выбор расстояния → результаты ──
    elif action.startswith('dist_'):
        dist_choice = action.replace('dist_', '')
        user_filters.setdefault(user_id, {})

        if dist_choice != 'any':
            min_d, max_d = dist_choice.split('-')
            user_filters[user_id]['min_distance'] = int(min_d)
            user_filters[user_id]['max_distance'] = int(max_d)

        filters = user_filters[user_id]
        if not any([filters.get('type'), filters.get('guests'),
                    filters.get('min_distance'), filters.get('max_distance')]):
            edit_msg(peer_id, cmid,
                     "🤔 Ты не выбрал ни одного параметра.\n\n"
                     "Выбери хотя бы один фильтр (тип жилья, количество гостей или расстояние).",
                     make_keyboard([[("🔍 Новый поиск", {"a": "new_search"})]]))
            user_filters.pop(user_id, None)
            return

        edit_msg(peer_id, cmid, "🔍 Ищу подходящие варианты...")
        all_apts = sheets.read_apartments()
        filtered = sheets.filter_apartments(all_apts, filters)
        db.log_search(user_id, filters, len(filtered))

        if not filtered:
            send_msg(peer_id, "😔 По твоим критериям ничего не найдено. Попробуй изменить параметры:",
                     make_keyboard([[("🔍 Новый поиск", {"a": "new_search"})]]))
            user_filters.pop(user_id, None)
            return

        has_sub, _ = db.check_subscription(user_id)
        if has_sub:
            show_results(peer_id, filtered)
            user_filters.pop(user_id, None)
        else:
            user_search_results[user_id] = filtered
            show_preview(peer_id, filtered)
            send_msg(
                peer_id,
                f"✅ Найдено вариантов: {len(filtered)}\n\n"
                f"Полный доступ к контактам открывается по подписке.\n\nВыбери тариф:",
                kb_subscription()
            )

    # ── Покупка подписки ──
    elif action.startswith('buy_'):
        tariff_key = action.replace('buy_', '')
        if tariff_key not in TARIFFS:
            return
        tariff = TARIFFS[tariff_key]
        kb = make_keyboard([
            [(f"📱 Мобильный — {tariff['price']}₽", {"a": f"pay_card_{tariff_key}"})],
            [(f"💵 USDT (BEP-20) — {tariff['price_usdt']} USDT", {"a": f"pay_usdt_{tariff_key}"})],
            [("🔙 Назад", {"a": "go_start"})],
        ])
        edit_msg(peer_id, cmid,
                 f"💰 Оплата подписки: {tariff['name']}\n\n"
                 f"Выбери способ оплаты:\n\n"
                 f"📱 Мобильный: {tariff['price']}₽\n"
                 f"💵 USDT: {tariff['price_usdt']} USDT",
                 kb)

    # ── Оплата мобильным ──
    elif action.startswith('pay_card_'):
        tariff_key = action.replace('pay_card_', '')
        if tariff_key not in TARIFFS:
            return
        tariff = TARIFFS[tariff_key]

        if not is_payment_time():
            current_time = datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')
            edit_msg(peer_id, cmid,
                     f"⏰ Оплата временно недоступна\n\n"
                     f"Текущее время МСК: {current_time}\n\n"
                     f"Оплата доступна только с 11:00 до 23:00 МСК\n\nПопробуй позже!",
                     make_keyboard([[("🏠 В начало", {"a": "go_start"})]]))
            return

        request_id = db.add_payment_request(user_id, tariff_key, 'mobile')
        try:
            send_msg(ADMIN_VK_ID,
                     f"💰 Новая заявка на оплату!\n\n"
                     f"ID заявки: {request_id}\n"
                     f"Способ: 📱 Пополнение мобильного\n"
                     f"User VK ID: {user_id}\n"
                     f"Тариф: {tariff['name']} — {tariff['price']}₽")
        except Exception as e:
            logger.error(f"Ошибка уведомления админа: {e}")

        edit_msg(peer_id, cmid,
                 f"📱 Оплата подписки: {tariff['name']}\n"
                 f"Сумма: {tariff['price']}₽\n\n"
                 f"💰 Пополните баланс мобильного:\n"
                 f"Номер: {PAYMENT_PHONE}\n"
                 f"Оператор: Теле2\n\n"
                 f"После оплаты нажми кнопку ниже.\n"
                 f"Доступ будет активирован в течение 15 минут.\n\n"
                 f"⏰ Подписка активируется только с 11:00 до 23:00 МСК",
                 make_keyboard([
                     [(f"✅ Я оплатил", {"a": f"paid_card_{request_id}_{tariff_key}"})],
                     [("🔙 Назад", {"a": "go_start"})],
                 ]))

    # ── Оплата USDT ──
    elif action.startswith('pay_usdt_'):
        tariff_key = action.replace('pay_usdt_', '')
        if tariff_key not in TARIFFS:
            return
        tariff = TARIFFS[tariff_key]

        request_id = db.add_payment_request(user_id, tariff_key, 'usdt')
        try:
            send_msg(ADMIN_VK_ID,
                     f"💰 Новая заявка на оплату!\n\n"
                     f"ID заявки: {request_id}\n"
                     f"Способ: 💵 USDT (BEP-20)\n"
                     f"User VK ID: {user_id}\n"
                     f"Тариф: {tariff['name']} — {tariff['price_usdt']} USDT")
        except Exception as e:
            logger.error(f"Ошибка уведомления админа: {e}")

        edit_msg(peer_id, cmid,
                 f"💵 Оплата подписки: {tariff['name']}\n"
                 f"Сумма: {tariff['price_usdt']} USDT\n\n"
                 f"💰 Адрес кошелька USDT (BEP-20):\n"
                 f"{USDT_WALLET}\n\n"
                 f"⚠️ Отправляйте ТОЛЬКО USDT по сети BEP-20 (Binance Smart Chain)!\n\n"
                 f"После оплаты нажми кнопку ниже.\n"
                 f"Доступ будет активирован в течение 15 минут.",
                 make_keyboard([
                     [(f"✅ Я оплатил", {"a": f"paid_usdt_{request_id}_{tariff_key}"})],
                     [("🔙 Назад", {"a": "go_start"})],
                 ]))

    # ── Подтверждение оплаты от пользователя ──
    elif action.startswith('paid_'):
        try:
            parts = action.replace('paid_', '').split('_')
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
            send_msg(ADMIN_VK_ID,
                     f"✅ Пользователь подтвердил оплату!\n\n"
                     f"ID заявки: {request_id}\n"
                     f"Способ: {payment_info}\n"
                     f"User VK ID: {user_id}\n"
                     f"Тариф: {tariff['name']}\n\n"
                     f"Проверь платёж и нажми кнопку ниже:",
                     make_keyboard([[(
                         f"✅ Активировать ({tariff['name']})",
                         {"a": f"admin_act_{user_id}_{tariff['days']}"}
                     )]]))
        except Exception as e:
            logger.error(f"Ошибка уведомления админа о подтверждении: {e}")

        edit_msg(peer_id, cmid,
                 "✅ Спасибо! Твоя заявка принята.\n\n"
                 "⏳ Ожидай активации подписки (обычно в течение 5–10 минут).\n"
                 "Как только доступ будет активирован, я сразу напишу!",
                 make_keyboard([[("🏠 В начало", {"a": "go_start"})]]))

    # ── Активация подписки администратором ──
    elif action.startswith('admin_act_'):
        if user_id != ADMIN_VK_ID:
            return
        try:
            parts = action.replace('admin_act_', '').split('_')
            target_user_id, days = int(parts[0]), int(parts[1])
        except (IndexError, ValueError) as e:
            logger.error(f"Ошибка парсинга admin_act '{action}': {e}")
            return

        end_date = db.add_subscription(target_user_id, days, f"{days}_days")
        edit_msg(peer_id, cmid,
                 f"✅ Подписка активирована!\n\n"
                 f"User VK ID: {target_user_id}\nДней: {days}\n"
                 f"До: {end_date.strftime('%d.%m.%Y %H:%M')}")

        tariff_name = f"{days} " + ("день" if days == 1 else "дней")
        try:
            send_msg(target_user_id,
                     f"🎉 Подписка активирована!\nТариф: {tariff_name}\n"
                     f"Активна до: {end_date.strftime('%d.%m.%Y %H:%M')}")
            if target_user_id in user_search_results:
                filtered = user_search_results.pop(target_user_id)
                send_msg(target_user_id, f"🔍 Вот результаты твоего поиска ({len(filtered)} вариантов):")
                show_results(target_user_id, filtered)
                user_filters.pop(target_user_id, None)
            else:
                user_filters[target_user_id] = {}
                send_msg(target_user_id,
                         "🔍 Давай найдём жильё!\n\n1️⃣ Выбери населённый пункт:", kb_location())
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя {target_user_id}: {e}")

    # ── Показать ещё ──
    elif action == 'show_more':
        if user_id not in user_pagination_data:
            edit_msg(peer_id, cmid, "⚠️ Данные поиска устарели. Начни новый поиск:",
                     make_keyboard([[("🔍 Новый поиск", {"a": "new_search"})]]))
            return
        data = user_pagination_data[user_id]
        edit_msg(peer_id, cmid, "🔍 Загружаю ещё варианты...")
        show_results(peer_id, data['filtered'], start_index=data['next_index'])
        if len(data['filtered']) - data['next_index'] - RESULTS_PER_PAGE <= 0:
            user_pagination_data.pop(user_id, None)

    # ── Подписка на уведомления ──
    elif action == 'alerts_sub':
        has_sub, _ = db.check_subscription(user_id)
        if not has_sub:
            edit_msg(peer_id, cmid, "🔒 Уведомления доступны только при активной подписке.",
                     make_keyboard([[("💳 Купить подписку", {"a": "buy_1_day"})]]))
            return
        db.set_alert_subscription(user_id, True)
        seed_seen_apartments_for_user(user_id)
        edit_msg(peer_id, cmid, "🔔 Готово! Теперь буду присылать новые объявления автоматически.")

    # ── В начало ──
    elif action == 'go_start':
        has_sub, end_date = db.check_subscription(user_id)
        welcome = WELCOME_TEXT
        if has_sub:
            welcome += f"\n✅ Подписка активна до {end_date.strftime('%d.%m.%Y %H:%M')}\n"
        user_filters[user_id] = {}
        edit_msg(peer_id, cmid, welcome, kb_main_menu())

    # ── Найти жильё ──
    elif action == 'search_housing':
        user_filters[user_id] = {}
        edit_msg(peer_id, cmid,
                 "🔍 Давай найдём идеальное жильё!\n\n1️⃣ Выбери населённый пункт:", kb_location())

    # ── Написать сообществу ──
    elif action == 'post_announcement':
        user_writing_to_community.add(user_id)
        edit_msg(peer_id, cmid,
                 "✍️ Напишите ваше сообщение следующим сообщением.\n\n"
                 "Администратор получит его и ответит вам.",
                 make_keyboard([[("🔙 Назад", {"a": "cancel_community_msg"})]]))

    # ── Отмена написания сообществу ──
    elif action == 'cancel_community_msg':
        user_writing_to_community.discard(user_id)
        has_sub, end_date = db.check_subscription(user_id)
        welcome = WELCOME_TEXT
        if has_sub:
            welcome += f"\n✅ Подписка активна до {end_date.strftime('%d.%m.%Y %H:%M')}\n"
        user_filters[user_id] = {}
        edit_msg(peer_id, cmid, welcome, kb_main_menu())

    # ── Новый поиск ──
    elif action == 'new_search':
        user_filters[user_id] = {}
        edit_msg(peer_id, cmid,
                 "🔍 Давай найдём идеальное жильё!\n\n1️⃣ Выбери населённый пункт:", kb_location())


# ─────────────────── Обработчики событий longpoll ───────────────────

def handle_message(message: dict):
    user_id = message.get('from_id')
    if not user_id or user_id < 0:
        return
    text = (message.get('text') or '').strip()
    text_lower = text.lower()

    if text_lower in ['/start', 'начать', 'старт']:
        cmd_start(user_id)
    elif text_lower in ['/search', 'поиск']:
        cmd_search(user_id)
    elif text_lower.startswith('/activate'):
        cmd_activate(user_id, text)
    elif text_lower.startswith('/check'):
        cmd_check(user_id, text)
    elif text_lower == '/stats':
        cmd_stats(user_id)
    elif text_lower == '/pending':
        cmd_pending(user_id)
    else:
        handle_free_message(user_id)


def handle_callback(obj: dict):
    user_id = obj.get('user_id')
    peer_id = obj.get('peer_id')
    cmid = obj.get('conversation_message_id')
    event_id = obj.get('event_id')

    if not user_id or not peer_id or not cmid:
        return

    try:
        vk.messages.sendMessageEventAnswer(
            event_id=event_id,
            user_id=user_id,
            peer_id=peer_id
        )
    except Exception as e:
        logger.warning(f"Не удалось ответить на callback: {e}")

    raw_payload = obj.get('payload', {})
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            raw_payload = {}
    action = raw_payload.get('a', '')

    if not action:
        return

    try:
        process_action(user_id, peer_id, cmid, action)
    except Exception as e:
        logger.error(f"Ошибка обработки action '{action}': {e}")


# ─────────────────── Фоновые уведомления ───────────────────

def check_new_apartments_job():
    user_ids = db.get_alert_subscribers()
    if not user_ids:
        return
    all_apartments = sheets.read_apartments()
    keyed = {build_apartment_key(apt): apt for apt in all_apartments}
    all_keys = set(keyed.keys())

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
        new_apts = [keyed[k] for k in new_keys[:NOTIFICATION_NEW_ITEMS_LIMIT]]
        try:
            send_msg(uid, f"🆕 Появились новые объявления: {len(new_keys)} шт. Показываю свежие:")
            show_results(uid, new_apts, show_contacts=True, show_vk=True)
        except Exception as e:
            logger.error(f"Ошибка уведомления user_id={uid}: {e}")


def notification_thread():
    time.sleep(30)
    while True:
        try:
            check_new_apartments_job()
        except Exception as e:
            logger.error(f"Ошибка в notification_thread: {e}")
        time.sleep(NOTIFICATION_CHECK_INTERVAL_SECONDS)


# ─────────────────── Точка входа ───────────────────

if __name__ == '__main__':
    logger.info("VK Бот запускается...")
    threading.Thread(target=notification_thread, daemon=True).start()

    for event in longpoll.listen():
        try:
            if event.type == VkBotEventType.MESSAGE_NEW:
                handle_message(event.obj['message'])
            elif event.type == VkBotEventType.MESSAGE_EVENT:
                handle_callback(event.obj)
        except Exception as e:
            logger.error(f"Ошибка обработки события: {e}")
