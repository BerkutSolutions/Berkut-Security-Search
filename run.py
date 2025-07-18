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
import folium
import hashlib
import csv
import io
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates')

def normalize_text(text):
    text = text.lower()
    text = re.sub(r'[^\w\s"]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def calculate_hash(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def load_settings():
    try:
        with open('settings.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'db_source': 'txt', 'db_path': './fs_em.txt', 'hash': ''}

def save_settings(settings):
    try:
        with open('settings.json', 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {str(e)}")

def check_db_integrity():
    try:
        conn = sqlite3.connect('./restricted.db')
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM sqlite_master WHERE type="table" AND name="restricted_materials"')
        table_exists = cursor.fetchone()
        if not table_exists:
            conn.close()
            return {'is_valid': False, 'error': 'Таблица restricted_materials отсутствует'}
        cursor.execute('SELECT COUNT(*) FROM restricted_materials')
        count = cursor.fetchone()[0]
        conn.close()
        if count == 0:
            return {'is_valid': False, 'error': 'База данных пуста'}
        return {'is_valid': True, 'count': count}
    except Exception as e:
        logger.error(f"Ошибка проверки целостности базы: {str(e)}")
        return {'is_valid': False, 'error': str(e)}

def init_db():
    settings = load_settings()
    db_source = settings.get('db_source', 'txt')
    db_path = settings.get('db_path', './fs_em.txt')
    materials = []
    
    try:
        if db_source == 'txt':
            encodings = ['utf-8', 'windows-1251', 'latin1']
            content = None
            for encoding in encodings:
                try:
                    with open(db_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    logger.info(f"Успешно прочитан файл {db_path} с кодировкой: {encoding}")
                    break
                except UnicodeDecodeError:
                    logger.warning(f"Не удалось прочитать с кодировкой {encoding}, пробуем следующую")
                    continue
                except Exception as e:
                    logger.error(f"Ошибка чтения TXT файла: {str(e)}")
                    raise
            if content is None:
                raise Exception(f"Не удалось прочитать {db_path}: неподдерживаемая кодировка")
            entries = content.split('Экстремистский материал №')
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
        elif db_source in ['local_csv', 'remote_csv']:
            try:
                if db_source == 'local_csv':
                    with open(db_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                else:  # remote_csv
                    logger.warning("SSL verification disabled for remote CSV fetch due to certificate issues")
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                    response = requests.get(db_path, timeout=5, verify=False, headers=headers)
                    response.raise_for_status()
                    content = response.text
                csv_reader = csv.reader(io.StringIO(content), delimiter=';')
                header = next(csv_reader, None)  # Считываем заголовок
                if header and len(header) >= 3 and header[0].strip() == '#' and header[1].strip() == 'Материал' and header[2].strip() == 'Дата включения (указывается с 01.01.2017)':
                    for row in csv_reader:
                        if len(row) >= 3 and row[0].strip().isdigit():
                            material_id = int(row[0].strip())
                            material_text = row[1].strip() if row[1].strip() else "Не указано"
                            date = row[2].strip() if row[2].strip() else "Не указана"
                            materials.append((material_id, date, material_text))
                        else:
                            logger.warning(f"Некорректная строка CSV: {row}")
                else:
                    logger.error(f"Некорректный заголовок CSV: {header}")
                    raise ValueError("Некорректный формат CSV")
            except requests.exceptions.RequestException as e:
                logger.error(f"Ошибка загрузки удаленного CSV: {str(e)}")
                raise
            except Exception as e:
                logger.error(f"Ошибка чтения CSV: {str(e)}")
                raise
        conn = sqlite3.connect('./restricted.db')
        cursor = conn.cursor()
        cursor.execute('DROP TABLE IF EXISTS restricted_materials_fts')
        cursor.execute('CREATE VIRTUAL TABLE restricted_materials_fts USING fts5(id, date, material)')
        cursor.execute('CREATE TABLE IF NOT EXISTS restricted_materials (id INTEGER PRIMARY KEY, date TEXT, material TEXT)')
        cursor.execute('DELETE FROM restricted_materials')
        for material_id, date, material_text in materials:
            cursor.execute('INSERT INTO restricted_materials (id, date, material) VALUES (?, ?, ?)', (material_id, date, material_text))
            cursor.execute('INSERT INTO restricted_materials_fts (id, date, material) VALUES (?, ?, ?)', (material_id, date, material_text))
        cursor.execute('SELECT id, material FROM restricted_materials WHERE id = 5467')
        result = cursor.fetchone()
        if result:
            logger.info(f"ID 5467 найден в базе: {result[1][:50]}...")
            logger.debug(f"Нормализованный текст ID 5467: {normalize_text(result[1])[:100]}...")
        else:
            logger.warning("ID 5467 НЕ найден в базе")
        conn.commit()
        conn.close()
        logger.info(f"База данных успешно инициализирована, загружено {len(materials)} записей")
        return {'is_valid': True, 'count': len(materials)}
    except Exception as e:
        logger.error(f"Ошибка инициализации базы: {str(e)}")
        return {'is_valid': False, 'error': str(e)}

def update_db():
    settings = load_settings()
    db_source = settings.get('db_source', 'txt')
    db_path = settings.get('db_path', './fs_em.txt')
    old_hash = settings.get('hash', '')
    content = None
    try:
        if db_source == 'txt':
            with open(db_path, 'r', encoding='utf-8') as f:
                content = f.read()
        elif db_source == 'local_csv':
            with open(db_path, 'r', encoding='utf-8') as f:
                content = f.read()
        elif db_source == 'remote_csv':
            logger.warning("SSL verification disabled for remote CSV fetch due to certificate issues")
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get(db_path, timeout=5, verify=False, headers=headers)
            response.raise_for_status()
            content = response.text
        new_hash = calculate_hash(content)
        if new_hash == old_hash:
            integrity = check_db_integrity()
            if not integrity['is_valid']:
                return {'updated': False, 'new_records': 0, 'error': integrity['error']}
            return {'updated': False, 'new_records': 0}
        settings['hash'] = new_hash
        save_settings(settings)
        conn = sqlite3.connect('./restricted.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM restricted_materials')
        old_count = cursor.fetchone()[0]
        conn.close()
        result = init_db()
        if not result['is_valid']:
            return {'updated': False, 'new_records': 0, 'error': result['error']}
        conn = sqlite3.connect('./restricted.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM restricted_materials')
        new_count = cursor.fetchone()[0]
        conn.close()
        return {'updated': True, 'new_records': new_count - old_count}
    except Exception as e:
        logger.error(f"Ошибка при обновлении базы: {str(e)}")
        return {'updated': False, 'new_records': 0, 'error': str(e)}

def get_public_ip_info():
    try:
        response = requests.get('http://ip-api.com/json/', timeout=5)
        data = response.json()
        if data['status'] == 'success':
            return {'ip': data['query'], 'country': data['country'], 'lat': data.get('lat', 0.0), 'lon': data.get('lon', 0.0)}
        return {'ip': 'Не удалось определить', 'country': 'Не удалось определить', 'lat': 0.0, 'lon': 0.0}
    except Exception as e:
        logger.error(f"Ошибка получения IP: {str(e)}")
        return {'ip': 'Ошибка', 'country': 'Ошибка', 'lat': 0.0, 'lon': 0.0}

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

def generate_map(lat, lon):
    try:
        m = folium.Map(location=[lat, lon], zoom_start=10, width='100%', height='400px')
        folium.Marker([lat, lon], popup='Примерное местоположение').add_to(m)
        return m._repr_html_()
    except Exception as e:
        logger.error(f"Ошибка генерации карты: {str(e)}")
        return "<p>Ошибка загрузки карты</p>"

@app.route('/', methods=['GET', 'POST'])
def index():
    ip_info = get_public_ip_info()
    tiles = load_tiles()
    settings = load_settings()
    db_status = check_db_integrity()
    map_html = generate_map(ip_info['lat'], ip_info['lon']) if ip_info['lat'] and ip_info['lon'] else "<p>Нет данных для карты</p>"
    update_info = None
    show_init_modal = db_status['is_valid'] is False
    if request.method == 'POST':
        if 'add_tile' in request.form:
            site_name = request.form['site_name']
            site_url = request.form['site_url']
            edit_index = request.form.get('edit_index')
            if site_name and site_url:
                if not edit_index and any(t['name'] == site_name for t in tiles):
                    logger.warning(f"Плитка с именем '{site_name}' уже существует")
                    return render_template('index.html', ip_info=ip_info, tiles=tiles, map_html=map_html, error="Плитка с таким именем уже существует", settings=settings, show_init_modal=show_init_modal)
                if edit_index:
                    tiles = [t for t in tiles if not (t['name'] == edit_index and t['url'] == request.form.get('edit_url', t['url']))]
                    logger.info(f"Отредактирована плитка: {site_name} ({site_url})")
                else:
                    logger.info(f"Добавлена новая плитка: {site_name} ({site_url})")
                tiles.append({'name': site_name, 'url': site_url})
                save_tiles(tiles)
        elif 'delete_tile' in request.form:
            delete_name = request.form['delete_tile']
            delete_url = request.form.get('delete_url')
            tiles_before = len(tiles)
            tiles = [t for t in tiles if not (t['name'] == delete_name and t['url'] == delete_url)]
            if len(tiles) < tiles_before:
                logger.info(f"Удалена плитка: {delete_name} ({delete_url})")
                save_tiles(tiles)
            else:
                logger.warning(f"Плитка для удаления не найдена: {delete_name} ({delete_url})")
        query = normalize_text(request.form.get('query', ''))
        if query:
            logger.info(f"Получен запрос: {query}")
            conn = sqlite3.connect('./restricted.db')
            cursor = conn.cursor()
            cursor.execute('SELECT id, date, material FROM restricted_materials_fts WHERE material MATCH ?', (query,))
            matches = cursor.fetchall()
            conn.close()
            if matches:
                logger.warning(f"Найдено {len(matches)} запрещённых материалов для запроса '{query}'")
                return render_template('index.html', warning=matches, query=query, ip_info=ip_info, tiles=tiles, map_html=map_html, update_info=update_info, settings=settings, show_init_modal=show_init_modal)
            logger.info(f"Запрос '{query}' безопасен")
            return render_template('index.html', safe_query=query, ip_info=ip_info, tiles=tiles, map_html=map_html, update_info=update_info, settings=settings, show_init_modal=show_init_modal)
        return render_template('index.html', ip_info=ip_info, tiles=tiles, map_html=map_html, update_info=update_info, settings=settings, show_init_modal=show_init_modal)
    return render_template('index.html', ip_info=ip_info, tiles=tiles, map_html=map_html, update_info=update_info, settings=settings, show_init_modal=show_init_modal)

@app.route('/update-db', methods=['POST'])
def update_db_route():
    update_info = update_db()
    ip_info = get_public_ip_info()
    tiles = load_tiles()
    settings = load_settings()
    db_status = check_db_integrity()
    map_html = generate_map(ip_info['lat'], ip_info['lon']) if ip_info['lat'] and ip_info['lon'] else "<p>Нет данных для карты</p>"
    show_init_modal = db_status['is_valid'] is False
    if update_info.get('error'):
        return render_template('index.html', ip_info=ip_info, tiles=tiles, map_html=map_html, error=f"Ошибка обновления базы: {update_info['error']}", settings=settings, show_init_modal=show_init_modal)
    return render_template('index.html', ip_info=ip_info, tiles=tiles, map_html=map_html, update_info=update_info, settings=settings, show_init_modal=show_init_modal)

@app.route('/init-database', methods=['POST'])
def init_database():
    settings = load_settings()
    settings['db_source'] = request.form.get('db_source', 'txt')
    if settings['db_source'] == 'local_csv':
        settings['db_path'] = request.form.get('db_path', './fs_em.csv')
    else:
        settings['db_path'] = './fs_em.txt' if settings['db_source'] == 'txt' else 'https://www.minjust.gov.ru/uploaded/files/exportfsm.csv'
    settings['hash'] = ''
    save_settings(settings)
    result = init_db()
    ip_info = get_public_ip_info()
    tiles = load_tiles()
    db_status = check_db_integrity()
    map_html = generate_map(ip_info['lat'], ip_info['lon']) if ip_info['lat'] and ip_info['lon'] else "<p>Нет данных для карты</p>"
    show_init_modal = db_status['is_valid'] is False
    if not result['is_valid']:
        return render_template('index.html', ip_info=ip_info, tiles=tiles, map_html=map_html, error=f"Ошибка инициализации базы: {result['error']}", settings=settings, show_init_modal=show_init_modal)
    return render_template('index.html', ip_info=ip_info, tiles=tiles, map_html=map_html, settings=settings, show_init_modal=show_init_modal)

@app.route('/update-settings', methods=['POST'])
def update_settings():
    settings = load_settings()
    settings['db_source'] = request.form.get('db_source', 'txt')
    if settings['db_source'] == 'local_csv':
        settings['db_path'] = request.form.get('db_path', './fs_em.csv')
    else:
        settings['db_path'] = './fs_em.txt' if settings['db_source'] == 'txt' else 'https://www.minjust.gov.ru/uploaded/files/exportfsm.csv'
    settings['hash'] = ''
    save_settings(settings)
    result = init_db()
    update_info = {'updated': True, 'new_records': result['count']} if result['is_valid'] else {'updated': False, 'new_records': 0}
    ip_info = get_public_ip_info()
    tiles = load_tiles()
    db_status = check_db_integrity()
    map_html = generate_map(ip_info['lat'], ip_info['lon']) if ip_info['lat'] and ip_info['lon'] else "<p>Нет данных для карты</p>"
    show_init_modal = db_status['is_valid'] is False
    if not result['is_valid']:
        return render_template('index.html', ip_info=ip_info, tiles=tiles, map_html=map_html, error=f"Ошибка инициализации базы: {result['error']}", settings=settings, show_init_modal=show_init_modal, update_info=update_info)
    return render_template('index.html', ip_info=ip_info, tiles=tiles, map_html=map_html, update_info=update_info, settings=settings, show_init_modal=show_init_modal)

@app.route('/export-tiles', methods=['GET'])
def export_tiles():
    tiles = load_tiles()
    return app.response_class(
        response=json.dumps(tiles, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=tiles.json'}
    )

@app.route('/import-tiles', methods=['POST'])
def import_tiles():
    tiles = request.get_json()
    save_tiles(tiles)
    return '', 200

@app.route('/clear-history', methods=['POST'])
def clear_history():
    return '', 200

def create_tray():
    try:
        icon = Image.open("icon.png")
    except FileNotFoundError:
        logger.error("Файл icon.png не найден. Создаётся пустая иконка.")
        icon = Image.new('RGB', (64, 64), color='black')
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

def run_flask():
    init_db()
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    tray = create_tray()
    Thread(target=run_flask, daemon=True).start()
    tray.run()