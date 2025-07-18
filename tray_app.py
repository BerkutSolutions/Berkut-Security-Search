# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.

import re
import sqlite3
import logging
import json
import webbrowser
import pystray
import requests
from PIL import Image
from flask import Flask, request, render_template
from threading import Thread

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Функция для нормализации текста
def normalize_text(text):
    text = text.lower()
    text = re.sub(r'[^\w\s"]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# Инициализация базы данных
def init_db():
    try:
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
            raise Exception("Не удалось прочитать fs_em.txt: неподдерживающая кодировка")

        entries = content.split('Экстремистский материал №')
        materials = []
        for entry in entries[1:]:
            match = re.match(r'(\d+): (.+)', entry, re.DOTALL)
            if match:
                material_id = int(match.group(1))
                material_text = match.group(2).strip()
                date_match = re.search(r'\(решение .+? от ([0-9.]+)\)?', entry)
                date = date_match.group(1) if date_match else "Не указана"
                materials.append((material_id, date, material_text))
            else:
                logger.warning(f"Не удалось разобрать запись: {entry[:50]}...")
        
        conn = sqlite3.connect('./restricted.db')
        cursor = conn.cursor()
        
        cursor.execute('DROP TABLE IF EXISTS restricted_materials_fts')
        cursor.execute('''
            CREATE VIRTUAL TABLE restricted_materials_fts USING fts5(id, date, material)
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS restricted_materials (
                id INTEGER PRIMARY KEY,
                date TEXT,
                material TEXT
            )
        ''')
        
        cursor.execute('DELETE FROM restricted_materials')
        
        for material_id, date, material_text in materials:
            cursor.execute('INSERT INTO restricted_materials (id, date, material) VALUES (?, ?, ?)',
                          (material_id, date, material_text))
            cursor.execute('INSERT INTO restricted_materials_fts (id, date, material) VALUES (?, ?, ?)',
                          (material_id, date, material_text))
        
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

# Получение публичного IP и страны
def get_public_ip_info():
    try:
        response = requests.get('http://ip-api.com/json/', timeout=5)
        data = response.json()
        if data['status'] == 'success':
            return {'ip': data['query'], 'country': data['country']}
        return {'ip': 'Не удалось определить', 'country': 'Не удалось определить'}
    except Exception as e:
        logger.error(f"Ошибка получения IP: {str(e)}")
        return {'ip': 'Ошибка', 'country': 'Ошибка'}

# Управление плитками
def load_tiles():
    try:
        with open('tiles.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.error(f"Ошибка загрузки tiles.json: {str(e)}")
        return []

def save_tiles(tiles):
    try:
        with open('tiles.json', 'w', encoding='utf-8') as f:
            json.dump(tiles, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения tiles.json: {str(e)}")

# Главная страница
@app.route('/', methods=['GET', 'POST'])
def index():
    ip_info = get_public_ip_info()
    tiles = load_tiles()
    
    if request.method == 'POST':
        if 'add_tile' in request.form:
            site_name = request.form['site_name']
            site_url = request.form['site_url']
            if site_name and site_url:
                tiles.append({'name': site_name, 'url': site_url})
                save_tiles(tiles)
                logger.info(f"Добавлена новая плитка: {site_name} ({site_url})")
            return render_template('index.html', ip_info=ip_info, tiles=tiles)
        
        query = normalize_text(request.form['query'])
        logger.info(f"Получен запрос: {query}")
        
        conn = sqlite3.connect('./restricted.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id, date, material FROM restricted_materials_fts WHERE material MATCH ?', (query,))
        matches = cursor.fetchall()
        conn.close()
        
        if matches:
            logger.warning(f"Найдено {len(matches)} запрещённых материалов для запроса '{query}'")
            return render_template('index.html', warning=matches, query=query, ip_info=ip_info, tiles=tiles)
        
        logger.info(f"Запрос '{query}' безопасен")
        return render_template('index.html', safe_query=query, ip_info=ip_info, tiles=tiles)
    
    return render_template('index.html', ip_info=ip_info, tiles=tiles)

# Создание системного трея
def create_tray():
    icon = Image.open("icon.png")
    menu = pystray.Menu(
        pystray.MenuItem("Открыть", lambda: webbrowser.open("http://127.0.0.1:5000")),
        pystray.MenuItem("Выход", lambda: stop_app())
    )
    tray = pystray.Icon("Berkut Search", icon, "Berkut Search", menu)
    return tray

def stop_app():
    tray.stop()
    import os
    os._exit(0)

# Запуск Flask в отдельном потоке
def run_flask():
    init_db()
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    tray = create_tray()
    Thread(target=run_flask, daemon=True).start()
    tray.run()