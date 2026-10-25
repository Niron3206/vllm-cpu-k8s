import json
import logging
import logging.config
import os
import unittest

from vllm_guard.log_filter import DropSensitive


def record(name, level):
    return logging.LogRecord(name, level, __file__, 1, "msg", None, None)


class DropSensitiveTest(unittest.TestCase):
    def setUp(self):
        self.f = DropSensitive()

    def test_debug_from_content_modules_dropped(self):
        for name in (
            "vllm.tool_parsers.hermes_tool_parser",
            "vllm.renderers.chat_utils",
            "vllm.entrypoints.serve.utils.request_logger",
            "vllm.parser.engine.parser_engine",
        ):
            self.assertFalse(self.f.filter(record(name, logging.DEBUG)), name)

    def test_info_from_content_modules_kept(self):
        self.assertTrue(self.f.filter(record("vllm.entrypoints.launchers.api_server.entry", logging.INFO)))

    def test_engine_debug_kept(self):
        self.assertTrue(self.f.filter(record("vllm.v1.engine.core", logging.DEBUG)))

    def test_similar_prefix_kept(self):
        self.assertTrue(self.f.filter(record("vllm.entrypoints_extra", logging.DEBUG)))

    def test_response_body_log_always_dropped(self):
        name = "vllm.entrypoints.serve.middleware.log_response"
        for level in (logging.INFO, logging.WARNING, logging.ERROR):
            self.assertFalse(self.f.filter(record(name, level)))

    @unittest.skipUnless(os.environ.get("VLLM_LOGGING_CONFIG_PATH"), "нужен конфиг логов")
    def test_logging_config_attaches_filter(self):
        with open(os.environ["VLLM_LOGGING_CONFIG_PATH"]) as f:
            logging.config.dictConfig(json.load(f))
        handler = logging.getLogger("vllm").handlers[0]
        self.assertTrue(any(isinstance(f, DropSensitive) for f in handler.filters))
        # vllm отдаёт этот же конфиг uvicorn. Без своего логгера пропадёт access-лог
        self.assertEqual(logging.getLogger("uvicorn").handlers, [handler])


if __name__ == "__main__":
    unittest.main()
