"""Render the approved weather alert as a legible image for Messages."""
from __future__ import annotations

import io
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False):
    family = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    mac = "Arial Bold.ttf" if bold else "Arial.ttf"
    for path in (family, str(Path("/System/Library/Fonts/Supplemental") / mac)):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def render_forecast_card(alert: str) -> bytes:
    lines = alert.splitlines()
    property_name = lines[0].partition(" · ")[2]
    forecast = lines[2]
    issue = next((line for line in lines if line.startswith(("Historical forecast", "Forecast issued"))), "")
    time = re.search(r"(\d+(?:\.\d+)?) hours to (tropical-storm winds|the warning)", alert)
    wind = re.search(r"(Sustained winds near|Gusts up to) (\d+(?:\.\d+)?) mph", alert)
    image = Image.new("RGB", (900, 580), "#101d31")
    draw = ImageDraw.Draw(image)
    for y in range(580):
        ratio = y / 579
        draw.line((0, y, 900, y), fill=(16 + int(10 * ratio), 29 + int(19 * ratio), 49 + int(25 * ratio)))
    for x in range(560, 1140, 112):
        draw.arc((x - 195, -70, x + 310, 340), 134, 241, fill="#283c56", width=3)
    draw.rectangle((0, 0, 900, 9), fill="#ffc25c")
    draw.text((36, 29), "BRACE  /  PROPERTY WEATHER ADVISORY", font=_font(25, True), fill="#ffc25c")
    name_size = 43
    while name_size > 24 and draw.textlength(property_name, font=_font(name_size, True)) > 825:
        name_size -= 1
    draw.text((36, 93), property_name, font=_font(name_size, True), fill="#ffffff")
    subtitle_font = _font(29)
    if draw.textlength(forecast, font=subtitle_font) > 824:
        first, second = "", ""
        for word in forecast.split():
            candidate = (first + " " + word).strip()
            if second or draw.textlength(candidate, font=subtitle_font) > 824:
                second = (second + " " + word).strip()
            else:
                first = candidate
        while draw.textlength(second, font=subtitle_font) > 820:
            second = second[:-1]
        if second and not forecast.endswith(second):
            second = second.rstrip() + "…"
        forecast = first + "\n" + second
    draw.multiline_text((38, 148), forecast, font=subtitle_font, spacing=3, fill="#c8d6e7")
    draw.rounded_rectangle((36, 219, 864, 471), 24, fill="#14253b", outline="#465c76", width=2)
    draw.line((450, 248, 450, 444), fill="#465c76", width=2)
    if time:
        draw.text((65, 252), time[1] + " h", font=_font(88, True), fill="#ffffff")
        draw.text((69, 365), "TO " + time[2].replace("the ", "").upper(), font=_font(22, True), fill="#ffc25c")
        draw.text((69, 402), "At forecast issue", font=_font(22), fill="#c8d6e7")
    else:
        draw.text((65, 274), "Weather\nforecast", font=_font(47, True), fill="#ffffff", spacing=5)
    if wind:
        draw.text((479, 252), wind[2], font=_font(88, True), fill="#ffffff")
        draw.text((482, 365), "MPH " + ("SUSTAINED" if wind[1].startswith("Sustained") else "GUSTS"),
                  font=_font(22, True), fill="#ffc25c")
        draw.text((482, 402), "Property forecast", font=_font(22), fill="#c8d6e7")
    else:
        draw.text((481, 275), "Property\nforecast", font=_font(43, True), fill="#ffffff", spacing=5)
    draw.text((37, 514), issue.replace("T", " ", 1).removesuffix("Z") + (" UTC" if issue.endswith("Z") else ""),
              font=_font(22), fill="#c8d6e7")
    result = io.BytesIO()
    image.save(result, format="PNG", optimize=True)
    return result.getvalue()
