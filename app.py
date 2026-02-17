"""
app.py — ЛР: обработка изображений (перестановка полос) + гистограмма RGB + капча
+ подпись времени обработки на выходном изображении
+ поддержка нескольких пользователей (у каждого — свои уникальные файлы)
+ возможность скачать обработанное изображение

Требования:
pip install flask pillow matplotlib
"""

import os
import time
import uuid
import random
import string
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    session,
    send_from_directory,
    url_for,
    redirect,
    abort,
)
from werkzeug.utils import secure_filename

from PIL import Image, ImageDraw, ImageFont

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ----------------------------
# Настройки приложения
# ----------------------------
app = Flask(__name__)
app.secret_key = "student_secret_key_123"  # для session (в реальном проекте хранить в env)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
OUTPUT_DIR = BASE_DIR / "static" / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Ограничим типы файлов (чтобы не принимали что угодно)
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

# Максимальный размер загрузки (например 10 МБ)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# ----------------------------
# Утилиты
# ----------------------------
def is_allowed_filename(filename: str) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXT


def make_request_id() -> str:
    """Уникальный id для файлов (чтобы несколько пользователей не перетирали друг другу результаты)."""
    return uuid.uuid4().hex


def new_captcha() -> str:
    """Простая капча: 5 символов (буквы+цифры). Храним в session."""
    chars = string.ascii_uppercase + string.digits
    code = "".join(random.choice(chars) for _ in range(5))
    session["captcha"] = code
    return code


# ----------------------------
# Обработка изображений
# ----------------------------
def swap_stripes(img: Image.Image, stripe: int, direction: str) -> Image.Image:
    """Меняет местами соседние полосы фиксированной ширины (вертикально/горизонтально)."""
    w, h = img.size
    out = Image.new(img.mode, (w, h))

    if stripe <= 0:
        return img.copy()

    if direction == "vertical":
        x = 0
        while x < w:
            a_start = x
            a_end = min(x + stripe, w)
            b_start = a_end
            b_end = min(a_end + stripe, w)

            # если второй полосы уже нет — копируем остаток
            if b_start >= w:
                out.paste(img.crop((a_start, 0, a_end, h)), (a_start, 0))
                break

            part_a = img.crop((a_start, 0, a_end, h))
            part_b = img.crop((b_start, 0, b_end, h))

            out.paste(part_b, (a_start, 0))
            out.paste(part_a, (b_start, 0))

            x = b_end
    else:
        y = 0
        while y < h:
            a_start = y
            a_end = min(y + stripe, h)
            b_start = a_end
            b_end = min(a_end + stripe, h)

            if b_start >= h:
                out.paste(img.crop((0, a_start, w, a_end)), (0, a_start))
                break

            part_a = img.crop((0, a_start, w, a_end))
            part_b = img.crop((0, b_start, w, b_end))

            out.paste(part_b, (0, a_start))
            out.paste(part_a, (0, b_start))

            y = b_end

    return out


def make_rgb_histogram(img: Image.Image, save_path: Path) -> None:
    """Строит гистограмму распределения значений R/G/B и сохраняет в PNG."""
    rgb = img.convert("RGB")
    pixels = list(rgb.getdata())

    r = [p[0] for p in pixels]
    g = [p[1] for p in pixels]
    b = [p[2] for p in pixels]

    plt.figure()
    plt.hist(r, bins=256, alpha=0.6, label="R")
    plt.hist(g, bins=256, alpha=0.6, label="G")
    plt.hist(b, bins=256, alpha=0.6, label="B")
    plt.title("Распределение цветов (RGB) для исходного изображения")
    plt.xlabel("Значение (0..255)")
    plt.ylabel("Количество пикселей")
    plt.legend()
    plt.tight_layout()
    plt.savefig(str(save_path))
    plt.close()


def draw_processing_time(img: Image.Image, elapsed_ms: float, stripe: int, direction: str) -> Image.Image:
    """
    Пишем на картинке время обработки и параметры на РУССКОМ.
    """
    base = img.convert("RGBA")
    draw = ImageDraw.Draw(base)

    # Перевод направления на русский
    direction_ru = "вертикально" if direction == "vertical" else "горизонтально"

    text = f"Время обработки: {elapsed_ms:.1f} мс | Ширина полосы: {stripe} px | Направление: {direction_ru}"

    # Шрифт с поддержкой кириллицы (Railway/Linux)
    # 1) пробуем DejaVuSans (обычно есть)
    # 2) если нет — пробуем arial
    # 3) если нет — стандартный (может быть без кириллицы, но редко)
    try:
        font = ImageFont.truetype("static/fonts/DejaVuSans.ttf", 22)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", 22)
        except OSError:
            font = ImageFont.load_default()

    # Размер текста (совместимость Pillow)
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except AttributeError:
        text_w, text_h = draw.textsize(text, font=font)

    padding = 10
    x = padding
    y = padding

    # Подложка под текст
    rect = (x - padding, y - padding, x + text_w + padding, y + text_h + padding)
    draw.rectangle(rect, fill=(0, 0, 0, 140))

    # Текст
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    return base.convert(img.mode)



# ----------------------------
# Роуты
# ----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    # создаём капчу при первом заходе
    if "captcha" not in session:
        new_captcha()

    if request.method == "GET":
        # Покажем страницу и (если есть) последние результаты пользователя
        return render_template(
            "index.html",
            captcha=session["captcha"],
            result_img=session.get("last_result_img"),
            hist_img=session.get("last_hist_img"),
            download_url=session.get("last_download_url"),
            stripe=session.get("last_stripe"),
            direction=session.get("last_direction"),
            error=None,
        )

    # ----------------------------
    # POST: проверка капчи
    # ----------------------------
    user_captcha = request.form.get("captcha_text", "").strip().upper()
    real_captcha = session.get("captcha", "")

    if user_captcha != real_captcha:
        new_captcha()
        return render_template(
            "index.html",
            captcha=session["captcha"],
            result_img=None,
            hist_img=None,
            download_url=None,
            error="Капча введена неверно. Попробуйте ещё раз.",
        )

    # ----------------------------
    # POST: проверка файла
    # ----------------------------
    file = request.files.get("image")
    if not file or not file.filename:
        new_captcha()
        return render_template(
            "index.html",
            captcha=session["captcha"],
            result_img=None,
            hist_img=None,
            download_url=None,
            error="Файл не выбран.",
        )

    filename = secure_filename(file.filename)
    if not filename or not is_allowed_filename(filename):
        new_captcha()
        return render_template(
            "index.html",
            captcha=session["captcha"],
            result_img=None,
            hist_img=None,
            download_url=None,
            error="Недопустимый тип файла. Разрешены: PNG/JPG/JPEG/BMP/GIF/WEBP.",
        )

    # параметры от пользователя
    direction = request.form.get("direction", "vertical")
    if direction not in {"vertical", "horizontal"}:
        direction = "vertical"

    stripe_str = request.form.get("stripe", "20")
    try:
        stripe = int(stripe_str)
    except ValueError:
        stripe = 20
    stripe = max(1, min(stripe, 5000))  # простая защита от странных значений

    # ----------------------------
    # Уникальные имена файлов (для многопользовательского режима)
    # ----------------------------
    req_id = make_request_id()

    input_path = UPLOAD_DIR / f"input_{req_id}{Path(filename).suffix.lower()}"
    output_img_path = OUTPUT_DIR / f"output_{req_id}.png"
    output_hist_path = OUTPUT_DIR / f"hist_{req_id}.png"

    # сохраняем входной файл
    file.save(str(input_path))

    # ----------------------------
    # Обработка
    # ----------------------------
    # Открываем изображение
    with Image.open(str(input_path)) as img:
        # строим гистограмму исходника
        make_rgb_histogram(img, output_hist_path)

        # замер времени перестановки полос
        t0 = time.perf_counter()
        out_img = swap_stripes(img, stripe, direction)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # рисуем время на выходном изображении
        out_img = draw_processing_time(out_img, elapsed_ms, stripe, direction)

        # сохраняем результат
        out_img.save(str(output_img_path))

    # ----------------------------
    # Сохраняем пути для конкретного пользователя в session
    # (чтобы он видел свои результаты на странице)
    # ----------------------------
    session["last_result_img"] = f"outputs/{output_img_path.name}"
    session["last_hist_img"] = f"outputs/{output_hist_path.name}"
    session["last_download_url"] = url_for("download_result", file_name=output_img_path.name)

    session["last_stripe"] = stripe
    session["last_direction"] = direction

    # обновляем капчу на следующую попытку
    new_captcha()

    return redirect(url_for("index"))


@app.route("/download/<path:file_name>")
def download_result(file_name: str):
    """
    Скачивание обработанного изображения.
    Мы ограничиваем скачивание только папкой OUTPUT_DIR.
    """
    # небольшая защита: скачиваем только output_*.png
    if not file_name.startswith("output_") or not file_name.lower().endswith(".png"):
        abort(404)

    file_path = OUTPUT_DIR / file_name
    if not file_path.exists():
        abort(404)

    # as_attachment=True => браузер скачает файл
    return send_from_directory(str(OUTPUT_DIR), file_name, as_attachment=True)


@app.route("/static/<path:filename>")
def static_files(filename):
    """Если нужно отдельное обслуживание static (обычно Flask и так умеет /static)."""
    return send_from_directory(str(BASE_DIR / "static"), filename)


if __name__ == "__main__":
    # debug=True удобно для разработки, для деплоя обычно выключают
    app.run(host="0.0.0.0", port=5000, debug=True)


