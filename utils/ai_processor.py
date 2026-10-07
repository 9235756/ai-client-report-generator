"""Работа с LLM: превращает транскрибацию диалога в структурированный JSON."""

import json
import os
import re

from dotenv import load_dotenv

from utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

DEFAULT_VALUE = "Не указано"
STRING_KEYS = ("client_name", "topic", "main_request", "mood", "deadline", "budget")
LIST_KEYS = ("key_requirements", "next_steps")
REQUIRED_KEYS = STRING_KEYS + LIST_KEYS

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
}

SYSTEM_PROMPT = """Ты — аналитик отдела продаж. Тебе дают транскрибацию диалога менеджера с клиентом.
Извлеки из неё ключевую информацию и верни ТОЛЬКО валидный JSON-объект без пояснений и markdown, строго такой структуры:

{
  "client_name": "имя клиента и, если есть, компания",
  "topic": "тема обращения в 3–8 словах",
  "main_request": "суть запроса клиента в 1–3 предложениях",
  "mood": "настроение клиента и его отношение к предложению, 1–2 предложения",
  "deadline": "сроки, которые назвал клиент",
  "budget": "бюджет, который назвал клиент",
  "key_requirements": ["требование 1", "требование 2"],
  "next_steps": ["договорённость или следующий шаг 1", "шаг 2"]
}

Правила:
- Пиши на русском языке.
- Используй только факты из диалога, ничего не придумывай.
- Если информации нет — пиши "Не указано" (для списков — пустой список).
- key_requirements и next_steps — массивы коротких строк."""

RETRY_PROMPT = (
    "Твой предыдущий ответ не удалось разобрать как JSON. "
    "Верни ТОЛЬКО JSON-объект указанной структуры — без пояснений, без markdown, без ```."
)


class AIProcessingError(Exception):
    """Ошибка конфигурации, сети или API провайдера."""


class AIResponseParseError(AIProcessingError):
    """Модель вернула ответ, который не удалось разобрать как JSON."""


def get_provider() -> str:
    provider = os.getenv("AI_PROVIDER", "openai").strip().lower()
    if provider not in DEFAULT_MODELS:
        raise AIProcessingError(
            f"Неизвестный AI_PROVIDER='{provider}'. Допустимые значения: openai, anthropic."
        )
    return provider


def _get_api_key(provider: str) -> str:
    env_name = f"{provider.upper()}_API_KEY"
    key = os.getenv(env_name, "").strip()
    if not key or key.startswith("your_"):
        raise AIProcessingError(
            f"Не задан {env_name}. Скопируйте .env.example в .env и впишите ключ."
        )
    return key


def _get_model(provider: str) -> str:
    return os.getenv(f"{provider.upper()}_MODEL", "").strip() or DEFAULT_MODELS[provider]


def _call_openai(messages: list[dict], model: str, api_key: str) -> str:
    import openai

    client = openai.OpenAI(api_key=api_key, timeout=60)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    except openai.AuthenticationError as exc:
        raise AIProcessingError("OpenAI отклонил API-ключ — проверьте OPENAI_API_KEY.") from exc
    except openai.APIConnectionError as exc:
        raise AIProcessingError(f"Нет соединения с OpenAI: {exc}") from exc
    except openai.APIError as exc:
        raise AIProcessingError(f"Ошибка OpenAI API: {exc}") from exc
    return response.choices[0].message.content or ""


def _call_anthropic(messages: list[dict], model: str, api_key: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=60)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
    except anthropic.AuthenticationError as exc:
        raise AIProcessingError(
            "Anthropic отклонил API-ключ — проверьте ANTHROPIC_API_KEY."
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise AIProcessingError(f"Нет соединения с Anthropic: {exc}") from exc
    except anthropic.APIError as exc:
        raise AIProcessingError(f"Ошибка Anthropic API: {exc}") from exc
    return "".join(block.text for block in response.content if block.type == "text")


def parse_ai_response(raw: str) -> dict:
    """Надёжно извлекает JSON из ответа модели и нормализует обязательные ключи."""
    if not raw or not raw.strip():
        raise AIResponseParseError("Модель вернула пустой ответ.")

    text = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise AIResponseParseError("В ответе модели не найден JSON-объект.")

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIResponseParseError(f"Невалидный JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AIResponseParseError("JSON в ответе модели не является объектом.")

    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        logger.warning("В ответе нет ключей %s — заполняю значением по умолчанию", missing)

    result = {}
    for key in STRING_KEYS:
        value = data.get(key)
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value)
        value = str(value).strip() if value is not None else ""
        result[key] = value or DEFAULT_VALUE

    for key in LIST_KEYS:
        value = data.get(key)
        if isinstance(value, str):
            value = [value] if value.strip() else []
        elif not isinstance(value, (list, tuple)):
            value = []
        items = [str(item).strip() for item in value if str(item).strip()]
        result[key] = items or [DEFAULT_VALUE]

    return result


def process_dialog_with_ai(text: str) -> dict:
    """Отправляет транскрибацию в LLM и возвращает структурированный словарь."""
    if not text or not text.strip():
        raise AIProcessingError("Пустой текст диалога — нечего анализировать.")

    provider = get_provider()
    api_key = _get_api_key(provider)
    model = _get_model(provider)
    call = _call_openai if provider == "openai" else _call_anthropic

    messages = [
        {"role": "user", "content": f"Транскрибация диалога:\n\n{text.strip()}"}
    ]
    logger.info(
        "Отправка в ИИ: провайдер=%s, модель=%s, длина текста=%d символов",
        provider, model, len(text),
    )
    raw = call(messages, model, api_key)
    logger.info("Ответ ИИ получен: %d символов", len(raw))

    try:
        data = parse_ai_response(raw)
    except AIResponseParseError as exc:
        logger.warning("Не удалось разобрать JSON (%s) — повторный запрос", exc)
        messages += [
            {"role": "assistant", "content": raw or "(пустой ответ)"},
            {"role": "user", "content": RETRY_PROMPT},
        ]
        raw = call(messages, model, api_key)
        logger.info("Повторный ответ ИИ получен: %d символов", len(raw))
        data = parse_ai_response(raw)

    logger.info("JSON успешно разобран: клиент=%s, тема=%s", data["client_name"], data["topic"])
    return data
