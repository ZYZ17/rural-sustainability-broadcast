from __future__ import annotations

import datetime as dt
import math
import re
from decimal import ROUND_HALF_UP, Decimal

DIGITS = "零一二三四五六七八九"


def num_to_zh_int(value: float | int) -> str:
    number = int(round(value))
    if number == 0:
        return "零"
    if number < 0:
        return "負" + num_to_zh_int(-number)
    text = str(number)
    length = len(text)
    output = ""
    zero_pending = False
    for index, char in enumerate(text):
        digit = int(char)
        position = length - index - 1
        if digit == 0:
            zero_pending = True
            if position == 4:
                output += "萬"
            continue
        if zero_pending and output:
            output += "零"
        zero_pending = False
        output += DIGITS[digit]
        if position % 4 == 3:
            output += "千"
        elif position % 4 == 2:
            output += "百"
        elif position % 4 == 1:
            output += "十"
        if position == 4:
            output += "萬"
    if output.startswith("一十"):
        output = output[1:]
    return output


def format_number(value: float | int | None, max_decimals: int = 2) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(number):
        return ""
    quantum = Decimal("1").scaleb(-max_decimals)
    rounded = Decimal(str(number)).quantize(quantum, rounding=ROUND_HALF_UP)
    text = format(rounded, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def num_to_zh(value: float | int) -> str:
    if isinstance(value, float) and not value.is_integer():
        negative = value < 0
        absolute = abs(value)
        whole = int(absolute)
        fraction = f"{absolute:.10f}".rstrip("0").split(".")[1]
        prefix = "負" if negative else ""
        return prefix + num_to_zh_int(whole) + "點" + "".join(DIGITS[int(digit)] for digit in fraction)
    return num_to_zh_int(value)


def price_to_zh(value: float) -> str:
    text = format_number(value, 2)
    if not text:
        return "無資料"
    return num_to_zh(float(text))


def field_to_zh(value: float | int | None) -> str:
    if value is None:
        return "無資料"
    return price_to_zh(float(value))


def trend_to_zh(change: float | None) -> str:
    if change is None:
        return "無昨日資料"
    text = format_number(change, 2)
    if not text:
        return "無昨日資料"
    numeric = float(text)
    if abs(numeric) < 0.005:
        return "持平"
    direction = "起" if numeric > 0 else "落"
    return f"{direction}{price_to_zh(abs(numeric))}元"


def date_to_zh(iso_date: str) -> str:
    parsed = dt.date.fromisoformat(iso_date)
    weekday = "一二三四五六日"[parsed.weekday()]
    month = num_to_zh_int(parsed.month)
    day = num_to_zh_int(parsed.day)
    return f"{month}月{day}號，拜{weekday}"


def _number(match: re.Match[str]) -> str:
    return num_to_zh(float(match.group(0)))


def normalize_tts_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(
        r"(\d+(?:\.\d+)?)\s*%",
        lambda match: "百分之" + num_to_zh(float(match.group(1))),
        text,
    )
    text = re.sub(r"(?<=\d)\s*(?:~|～|-)\s*(?=\d)", "到", text)
    text = re.sub(r"\d+(?:\.\d+)?", _number, text)
    text = text.replace("、", "，")
    text = text.replace("；", "，")
    text = text.replace("：", "，")
    text = text.replace("…", "。")
    text = re.sub(r"[「」『』【】〔〕（）()\[\]{}]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([，。！？])", r"\1", text)
    text = re.sub(r"([，。！？])\s+", r"\1", text)
    text = re.sub(r"。{2,}", "。", text)
    return text.strip()
