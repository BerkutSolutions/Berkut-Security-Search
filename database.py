# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pandas as pd
import sqlite3

def init_db():
    # Читаем CSV файл
    df = pd.read_csv(r'C:\Users\berkut\Desktop\search\fs_em.csv', encoding='utf-8')
    
    # Подключаемся к SQLite
    conn = sqlite3.connect(r'C:\Users\berkut\Desktop\search\restricted.db')
    cursor = conn.cursor()
    
    # Создаём таблицу
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS restricted_materials (
            id INTEGER PRIMARY KEY,
            date TEXT,
            material TEXT
        )
    ''')
    
    # Очищаем таблицу перед загрузкой
    cursor.execute('DELETE FROM restricted_materials')
    
    # Загружаем данные
    for _, row in df.iterrows():
        cursor.execute('INSERT INTO restricted_materials (id, date, material) VALUES (?, ?, ?)',
                      (row['№'], row['Дата'], row['Материал']))
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()