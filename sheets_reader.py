import os
import time
try:
    import openpyxl
except ImportError:
    print("ОШИБКА: Не установлена библиотека openpyxl")
    print("Установите: pip install openpyxl")

class GoogleSheetsReader:
    """Читает данные из локального Excel файла с кешированием"""
    
    def __init__(self, sheet_url=None, cache_duration=300):
        # sheet_url теперь не используется, но оставляем для совместимости
        # Файл должен быть в той же папке что и бот
        self.excel_file = "apartments.xlsx"
        self.cache_duration = cache_duration  # Время кеширования в секундах (по умолчанию 5 минут)
        self._cache = None
        self._cache_time = 0
    
    def read_apartments(self):
        """Читает данные из Excel файла с кешированием"""
        # Проверяем кеш
        current_time = time.time()
        if self._cache is not None and (current_time - self._cache_time) < self.cache_duration:
            print(f"📦 Использую кешированные данные (возраст: {int(current_time - self._cache_time)}с)")
            return self._cache
        
        # Кеш устарел или пуст - читаем файл заново
        try:
            # Проверяем существование файла
            if not os.path.exists(self.excel_file):
                print(f"❌ Файл {self.excel_file} не найден!")
                print(f"Создайте файл {self.excel_file} в папке с ботом")
                return []
            
            print(f"📂 Читаю файл: {self.excel_file}")
            
            # Открываем Excel файл
            workbook = openpyxl.load_workbook(self.excel_file, data_only=True)
            sheet = workbook.active
            
            # Читаем заголовки (первая строка)
            headers = []
            for cell in sheet[1]:
                if cell.value:
                    headers.append(str(cell.value).strip())
            
            if not headers:
                print("❌ Не найдены заголовки в первой строке")
                return []
            
            print(f"📋 Заголовки: {headers}")
            
            # Читаем данные
            apartments = []
            for row_num, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                # Пропускаем полностью пустые строки
                if not any(row):
                    continue
                
                # Создаем словарь из заголовков и значений
                apartment = {}
                for i, header in enumerate(headers):
                    if i < len(row):
                        value = row[i]
                        # Конвертируем в строку, если не None
                        apartment[header] = str(value) if value is not None else ""
                    else:
                        apartment[header] = ""
                
                apartments.append(apartment)
            
            print(f"✅ Загружено объявлений: {len(apartments)}")
            workbook.close()
            
            # Сохраняем в кеш
            self._cache = apartments
            self._cache_time = current_time
            print(f"💾 Данные закешированы на {self.cache_duration}с")
            
            return apartments
            
        except Exception as e:
            print(f"❌ Ошибка при чтении файла {self.excel_file}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def clear_cache(self):
        """Очищает кеш принудительно"""
        self._cache = None
        self._cache_time = 0
        print("🗑️ Кеш очищен")
    
    def filter_apartments(self, apartments, filters):
        """Фильтрует объявления по параметрам"""
        result = []
        
        print(f"🔍 Применяю фильтры: {filters}")
        
        for apt in apartments:
            # Фильтр по населённому пункту
            if filters.get('location'):
                apt_location = apt.get('Населенный_пункт', '').lower().strip()
                filter_location = filters['location'].lower().strip()
                if apt_location != filter_location:
                    continue
            
            # Фильтр по типу жилья
            if filters.get('type'):
                apt_type = apt.get('Тип_жилья', '').lower().strip()
                filter_type = filters['type'].lower().strip()
                if apt_type != filter_type:
                    continue
            
            # Фильтр по расстоянию от моря (диапазон)
            if filters.get('min_distance') is not None or filters.get('max_distance') is not None:
                try:
                    distance = int(apt.get('Расстояние_от_моря_м', 99999))
                    
                    # Проверяем минимум
                    if filters.get('min_distance') is not None:
                        if distance < filters['min_distance']:
                            continue
                    
                    # Проверяем максимум
                    if filters.get('max_distance') is not None:
                        if distance > filters['max_distance']:
                            continue
                except (ValueError, TypeError):
                    continue
            
            # Фильтр по количеству гостей
            if filters.get('guests'):
                try:
                    max_guests = int(apt.get('Гостей_макс', 0))
                    
                    # Если включен режим "2 номера" - ищем номера от 3 до 6 человек
                    if filters.get('two_rooms_mode'):
                        if max_guests < 3 or max_guests > 6:
                            continue
                    else:
                        # Обычный режим - номер должен вмещать нужное количество
                        if max_guests < filters['guests']:
                            continue
                except (ValueError, TypeError):
                    continue
            
            result.append(apt)
        
        print(f"✅ Найдено после фильтрации: {len(result)}")
        return result
