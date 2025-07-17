# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.

from flask import Flask, request, render_template, redirect
import sqlite3
from sentence_transformers import SentenceTransformer, util
import numpy as np

app = Flask(__name__)

# Загружаем модель для векторного поиска
model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

# Функция для получения данных из базы
def get_restricted_materials():
    conn = sqlite3.connect('./restricted.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, date, material FROM restricted_materials')
    materials = cursor.fetchall()
    conn.close()
    return materials

# Главная страница
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        query = request.form['query']
        
        # Получаем материалы из базы
        materials = get_restricted_materials()
        
        # Преобразуем запрос в вектор
        query_embedding = model.encode(query, convert_to_tensor=True)
        
        # Проверяем сходство с каждым материалом
        for material_id, date, material_text in materials:
            material_embedding = model.encode(material_text, convert_to_tensor=True)
            similarity = util.cos_sim(query_embedding, material_embedding).item()
            
            # Если сходство выше порога (например, 0.7), считаем запрос запрещённым
            if similarity > 0.7:
                return render_template('index.html', warning=f"Запрос запрещён! Найден запрещённый материал (ID: {material_id}, Дата: {date}). Причина: {material_text}")
        
        # Если запрос безопасен, перенаправляем на Google
        return redirect(f"https://www.google.com/search?q={query}")
    
    return render_template('index.html')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
