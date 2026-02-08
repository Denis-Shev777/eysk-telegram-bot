# Конфигурация бота
import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

def _get_env(
    name: str,
    required: bool = True,
    allow_whitespace: bool = True,
) -> str | None:
    value = os.getenv(name)
    if value is None:
        if required:
            raise ValueError(f"Переменная окружения {name} не задана")
        return None
    value = value.strip()
    if required and not value:
        raise ValueError(f"Переменная окружения {name} пуста")
    if not allow_whitespace and any(char.isspace() for char in value):
        raise ValueError(
            f"Переменная окружения {name} содержит пробелы или переносы строк"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(
            f"Переменная окружения {name} содержит непечатные символы"
        )
    return value

# Telegram Bot Token (получен от @BotFather)
BOT_TOKEN = _get_env("BOT_TOKEN", allow_whitespace=False)

# ID администратора (твой Telegram ID)
_admin_id_raw = _get_env("ADMIN_ID", allow_whitespace=False)
try:
    ADMIN_ID = int(_admin_id_raw)
except ValueError as exc:
    raise ValueError("Переменная окружения ADMIN_ID должна быть числом") from exc

# Реквизиты для оплаты
PAYMENT_CARD = _get_env("PAYMENT_CARD", required=False)
PAYMENT_RECIPIENT = _get_env("PAYMENT_RECIPIENT", required=False)

# Номер телефона для пополнения баланса (Теле2)
PAYMENT_PHONE = _get_env("PAYMENT_PHONE", required=False) or "+7-929-830-17-02"

# USDT кошелек (BEP-20 / Binance Smart Chain)
USDT_WALLET = _get_env("USDT_WALLET", required=False)

# Тарифы (в рублях, stars и USDT)
TARIFFS = {
    "1_day": {
        "price": 99,
        "price_stars": 80,   # Цена в Telegram Stars
        "price_usdt": 1.5,   # Цена в USDT
        "days": 1,
        "name": "1 день"
    },
    "7_days": {
        "price": 299,
        "price_stars": 250,  # Цена в Telegram Stars
        "price_usdt": 5,     # Цена в USDT
        "days": 7,
        "name": "7 дней"
    },
    "30_days": {
        "price": 499,
        "price_stars": 400,  # Цена в Telegram Stars
        "price_usdt": 7.5,   # Цена в USDT
        "days": 30,
        "name": "30 дней"
    }
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
