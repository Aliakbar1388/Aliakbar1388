#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تبدیل تاریخ میلادی به شمسی و قالب‌بندی آن برای جلد جزوه."""

from __future__ import annotations

import datetime as _dt

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

MONTHS = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تبدیل تاریخ میلادی به هجری شمسی (الگوریتم استاندارد جلالی)."""
    days_in_month = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
        + days_in_month[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def fa_num(value: object) -> str:
    return str(value).translate(FA_DIGITS)


def jalali_today(prefix: str = "", suffix: str = "") -> str:
    """تاریخ امروز به‌صورت «۹ مهر ۱۴۰۵» (با ارقام فارسی)."""
    today = _dt.date.today()
    jy, jm, jd = gregorian_to_jalali(today.year, today.month, today.day)
    text = f"{jd} {MONTHS[jm - 1]} {jy}"
    return f"{prefix}{text}{suffix}"


if __name__ == "__main__":
    print(jalali_today())
