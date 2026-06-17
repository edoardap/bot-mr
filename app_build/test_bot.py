import unittest
from datetime import datetime, timezone, timedelta
import discord
from bot import fetch_gitlab_data, MockMergeRequest, format_summary_embeds

class TestGitLabMRBot(unittest.TestCase):
    def setUp(self):
        # Default threshold for stale check is 3 days
        self.stale_days = 3

    def test_filter_drafts(self):
        """Verify draft or WIP merge requests are skipped during parsing."""
        mock_mrs = [
            MockMergeRequest("MR 1", "url1", ["Aguardando Revisão"], "user1", draft=True),
            MockMergeRequest("MR 2", "url2", ["Aguardando Revisão"], "user2", work_in_progress=True),
            MockMergeRequest("MR 3", "url3", ["Aguardando Revisão"], "user3")  # valid
        ]
        
        # We temporarily patch get_mock_mrs to return our controlled list
        import bot
        original_get_mock = bot.get_mock_mrs
        bot.get_mock_mrs = lambda: mock_mrs
        
        try:
            data = fetch_gitlab_data(None, None, None, self.stale_days, mock=True)
            # Only MR 3 should be processed.
            # However, MR 3 doesn't have assignees/reviewers, so it will go to no_reviewers
            self.assertEqual(len(data['no_reviewers']), 1)
            self.assertEqual(data['no_reviewers'][0].title, "MR 3")
            self.assertEqual(len(data['awaiting_review']), 0)
        finally:
            bot.get_mock_mrs = original_get_mock

    def test_awaiting_review_and_workload(self):
        """Verify MRs with 'awaiting review' label are parsed and reviewers' workloads are updated."""
        mock_mrs = [
            MockMergeRequest(
                title="Awaiting Review MR",
                web_url="url1",
                labels=["Aguardando Revisão"],
                author_username="author1",
                assignees=[{"username": "reviewer1"}],
                reviewers=[{"username": "reviewer2"}]
            )
        ]
        
        import bot
        original_get_mock = bot.get_mock_mrs
        bot.get_mock_mrs = lambda: mock_mrs
        
        try:
            data = fetch_gitlab_data(None, None, None, self.stale_days, mock=True)
            
            # Check awaiting review MR
            self.assertEqual(len(data['awaiting_review']), 1)
            mr, reviewers = data['awaiting_review'][0]
            self.assertEqual(mr.title, "Awaiting Review MR")
            self.assertIn("reviewer1", reviewers)
            self.assertIn("reviewer2", reviewers)
            
            # Check workload
            self.assertEqual(data['reviewer_workload'].get("reviewer1"), 1)
            self.assertEqual(data['reviewer_workload'].get("reviewer2"), 1)
        finally:
            bot.get_mock_mrs = original_get_mock

    def test_changes_requested(self):
        """Verify MRs with 'changes requested' label are correctly categorized."""
        mock_mrs = [
            MockMergeRequest(
                title="Changes Requested MR",
                web_url="url1",
                labels=["Alterações Solicitadas"],
                author_username="author1"
            )
        ]
        
        import bot
        original_get_mock = bot.get_mock_mrs
        bot.get_mock_mrs = lambda: mock_mrs
        
        try:
            data = fetch_gitlab_data(None, None, None, self.stale_days, mock=True)
            self.assertEqual(len(data['changes_requested']), 1)
            self.assertEqual(data['changes_requested'][0].title, "Changes Requested MR")
            self.assertEqual(data['changes_requested'][0].author['username'], "author1")
        finally:
            bot.get_mock_mrs = original_get_mock

    def test_stale_mrs(self):
        """Verify MRs older than the threshold are flagged as stale."""
        mock_mrs = [
            MockMergeRequest("Active MR", "url1", [], "user1", updated_days_ago=1),
            MockMergeRequest("Stale MR", "url2", [], "user2", updated_days_ago=4)
        ]
        
        import bot
        original_get_mock = bot.get_mock_mrs
        bot.get_mock_mrs = lambda: mock_mrs
        
        try:
            data = fetch_gitlab_data(None, None, None, self.stale_days, mock=True)
            self.assertEqual(len(data['stale_mrs']), 1)
            self.assertEqual(data['stale_mrs'][0].title, "Stale MR")
        finally:
            bot.get_mock_mrs = original_get_mock

    def test_author_not_in_reviewers(self):
        """Verify the author of the MR is filtered out from the reviewers list."""
        mock_mrs = [
            MockMergeRequest(
                title="Author in assignees",
                web_url="url1",
                labels=["Aguardando Revisão"],
                author_username="author_user",
                assignees=[{"username": "author_user"}, {"username": "reviewer_user"}]
            )
        ]
        import bot
        original_get_mock = bot.get_mock_mrs
        bot.get_mock_mrs = lambda: mock_mrs
        
        try:
            data = fetch_gitlab_data(None, None, None, self.stale_days, mock=True)
            self.assertEqual(len(data['awaiting_review']), 1)
            mr, reviewers = data['awaiting_review'][0]
            self.assertEqual(len(reviewers), 1)
            self.assertIn("reviewer_user", reviewers)
            self.assertNotIn("author_user", reviewers)
        finally:
            bot.get_mock_mrs = original_get_mock

    def test_format_summary_embeds_single(self):
        """Verify format_summary_embeds returns a single embed when content is short."""
        data = {
            'awaiting_review': [],
            'changes_requested': [],
            'stale_mrs': [],
            'no_reviewers': [],
            'reviewer_workload': {}
        }
        embeds = format_summary_embeds(data, {})
        self.assertEqual(len(embeds), 1)
        self.assertIn("Aguardando Revisão", embeds[0].description)

    def test_format_summary_embeds_splitting(self):
        """Verify format_summary_embeds splits into multiple embeds when content is very long."""
        awaiting = []
        for i in range(30):
            mr = MockMergeRequest(
                title=f"Very long MR title {'x'*100} #{i}",
                web_url=f"https://gitlab.com/mock/project/-/merge_requests/{i}",
                labels=["Aguardando Revisão"],
                author_username=f"user{i}"
            )
            awaiting.append((mr, ["reviewer"]))
        
        data = {
            'awaiting_review': awaiting,
            'changes_requested': [],
            'stale_mrs': [],
            'no_reviewers': [],
            'reviewer_workload': {}
        }
        embeds = format_summary_embeds(data, {})
        # With 30 MRs of ~200 chars each, it should exceed 4000 characters and split
        self.assertGreater(len(embeds), 1)
        for embed in embeds:
            self.assertTrue(len(embed.description) <= 4000)

if __name__ == "__main__":
    unittest.main()
