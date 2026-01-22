# Используем легковесный образ Python для минимального потребления RAM
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости без кэша для экономии места
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта
COPY . .

# Создаем директорию для базы данных
RUN mkdir -p /app/data

# Переменные окружения для оптимизации Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Запускаем бота
CMD ["python", "Eysk_bot.py"]
