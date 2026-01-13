# Конфигурация бота
import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

# Telegram Bot Token (получен от @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ID администратора (твой Telegram ID)
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Реквизиты для оплаты
PAYMENT_CARD = os.getenv("PAYMENT_CARD")
PAYMENT_RECIPIENT = os.getenv("PAYMENT_RECIPIENT")

# Тарифы (в рублях)
TARIFFS = {
    "1_day": {"price": 99, "days": 1, "name": "1 день"},
    "7_days": {"price": 299, "days": 7, "name": "7 дней"}
}

# Текст приветствия
WELCOME_TEXT = """
👋 Добро пожаловать в бот для поиска жилья в Ейске и Должанской!

🏖️ Я помогу тебе найти идеальные варианты для отдыха:
• Квартиры, номера, дома
• Фильтр по расстоянию до моря
• Прямые контакты владельцев
"""

# Текст для неактивной подписки
SUBSCRIPTION_REQUIRED = """
⚠️ Для поиска жилья необходима активная подписка.

Выбери тариф:
"""
