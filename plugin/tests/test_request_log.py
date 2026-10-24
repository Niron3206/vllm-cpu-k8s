import unittest
from importlib.metadata import entry_points

from vllm.entrypoints.serve.utils.request_logger import RequestLogger
from vllm.sampling_params import SamplingParams

from vllm_guard import request_log

PROMPT = "канарейка-промпт-7f3a"
ANSWER = "канарейка-ответ-9c1d"


class FakeRequest:
    request_id = "req-1"

    def model_dump_json(self, **kwargs):
        return f'{{"prompt": "{PROMPT}"}}'


class RequestLogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        request_log.register()

    def test_no_text_even_on_debug(self):
        with self.assertLogs("vllm", level="DEBUG") as logs:
            rl = RequestLogger(max_log_len=None)
            rl.log_request_body(FakeRequest())
            rl.log_inputs(
                "req-1", PROMPT, [1, 2, 3], None,
                params=SamplingParams(max_tokens=16), lora_request=None,
            )
            rl.log_outputs(
                request_id="req-1", outputs=ANSWER, output_token_ids=[4],
                finish_reason=None, is_streaming=True, delta=True,
            )
            rl.log_outputs(
                request_id="req-1", outputs=ANSWER, output_token_ids=[4, 5],
                finish_reason="stop",
            )

        text = "\n".join(logs.output)
        self.assertNotIn(PROMPT, text)
        self.assertNotIn(ANSWER, text)
        self.assertIn("request req-1: prompt_tokens=3 max_tokens=16", text)
        self.assertIn("response req-1: output_tokens=2 finish_reason=stop", text)

    def test_register_is_idempotent(self):
        request_log.register()

    def test_changed_signature_fails(self):
        class Changed:
            def log_inputs(self, request_id, prompt):
                pass

        with self.assertRaises(RuntimeError):
            request_log.patch(Changed)

    def test_entry_point_installed(self):
        values = [ep.value for ep in entry_points(group="vllm.general_plugins")]
        self.assertIn("vllm_guard.request_log:register", values)


if __name__ == "__main__":
    unittest.main()
