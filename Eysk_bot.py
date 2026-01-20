#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Eysk Telegram Bot - Version 2.0 with Stars and USDT payments
"""

import logging
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler
)

from config import *
from database import Database
from sheets_reader import GoogleSheetsReader

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация
db = Database()
sheets = GoogleSheetsReader()  # Теперь читает из apartments.xlsx

# Временное хранилище фильтров пользователя
user_filters = {}

# Временное хранилище данных пагинации (для кнопки "Показать еще")
user_pagination_data = {}

# Временное хранилище результатов поиска (для пользователей без подписки)
user_search_results = {}


def is_payment_time():
    """Проверка, доступна ли оплата в текущее время (11:00-23:00 МСК)"""
    msk_tz = pytz.timezone('Europe/Moscow')
    now_msk = datetime.now(msk_tz)
    current_hour = now_msk.hour
    
    # Возвращаем True если время между 11:00 и 23:00 МСК
    return 11 <= current_hour < 23


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    db.add_user(user.id, user.username, user.first_name)
    
    # Проверяем подписку для информации
    has_subscription, end_date = db.check_subscription(user.id)
    
    # Приветствие
    if has_subscription:
        await update.message.reply_text(
            f"{WELCOME_TEXT}\n\n"
            f"✅ Подписка активна до {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
    else:
        await update.message.reply_text(WELCOME_TEXT)
    
    # Инициализируем фильтры для всех пользователей
    user_filters[user.id] = {}
    
    # ПЕРВЫЙ ВОПРОС - выбор населённого пункта (для всех)
    keyboard = [
        [InlineKeyboardButton("🏖️ Ейск", callback_data='location_ейск')],
        [InlineKeyboardButton("🌊 Должанская", callback_data='location_должанская')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔍 Давай найдем идеальное жилье!\n\n"
        "1️⃣ Выбери населённый пункт:",
        reply_markup=reply_markup
    )


async def buy_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик покупки подписки - показываем выбор способа оплаты"""
    query = update.callback_query
    await query.answer()

    tariff_key = query.data.replace('buy_', '')

    # Проверяем корректность тарифа
    if tariff_key not in TARIFFS:
        await query.edit_message_text("❌ Некорректный тариф")
        logger.error(f"Некорректный tariff_key: {tariff_key}")
        return

    tariff = TARIFFS[tariff_key]

    # Показываем выбор способа оплаты
    keyboard = [
        [InlineKeyboardButton("💳 Банковская карта", callback_data=f'pay_card_{tariff_key}')],
        [InlineKeyboardButton(f"⭐ Telegram Stars ({tariff['price_stars']} Stars)", callback_data=f'pay_stars_{tariff_key}')],
        [InlineKeyboardButton(f"💵 USDT (BEP-20) - {tariff['price_usdt']} USDT", callback_data=f'pay_usdt_{tariff_key}')],
        [InlineKeyboardButton("🔙 Назад", callback_data='go_start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"💰 Оплата подписки: {tariff['name']}\n\n"
        f"Выбери способ оплаты:\n\n"
        f"💳 Карта: {tariff['price']}₽\n"
        f"⭐ Stars: {tariff['price_stars']} Stars\n"
        f"💵 USDT: {tariff['price_usdt']} USDT",
        reply_markup=reply_markup
    )


async def pay_with_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплата банковской картой"""
    query = update.callback_query
    await query.answer()

    tariff_key = query.data.replace('pay_card_', '')

    # Проверяем корректность тарифа
    if tariff_key not in TARIFFS:
        await query.edit_message_text("❌ Некорректный тариф")
        logger.error(f"Некорректный tariff_key: {tariff_key}")
        return

    tariff = TARIFFS[tariff_key]

    # Проверяем время по МСК
    if not is_payment_time():
        msk_tz = pytz.timezone('Europe/Moscow')
        now_msk = datetime.now(msk_tz)
        current_time = now_msk.strftime('%H:%M')

        keyboard = [[InlineKeyboardButton("🏠 В начало", callback_data='go_start')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"⏰ Оплата временно недоступна\n\n"
            f"Текущее время МСК: {current_time}\n\n"
            f"Оплата и активация подписки доступны только:\n"
            f"📅 С 11:00 до 23:00 по МСК\n\n"
            f"Попробуй позже!",
            reply_markup=reply_markup
        )
        return

    # Добавляем заявку на оплату
    request_id = db.add_payment_request(query.from_user.id, tariff_key, 'card')

    # Уведомляем админа
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💰 Новая заявка на оплату!\n\n"
                 f"ID заявки: {request_id}\n"
                 f"Способ оплаты: 💳 Карта\n"
                 f"Пользователь: @{query.from_user.username or 'без username'} "
                 f"({query.from_user.first_name})\n"
                 f"User ID: {query.from_user.id}\n"
                 f"Тариф: {tariff['name']} - {tariff['price']}₽"
        )
    except Exception as e:
        logger.error(f"Ошибка при уведомлении админа: {e}")

    # Показываем реквизиты
    keyboard = [[InlineKeyboardButton("✅ Я оплатил", callback_data=f'paid_card_{request_id}_{tariff_key}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"💳 Оплата подписки: {tariff['name']}\n"
        f"Сумма: {tariff['price']}₽\n\n"
        f"💰 Реквизиты для оплаты:\n"
        f"Карта Т-Банк: `{PAYMENT_CARD}`\n"
        f"Получатель: {PAYMENT_RECIPIENT}\n\n"
        f"После оплаты нажми кнопку ниже.\n"
        f"Доступ будет активирован в течение 15 минут.\n\n"
        f"⏰ Подписка активируется только с 11:00 до 23:00 по МСК",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def pay_with_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплата через Telegram Stars"""
    query = update.callback_query
    await query.answer()

    tariff_key = query.data.replace('pay_stars_', '')

    # Проверяем корректность тарифа
    if tariff_key not in TARIFFS:
        await query.edit_message_text("❌ Некорректный тариф")
        logger.error(f"Некорректный tariff_key: {tariff_key}")
        return

    tariff = TARIFFS[tariff_key]

    # Создаем инвойс для оплаты Stars
    title = f"Подписка {tariff['name']}"
    description = f"Доступ к базе жилья в Ейске и Должанской на {tariff['days']} " + ("день" if tariff['days'] == 1 else "дней")
    payload = f"subscription_{tariff_key}_{query.from_user.id}"

    # Отправляем инвойс
    try:
        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",  # Для Stars используется пустая строка
            currency="XTR",  # XTR - код валюты для Telegram Stars
            prices=[LabeledPrice(label=title, amount=tariff['price_stars'])]
        )

        await query.edit_message_text(
            f"⭐ Оплата через Telegram Stars\n\n"
            f"Счет на оплату отправлен!\n"
            f"Сумма: {tariff['price_stars']} Stars\n\n"
            f"После успешной оплаты подписка активируется автоматически."
        )
    except Exception as e:
        logger.error(f"Ошибка при создании инвойса Stars: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при создании счета.\n\n"
            f"Пожалуйста, попробуйте другой способ оплаты или обратитесь к администратору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 В начало", callback_data='go_start')
            ]])
        )


async def pay_with_usdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оплата через USDT"""
    query = update.callback_query
    await query.answer()

    tariff_key = query.data.replace('pay_usdt_', '')

    # Проверяем корректность тарифа
    if tariff_key not in TARIFFS:
        await query.edit_message_text("❌ Некорректный тариф")
        logger.error(f"Некорректный tariff_key: {tariff_key}")
        return

    tariff = TARIFFS[tariff_key]

    # Добавляем заявку на оплату
    request_id = db.add_payment_request(query.from_user.id, tariff_key, 'usdt')

    # Уведомляем админа
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"💰 Новая заявка на оплату!\n\n"
                 f"ID заявки: {request_id}\n"
                 f"Способ оплаты: 💵 USDT (BEP-20)\n"
                 f"Пользователь: @{query.from_user.username or 'без username'} "
                 f"({query.from_user.first_name})\n"
                 f"User ID: {query.from_user.id}\n"
                 f"Тариф: {tariff['name']} - {tariff['price_usdt']} USDT"
        )
    except Exception as e:
        logger.error(f"Ошибка при уведомлении админа: {e}")

    # Показываем реквизиты USDT
    keyboard = [[InlineKeyboardButton("✅ Я оплатил", callback_data=f'paid_usdt_{request_id}_{tariff_key}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"💵 Оплата подписки: {tariff['name']}\n"
        f"Сумма: {tariff['price_usdt']} USDT\n\n"
        f"💰 Адрес кошелька USDT (BEP-20):\n"
        f"`{USDT_WALLET}`\n\n"
        f"⚠️ Внимание! Отправляйте ТОЛЬКО USDT по сети BEP-20 (Binance Smart Chain)!\n\n"
        f"После оплаты нажми кнопку ниже.\n"
        f"Доступ будет активирован в течение 15 минут.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение оплаты от пользователя"""
    query = update.callback_query
    await query.answer()

    # Безопасный парсинг callback_data: paid_METHOD_REQUEST_ID_TARIFF_KEY
    try:
        # Убираем префикс 'paid_'
        data = query.data.replace('paid_', '')
        parts = data.split('_')

        # Определяем метод оплаты
        payment_method = parts[0]  # card или usdt
        request_id = int(parts[1])
        tariff_key = '_'.join(parts[2:])  # Соединяем все части после request_id: '1_day'

        # Проверяем корректность тарифа
        if tariff_key not in TARIFFS:
            await query.answer("❌ Некорректный тариф", show_alert=True)
            logger.error(f"Некорректный tariff_key в payment_confirmation: {tariff_key}")
            return

        tariff = TARIFFS[tariff_key]
    except (IndexError, ValueError) as e:
        logger.error(f"Ошибка парсинга callback_data в payment_confirmation: {query.data}, {e}")
        await query.answer("❌ Некорректные данные", show_alert=True)
        return
    
    user_id = query.from_user.id

    # Определяем сообщение в зависимости от метода оплаты
    payment_info = ""
    if payment_method == 'card':
        payment_info = f"💳 Карта - {tariff['price']}₽"
    elif payment_method == 'usdt':
        payment_info = f"💵 USDT - {tariff['price_usdt']} USDT"

    # Уведомляем админа с кнопкой активации
    try:
        keyboard = [[
            InlineKeyboardButton(
                f"✅ Активировать ({tariff['name']})",
                callback_data=f'admin_activate_{user_id}_{tariff["days"]}'
            )
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"✅ Пользователь подтвердил оплату!\n\n"
                 f"ID заявки: {request_id}\n"
                 f"Способ оплаты: {payment_info}\n"
                 f"Пользователь: @{query.from_user.username or 'без username'} "
                 f"({query.from_user.first_name})\n"
                 f"User ID: {user_id}\n"
                 f"Тариф: {tariff['name']}\n\n"
                 f"Проверь платеж и нажми кнопку ниже:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка при уведомлении админа о подтверждении: {e}")
    
    await query.edit_message_text(
        "✅ Спасибо! Твоя заявка принята.\n\n"
        "⏳ Ожидай активации подписки (обычно в течение 5-10 минут).\n"
        "Как только доступ будет активирован, я сразу тебе напишу!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 В начало", callback_data='go_start')
        ]])
    )
    
    # Запланировать напоминание через 1 час
    context.job_queue.run_once(
        send_payment_reminder,
        3600,  # 3600 секунд = 1 час
        data={'user_id': user_id, 'request_id': request_id},
        name=f'reminder_{user_id}_{request_id}'
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение платежа Stars перед оплатой"""
    query = update.pre_checkout_query
    # Всегда подтверждаем платеж
    await query.answer(ok=True)


async def successful_payment_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка успешной оплаты через Stars"""
    payment = update.message.successful_payment
    user_id = update.effective_user.id

    # Парсим payload: subscription_TARIFF_KEY_USER_ID
    try:
        payload_parts = payment.invoice_payload.split('_')
        tariff_key = '_'.join(payload_parts[1:-1])  # Получаем tariff_key (например, "1_day")

        if tariff_key not in TARIFFS:
            logger.error(f"Некорректный tariff_key из payload: {tariff_key}")
            await update.message.reply_text("❌ Ошибка обработки платежа. Обратитесь к администратору.")
            return

        tariff = TARIFFS[tariff_key]

        # Активируем подписку автоматически
        end_date = db.add_subscription(user_id, tariff['days'], tariff_key)

        # Уведомляем админа об успешной оплате Stars
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⭐ Успешная оплата через Stars!\n\n"
                     f"Пользователь: @{update.effective_user.username or 'без username'} "
                     f"({update.effective_user.first_name})\n"
                     f"User ID: {user_id}\n"
                     f"Тариф: {tariff['name']}\n"
                     f"Сумма: {tariff['price_stars']} Stars\n"
                     f"Подписка активирована до: {end_date.strftime('%d.%m.%Y %H:%M')}"
            )
        except Exception as e:
            logger.error(f"Ошибка при уведомлении админа об оплате Stars: {e}")

        # Уведомляем пользователя
        await update.message.reply_text(
            f"🎉 Оплата успешна!\n\n"
            f"✅ Подписка активирована!\n"
            f"Тариф: {tariff['name']}\n"
            f"Активна до: {end_date.strftime('%d.%m.%Y %H:%M')}"
        )

        # Проверяем есть ли сохраненные результаты поиска
        if user_id in user_search_results:
            # Есть сохраненные результаты - показываем их
            filtered = user_search_results[user_id]

            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔍 Вот результаты твоего поиска ({len(filtered)} вариантов):"
            )

            await show_results_function(context, user_id, filtered)

            # Очищаем сохраненные результаты
            del user_search_results[user_id]

            # Очищаем фильтры
            if user_id in user_filters:
                del user_filters[user_id]
        else:
            # Нет сохраненных результатов - начинаем новый поиск
            user_filters[user_id] = {}

            keyboard = [
                [InlineKeyboardButton("🏖️ Ейск", callback_data='location_ейск')],
                [InlineKeyboardButton("🌊 Должанская", callback_data='location_должанская')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await context.bot.send_message(
                chat_id=user_id,
                text="🔍 Давай найдем жилье для тебя!\n\n1️⃣ Выбери населённый пункт:",
                reply_markup=reply_markup
            )

    except Exception as e:
        logger.error(f"Ошибка при обработке успешной оплаты Stars: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при активации подписки.\n"
            "Пожалуйста, обратитесь к администратору."
        )


async def send_payment_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Отправка напоминания если подписка не активирована через 1 час"""
    job_data = context.job.data
    user_id = job_data['user_id']
    request_id = job_data['request_id']

    # Проверяем, активирована ли подписка
    has_subscription, end_date = db.check_subscription(user_id)

    if not has_subscription:
        # Подписка не активирована - отправляем напоминание
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏰ Прошел 1 час с момента подтверждения оплаты.\n\n"
                     f"Если ваша подписка по каким-то причинам не активирована, "
                     f"пожалуйста, обратитесь к администратору:\n"
                     f"👤 https://t.me/Den_Shev_007\n\n"
                     f"📎 Прикрепите чек об оплате.\n\n"
                     f"Спасибо за понимание! 🙏"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке напоминания пользователю {user_id}: {e}")


async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало поиска жилья"""
    user_id = update.effective_user.id
    
    # Инициализируем фильтры для всех
    user_filters[user_id] = {}
    
    # ПЕРВЫЙ ВОПРОС - выбор населённого пункта
    keyboard = [
        [InlineKeyboardButton("🏖️ Ейск", callback_data='location_ейск')],
        [InlineKeyboardButton("🌊 Должанская", callback_data='location_должанская')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔍 Давай найдем идеальное жилье!\n\n"
        "1️⃣ Выбери населённый пункт:",
        reply_markup=reply_markup
    )


async def show_results_function(context, user_id, filtered, start_index=0):
    """Вспомогательная функция для показа результатов с пагинацией"""
    
    RESULTS_PER_PAGE = 20  # Показываем по 20 за раз
    
    total_results = len(filtered)
    end_index = min(start_index + RESULTS_PER_PAGE, total_results)
    current_batch = filtered[start_index:end_index]
    
    # Первое сообщение только при start_index = 0
    if start_index == 0:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Найдено вариантов: {total_results}\n\n"
                 f"Сейчас покажу их по очереди:"
        )
    
    for i, apt in enumerate(current_batch, start_index + 1):
        # Заголовок
        text = f"📍 Вариант {i} ⬇️⬇️⬇️\n\n"
        
        # Основная информация
        tip = apt.get('Тип_жилья', 'не указан')
        if tip == '1-комн':
            tip = '1-комнатная квартира'
        elif tip == '2-комн':
            tip = '2-комнатная квартира'
        elif tip == '3-комн':
            tip = '3-комнатная квартира'
        elif tip == 'частный дом':
            tip = 'Частный дом'
        elif tip == 'гостевой дом':
            tip = 'Гостевой дом'
        
        text += f"🏠 {tip}\n"
        text += f"🏖️ {apt.get('Расстояние_от_моря_м', '?')} метров от моря\n"
        text += f"👥 До {apt.get('Гостей_макс', '?')} гостей\n"
        
        # Цена
        price = apt.get('Цена_за_сутки', '')
        if price and price != 'по запросу':
            text += f"💰 {price}₽/сутки\n"
        else:
            text += f"💰 Цена по запросу\n"
        
        # Описание (если есть)
        description = apt.get('Описание', '').strip()
        if description:
            text += f"\n📝 {description}\n"
        
        # Контакты - сначала телефон
        text += f"\n📞 {apt.get('Телефон', 'не указан')}\n"
        
        # Потом имя хозяина (если есть)
        owner = apt.get('Имя_хозяина', '').strip()
        if owner:
            text += f"👤 {owner}\n"
        
        # VK ссылка с красивым текстом
        vk_link = apt.get('VK_ссылка', '').strip()
        if vk_link and vk_link.startswith('http'):
            text += f"\n🔗 Подробнее здесь: {vk_link}"

        # Если есть фото
        photo_url = apt.get('Фото_URL', '').strip()
        if photo_url and photo_url.startswith('http'):
            try:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo_url,
                    caption=text
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке фото: {e}")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=text
                )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=text
            )
    
    # Проверяем есть ли еще результаты
    remaining = total_results - end_index
    
    if remaining > 0:
        # Есть еще результаты - показываем кнопку "Показать еще"
        # Сохраняем данные для следующей порции
        user_pagination_data[user_id] = {
            'filtered': filtered,
            'next_index': end_index
        }
        
        keyboard = [
            [InlineKeyboardButton(f"📋 Показать еще {remaining}", callback_data='show_more')],
            [InlineKeyboardButton("🔍 Новый поиск", callback_data='new_search')]
        ]
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Показано {end_index} из {total_results} вариантов",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # Все результаты показаны
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ Все результаты показаны!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Новый поиск", callback_data='new_search')
            ]])
        )


async def select_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор населённого пункта"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    location = query.data.replace('location_', '')
    
    # Инициализируем фильтры если их нет
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    # Сохраняем выбор
    user_filters[user_id]['location'] = location
    
    # Если выбрана Должанская - сразу показываем все объявления
    if location == 'должанская':
        await query.edit_message_text("🔍 Ищу все варианты в Должанской...")
        
        # Получаем все объявления Должанской
        all_apartments = sheets.read_apartments()
        filtered = [apt for apt in all_apartments if apt.get('Населенный_пункт', '').lower() == 'должанская']
        
        # Логируем поиск
        db.log_search(user_id, user_filters[user_id], len(filtered))
        
        if not filtered:
            await context.bot.send_message(
                chat_id=user_id,
                text="😔 К сожалению, в Должанской пока нет объявлений.\n\n"
                     "Попробуй поискать в Ейске:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔍 Новый поиск", callback_data='new_search')
                ]])
            )
            if user_id in user_filters:
                del user_filters[user_id]
            return
        
        # Проверяем подписку
        has_subscription, end_date = db.check_subscription(user_id)
        
        if has_subscription:
            # Если есть подписка - показываем результаты
            await show_results_function(context, user_id, filtered)
            
            # Очищаем фильтры
            if user_id in user_filters:
                del user_filters[user_id]
        else:
            # Если нет подписки - показываем количество и предлагаем оплатить
            # Сохраняем результаты для показа после оплаты
            user_search_results[user_id] = filtered
            
            keyboard = [
                [InlineKeyboardButton(f"💳 {TARIFFS['1_day']['name']} - {TARIFFS['1_day']['price']}₽", 
                                     callback_data='buy_1_day')],
                [InlineKeyboardButton(f"💳 {TARIFFS['7_days']['name']} - {TARIFFS['7_days']['price']}₽", 
                                     callback_data='buy_7_days')],
                [InlineKeyboardButton("🔍 Новый поиск", callback_data='new_search')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ Найдено вариантов: {len(filtered)}\n\n"
                     f"Для просмотра контактов и фотографий жилья нужна подписка.\n\n"
                     f"Выбери тариф:",
                reply_markup=reply_markup
            )
            
            # НЕ очищаем фильтры - они могут пригодиться
    
    # Если выбран Ейск - задаём вопросы
    else:
        keyboard = [
            [InlineKeyboardButton("🏠 1-комнатная", callback_data='type_1-комн')],
            [InlineKeyboardButton("🏡 2-комнатная", callback_data='type_2-комн')],
            [InlineKeyboardButton("🏘 3-комнатная", callback_data='type_3-комн')],
            [InlineKeyboardButton("🏘️ Частный дом", callback_data='type_частный дом')],
            [InlineKeyboardButton("🏨 Гостевой дом", callback_data='type_гостевой дом')],
            [InlineKeyboardButton("➡️ Любой тип", callback_data='type_any')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "2️⃣ Какой тип жилья тебе нужен?",
            reply_markup=reply_markup
        )
    
    


async def select_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор типа жилья"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    type_choice = query.data.replace('type_', '')
    
    # Инициализируем фильтры если их нет
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    if type_choice != 'any':
        user_filters[user_id]['type'] = type_choice
    
    # Вопрос о количестве гостей
    keyboard = [
        [InlineKeyboardButton("👤 1-2 гостя", callback_data='guests_2')],
        [InlineKeyboardButton("👥 3-4 гостя", callback_data='guests_4')],
        [InlineKeyboardButton("👨‍👩‍👧‍👦 5-6 гостей", callback_data='guests_6')],
        [InlineKeyboardButton("🏢 7+ гостей", callback_data='guests_7')],
        [InlineKeyboardButton("➡️ Не важно", callback_data='guests_any')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "3️⃣ Сколько человек будет отдыхать?",
        reply_markup=reply_markup
    )


async def select_guests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор количества гостей"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    guests_choice = query.data.replace('guests_', '')
    
    # Инициализируем фильтры если их нет
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    if guests_choice != 'any':
        user_filters[user_id]['guests'] = int(guests_choice)
    
    # ПРОВЕРКА: Если гостевой дом + 5-6 или 7+ гостей → спрашиваем про 2 номера
    is_guesthouse = user_filters[user_id].get('type') == 'гостевой дом'
    is_many_guests = guests_choice in ['6', '7']  # 5-6 гостей или 7+
    
    if is_guesthouse and is_many_guests:
        # Задаём дополнительный вопрос про 2 номера
        keyboard = [
            [InlineKeyboardButton("✅ Да, подойдет 2 номера", callback_data='two_rooms_yes')],
            [InlineKeyboardButton("❌ Нет, нужен один номер", callback_data='two_rooms_no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💡 Вам подойдет 2 номера?\n\n"
            "Это увеличит шансы найти варианты для большой компании!",
            reply_markup=reply_markup
        )
        return
    
    # Обычный вопрос о расстоянии от моря
    keyboard = [
        [InlineKeyboardButton("🏖️ До 100м", callback_data='dist_0-100')],
        [InlineKeyboardButton("🚶 150-500м", callback_data='dist_150-500')],
        [InlineKeyboardButton("🚗 500-1000м", callback_data='dist_500-1000')],
        [InlineKeyboardButton("🏙️ Более 1000м", callback_data='dist_1000-99999')],
        [InlineKeyboardButton("➡️ Не важно", callback_data='dist_any')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "4️⃣ На каком расстоянии от моря?",
        reply_markup=reply_markup
    )


async def select_two_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа на вопрос про 2 номера"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    answer = query.data.replace('two_rooms_', '')
    
    # Инициализируем фильтры если их нет
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    # Если ДА - меняем фильтр на 3-6 человек
    if answer == 'yes':
        user_filters[user_id]['guests'] = 6  # Ищем номера до 6 человек
        user_filters[user_id]['two_rooms_mode'] = True  # Флаг что ищем 2 номера
    # Если НЕТ - оставляем как есть (5-6 или 7+)
    
    # Переходим к вопросу о расстоянии
    keyboard = [
        [InlineKeyboardButton("🏖️ До 100м", callback_data='dist_0-100')],
        [InlineKeyboardButton("🚶 150-500м", callback_data='dist_150-500')],
        [InlineKeyboardButton("🚗 500-1000м", callback_data='dist_500-1000')],
        [InlineKeyboardButton("🏙️ Более 1000м", callback_data='dist_1000-99999')],
        [InlineKeyboardButton("➡️ Не важно", callback_data='dist_any')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "4️⃣ На каком расстоянии от моря?",
        reply_markup=reply_markup
    )


async def select_distance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор расстояния от моря - ПОСЛЕДНИЙ вопрос, затем показ результатов"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    dist_choice = query.data.replace('dist_', '')
    
    # Инициализируем фильтры если их нет
    if user_id not in user_filters:
        user_filters[user_id] = {}
    
    # Парсим диапазон (например "150-500" или "0-100")
    if dist_choice != 'any':
        min_dist, max_dist = dist_choice.split('-')
        user_filters[user_id]['min_distance'] = int(min_dist)
        user_filters[user_id]['max_distance'] = int(max_dist)
    
    # ПРОВЕРКА: если не выбран ни один фильтр кроме города → просим уточнить
    filters = user_filters[user_id]
    has_filters = any([
        filters.get('type'),           # тип жилья
        filters.get('guests'),         # количество гостей
        filters.get('min_distance'),   # расстояние от моря
        filters.get('max_distance')
    ])
    
    if not has_filters:
        await query.edit_message_text(
            "🤔 Вы не выбрали ни один параметр поиска.\n\n"
            "Пожалуйста, выберите хотя бы один из фильтров "
            "(тип жилья, количество гостей или расстояние до моря), "
            "чтобы я мог найти для вас подходящие варианты!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Новый поиск", callback_data='new_search')
            ]])
        )
        # Очищаем фильтры
        if user_id in user_filters:
            del user_filters[user_id]
        return
    
    # Показываем результаты
    await query.edit_message_text("🔍 Ищу подходящие варианты...")
    
    # Получаем объявления из таблицы
    all_apartments = sheets.read_apartments()
    
    # Фильтруем
    filtered = sheets.filter_apartments(all_apartments, user_filters[user_id])
    
    # Логируем поиск
    db.log_search(user_id, user_filters[user_id], len(filtered))
    
    if not filtered:
        await context.bot.send_message(
            chat_id=user_id,
            text="😔 К сожалению, по твоим критериям ничего не найдено.\n\n"
                 "Попробуй изменить параметры поиска:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Новый поиск", callback_data='new_search')
            ]])
        )
        # Очищаем фильтры
        if user_id in user_filters:
            del user_filters[user_id]
        return
    
    # Проверяем подписку
    has_subscription, end_date = db.check_subscription(user_id)
    
    if has_subscription:
        # Если есть подписка - показываем результаты
        await show_results_function(context, user_id, filtered)
        
        # Очищаем фильтры
        if user_id in user_filters:
            del user_filters[user_id]
    else:
        # Если нет подписки - показываем количество и предлагаем оплатить
        # Сохраняем результаты для показа после оплаты
        user_search_results[user_id] = filtered
        
        keyboard = [
            [InlineKeyboardButton(f"💳 {TARIFFS['1_day']['name']} - {TARIFFS['1_day']['price']}₽", 
                                 callback_data='buy_1_day')],
            [InlineKeyboardButton(f"💳 {TARIFFS['7_days']['name']} - {TARIFFS['7_days']['price']}₽", 
                                 callback_data='buy_7_days')],
            [InlineKeyboardButton("🔍 Новый поиск", callback_data='new_search')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Найдено вариантов: {len(filtered)}\n\n"
                 f"Для просмотра контактов и фотографий жилья нужна подписка.\n\n"
                 f"Выбери тариф:",
            reply_markup=reply_markup
        )
        
        # НЕ очищаем фильтры - они могут пригодиться


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена поиска"""
    user_id = update.effective_user.id
    if user_id in user_filters:
        del user_filters[user_id]
    
    await update.message.reply_text(
        "❌ Поиск отменен.\n\n"
        "Для нового поиска используй /search"
    )
    


# === АДМИНСКИЕ КОМАНДЫ ===

async def admin_activate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки активации подписки админом"""
    query = update.callback_query
    
    # Проверка что это админ
    if query.from_user.id != ADMIN_ID:
        await query.answer("⛔ Только для администратора", show_alert=True)
        return
    
    await query.answer()
    
    # Безопасный парсинг данных: admin_activate_USER_ID_DAYS
    try:
        parts = query.data.replace('admin_activate_', '').split('_')
        user_id = int(parts[0])
        days = int(parts[1])
    except (IndexError, ValueError) as e:
        logger.error(f"Ошибка парсинга admin callback_data: {query.data}, {e}")
        await query.answer("❌ Некорректные данные", show_alert=True)
        return
    
    try:
        # Активируем подписку
        end_date = db.add_subscription(user_id, days, f"{days}_days")
        
        # Отменяем запланированное напоминание если оно есть
        # Ищем все задачи и отменяем те, которые относятся к этому пользователю
        all_jobs = context.job_queue.jobs()
        for job in all_jobs:
            if job.name and job.name.startswith(f'reminder_{user_id}_'):
                job.schedule_removal()
        
        # Обновляем сообщение админу
        await query.edit_message_text(
            f"✅ Подписка активирована!\n\n"
            f"User ID: {user_id}\n"
            f"Дней: {days}\n"
            f"До: {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        
        # Уведомляем пользователя
        try:
            tariff_name = f"{days} " + ("день" if days == 1 else "дней")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 Подписка активирована!\n\n"
                     f"Тариф: {tariff_name}\n"
                     f"Активна до: {end_date.strftime('%d.%m.%Y %H:%M')}"
            )
            
            # Проверяем есть ли сохраненные результаты поиска
            if user_id in user_search_results:
                # Есть сохраненные результаты - показываем их
                filtered = user_search_results[user_id]
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🔍 Вот результаты твоего поиска ({len(filtered)} вариантов):"
                )
                
                await show_results_function(context, user_id, filtered)
                
                # Очищаем сохраненные результаты
                del user_search_results[user_id]
                
                # Очищаем фильтры
                if user_id in user_filters:
                    del user_filters[user_id]
            else:
                # Нет сохраненных результатов - начинаем новый поиск
                # Инициализируем фильтры
                user_filters[user_id] = {}
                
                # Запускаем поиск автоматически
                keyboard = [
                    [InlineKeyboardButton("🏖️ Ейск", callback_data='location_ейск')],
                    [InlineKeyboardButton("🌊 Должанская", callback_data='location_должанская')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🔍 Давай найдем жилье для тебя!\n\n1️⃣ Выбери населённый пункт:",
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Ошибка при уведомлении пользователя об активации: {e}")
            
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка при активации: {e}"
        )


async def activate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активация подписки пользователю (только для админа)"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(context.args[0])
        days = int(context.args[1])
        
        end_date = db.add_subscription(user_id, days, f"{days}_days")
        
        # Отменяем запланированное напоминание если оно есть
        all_jobs = context.job_queue.jobs()
        for job in all_jobs:
            if job.name and job.name.startswith(f'reminder_{user_id}_'):
                job.schedule_removal()
        
        await update.message.reply_text(
            f"✅ Подписка активирована!\n\n"
            f"User ID: {user_id}\n"
            f"Дней: {days}\n"
            f"До: {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        
        # Уведомляем пользователя и сразу запускаем поиск
        try:
            tariff_name = f"{days} " + ("день" if days == 1 else "дней")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 Подписка активирована!\n\n"
                     f"Тариф: {tariff_name}\n"
                     f"Активна до: {end_date.strftime('%d.%m.%Y %H:%M')}\n\n"
                     f"🔍 Давай найдем жилье для тебя!"
            )
            
            # Инициализируем фильтры
            user_filters[user_id] = {}
            
            # Запускаем поиск автоматически - ПЕРВЫЙ ВОПРОС о населённом пункте
            keyboard = [
                [InlineKeyboardButton("🏖️ Ейск", callback_data='location_ейск')],
                [InlineKeyboardButton("🌊 Должанская", callback_data='location_должанская')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=user_id,
                text="1️⃣ Выбери населённый пункт:",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка при уведомлении пользователя об активации: {e}")
            
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❌ Неверный формат команды\n\n"
            "Используй: /activate <user_id> <дни>\n"
            "Пример: /activate 123456789 7"
        )


async def check_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса пользователя (только для админа)"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(context.args[0])
        has_sub, end_date = db.check_subscription(user_id)
        
        if has_sub:
            await update.message.reply_text(
                f"✅ Подписка активна\n\n"
                f"User ID: {user_id}\n"
                f"До: {end_date.strftime('%d.%m.%Y %H:%M')}"
            )
        else:
            await update.message.reply_text(
                f"❌ Подписка неактивна\n\n"
                f"User ID: {user_id}"
            )
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❌ Неверный формат\n\n"
            "Используй: /check <user_id>"
        )


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ статистики (только для админа)"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    stats = db.get_stats()
    
    text = "📊 Статистика бота\n\n"
    text += f"👥 Всего пользователей: {stats['total_users']}\n"
    text += f"✅ Активных подписок: {stats['active_subscriptions']}\n"
    text += f"⏳ Ожидают оплаты: {stats['pending_payments']}\n"
    text += f"🔍 Поисков сегодня: {stats['searches_today']}\n"
    
    await update.message.reply_text(text)


async def show_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ ожидающих оплат (только для админа)"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    pending = db.get_pending_payments()
    
    if not pending:
        await update.message.reply_text("✅ Нет ожидающих оплат")
        return
    
    text = "⏳ Ожидающие оплаты:\n\n"
    for req_id, user_id, username, first_name, tariff, created_at in pending:
        text += f"ID: {req_id}\n"
        text += f"User: @{username or 'нет'} ({first_name})\n"
        text += f"User ID: {user_id}\n"
        text += f"Тариф: {tariff}\n"
        text += f"Создано: {created_at}\n"
        text += f"Активировать: /activate {user_id} {TARIFFS[tariff]['days']}\n\n"
    
    await update.message.reply_text(text)


async def show_more_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Показать еще'"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Получаем сохраненные данные
    if user_id not in user_pagination_data:
        await query.edit_message_text(
            "⚠️ Данные поиска устарели. Начните новый поиск:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔍 Новый поиск", callback_data='new_search')
            ]])
        )
        return
    
    data = user_pagination_data[user_id]
    filtered = data['filtered']
    next_index = data['next_index']
    
    await query.edit_message_text("🔍 Загружаю еще варианты...")
    
    # Показываем следующую порцию
    await show_results_function(context, user_id, filtered, start_index=next_index)
    
    # Очищаем данные пагинации если все показано
    remaining = len(filtered) - next_index - RESULTS_PER_PAGE
    if remaining <= 0:
        if user_id in user_pagination_data:
            del user_pagination_data[user_id]


async def go_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'В начало'"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = query.from_user
    
    # Проверяем подписку для информации
    has_subscription, end_date = db.check_subscription(user_id)
    
    # Приветствие
    if has_subscription:
        await query.edit_message_text(
            f"{WELCOME_TEXT}\n\n"
            f"✅ Подписка активна до {end_date.strftime('%d.%m.%Y %H:%M')}"
        )
    else:
        await query.edit_message_text(WELCOME_TEXT)
    
    # Инициализируем фильтры для всех
    user_filters[user_id] = {}
    
    # Показываем выбор населённого пункта
    keyboard = [
        [InlineKeyboardButton("🏖️ Ейск", callback_data='location_ейск')],
        [InlineKeyboardButton("🌊 Должанская", callback_data='location_должанская')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=user_id,
        text="🔍 Давай найдем идеальное жилье!\n\n"
             "1️⃣ Выбери населённый пункт:",
        reply_markup=reply_markup
    )


async def new_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки 'Новый поиск'"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Очищаем старые фильтры если есть
    if user_id in user_filters:
        del user_filters[user_id]
    
    # Инициализируем новые фильтры
    user_filters[user_id] = {}
    
    # Показываем выбор населённого пункта
    keyboard = [
        [InlineKeyboardButton("🏖️ Ейск", callback_data='location_ейск')],
        [InlineKeyboardButton("🌊 Должанская", callback_data='location_должанская')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🔍 Давай найдем идеальное жилье!\n\n"
        "1️⃣ Выбери населённый пункт:",
        reply_markup=reply_markup
    )


# Константа для использования в show_more_handler
RESULTS_PER_PAGE = 20


def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('search', search_start))
    application.add_handler(CommandHandler('cancel', cancel))

    # Обработчики оплаты Stars
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_stars))

    # Обработчики кнопок (callback queries)
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

    # Админские команды
    application.add_handler(CommandHandler('activate', activate_user))
    application.add_handler(CommandHandler('check', check_user))
    application.add_handler(CommandHandler('stats', show_stats))
    application.add_handler(CommandHandler('pending', show_pending))

    # Запускаем бота
    logger.info("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
