"""AI Client Report Generator — CLI.

Использование:
    python main.py examples/example_dialog.txt   # прочитать диалог из файла
    python main.py                               # вставить текст вручную
    python main.py --from-json examples/example_response.json   # PDF из готового JSON, без ИИ
"""

import argparse
import sys
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("main")

BASE_DIR = Path(__file__).resolve().parent


def read_text_file(path_str: str) -> str:
    path = Path(path_str)
    logger.info("Чтение файла: %s", path)
    if not path.is_file():
        raise ValueError(f"Файл не найден: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Файл {path} не в кодировке UTF-8: {exc}") from exc
    logger.info("Файл прочитан: %d символов", len(text))
    return text


def read_dialog_stdin() -> str:
    print("Вставьте текст диалога. Чтобы закончить ввод, оставьте пустую строку:")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
    text = "\n".join(lines)
    logger.info("Текст введён вручную: %d символов", len(text))
    return text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Формирует PDF-отчёт по транскрибации диалога с клиентом с помощью ИИ."
    )
    parser.add_argument("file", nargs="?", help="путь к .txt с транскрибацией диалога")
    parser.add_argument(
        "--from-json",
        metavar="PATH",
        help="собрать PDF из готового JSON-ответа без обращения к ИИ (демо и отладка шаблона)",
    )
    args = parser.parse_args()
    if args.file and args.from_json:
        parser.error("укажите либо файл диалога, либо --from-json")

    # Импорт здесь, чтобы логирование уже было настроено при загрузке модулей
    from utils.ai_processor import (
        AIProcessingError,
        AIResponseParseError,
        parse_ai_response,
        process_dialog_with_ai,
    )
    from utils.pdf_generator import PDFGenerationError, generate_pdf

    try:
        if args.from_json:
            logger.info("Демо-режим: ИИ не вызывается, данные берутся из %s", args.from_json)
            data = parse_ai_response(read_text_file(args.from_json))
        else:
            text = read_text_file(args.file) if args.file else read_dialog_stdin()
            if not text.strip():
                raise ValueError("Текст диалога пустой — нечего анализировать.")
            data = process_dialog_with_ai(text)

        pdf_path = generate_pdf(data)
    except ValueError as exc:
        logger.error("Ошибка входных данных: %s", exc)
        return 1
    except AIResponseParseError as exc:
        logger.error("ИИ вернул невалидный JSON даже после повторной попытки: %s", exc)
        return 3
    except AIProcessingError as exc:
        logger.error("Ошибка ИИ: %s", exc)
        return 2
    except PDFGenerationError as exc:
        logger.error("%s", exc)
        return 4
    except KeyboardInterrupt:
        logger.warning("Прервано пользователем")
        return 130

    try:
        shown = pdf_path.relative_to(BASE_DIR)
    except ValueError:
        shown = pdf_path
    print(f"Отчёт успешно создан: {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
