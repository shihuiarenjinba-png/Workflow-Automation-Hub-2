"""Offline evidence that Blogger writes cannot be blindly re-sent by Google API."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from googleapiclient.errors import HttpError
from automation_hub.google_blogger import GoogleBloggerConnector, GoogleBloggerError


class BloggerMutationRetryTests(unittest.TestCase):
    @staticmethod
    def _make_connector() -> tuple[GoogleBloggerConnector, MagicMock]:
        connector = GoogleBloggerConnector.__new__(GoogleBloggerConnector)
        service = MagicMock()
        return connector, service

    def test_patch_uses_zero_http_retries(self) -> None:
        connector, service = self._make_connector()
        service.posts.return_value.patch.return_value.execute.return_value = {"id": "post-1"}
        with patch.object(connector, "_service", return_value=service):
            result = connector.patch_post_content("blog-1", "post-1", "<p>safe</p>")
        self.assertEqual(result, {"id": "post-1"})
        service.posts.return_value.patch.assert_called_once_with(
            blogId="blog-1", postId="post-1",
            body={"content": "<p>safe</p>"}, fetchBody=False,
        )
        service.posts.return_value.patch.return_value.execute.assert_called_once_with(num_retries=0)

    def test_http_503_never_becomes_a_hidden_second_update(self) -> None:
        connector, service = self._make_connector()
        request = service.posts.return_value.patch.return_value.execute
        response = MagicMock()
        response.status = 503
        response.reason = "Service Unavailable"
        request.side_effect = HttpError(response, b'{"error":{"message":"temporary failure"}}')
        with patch.object(connector, "_service", return_value=service):
            with self.assertRaises(GoogleBloggerError):
                connector.patch_post_content("blog-1", "post-1", "<p>test</p>")
        request.assert_called_once_with(num_retries=0)

    def test_read_only_listing_retains_retry(self) -> None:
        connector, service = self._make_connector()
        query = service.posts.return_value.list.return_value.execute
        query.return_value = {"items": [{"id": "post-1"}]}
        with patch.object(connector, "_service", return_value=service):
            posts = connector.list_posts("blog-1", max_posts=1)
        self.assertEqual(posts[0]["id"], "post-1")
        query.assert_called_once_with(num_retries=2)


if __name__ == "__main__":
    unittest.main()
