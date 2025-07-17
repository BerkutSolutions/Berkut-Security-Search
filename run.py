# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.

import re
import sqlite3
from flask import Flask, Response, request, render_template
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Функция для нормализации текста
def normalize_text(text):
    text = text.lower()
    text = re.sub(r'[^\w\s"]', '', text)  # Удаляем знаки препинания, кроме кавычек
    text = re.sub(r'\s+', ' ', text).strip()  # Удаляем лишние пробелы
    return text

# Инициализация базы данных
def init_db():
    try:
        # Пробуем разные кодировки
        encodings = ['utf-8', 'windows-1251', 'latin1']
        content = None
        for encoding in encodings:
            try:
                with open('./fs_em.txt', 'r', encoding=encoding) as f:
                    content = f.read()
                logger.info(f"Успешно прочитан файл с кодировкой: {encoding}")
                break
            except UnicodeDecodeError:
                logger.warning(f"Не удалось прочитать с кодировкой {encoding}, пробуем следующую")
                continue
        
        if content is None:
            raise Exception("Не удалось прочитать fs_em.txt: неподдерживаемая кодировка")

        # Разделяем на записи
        entries = content.split('Экстремистский материал №')
        materials = []
        for entry in entries[1:]:  # Пропускаем пустую первую часть
            # Извлекаем ID и текст до конца записи
            match = re.match(r'(\d+): (.+)', entry, re.DOTALL)
            if match:
                material_id = int(match.group(1))
                material_text = match.group(2).strip()
                # Ищем дату в скобках
                date_match = re.search(r'\(решение .+? от ([0-9.]+)\)?', entry)
                date = date_match.group(1) if date_match else "Не указана"
                materials.append((material_id, date, material_text))
            else:
                logger.warning(f"Не удалось разобрать запись: {entry[:50]}...")
        
        # Подключаемся к SQLite
        conn = sqlite3.connect('./restricted.db')
        cursor = conn.cursor()
        
        # Создаём таблицу FTS5
        cursor.execute('DROP TABLE IF EXISTS restricted_materials_fts')
        cursor.execute('''
            CREATE VIRTUAL TABLE restricted_materials_fts USING fts5(id, date, material)
        ''')
        
        # Создаём обычную таблицу для хранения полных данных
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS restricted_materials (
                id INTEGER PRIMARY KEY,
                date TEXT,
                material TEXT
            )
        ''')
        
        # Очищаем таблицы
        cursor.execute('DELETE FROM restricted_materials')
        
        # Загружаем данные
        for material_id, date, material_text in materials:
            cursor.execute('INSERT INTO restricted_materials (id, date, material) VALUES (?, ?, ?)',
                          (material_id, date, material_text))
            cursor.execute('INSERT INTO restricted_materials_fts (id, date, material) VALUES (?, ?, ?)',
                          (material_id, date, material_text))
        
        # Дебаг: проверяем, есть ли ID 5467
        cursor.execute('SELECT id, material FROM restricted_materials WHERE id = 5467')
        result = cursor.fetchone()
        if result:
            logger.info(f"ID 5467 найден в базе: {result[1][:50]}...")
            logger.debug(f"Нормализованный текст ID 5467: {normalize_text(result[1])[:100]}...")
        else:
            logger.error("ID 5467 НЕ найден в базе")
        
        conn.commit()
        conn.close()
        logger.info(f"База данных успешно инициализирована, загружено {len(materials)} записей")
    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {str(e)}")
        raise

# SSE для отправки прогресса
@app.route('/progress/<path:query>')
def progress(query):
    def generate():
        normalized_query = normalize_text(query) if query else ""
        if not normalized_query:
            yield "data: {'progress': 100, 'found': false}\n\n"
            return
        logger.debug(f"Прогресс для запроса: {normalized_query}")
        conn = sqlite3.connect('./restricted.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id, date, material FROM restricted_materials')
        materials = cursor.fetchall()
        total = len(materials)
        for i, (material_id, date, material_text) in enumerate(materials):
            material_text_normalized = normalize_text(material_text)
            if normalized_query in material_text_normalized:
                logger.warning(f"Найден запрещённый материал ID {material_id} для запроса '{normalized_query}'")
                yield f"data: {{'progress': 100, 'found': true}}\n\n"
                conn.close()
                return
            if i % (total // 10) == 0:  # Обновляем прогресс каждые 10%
                progress = (i + 1) / total * 100
                yield f"data: {{'progress': {progress:.2f}, 'found': false}}\n\n"
        conn.close()
        yield f"data: {{'progress': 100, 'found': false}}\n\n"
    return Response(generate(), mimetype='text/event-stream')

# Главная страница
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        query = normalize_text(request.form['query'])
        logger.info(f"Получен запрос: {query}")
        
        # Поиск в базе с помощью FTS5
        conn = sqlite3.connect('./restricted.db')
        cursor = conn.cursor()
        # Используем FTS5 для поиска
        cursor.execute('SELECT id, date, material FROM restricted_materials_fts WHERE material MATCH ?', (query,))
        matches = cursor.fetchall()
        conn.close()
        
        if matches:
            material_id, date, material_text = matches[0]
            logger.warning(f"Найден запрещённый материал ID {material_id} для запроса '{query}'")
            return render_template('index.html', warning=f"Запрос запрещён! Найден запрещённый материал (ID: {material_id}, Дата: {date}). Причина: {material_text}", query=query)
        
        logger.info(f"Запрос '{query}' безопасен")
        return render_template('index.html', safe_query=query)
    
    return render_template('index.html')

if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1', port=5000, debug=True)
