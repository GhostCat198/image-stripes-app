"""
app.py — готовая версия под Railway (и локально)
✔ несколько пользователей (у каждого уникальные файлы)
✔ капча (текстовая)
✔ обмен соседних полос (верт/гор)
✔ гистограмма RGB (без огромных списков -> экономия RAM)
✔ подпись на изображении на РУССКОМ + время обработки
✔ скачивание результата
✔ устойчиво к большим фото (уменьшение img.thumbnail)
✔ обработчики ошибок (413, битая картинка и т.п.)

Установка:
pip install flask pillow matplotlib gunicorn

Railway Start Command (пример):
gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120

Структура:
- app.py
- templates/index.html
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

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ----------------------------
# Flask config
# ----------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "student_secret_key_123")

# На Railway файловая система эфемерная, но /tmp обычно доступен на запись и быстрее/надежнее
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/uploads"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/tmp/outputs"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Ограничим размер загрузки (уменьшает шанс OOM и 413)
# Если хочешь больше — увеличивай аккуратно
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))  # 5MB по умолчанию

# Разрешённые расширения
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}

# Ограничение по размеру изображения (важно для Railway, чтобы не падало по памяти)
# img.thumbnail() приведёт к этому максимуму, сохраняя пропорции
MAX_IMAGE_SIDE = int(os.environ.get("MAX_IMAGE_SIDE", "1200"))  # 1200px по умолчанию


# ----------------------------
# Helpers
# ----------------------------
def is_allowed_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXT


def make_request_id() -> str:
    return uuid.uuid4().hex


def new_captcha() -> str:
    chars = string.ascii_uppercase + string.digits
    code = "".join(random.choice(chars) for _ in range(5))
    session["captcha"] = code
    return code


# ----------------------------
# Image processing
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
    """
    Экономичная гистограмма:
    НЕ создаём list(pixels) (это и убивает память).
    Используем встроенный histogram() -> 768 чисел (256*3).
    """
    rgb = img.convert("RGB")
    hist = rgb.histogram()  # [R(256), G(256), B(256)]
    r = hist[0:256]
    g = hist[256:512]
    b = hist[512:768]

    plt.figure()
    # matplotlib тут рисует линии — памяти почти не ест
    plt.plot(r, label="R")
    plt.plot(g, label="G")
    plt.plot(b, label="B")
    plt.title("Гистограмма распределения цветов (RGB)")
    plt.xlabel("Значение (0..255)")
    plt.ylabel("Количество пикселей")
    plt.legend()
    plt.tight_layout()
    plt.savefig(str(save_path))
    plt.close()


def _load_cyrillic_font(size: int) -> ImageFont.ImageFont:
    """
    На Linux/Railway почти всегда есть DejaVuSans — поддерживает кириллицу.
    Если нет — fallback.
    """
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "DejaVuSans.ttf",
        "arial.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_processing_time(img: Image.Image, elapsed_ms: float, stripe: int, direction: str) -> Image.Image:
    base = img.convert("RGBA")
    draw = ImageDraw.Draw(base)

    # Русский текст
    direction_ru = "вертикально" if direction == "vertical" else "горизонтально"
    text = f"Время обработки: {elapsed_ms:.1f} мс | Ширина полосы: {stripe} px | Направление: {direction_ru}"

    # --- Шрифт с кириллицей ---
    try:
        font = ImageFont.truetype("static/fonts/DejaVuSans.ttf", 22)

            
    except OSError:
        # если вдруг нет — fallback
        font = ImageFont.load_default()

    # Размер текста
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except AttributeError:
        text_w, text_h = draw.textsize(text, font=font)

    padding = 10
    x, y = padding, padding

    # Подложка
    rect = (x - padding, y - padding,
            x + text_w + padding,
            y + text_h + padding)

    draw.rectangle(rect, fill=(0, 0, 0, 140))

    # Сам текст
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    return base.convert(img.mode)


def downscale_for_server(img: Image.Image) -> Image.Image:
    """
    Уменьшает изображение до MAX_IMAGE_SIDE, чтобы не убиться по RAM на Railway.
    thumbnail() меняет изображение "на месте", поэтому делаем копию, чтобы не портить объект,
    если вдруг это нужно (здесь не критично, но аккуратнее).
    """
    out = img.copy()
    out.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    return out


# ----------------------------
# Error handlers
# ----------------------------
@app.errorhandler(413)
def too_large(_e):
    # если капчи не было — создадим
    if "captcha" not in session:
        new_captcha()
    else:
        new_captcha()

    return render_template(
        "index.html",
        captcha=session["captcha"],
        result_img=None,
        hist_img=None,
        download_url=None,
        stripe=20,
        direction="vertical",
        error=f"Файл слишком большой. Максимум {app.config['MAX_CONTENT_LENGTH'] // (1024*1024)} МБ.",
    ), 413


# ----------------------------
# Routes
# ----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if "captcha" not in session:
        new_captcha()

    # Вариант 1: при открытии страницы сбрасываем прошлые результаты
    if request.method == "GET":
        session.pop("last_result_img", None)
        session.pop("last_hist_img", None)
        session.pop("last_download_url", None)
        session.pop("last_stripe", None)
        session.pop("last_direction", None)

        return render_template(
            "index.html",
            captcha=session["captcha"],
            result_img=None,
            hist_img=None,
            download_url=None,
            stripe=20,
            direction="vertical",
            error=None,
        )

    # -------------------------
    # POST: проверка капчи
    # -------------------------
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
            stripe=20,
            direction="vertical",
            error="Капча введена неверно. Попробуйте ещё раз.",
        )

    # -------------------------
    # POST: проверка файла
    # -------------------------
    file = request.files.get("image")
    if not file or not file.filename:
        new_captcha()
        return render_template(
            "index.html",
            captcha=session["captcha"],
            result_img=None,
            hist_img=None,
            download_url=None,
            stripe=20,
            direction="vertical",
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
            stripe=20,
            direction="vertical",
            error="Недопустимый тип файла. Разрешены: PNG/JPG/JPEG/BMP/GIF/WEBP.",
        )

    # параметры
    direction = request.form.get("direction", "vertical")
    if direction not in {"vertical", "horizontal"}:
        direction = "vertical"

    stripe_str = request.form.get("stripe", "20")
    try:
        stripe = int(stripe_str)
    except ValueError:
        stripe = 20
    stripe = max(1, min(stripe, 5000))

    # -------------------------
    # Уникальные имена (многопользовательский режим)
    # -------------------------
    req_id = make_request_id()
    ext = Path(filename).suffix.lower()

    input_path = UPLOAD_DIR / f"input_{req_id}{ext}"
    output_img_path = OUTPUT_DIR / f"output_{req_id}.png"
    output_hist_path = OUTPUT_DIR / f"hist_{req_id}.png"

    file.save(str(input_path))

    # -------------------------
    # Обработка
    # -------------------------
    try:
        with Image.open(str(input_path)) as img:
            # уменьшаем перед всем, чтобы не словить OOM
            img_small = downscale_for_server(img)

            # гистограмма (экономичная)
            make_rgb_histogram(img_small, output_hist_path)

            # перестановка полос + время
            t0 = time.perf_counter()
            out_img = swap_stripes(img_small, stripe, direction)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            # подпись на русском
            out_img = draw_processing_time(out_img, elapsed_ms, stripe, direction)

            out_img.save(str(output_img_path))

    except UnidentifiedImageError:
        new_captcha()
        return render_template(
            "index.html",
            captcha=session["captcha"],
            result_img=None,
            hist_img=None,
            download_url=None,
            stripe=stripe,
            direction=direction,
            error="Файл не распознан как изображение. Попробуйте PNG/JPG/WEBP.",
        )
    except Exception as e:
        # чтобы сайт не падал даже при неожиданных ошибках
        new_captcha()
        return render_template(
            "index.html",
            captcha=session["captcha"],
            result_img=None,
            hist_img=None,
            download_url=None,
            stripe=stripe,
            direction=direction,
            error=f"Ошибка обработки: {type(e).__name__}",
        )
    finally:
        # можно удалить входной файл, чтобы не копить мусор
        try:
            input_path.unlink(missing_ok=True)
        except Exception:
            pass

    # сохраняем для показа результата (для ЭТОГО пользователя)
    session["last_result_img"] = output_img_path.name
    session["last_hist_img"] = output_hist_path.name
    session["last_download_url"] = url_for("download_result", file_name=output_img_path.name)
    session["last_stripe"] = stripe
    session["last_direction"] = direction

    new_captcha()
    return redirect(url_for("show_result"))


@app.route("/result")
def show_result():
    """Страница результата (чтобы после POST не повторялась отправка формы)."""
    if "captcha" not in session:
        new_captcha()

    result_name = session.get("last_result_img")
    hist_name = session.get("last_hist_img")
    download_url = session.get("last_download_url")
    stripe = session.get("last_stripe", 20)
    direction = session.get("last_direction", "vertical")

    # если результатов нет — покажем пустую форму
    if not result_name or not hist_name:
        return redirect(url_for("index"))

    return render_template(
        "index.html",
        captcha=session["captcha"],
        result_img=url_for("get_output_file", file_name=result_name),
        hist_img=url_for("get_output_file", file_name=hist_name),
        download_url=download_url,
        stripe=stripe,
        direction=direction,
        error=None,
    )


@app.route("/files/<path:file_name>")
def get_output_file(file_name: str):
    """Отдаём изображения результата/гистограммы из OUTPUT_DIR."""
    # простая защита: только наши имена
    if not (file_name.startswith("output_") or file_name.startswith("hist_")):
        abort(404)
    # только png
    if not file_name.lower().endswith(".png"):
        abort(404)

    file_path = OUTPUT_DIR / file_name
    if not file_path.exists():
        abort(404)
    return send_from_directory(str(OUTPUT_DIR), file_name)


@app.route("/download/<path:file_name>")
def download_result(file_name: str):
    """Скачивание обработанного изображения."""
    if not file_name.startswith("output_") or not file_name.lower().endswith(".png"):
        abort(404)

    file_path = OUTPUT_DIR / file_name
    if not file_path.exists():
        abort(404)

    return send_from_directory(str(OUTPUT_DIR), file_name, as_attachment=True)


# ----------------------------
# Local run (Railway запускает через gunicorn)
# ----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)


