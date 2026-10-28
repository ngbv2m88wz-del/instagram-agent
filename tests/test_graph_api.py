import pytest

from instagram_agent.config import Settings
from instagram_agent.graph_api import GraphAPIError, InstagramGraphClient


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def make_client(responses):
    session = FakeSession(responses)
    settings = Settings(access_token="TOKEN", account_id="123")
    return InstagramGraphClient(settings, session=session), session


def test_profile_request():
    client, session = make_client([FakeResponse({"id": "123", "username": "me"})])
    assert client.get_profile()["username"] == "me"
    url, params = session.calls[0]
    assert url == "https://graph.facebook.com/v23.0/123"
    assert params["access_token"] == "TOKEN"
    assert "followers_count" in params["fields"]


def test_media_follows_pagination_and_limit():
    client, session = make_client([
        FakeResponse({"data": [{"id": "1"}, {"id": "2"}], "paging": {"next": "https://next/page"}}),
        FakeResponse({"data": [{"id": "3"}, {"id": "4"}]}),
    ])
    assert [m["id"] for m in client.iter_media(limit=3)] == ["1", "2", "3"]
    assert session.calls[1] == ("https://next/page", None)


def test_media_insights_uses_metrics_for_type():
    client, session = make_client([FakeResponse({"data": [
        {"name": "reach", "values": [{"value": 10}]},
        {"name": "views", "total_value": {"value": 25}},
    ]})])
    insights = client.get_media_insights({"id": "9", "media_product_type": "REELS"})
    assert insights == {"reach": 10, "views": 25}
    url, params = session.calls[0]
    assert url.endswith("/9/insights")
    assert "ig_reels_avg_watch_time" in params["metric"]


def test_error_is_raised():
    client, _ = make_client([FakeResponse(
        {"error": {"message": "Invalid OAuth access token", "type": "OAuthException", "code": 190}},
        status=400,
    )])
    with pytest.raises(GraphAPIError) as exc:
        client.get_profile()
    assert exc.value.code == 190
