#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_fonts — دریافت و آماده‌سازی فونت‌های لازم برای md2pdf_fa

این اسکریپت سه بستهٔ فونت را از رجیستری npm می‌گیرد (چون دانلود مستقیم از GitHub
در برخی شبکه‌ها بسته است) و آن‌ها را داخل پوشهٔ tools/fonts می‌گذارد:

  • Vazirmatn          → فونت اصلی متن فارسی (Regular / Bold / Medium)
  • JetBrains Mono     → فونت بلوک‌های کد (از woff2 به ttf تبدیل می‌شود)
  • DejaVu Sans        → فونت پشتیبان برای نمادهای ریاضی/یونانی/فلش (زیرمجموعه‌سازی‌شده)

اجرا:
    python3 tools/fetch_fonts.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

PACKAGES = {
    "vazirmatn": ["vazirmatn@33.0.3"],
    "jetbrains": ["@fontsource/jetbrains-mono@5.3.0"],
    "dejavu": ["dejavu-fonts-ttf@2.37.3"],
}

# محدودهٔ یونیکد برای زیرمجموعهٔ DejaVu: علائم نگارشی، یونانی، سیریلیک،
# نمادهای ریاضی، فلش‌ها و شکل‌های هندسی.
DEJAVU_UNICODES = (
    "U+00A0-00FF,U+2000-206F,U+2070-209F,U+20A0-20CF,U+2100-214F,"
    "U+2190-21FF,U+2200-22FF,U+2300-23FF,U+25A0-25FF,U+2600-26FF,"
    "U+2700-27BF,U+0370-03FF,U+0400-04FF,U+02B0-02FF"
)


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def npm_pack(spec: str, workdir: Path) -> Path:
    """بستهٔ npm را دانلود و استخراج می‌کند و مسیر پوشهٔ استخراج‌شده را برمی‌گرداند."""
    result = run(["npm", "pack", spec], cwd=workdir)
    tarball = workdir / result.stdout.strip().splitlines()[-1]
    extract_dir = workdir / spec.replace("@", "").replace("/", "_").replace(":", "_")
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball) as archive:
        archive.extractall(extract_dir)  # noqa: S202 - بستهٔ npm مورد اعتماد است
    return extract_dir / "package"


def woff2_to_ttf(source: Path, destination: Path) -> None:
    """تبدیل woff2 به ttf (نیازمند fontTools و brotli)."""
    from fontTools.ttLib import TTFont

    font = TTFont(str(source))
    font.flavor = None
    font.save(str(destination))


def subset_dejavu(source: Path, destination: Path) -> None:
    """زیرمجموعه‌سازی DejaVu تا حجم فایل کم شود."""
    from fontTools import subset

    subset.main(
        [
            str(source),
            f"--unicodes={DEJAVU_UNICODES}",
            "--layout-features=*",
            "--no-hinting",
            "--desubroutinize",
            "--name-IDs=*",
            f"--output-file={destination}",
        ]
    )


def main() -> int:
    if shutil.which("npm") is None:
        print("✗ دستور npm پیدا نشد؛ برای اجرای این اسکریپت Node.js/npm لازم است.", file=sys.stderr)
        return 2

    try:
        import fontTools  # noqa: F401
        import brotli  # noqa: F401
    except ImportError:
        print("… نصب پیش‌نیازهای پایتون: fonttools, brotli")
        try:
            run([sys.executable, "-m", "pip", "install", "--quiet", "fonttools", "brotli"])
        except subprocess.CalledProcessError:
            print(
                "✗ نصب خودکار ناموفق بود. دستی اجرا کنید:\n"
                "    pip install fonttools brotli",
                file=sys.stderr,
            )
            return 2

    FONTS_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        print("… دریافت وزیرمتن")
        package = npm_pack(PACKAGES["vazirmatn"][0], workdir)
        for name in ("Regular", "Bold", "Medium"):
            shutil.copy(package / "fonts" / "ttf" / f"Vazirmatn-{name}.ttf", FONTS_DIR)

        print("… دریافت JetBrains Mono")
        package = npm_pack(PACKAGES["jetbrains"][0], workdir)
        woff2_to_ttf(
            package / "files" / "jetbrains-mono-latin-400-normal.woff2",
            FONTS_DIR / "JetBrainsMono-Regular.ttf",
        )
        woff2_to_ttf(
            package / "files" / "jetbrains-mono-latin-700-normal.woff2",
            FONTS_DIR / "JetBrainsMono-Bold.ttf",
        )

        print("… دریافت و زیرمجموعه‌سازی DejaVu Sans (فونت پشتیبان نمادها)")
        package = npm_pack(PACKAGES["dejavu"][0], workdir)
        subset_dejavu(package / "ttf" / "DejaVuSans.ttf", FONTS_DIR / "DejaVuSans-Subset.ttf")
        subset_dejavu(
            package / "ttf" / "DejaVuSans-Bold.ttf", FONTS_DIR / "DejaVuSans-Bold-Subset.ttf"
        )

    print("✓ فونت‌ها در", FONTS_DIR, "آماده شدند:")
    for font in sorted(FONTS_DIR.glob("*.ttf")):
        print(f"   • {font.name} ({font.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
