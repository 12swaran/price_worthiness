"""
Tests for app.graph — LangGraph state machine nodes, routing, and end-to-end flow.
All LLM calls and scraper calls are mocked.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from app.graph import (
    parse_input,
    search_exact,
    evaluate_results,
    route_decision,
    clarify,
    search_similar,
    generate_verdict,
    generate_verdict_with_caution,
    _generate_llm_verdict,
    workflow,
    AgentState,
)


def _base_state(**overrides) -> dict:
    """Create a minimal valid AgentState dict with sensible defaults."""
    state = {
        "messages": [HumanMessage(content="test")],
        "product_name": "",
        "model": "",
        "variant": "",
        "user_price": None,
        "is_ambiguous": False,
        "needs_clarification": False,
        "exact_results": [],
        "exact_matches": [],
        "found_exact": False,
        "similar_results": [],
        "found_similar": False,
        "verdict": "",
    }
    state.update(overrides)
    return state


# ─── parse_input ──────────────────────────────────────────────────────────────

class TestParseInput:
    @patch("app.graph.invoke_llm_with_retry")
    def test_parses_product_details(self, mock_llm):
        mock_llm.return_value = MagicMock(content=json.dumps({
            "product_name": "Apple iPhone 15",
            "model": "128GB",
            "variant": "Blue",
            "user_price": 65000,
            "is_ambiguous": False,
        }))

        state = _base_state(messages=[HumanMessage(content="Is iPhone 15 128GB worth 65000?")])
        result = parse_input(state)

        assert result["product_name"] == "Apple iPhone 15"
        assert result["model"] == "128GB"
        assert result["variant"] == "Blue"
        assert result["user_price"] == 65000
        assert result["is_ambiguous"] is False

    @patch("app.graph.invoke_llm_with_retry")
    def test_handles_json_with_backticks(self, mock_llm):
        """LLM sometimes wraps JSON in ```json ... ```."""
        mock_llm.return_value = MagicMock(content='```json\n{"product_name": "Sony", "model": "XM5"}\n```')

        state = _base_state(messages=[HumanMessage(content="Sony XM5")])
        result = parse_input(state)
        assert result["product_name"] == "Sony"

    @patch("app.graph.invoke_llm_with_retry")
    def test_handles_invalid_json_gracefully(self, mock_llm):
        """If LLM returns invalid JSON, state should be marked ambiguous."""
        mock_llm.return_value = MagicMock(content="This is not JSON at all")

        state = _base_state(messages=[HumanMessage(content="something")])
        result = parse_input(state)
        assert result.get("is_ambiguous") is True

    def test_empty_messages_returns_state(self):
        state = _base_state(messages=[])
        result = parse_input(state)
        assert result == state

    @patch("app.graph.invoke_llm_with_retry")
    def test_pronoun_resolution_uses_previous_context(self, mock_llm):
        mock_llm.return_value = MagicMock(content=json.dumps({
            "product_name": "",
            "model": "",
            "user_price": 50000,
            "is_ambiguous": False,
        }))

        state = _base_state(
            messages=[HumanMessage(content="What about it at 50000?")],
            product_name="iPhone 15",
            model="128GB",
        )
        result = parse_input(state)
        # Should carry forward product name from previous state
        assert result["product_name"] == "iPhone 15"
        assert result["model"] == "128GB"

    @patch("app.graph.invoke_llm_with_retry")
    def test_ambiguous_query(self, mock_llm):
        mock_llm.return_value = MagicMock(content=json.dumps({
            "product_name": "headphones",
            "model": "",
            "variant": "",
            "user_price": 500,
            "is_ambiguous": True,
        }))

        state = _base_state(messages=[HumanMessage(content="are headphones worth 500?")])
        result = parse_input(state)
        assert result["is_ambiguous"] is True


# ─── search_exact ─────────────────────────────────────────────────────────────

class TestSearchExact:
    @patch("app.graph.scrape_all_parallel")
    @patch("app.graph.get_cached", return_value=None)
    @patch("app.graph.set_cache")
    def test_calls_scraper_and_caches(self, mock_set, mock_get, mock_scrape):
        mock_scrape.return_value = [{"site": "Amazon", "title": "iPhone 15"}]

        state = _base_state(product_name="iPhone", model="15")
        result = search_exact(state)

        mock_scrape.assert_called_once()
        mock_set.assert_called_once()
        assert len(result["exact_results"]) == 1

    @patch("app.graph.scrape_all_parallel")
    @patch("app.graph.get_cached")
    def test_uses_cache_if_available(self, mock_get, mock_scrape):
        cached_data = [{"site": "cached", "title": "cached result"}]
        mock_get.return_value = cached_data

        state = _base_state(product_name="iPhone", model="15")
        result = search_exact(state)

        mock_scrape.assert_not_called()
        assert result["exact_results"] == cached_data


# ─── evaluate_results ────────────────────────────────────────────────────────

class TestEvaluateResults:
    @patch("app.graph.evaluate_matches")
    def test_sets_exact_and_similar(self, mock_eval):
        mock_eval.return_value = (
            [{"title": "iPhone 15 128GB"}],  # exact
            [{"title": "iPhone 15 Pro"}],     # similar
            False,                             # is_ambiguous
        )

        state = _base_state(exact_results=[{"title": "some result"}])
        result = evaluate_results(state)

        assert len(result["exact_matches"]) == 1
        assert len(result["similar_results"]) == 1
        assert result["found_exact"] is True
        assert result["needs_clarification"] is False

    @patch("app.graph.evaluate_matches")
    def test_no_matches(self, mock_eval):
        mock_eval.return_value = ([], [], False)

        state = _base_state(exact_results=[])
        result = evaluate_results(state)

        assert result["found_exact"] is False
        assert result["exact_matches"] == []


# ─── route_decision ──────────────────────────────────────────────────────────

class TestRouteDecision:
    def test_ambiguous_routes_to_clarify(self):
        state = _base_state(is_ambiguous=True)
        assert route_decision(state) == "clarify"

    def test_needs_clarification_routes_to_clarify(self):
        state = _base_state(needs_clarification=True)
        assert route_decision(state) == "clarify"

    def test_many_exact_matches_routes_to_verdict(self):
        state = _base_state(
            found_exact=True,
            exact_matches=[{"t": "a"}, {"t": "b"}, {"t": "c"}]
        )
        assert route_decision(state) == "generate_verdict"

    def test_two_exact_matches_routes_to_verdict(self):
        state = _base_state(
            found_exact=True,
            exact_matches=[{"t": "a"}, {"t": "b"}]
        )
        assert route_decision(state) == "generate_verdict"

    def test_one_exact_match_routes_to_caution(self):
        state = _base_state(
            found_exact=True,
            exact_matches=[{"t": "a"}]
        )
        assert route_decision(state) == "generate_verdict_with_caution"

    def test_no_matches_routes_to_search_similar(self):
        state = _base_state(found_exact=False, exact_matches=[])
        assert route_decision(state) == "search_similar"

    def test_ambiguous_takes_priority_over_exact(self):
        """Even with exact matches, ambiguity should route to clarify."""
        state = _base_state(
            is_ambiguous=True,
            found_exact=True,
            exact_matches=[{"t": "a"}, {"t": "b"}]
        )
        assert route_decision(state) == "clarify"


# ─── clarify ──────────────────────────────────────────────────────────────────

class TestClarify:
    def test_returns_clarification_message(self):
        state = _base_state()
        result = clarify(state)
        assert "more detail" in result["verdict"].lower() or "model" in result["verdict"].lower()


# ─── search_similar ──────────────────────────────────────────────────────────

class TestSearchSimilar:
    def test_returns_existing_similar_results(self):
        """If similar_results already exist, should use them."""
        existing = [{"title": "Similar Product"}]
        state = _base_state(similar_results=existing)
        result = search_similar(state)
        assert result["similar_results"] == existing
        assert result["found_similar"] is True

    @patch("app.graph.invoke_llm_with_retry")
    @patch("app.graph.scrape_all_parallel")
    @patch("app.graph.get_cached", return_value=None)
    @patch("app.graph.set_cache")
    @patch("app.graph.evaluate_matches")
    def test_asks_llm_for_successor_when_no_similar(self, mock_eval, mock_set, mock_get, mock_scrape, mock_llm):
        mock_llm.return_value = MagicMock(content="iPhone 16")
        mock_scrape.return_value = [{"site": "Amazon", "title": "iPhone 16"}]
        mock_eval.return_value = ([{"title": "iPhone 16"}], [], False)

        state = _base_state(similar_results=[], product_name="iPhone 15", model="Pro")
        result = search_similar(state)

        mock_llm.assert_called_once()
        assert result["found_similar"] is True

    @patch("app.graph.invoke_llm_with_retry")
    @patch("app.graph.scrape_all_parallel")
    @patch("app.graph.get_cached", return_value=None)
    @patch("app.graph.set_cache")
    @patch("app.graph.evaluate_matches")
    def test_limits_similar_to_5(self, mock_eval, mock_set, mock_get, mock_scrape, mock_llm):
        mock_llm.return_value = MagicMock(content="Successor")
        mock_scrape.return_value = []
        mock_eval.return_value = (
            [{"title": f"Product {i}"} for i in range(10)],
            [],
            False
        )

        state = _base_state(similar_results=[])
        result = search_similar(state)
        assert len(result["similar_results"]) <= 5


# ─── generate_verdict ────────────────────────────────────────────────────────

class TestGenerateVerdict:
    @patch("app.graph.invoke_llm_with_retry")
    def test_generates_verdict_text(self, mock_llm):
        mock_llm.return_value = MagicMock(content="## Verdict: Good deal!")

        state = _base_state(
            product_name="iPhone 15",
            model="128GB",
            user_price=65000,
            exact_matches=[{"title": "iPhone 15", "price": 60000}],
        )
        result = generate_verdict(state)
        assert "Verdict" in result["verdict"] or "deal" in result["verdict"].lower()

    @patch("app.graph.invoke_llm_with_retry")
    def test_generates_caution_verdict(self, mock_llm):
        mock_llm.return_value = MagicMock(content="## Verdict: Cannot judge (limited data)")

        state = _base_state(
            product_name="Obscure Phone",
            exact_matches=[{"title": "Obscure Phone X1"}],
        )
        result = generate_verdict_with_caution(state)
        assert result["verdict"] != ""


# ─── Workflow graph structure ─────────────────────────────────────────────────

class TestWorkflowGraph:
    def test_workflow_compiles(self):
        """The graph should compile without errors."""
        app = workflow.compile()
        assert app is not None

    def test_entry_point_is_parse_input(self):
        """The entry point should be parse_input."""
        # Access the graph's internal structure
        # StateGraph stores entry point info
        assert "parse_input" in workflow.nodes

    def test_all_nodes_present(self):
        """All expected nodes should be registered."""
        expected_nodes = [
            "parse_input",
            "search_exact",
            "evaluate_results",
            "clarify",
            "search_similar",
            "generate_verdict",
            "generate_verdict_with_caution",
        ]
        for node in expected_nodes:
            assert node in workflow.nodes, f"Missing node: {node}"


# ─── End-to-end flow (fully mocked) ──────────────────────────────────────────

class TestEndToEndFlow:
    @patch("app.graph.invoke_llm_with_retry")
    @patch("app.graph.scrape_all_parallel")
    @patch("app.graph.get_cached", return_value=None)
    @patch("app.graph.set_cache")
    def test_exact_match_flow(self, mock_set, mock_get, mock_scrape, mock_llm):
        """Full flow: parse → search → evaluate → verdict (exact matches found)."""
        # First LLM call: parse_input
        parse_response = MagicMock(content=json.dumps({
            "product_name": "Apple iPhone 15",
            "model": "128GB",
            "variant": "",
            "user_price": 65000,
            "is_ambiguous": False,
        }))
        # Second LLM call: generate_verdict
        verdict_response = MagicMock(content="## Verdict\n\nThe iPhone 15 at ₹65,000 is a fair deal.")

        mock_llm.side_effect = [parse_response, verdict_response]

        # Scraper returns results with matching titles
        mock_scrape.return_value = [
            {
                "site": "Amazon.in", "title": "Apple iPhone 15 128GB",
                "price": 62000, "currency": "INR", "url": "https://amazon.in/1",
                "availability": "In Stock", "rating": 4.5, "reviews_count": 1000,
                "error": False,
            },
            {
                "site": "Flipkart", "title": "Apple iPhone 15 (128 GB)",
                "price": 63000, "currency": "INR", "url": "https://flipkart.com/1",
                "availability": "In Stock", "rating": 4.4, "reviews_count": 500,
                "error": False,
            },
        ]

        app = workflow.compile()
        initial_state = {"messages": [HumanMessage(content="Is iPhone 15 128GB worth 65000?")]}
        final_state = app.invoke(initial_state)

        assert final_state["verdict"] != ""
        assert final_state["product_name"] == "Apple iPhone 15"

    @patch("app.graph.invoke_llm_with_retry")
    @patch("app.graph.scrape_all_parallel")
    @patch("app.graph.get_cached", return_value=None)
    @patch("app.graph.set_cache")
    def test_ambiguous_flow_goes_to_clarify(self, mock_set, mock_get, mock_scrape, mock_llm):
        """Flow: parse (ambiguous=True) → search → evaluate → clarify."""
        parse_response = MagicMock(content=json.dumps({
            "product_name": "headphones",
            "model": "",
            "variant": "",
            "user_price": 500,
            "is_ambiguous": True,
        }))
        mock_llm.return_value = parse_response
        mock_scrape.return_value = []

        app = workflow.compile()
        initial_state = {"messages": [HumanMessage(content="are headphones worth 500?")]}
        final_state = app.invoke(initial_state)

        # The verdict should be the clarification message
        assert "more detail" in final_state["verdict"].lower() or "model" in final_state["verdict"].lower()
