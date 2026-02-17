import os
import random
import string
import time
from flask import Flask, render_template, request, send_from_directory, session
from PIL import Image, ImageDraw, ImageFont
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

app = Flask(__name__)
app.secret_key = "student_secret_key_123"  # нужно для session (можно заменить)

UPLOAD_DIR = "static/uploads"
OUTPUT_DIR = "static/outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def new_captcha() -> str:
    # простая капча: 5 символов (буквы+цифры)
    chars = string.ascii_uppercase + string.digits
    code = "".join(random.choice(chars) for _ in range(5))
    session["captcha"] = code
    return code


def swap_stripes(img: Image.Image, stripe: int, direction: str) -> Image.Image:
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



def make_rgb_histogram(img: Image.Image, save_path: str) -> None:
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
    plt.savefig(save_path)
    plt.close()
    
def draw_processing_time(img: Image.Image, elapsed_ms: float) -> Image.Image:
    """Рисует время обработки на изображении и возвращает новое изображение."""
    out = img.convert("RGBA")
    draw = ImageDraw.Draw(out)

    text = f"Время обработки: {elapsed_ms:.1f} мс"

    # Попытка загрузить шрифт (если нет — используем стандартный)
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except OSError:
        font = ImageFont.load_default()

    # Размер текста
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    padding = 10
    x = padding
    y = padding

    # Полупрозрачная подложка под текст
    rect = (x - padding, y - padding, x + text_w + padding, y + text_h + padding)
    draw.rectangle(rect, fill=(0, 0, 0, 140))

    # Сам текст
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    return out.convert(img.mode)

@app.route("/", methods=["GET", "POST"])
def index():
    # если капчи нет — создаём
    if "captcha" not in session:
        new_captcha()

    if request.method == "GET":
        return render_template("index.html", result_img=None, hist_img=None, captcha=session["captcha"])

    # ---- проверка капчи ----
    user_captcha = request.form.get("captcha_text", "").strip().upper()
    real_captcha = session.get("captcha", "")

    if user_captcha != real_captcha:
        # обновляем капчу и показываем ошибку
        new_captcha()
        return render_template(
            "index.html",
            result_img=None,
            hist_img=None,
            captcha=session["captcha"],
            error="Капча введена неверно. Попробуйте ещё раз."
        )

    # капча пройдена — можно обработать изображение
    file = request.files.get("image")
    if not file or file.filename == "":
        new_captcha()
        return render_template("index.html", result_img=None, hist_img=None, captcha=session["captcha"], error="Файл не выбран")

    direction = request.form.get("direction", "vertical")
    stripe_str = request.form.get("stripe", "20")

    try:
        stripe = int(stripe_str)
    except ValueError:
        stripe = 20

    in_path = os.path.join(UPLOAD_DIR, "input.png")
    file.save(in_path)

    img = Image.open(in_path)

    hist_path = os.path.join(OUTPUT_DIR, "hist.png")
    make_rgb_histogram(img, hist_path)

    # --- замер времени ---
t0 = time.perf_counter()

out_img = swap_stripes(img, stripe, direction)

elapsed_ms = (time.perf_counter() - t0) * 1000.0

# --- добавляем подпись ---
out_img = draw_processing_time(out_img, elapsed_ms)

out_path = os.path.join(OUTPUT_DIR, "output.png")
out_img.save(out_path)


    # после успешной обработки — обновим капчу на следующую попытку
    new_captcha()

    return render_template(
        "index.html",
        result_img="outputs/output.png",
        hist_img="outputs/hist.png",
        captcha=session["captcha"],
        stripe=stripe,
        direction=direction
    )


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

