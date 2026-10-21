import json
import unittest
from unittest.mock import patch, Mock
from llm_judge import Judge


class JudgeTests(unittest.TestCase):
    def run_case(self, verdict, finish='stop'):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'choices': [{'finish_reason': finish,
            'message': {'content': json.dumps(verdict)}}]}).encode()
        return patch('llm_judge.urllib.request.urlopen', return_value=response)

    @patch.dict('os.environ', {'JUDGE_API_KEY': 'test', 'JUDGE_MODEL': 'test-model'})
    def test_full_text_and_cache(self):
        judge = Judge(':memory:')
        text = "Day 15/ Nevermind, we're still cooking... and reset. Enjoy."
        with self.run_case({'verdict': 'reset', 'reason': 'Daily reset announcement', 'evidence': text}) as req:
            for _ in range(2):
                self.assertEqual(judge.evaluate({'id': '1', 'text': text})['verdict'], 'reset')
            self.assertEqual(req.call_count, 1)
            body = json.loads(req.call_args.args[0].data)
            self.assertEqual(json.loads(body['messages'][1]['content'])['text'], text)

    @patch.dict('os.environ', {'JUDGE_API_KEY': 'test', 'JUDGE_MODEL': 'test-model'})
    def test_reject_hallucinated_evidence_and_retry(self):
        judge = Judge(':memory:')
        with self.run_case({'verdict': 'reset', 'reason': 'test', 'evidence': 'invented'}) as req:
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    judge.evaluate({'id': '1', 'text': 'hello'})
            self.assertEqual(req.call_count, 2)

    @patch.dict('os.environ', {'JUDGE_API_KEY': 'test', 'JUDGE_MODEL': 'test-model'})
    def test_truncated_response_rejected(self):
        with self.run_case({'verdict': 'reset', 'reason': 'test', 'evidence': 'reset'}, 'length'):
            with self.assertRaises(RuntimeError):
                Judge(':memory:').evaluate({'id': '1', 'text': 'reset'})
