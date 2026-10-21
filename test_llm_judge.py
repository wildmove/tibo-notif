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

    @patch.dict('os.environ', {'JUDGE_PROVIDER': 'openai', 'JUDGE_API_KEY': 'test', 'JUDGE_MODEL': 'test-model'})
    def test_full_text_and_cache(self):
        judge = Judge(':memory:')
        text = "Day 15/ Nevermind, we're still cooking... and reset. Enjoy."
        with self.run_case({'verdict': 'reset', 'reason': 'Daily reset announcement', 'evidence': text}) as req:
            for _ in range(2):
                self.assertEqual(judge.evaluate({'id': '1', 'text': text})['verdict'], 'reset')
            self.assertEqual(req.call_count, 1)
            body = json.loads(req.call_args.args[0].data)
            self.assertEqual(json.loads(body['messages'][1]['content'])['text'], text)

    @patch.dict('os.environ', {'JUDGE_PROVIDER': 'openai', 'JUDGE_API_KEY': 'test', 'JUDGE_MODEL': 'test-model'})
    def test_reject_hallucinated_evidence_and_retry(self):
        judge = Judge(':memory:')
        with self.run_case({'verdict': 'reset', 'reason': 'test', 'evidence': 'invented'}) as req:
            judge.last_request = None
            for _ in range(2):
                judge.last_request = None
                with self.assertRaises(RuntimeError):
                    judge.evaluate({'id': '1', 'text': 'hello'})
            self.assertEqual(req.call_count, 2)

    @patch.dict('os.environ', {'JUDGE_PROVIDER': 'openai', 'JUDGE_API_KEY': 'test', 'JUDGE_MODEL': 'test-model'})
    def test_truncated_response_rejected(self):
        with self.run_case({'verdict': 'reset', 'reason': 'test', 'evidence': 'reset'}, 'length'):
            with self.assertRaises(RuntimeError):
                Judge(':memory:').evaluate({'id': '1', 'text': 'reset'})


class GeminiTests(unittest.TestCase):
    @patch.dict('os.environ', {'JUDGE_PROVIDER': 'gemini', 'gemini_api_key': 'fake', 'JUDGE_MODEL': 'gemini-2.5-flash'})
    def test_native_gemini_full_text(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'candidates': [{'finishReason': 'STOP',
            'content': {'parts': [{'text': json.dumps({'verdict': 'not_reset',
                'reason': 'Request rather than announcement', 'evidence': 'please'})}]}}]}).encode()
        with patch('llm_judge.urllib.request.urlopen', return_value=response) as req:
            verdict = Judge(':memory:').evaluate({'id': '2', 'text': 'please reset my limit'})
            self.assertEqual(verdict['verdict'], 'not_reset')
            request = req.call_args.args[0]
            self.assertEqual(request.get_header('X-goog-api-key'), 'fake')
            self.assertNotIn('fake', request.full_url)
            body = json.loads(request.data)
            self.assertEqual(json.loads(body['contents'][0]['parts'][0]['text'])['text'],
                             'please reset my limit')


class BudgetTests(unittest.TestCase):
    @patch.dict('os.environ', {'JUDGE_PROVIDER': 'gemini', 'gemini_api_key': 'fake',
                              'JUDGE_DAILY_MAX_CALLS': '1', 'JUDGE_RUN_MAX_CALLS': '5'})
    def test_budget_shared_across_instances(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            first = Judge(directory + '/cache.sqlite3')
            first.reserve_call()
            second = Judge(directory + '/cache.sqlite3')
            with self.assertRaisesRegex(RuntimeError, 'daily'):
                second.reserve_call()

    @patch.dict('os.environ', {'JUDGE_PROVIDER': 'gemini', 'gemini_api_key': 'fake'})
    def test_oversize_not_sent(self):
        with patch('llm_judge.urllib.request.urlopen') as req:
            with self.assertRaisesRegex(RuntimeError, '4000'):
                Judge(':memory:').evaluate({'id': '1', 'text': 'a' * 4001})
            req.assert_not_called()
