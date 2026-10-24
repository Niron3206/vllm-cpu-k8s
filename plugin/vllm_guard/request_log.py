"""логирование запросов к vllm без текста промптов и ответов

vllm грузит модуль как general-плагин (entry point в pyproject.toml) и вызывает
register(). Тот подменяет методы RequestLogger. В лог попадают id запроса и
число токенов, а промпт, тело запроса и сгенерированный текст не попадают ни на
каком уровне логирования. Строки пишутся, когда включён --enable-log-requests
"""

import inspect
import logging

# логгер внутри иерархии vllm
logger = logging.getLogger("vllm.guard")


def _count(token_ids):
    return len(token_ids) if token_ids is not None else "?"

def _init(self, *, max_log_len):
    self.max_log_len = max_log_len
    logger.info("request logging is on, prompts and outputs are not logged")

def _log_inputs(self, request_id, prompt, prompt_token_ids, prompt_embeds, params, lora_request):
    logger.info(
        "request %s: prompt_tokens=%s max_tokens=%s",
        request_id,
        _count(prompt_token_ids),
        getattr(params, "max_tokens", None),
    )

def _log_request_body(self, request):
    pass

def _log_outputs(self, request_id, outputs, output_token_ids, finish_reason=None, is_streaming=False, delta=False):
    if delta:
        return
    logger.info(
        "response %s: output_tokens=%s finish_reason=%s",
        request_id,
        _count(output_token_ids),
        finish_reason,
    )


_REPLACEMENTS = {
    "__init__": _init,
    "log_inputs": _log_inputs,
    "log_request_body": _log_request_body,
    "log_outputs": _log_outputs,
}


def _params(func):
    return list(inspect.signature(func).parameters)

def patch(cls):
    for name, func in _REPLACEMENTS.items():
        original = getattr(cls, name, None)
        if original is func:
            continue
        # если vllm поменял сигнатуры, лучше не стартовать, чем молча писать промпты
        if original is None or _params(original) != _params(func):
            raise RuntimeError(
                f"{cls.__name__}.{name} не совпадает с ожидаемым, vllm_guard надо обновить"
            )
        setattr(cls, name, func)

def register():
    from vllm.entrypoints.serve.utils.request_logger import RequestLogger

    patch(RequestLogger)
