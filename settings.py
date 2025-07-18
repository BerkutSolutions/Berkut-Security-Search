# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.

from flask import Flask, request
import json
import os

app = Flask(__name__)

# Путь к файлу настроек
SETTINGS_FILE = 'settings.json'

# Функция для загрузки настроек
def load_settings():
    default_settings = {'db_source': 'txt', 'db_path': './fs_em.txt'}
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default_settings
    except Exception as e:
        print(f"Ошибка загрузки настроек: {e}")
        return default_settings

# Функция для сохранения настроек
def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")

@app.route('/clear-history', methods=['GET'])
def clear_history():
    return "OK", 200

@app.route('/update-settings', methods=['POST'])
def update_settings():
    settings = load_settings()
    settings['db_source'] = request.form.get('db_source', 'txt')
    if settings['db_source'] == 'local_csv':
        settings['db_path'] = request.form.get('db_path', './fs_em.csv')
    elif settings['db_source'] == 'remote_csv':
        settings['db_path'] = 'https://www.minjust.gov.ru/uploaded/files/exportfsm.csv'
    else:
        settings['db_path'] = './fs_em.txt'
    save_settings(settings)
    return "OK", 200

@app.route('/update-database', methods=['GET'])
def update_database():
    from database import update_db
    result = update_db()
    return json.dumps(result), 200

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)