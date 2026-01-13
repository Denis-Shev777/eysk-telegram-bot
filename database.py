import sqlite3
from datetime import datetime, timedelta
import pytz

class Database:
    def __init__(self, db_file='users.db'):
        self.db_file = db_file
        self.msk_tz = pytz.timezone('Europe/Moscow')
        self.init_db()
    
    def init_db(self):
        """Создает таблицы если их нет"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица подписок
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    start_date TIMESTAMP,
                    end_date TIMESTAMP,
                    tariff TEXT,
                    status TEXT DEFAULT 'active',
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица заявок на оплату
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payment_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    tariff TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            # Таблица поисковых запросов (статистика)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS search_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    filters TEXT,
                    results_count INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            conn.commit()
    
    def add_user(self, user_id, username, first_name):
        """Добавляет нового пользователя"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
            ''', (user_id, username, first_name))
            conn.commit()
    
    def check_subscription(self, user_id):
        """Проверяет активна ли подписка"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT end_date FROM subscriptions
                WHERE user_id = ? AND status = 'active'
                ORDER BY end_date DESC LIMIT 1
            ''', (user_id,))
            result = cursor.fetchone()
        
        if result:
            # Преобразуем строку в datetime с timezone
            end_date_str = result[0]
            # Если в БД уже есть данные с timezone
            if '+' in end_date_str or end_date_str.endswith('Z'):
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
            else:
                # Старые данные без timezone - считаем их МСК
                end_date = datetime.fromisoformat(end_date_str)
                end_date = self.msk_tz.localize(end_date)
            
            # Текущее время в МСК
            now_msk = datetime.now(self.msk_tz)
            
            if now_msk < end_date:
                return True, end_date
            else:
                self.deactivate_subscription(user_id)
                return False, None
        return False, None
    
    def add_subscription(self, user_id, days, tariff):
        """Добавляет подписку пользователю"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            # Используем московское время
            start_date = datetime.now(self.msk_tz)
            end_date = start_date + timedelta(days=days)
            
            cursor.execute('''
                INSERT INTO subscriptions (user_id, start_date, end_date, tariff, status)
                VALUES (?, ?, ?, ?, 'active')
            ''', (user_id, start_date.isoformat(), end_date.isoformat(), tariff))
            
            conn.commit()
            return end_date
    
    def deactivate_subscription(self, user_id):
        """Деактивирует подписку"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE subscriptions
                SET status = 'expired'
                WHERE user_id = ? AND status = 'active'
            ''', (user_id,))
            conn.commit()
    
    def add_payment_request(self, user_id, tariff):
        """Добавляет заявку на оплату"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO payment_requests (user_id, tariff, status)
                VALUES (?, ?, 'pending')
            ''', (user_id, tariff))
            request_id = cursor.lastrowid
            conn.commit()
            return request_id
    
    def get_pending_payments(self):
        """Получает все ожидающие оплаты"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT pr.id, pr.user_id, u.username, u.first_name, pr.tariff, pr.created_at
                FROM payment_requests pr
                JOIN users u ON pr.user_id = u.user_id
                WHERE pr.status = 'pending'
                ORDER BY pr.created_at DESC
            ''')
            results = cursor.fetchall()
            return results
    
    def approve_payment(self, request_id):
        """Одобряет платеж"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE payment_requests
                SET status = 'approved'
                WHERE id = ?
            ''', (request_id,))
            conn.commit()
    
    def get_stats(self):
        """Получает статистику"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            
            # Всего пользователей
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            # Активных подписок
            cursor.execute('''
                SELECT COUNT(*) FROM subscriptions
                WHERE status = 'active' AND end_date > datetime('now')
            ''')
            active_subs = cursor.fetchone()[0]
            
            # Ожидающих оплаты
            cursor.execute('''
                SELECT COUNT(*) FROM payment_requests
                WHERE status = 'pending'
            ''')
            pending_payments = cursor.fetchone()[0]
            
            # Поисков сегодня
            cursor.execute('''
                SELECT COUNT(*) FROM search_logs
                WHERE DATE(created_at) = DATE('now')
            ''')
            searches_today = cursor.fetchone()[0]
            
            return {
                'total_users': total_users,
                'active_subscriptions': active_subs,
                'pending_payments': pending_payments,
                'searches_today': searches_today
            }
    
    def log_search(self, user_id, filters, results_count):
        """Логирует поисковый запрос"""
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO search_logs (user_id, filters, results_count)
                VALUES (?, ?, ?)
            ''', (user_id, str(filters), results_count))
            conn.commit()
