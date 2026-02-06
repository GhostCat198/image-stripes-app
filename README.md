# Image Stripes App (Variant 17)

Простое веб-приложение на Flask (уровень 1 курса):

- меняет изображение, обменивая местами соседние полосы (вертикально/горизонтально)
- пользователь задаёт ширину полосы (в пикселях)
- строит RGB-гистограмму исходного изображения

## Локальный запуск

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
python app.py
```

Открыть в браузере: http://localhost:5000

## Деплой на Railway

1. Загрузите проект в GitHub
2. На Railway: New Project → Deploy from GitHub Repo
3. Railway установит зависимости из `requirements.txt` и запустит команду из `Procfile`
