# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pandas as pd
import sqlite3
import re
import hashlib
import requests
import os
import json
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Путь к файлу для хранения хэш-суммы
HASH_FILE = 'db_hash.json'

# Функция для вычисления хэш-суммы файла
def calculate_file_hash(file_path):
    sha256 = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception as e:
        logger.error(f"Ошибка вычисления хэш-суммы для {file_path}: {e}")
        return None

# Функция для вычисления хэш-суммы содержимого удалённого файла
def calculate_remote_file_hash(url):
    sha256 = hashlib.sha256()
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        sha256.update(response.content)
        return sha256.hexdigest()
    except Exception as e:
        logger.error(f"Ошибка вычисления хэш-суммы для {url}: {e}")
        return None

# Функция для загрузки хэш-суммы
def load_hash():
    try:
        if os.path.exists(HASH_FILE):
            with open(HASH_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Ошибка загрузки хэш-суммы: {e}")
        return {}

# Функция для сохранения хэш-суммы
def save_hash(hash_dict):
    try:
        with open(HASH_FILE, 'w', encoding='utf-8') as f:
            json.dump(hash_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения хэш-суммы: {e}")

# Функция для получения настроек
def load_settings():
    try:
        with open('settings.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'db_source': 'txt', 'db_path': './fs_em.txt'}

# Основная функция инициализации базы
def init_db():
    settings = load_settings()
    db_source = settings.get('db_source', 'txt')
    db_path = settings.get('db_path', './fs_em.txt')
    
    conn = sqlite3.connect('./restricted.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS restricted_materials (
            id INTEGER PRIMARY KEY,
            date TEXT,
            material TEXT
        )
    ''')
    
    cursor.execute('DROP TABLE IF EXISTS restricted_materials_fts')
    cursor.execute('''
        CREATE VIRTUAL TABLE restricted_materials_fts USING fts5(id, date, material)
    ''')
    
    cursor.execute('DELETE FROM restricted_materials')
    
    materials = []
    if db_source == 'txt':
        try:
            encodings = ['utf-8', 'windows-1251', 'latin1']
            content = None
            for encoding in encodings:
                try:
                    with open(db_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    logger.info(f"Успешно прочитан файл {db_path} с кодировкой: {encoding}")
                    break
                except UnicodeDecodeError:
                    logger.warning(f"Не удалось прочитать {db_path} с кодировкой {encoding}")
                    continue
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
        except Exception as e:
            logger.error(f"Ошибка обработки txt файла: {e}")
            raise
    elif db_source in ['local_csv', 'remote_csv']:
        try:
            if db_source == 'local_csv':
                df = pd.read_csv(db_path, encoding='utf-8')
            else:
                response = requests.get(db_path, timeout=5)
                response.raise_for_status()
                from io import StringIO
                df = pd.read_csv(StringIO(response.text), encoding='utf-8')
            for _, row in df.iterrows():
                materials.append((row['№'], row['Дата'], row['Материал']))
        except Exception as e:
            logger.error(f"Ошибка обработки csv файла: {e}")
            raise
    
    for material_id, date, material_text in materials:
        cursor.execute('INSERT INTO restricted_materials (id, date, material) VALUES (?, ?, ?)',
                      (material_id, date, material_text))
        cursor.execute('INSERT INTO restricted_materials_fts (id, date, material) VALUES (?, ?, ?)',
                      (material_id, date, material_text))
    
    cursor.execute('SELECT id, material FROM restricted_materials WHERE id = 5467')
    result = cursor.fetchone()
    if result:
        logger.info(f"ID 5467 найден в базе: {result[1][:50]}...")
        logger.debug(f"Нормализованный текст ID 5467: {material_text[:100]}...")
    else:
        logger.error("ID 5467 НЕ найден в базе")
    
    conn.commit()
    conn.close()
    logger.info(f"База данных успешно инициализирована, загружено {len(materials)} записей")
    return len(materials)

# Функция обновления базы
def update_db():
    settings = load_settings()
    db_source = settings.get('db_source', 'txt')
    db_path = settings.get('db_path', './fs_em.txt')
    hash_dict = load_hash()
    old_count = hash_dict.get('record_count', 0)
    
    # Проверка хэш-суммы для локальных файлов
    current_hash = None
    if db_source in ['txt', 'local_csv']:
        current_hash = calculate_file_hash(db_path)
    elif db_source == 'remote_csv':
        current_hash = calculate_remote_file_hash(db_path)
    
    if current_hash and hash_dict.get('hash') == current_hash:
        logger.info("Хэш-сумма не изменилась, обновление не требуется")
        return {'updated': False, 'new_records': 0}
    
    # Обновляем базу
    new_count = init_db()
    new_records = new_count - old_count if old_count else new_count
    
    # Сохраняем новую хэш-сумму и количество записей
    if current_hash:
        hash_dict['hash'] = current_hash
        hash_dict['record_count'] = new_count
        save_hash(hash_dict)
    
    logger.info(f"База обновлена, добавлено {new_records} новых записей")
    return {'updated': True, 'new_records': new_records}

if __name__ == '__main__':
    init_db()