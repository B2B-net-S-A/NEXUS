import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('digest', Path(__file__).parents[1] / 'sentry_daily_digest.py')
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)

class DigestTests(unittest.TestCase):
    @patch.dict(os.environ, {'SENTRY_READ_TOKEN': 'synthetic', 'DRY_RUN': '1'}, clear=True)
    def test_forbidden_is_failure(self):
        with patch.object(digest, 'fetch_issues', side_effect=HTTPError('https://test',403,'Forbidden',{},None)):
            self.assertEqual(digest.main(), 1)

    @patch.dict(os.environ, {'SENTRY_READ_TOKEN': 'synthetic'}, clear=True)
    def test_missing_receiver_is_failure(self):
        self.assertEqual(digest.main(), 1)

    @patch.dict(os.environ, {'SENTRY_READ_TOKEN': 'synthetic', 'TEAMS_SENTRY_WEBHOOK_URL':'https://test'}, clear=True)
    def test_delivery_failure(self):
        with patch.object(digest, 'build_message', return_value=('safe', True)), patch.object(digest, 'post_to_teams', side_effect=TimeoutError()):
            self.assertEqual(digest.main(), 2)

    def test_no_raw_title_and_no_lifetime_as_daily_count(self):
        line=digest.format_issue_line({'id':'123','shortId':'NEXUS-BE-1','title':'private CV','count':9000,'filtered':{'count':'5'}})
        self.assertNotIn('private',line)
        self.assertNotIn('9000',line)
        self.assertIn('Sentry events/window: 5',line)

    def test_pagination_and_production(self):
        first, second = MagicMock(), MagicMock()
        first.__enter__.return_value=first
        second.__enter__.return_value=second
        first.read.return_value=b'[{"id":"1"}]'
        second.read.return_value=b'[{"id":"2"}]'
        first.headers={'Link':'<https://test>; rel="next"; results="true"; cursor="abc"'}
        second.headers={}
        with patch.object(digest.urllib.request,'urlopen',side_effect=[first,second]) as call:
            self.assertEqual(len(digest.fetch_issues('test','nexus-be')),2)
            self.assertIn('environment=production',call.call_args_list[0].args[0].full_url)
            self.assertIn('cursor=abc',call.call_args_list[1].args[0].full_url)
            self.assertIn('project=nexus-be',call.call_args_list[0].args[0].full_url)

    def test_both_projects_share_one_explicit_time_window(self):
        with patch.object(digest, 'project_section', return_value=('ok', True)) as call:
            message, complete = digest.build_message('test')
            self.assertTrue(complete)
            self.assertEqual(call.call_args_list[0].kwargs, call.call_args_list[1].kwargs)
            self.assertIn('UTC window:', message)

    def test_linked_pr_and_sanitized_operation(self):
        line = digest.format_issue_line({'id':'145702601','operation':'GET /api/reports/clients/:id','title':'private CV'})
        self.assertIn('/pull/1515', line)
        self.assertIn('GET /api/reports/clients/:id', line)
        self.assertNotIn('private CV', line)

if __name__=='__main__':
    unittest.main()
