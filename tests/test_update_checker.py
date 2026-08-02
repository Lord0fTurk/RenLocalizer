import unittest
from unittest.mock import patch, MagicMock
from src.utils.update_checker import check_for_updates, _is_newer, _parse_version

class TestUpdateChecker(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(_parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(_parse_version("v2.8.5"), (2, 8, 5))
        self.assertEqual(_parse_version(""), (0,))
        self.assertEqual(_parse_version(None), (0,))

    def test_is_newer(self):
        self.assertTrue(_is_newer("2.8.6", "2.8.5"))
        self.assertTrue(_is_newer("2.9.0", "2.8.5"))
        self.assertTrue(_is_newer("10.0.0", "2.8.5"))
        self.assertFalse(_is_newer("2.8.5", "2.8.5"))
        self.assertFalse(_is_newer("2.8.4", "2.8.5"))
        self.assertFalse(_is_newer("2.8.5", "2.8.5")) # Same versions

    @patch('requests.get')
    def test_check_for_updates_available(self, mock_get):
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v2.8.6",
            "html_url": "https://github.com/Lord0fTurk/RenLocalizer/releases/tag/v2.8.6"
        }
        mock_get.return_value = mock_response

        result = check_for_updates("2.8.5")
        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "v2.8.6")
        self.assertEqual(result.release_url, "https://github.com/Lord0fTurk/RenLocalizer/releases/tag/v2.8.6")
        self.assertNil = result.error

    @patch('requests.get')
    def test_check_for_updates_up_to_date(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v2.8.5",
            "html_url": "https://github.com/Lord0fTurk/RenLocalizer/releases/tag/v2.8.5"
        }
        mock_get.return_value = mock_response

        result = check_for_updates("2.8.5")
        self.assertFalse(result.update_available)
        self.assertEqual(result.latest_version, "v2.8.5")

    @patch('requests.get')
    def test_check_for_updates_api_fallback_to_html(self, mock_get):
        # API fails, html parsing succeeds
        mock_api_response = MagicMock()
        mock_api_response.status_code = 404
        
        mock_html_response = MagicMock()
        mock_html_response.status_code = 200
        mock_html_response.text = 'href="/releases/tag/v2.8.6"'
        
        mock_get.side_effect = [mock_api_response, mock_html_response]

        result = check_for_updates("2.8.5")
        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "v2.8.6")

if __name__ == '__main__':
    unittest.main()
