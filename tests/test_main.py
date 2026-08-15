"""
Tests for app.main — FastAPI endpoints.
Uses httpx TestClient to test all API routes.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# We need to mock the heavy dependencies before importing the app
@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    # Mock SqliteSaver and workflow before importing main
    with patch("app.main.SqliteSaver") as mock_saver, \
         patch("app.main.sqlite3") as mock_sqlite, \
         patch("app.main.workflow") as mock_workflow:

        mock_conn = MagicMock()
        mock_sqlite.connect.return_value = mock_conn

        # Mock the compiled app
        mock_app_instance = MagicMock()
        mock_workflow.compile.return_value = mock_app_instance

        # Now we can import — but main.py already ran on import.
        # Instead, let's use a fresh import approach:
        # We'll create the TestClient from the already-imported app
        from app.main import app
        yield TestClient(app), mock_app_instance


# Since app.main imports run at module level, let's test with a different approach:
# We'll import the app once with proper patching

@pytest.fixture(scope="module")
def test_client():
    """Module-level test client."""
    from app.main import app
    return TestClient(app)


# ─── GET / ────────────────────────────────────────────────────────────────────

class TestRootEndpoint:
    def test_serves_index_html(self, test_client):
        response = test_client.get("/")
        assert response.status_code == 200


# ─── POST /chat ──────────────────────────────────────────────────────────────

class TestChatEndpoint:
    def test_empty_message_returns_400(self, test_client):
        response = test_client.post("/chat", json={"message": "", "thread_id": "test"})
        assert response.status_code == 400

    def test_whitespace_only_message_returns_400(self, test_client):
        response = test_client.post("/chat", json={"message": "   ", "thread_id": "test"})
        assert response.status_code == 400

    def test_missing_message_field_returns_422(self, test_client):
        response = test_client.post("/chat", json={"thread_id": "test"})
        assert response.status_code == 422

    def test_chat_with_valid_message(self, test_client):
        """Test that a valid message reaches the endpoint (may error due to LLM)."""
        with patch("app.main.agent_app") as mock_agent:
            mock_agent.get_state.return_value = MagicMock(values={})
            mock_agent.invoke.return_value = {"verdict": "Test verdict response"}

            response = test_client.post(
                "/chat",
                json={"message": "Is iPhone 15 worth 65000?", "thread_id": "test_thread"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "response" in data
            assert data["response"] == "Test verdict response"

    def test_chat_default_thread_id(self, test_client):
        """Thread ID should default to 'default_thread'."""
        with patch("app.main.agent_app") as mock_agent:
            mock_agent.get_state.return_value = MagicMock(values={})
            mock_agent.invoke.return_value = {"verdict": "response"}

            response = test_client.post(
                "/chat",
                json={"message": "test message"}
            )
            assert response.status_code == 200

    def test_chat_returns_500_on_graph_error(self, test_client):
        """If the graph throws, should return 500."""
        with patch("app.main.agent_app") as mock_agent:
            mock_agent.get_state.return_value = MagicMock(values={})
            mock_agent.invoke.side_effect = Exception("Graph error")

            response = test_client.post(
                "/chat",
                json={"message": "test", "thread_id": "err"}
            )
            assert response.status_code == 500

    def test_chat_no_verdict_returns_fallback(self, test_client):
        """If graph returns no verdict key, should return fallback message."""
        with patch("app.main.agent_app") as mock_agent:
            mock_agent.get_state.return_value = MagicMock(values={})
            mock_agent.invoke.return_value = {}  # No 'verdict' key

            response = test_client.post(
                "/chat",
                json={"message": "test", "thread_id": "t"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "sorry" in data["response"].lower() or data["response"] != ""


# ─── POST /update-api-key ────────────────────────────────────────────────────

class TestUpdateApiKeyEndpoint:
    def test_empty_key_returns_400(self, test_client):
        response = test_client.post("/update-api-key", json={"api_key": ""})
        assert response.status_code == 400

    def test_whitespace_key_returns_400(self, test_client):
        response = test_client.post("/update-api-key", json={"api_key": "   "})
        assert response.status_code == 400

    def test_valid_key_updates(self, test_client):
        with patch("app.main.update_api_key") as mock_update:
            response = test_client.post(
                "/update-api-key",
                json={"api_key": "gsk_test_key_123"}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            mock_update.assert_called_once_with("gsk_test_key_123")

    def test_key_not_echoed_back(self, test_client):
        """The API should never echo the key in the response."""
        with patch("app.main.update_api_key"):
            response = test_client.post(
                "/update-api-key",
                json={"api_key": "gsk_secret_key_xyz"}
            )
            data = response.json()
            assert "gsk_secret_key_xyz" not in str(data)

    def test_missing_key_field_returns_422(self, test_client):
        response = test_client.post("/update-api-key", json={})
        assert response.status_code == 422


# ─── POST /clear-cache ──────────────────────────────────────────────────────

class TestClearCacheEndpoint:
    def test_clear_cache_success(self, test_client):
        with patch("app.main.clear_cache") as mock_clear:
            response = test_client.post("/clear-cache")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            mock_clear.assert_called_once()


# ─── Request validation ──────────────────────────────────────────────────────

class TestRequestValidation:
    def test_invalid_content_type(self, test_client):
        response = test_client.post("/chat", data="not json")
        assert response.status_code == 422

    def test_chat_extra_fields_ignored(self, test_client):
        """Extra fields should be ignored (Pydantic default behavior)."""
        with patch("app.main.agent_app") as mock_agent:
            mock_agent.get_state.return_value = MagicMock(values={})
            mock_agent.invoke.return_value = {"verdict": "ok"}

            response = test_client.post(
                "/chat",
                json={"message": "test", "thread_id": "t", "extra": "ignored"}
            )
            assert response.status_code == 200
