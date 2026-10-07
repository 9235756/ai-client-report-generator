"""Рендер HTML-шаблона отчёта и конвертация в PDF через WeasyPrint."""

import sys
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateError, select_autoescape

from utils.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
REPORTS_DIR = BASE_DIR / "reports"
TEMPLATE_NAME = "report_template.html"

WEASYPRINT_HELP = (
    "Проверьте установку системных библиотек WeasyPrint "
    "(https://doc.courtbouillon.org/weasyprint/stable/first_steps.html). "
    "Windows: установите GTK через MSYS2 (pacman -S mingw-w64-x86_64-pango). "
    "macOS: brew install pango. Linux: apt install libpango-1.0-0 libpangoft2-1.0-0."
)


class PDFGenerationError(Exception):
    """Ошибка рендера шаблона или генерации PDF."""


MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def render_html(data: dict, generated_at: datetime) -> str:
    """Подставляет данные в Jinja2-шаблон и возвращает готовый HTML."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    try:
        template = env.get_template(TEMPLATE_NAME)
        human_date = (
            f"{generated_at.day} {MONTHS[generated_at.month - 1]} {generated_at.year}, "
            f"{generated_at:%H:%M}"
        )
        html = template.render(report=data, generated_at=human_date)
    except TemplateError as exc:
        raise PDFGenerationError(f"Ошибка рендера шаблона {TEMPLATE_NAME}: {exc}") from exc
    logger.info("Шаблон %s отрендерен (%d символов HTML)", TEMPLATE_NAME, len(html))
    return html


def generate_pdf(data: dict) -> Path:
    """Создаёт PDF-отчёт в папке reports/ и возвращает путь к файлу."""
    generated_at = datetime.now()
    html = render_html(data, generated_at)

    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        hint = ""
        if sys.platform.startswith("win"):
            hint = " На Windows WeasyPrint требует GTK — см. README, раздел «Установка»."
        raise PDFGenerationError(
            f"Не удалось загрузить WeasyPrint: {exc}.{hint} {WEASYPRINT_HELP}"
        ) from exc

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORTS_DIR / f"report_{generated_at:%Y-%m-%d_%H-%M-%S}.pdf"

    logger.info("Генерация PDF...")
    try:
        HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf(output)
    except Exception as exc:  # WeasyPrint не имеет единого базового исключения
        raise PDFGenerationError(f"Ошибка WeasyPrint при генерации PDF: {exc}. {WEASYPRINT_HELP}") from exc

    logger.info("PDF сохранён: %s", output)
    return output
