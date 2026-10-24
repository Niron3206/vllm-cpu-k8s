"""фильтр для хендлера логов vllm, подключается в logging.json

Второй слой после request_log. Отсекает записи модулей, 
которые сами по себе пишут текст запросов или ответов.
"""

import logging

# эти пишут контент на любом уровне
ALWAYS_DROP = (
    # тела ответов целиком, включается VLLM_DEBUG_LOG_API_SERVER_RESPONSE
    "vllm.entrypoints.serve.middleware.log_response",
    # gpt-oss: WARNING с аргументами tool call, которые сгенерировала модель
    "vllm.entrypoints.openai.responses.harmony",
)

# эти пишут промпты, тела запросов и куски генерации на DEBUG
DEBUG_DROP = (
    "vllm.entrypoints",
    "vllm.parser",
    "vllm.renderers",
    "vllm.tool_parsers",
)


def _under(name, prefixes):
    return any(name == p or name.startswith(p + ".") for p in prefixes)


class DropSensitive(logging.Filter):
    def filter(self, record):
        if _under(record.name, ALWAYS_DROP):
            return False
        if record.levelno < logging.INFO and _under(record.name, DEBUG_DROP):
            return False
        return True
