"""
Tests for app.utils.llm — LLM initialization, retry logic, and API key updates.
All LLM calls are mocked (no real API calls).
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.utils.llm import init_llm, get_llm, invoke_llm_with_retry, update_api_key, _llm_instance


@pytest.fixture(autouse=True)
def _reset_llm():
    """Reset the global LLM instance before each test."""
    import app.utils.llm as llm_mod
    llm_mod._llm_instance = None
    yield
    llm_mod._llm_instance = None


# ─── init_llm ─────────────────────────────────────────────────────────────────

class TestInitLlm:
    def test_init_with_explicit_key(self):
        """Should create a ChatGroq instance when given an API key."""
        with patch.dict(os.environ, {}, clear=False):
            llm = init_llm(api_key="test_key_123")
            assert llm is not None
            assert os.environ.get("GROQ_API_KEY") == "test_key_123"

    def test_init_with_env_key(self):
        """Should work when GROQ_API_KEY is already in environment."""
        with patch.dict(os.environ, {"GROQ_API_KEY": "env_key_456"}):
            llm = init_llm()
            assert llm is not None

    def test_init_raises_without_key(self):
        """Should raise ValueError when no key is available."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear GROQ_API_KEY if it exists
            os.environ.pop("GROQ_API_KEY", None)
            with pytest.raises(ValueError, match="GROQ_API_KEY"):
                init_llm()


# ─── get_llm ──────────────────────────────────────────────────────────────────

class TestGetLlm:
    def test_get_llm_initializes_if_none(self):
        """get_llm() should auto-initialize if no instance exists."""
        with patch.dict(os.environ, {"GROQ_API_KEY": "test_key"}):
            llm = get_llm()
            assert llm is not None

    def test_get_llm_returns_same_instance(self):
        """Should return the same instance on subsequent calls."""
        with patch.dict(os.environ, {"GROQ_API_KEY": "test_key"}):
            llm1 = get_llm()
            llm2 = get_llm()
            assert llm1 is llm2


# ─── invoke_llm_with_retry ────────────────────────────────────────────────────

class TestInvokeLlmWithRetry:
    @patch("app.utils.llm.get_llm")
    def test_successful_invocation(self, mock_get_llm):
        """Should return the LLM's response on success."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Test response"
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = invoke_llm_with_retry(
            [HumanMessage(content="Hello")],
            temperature=0.0,
            max_tokens=100
        )
        assert result.content == "Test response"
        mock_llm.invoke.assert_called_once()

    @patch("app.utils.llm.get_llm")
    def test_sets_temperature_and_max_tokens(self, mock_get_llm):
        """Should pass temperature and max_tokens to the LLM."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="ok")
        mock_get_llm.return_value = mock_llm

        invoke_llm_with_retry([HumanMessage(content="test")], temperature=0.5, max_tokens=200)
        assert mock_llm.temperature == 0.5
        assert mock_llm.max_tokens == 200

    @patch("app.utils.llm.get_llm")
    def test_retries_on_exception(self, mock_get_llm):
        """Should retry up to 3 times on failure, then reraise."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("Rate limit exceeded")
        mock_get_llm.return_value = mock_llm

        with pytest.raises(Exception, match="Rate limit exceeded"):
            invoke_llm_with_retry([HumanMessage(content="test")])

        # tenacity retries 3 times total
        assert mock_llm.invoke.call_count == 3


# ─── update_api_key ───────────────────────────────────────────────────────────

class TestUpdateApiKey:
    def test_update_key_changes_env(self):
        """update_api_key() should change the GROQ_API_KEY env var."""
        update_api_key("new_key_789")
        assert os.environ.get("GROQ_API_KEY") == "new_key_789"

    def test_update_key_creates_new_instance(self):
        """update_api_key() should reinitialize the LLM instance."""
        import app.utils.llm as llm_mod
        with patch.dict(os.environ, {"GROQ_API_KEY": "old_key"}):
            old_llm = get_llm()
            update_api_key("brand_new_key")
            new_llm = get_llm()
            # The instances should be different
            assert old_llm is not new_llm
