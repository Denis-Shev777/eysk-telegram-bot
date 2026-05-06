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

# Telegram Bot Token (получен от @BotFather) — нужен только для Telegram-бота
BOT_TOKEN = _get_env("BOT_TOKEN", required=False, allow_whitespace=False)

# ID администратора в Telegram — нужен только для Telegram-бота
_admin_id_raw = _get_env("ADMIN_ID", required=False, allow_whitespace=False)
try:
    ADMIN_ID = int(_admin_id_raw) if _admin_id_raw else None
except ValueError as exc:
    raise ValueError("Переменная окружения ADMIN_ID должна быть числом") from exc

# ВКонтакте: токен сообщества (Управление → Настройки → Работа с API)
VK_TOKEN = _get_env("VK_TOKEN", required=False, allow_whitespace=False)

# ВКонтакте: VK user_id администратора (твой личный ID ВКонтакте)
_admin_vk_id_raw = _get_env("ADMIN_VK_ID", required=False, allow_whitespace=False)
try:
    ADMIN_VK_ID = int(_admin_vk_id_raw) if _admin_vk_id_raw else None
except ValueError as exc:
    raise ValueError("Переменная окружения ADMIN_VK_ID должна быть числом") from exc

# Реквизиты для оплаты
PAYMENT_CARD = _get_env("PAYMENT_CARD", required=False)
PAYMENT_RECIPIENT = _get_env("PAYMENT_RECIPIENT", required=False)

# Номер телефона для пополнения баланса (Теле2)
PAYMENT_PHONE = _get_env("PAYMENT_PHONE", required=False) or "+7-929-830-17-02"

# USDT кошелек (BEP-20 / Binance Smart Chain)
USDT_WALLET = _get_env("USDT_WALLET", required=False)

# Тарифы (в рублях, stars и USDT)
TARIFFS = {
    "1_month": {
        "price": 99,
        "price_usdt": 1.5,
        "days": 30,
        "name": "1 месяц"
    },
    "3_months": {
        "price": 299,
        "price_usdt": 4,
        "days": 90,
        "name": "3 месяца"
    },
}

# Текст приветствия
WELCOME_TEXT = """
👋 Привет! Это бот сообщества Ейск и Должанская.

Выбери, что хочешь сделать:
"""

# Текст для неактивной подписки
SUBSCRIPTION_REQUIRED = """
⚠️ Для поиска жилья необходима активная подписка.

Выбери тариф:
"""
