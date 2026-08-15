import json
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.utils.llm import invoke_llm_with_retry
from app.utils.matching import evaluate_matches
from app.utils.cache import get_cached, set_cache
from app.tools.scrapers import scrape_all_sequential

class AgentState(TypedDict):
    messages: List[Any]
    product_name: str
    model: Optional[str]
    variant: Optional[str]
    user_price: Optional[float]
    is_ambiguous: bool
    needs_clarification: bool
    exact_results: List[Dict[str, Any]]
    exact_matches: List[Dict[str, Any]]
    found_exact: bool
    similar_results: List[Dict[str, Any]]
    found_similar: bool
    verdict: str

def parse_input(state: AgentState) -> AgentState:
    """Extract structured fields from user message."""
    messages = state.get('messages', [])
    if not messages:
        return state
        
    last_message = messages[-1].content
    
    # Simple check for pronouns to use previous state
    # A real implementation would use LLM for coreference resolution, but this is a simple rule.
    pronouns = ["it", "this", "that", "the one", "the product"]
    has_pronoun = any(p in last_message.lower() for p in pronouns)
    
    # If it has a pronoun and we have a previous product name, we don't need to re-parse from scratch
    # but we still want the LLM to extract any new info (like a new price).
    
    prompt = f"""
    You are an AI that extracts product information from user queries.
    Extract the following fields from this message and return ONLY valid JSON:
    - product_name: The full product name/brand (e.g., "Sony Headphones")
    - model: The specific model number if present (e.g., "WH-1000XM5")
    - variant: Color/storage/size if mentioned
    - user_price: Numeric price if provided, else null
    - is_ambiguous: boolean, true if the product description is too vague (e.g., just "headphones" or "a phone")
    
    Message: "{last_message}"
    
    Previous Product Context (if user used a pronoun): {state.get('product_name', 'None')} {state.get('model', '')}
    """
    
    # We use LLM to parse
    response = invoke_llm_with_retry(
        [SystemMessage(content="You return ONLY valid JSON."), HumanMessage(content=prompt)],
        temperature=0.0,
        max_tokens=500
    )
    
    try:
        # Strip backticks if present
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]
            
        parsed = json.loads(content)
        
        # Merge with existing state if pronoun used
        if has_pronoun and state.get('product_name') and not parsed.get('product_name'):
            parsed['product_name'] = state.get('product_name')
            parsed['model'] = parsed.get('model') or state.get('model')
            
        return {
            **state,
            "product_name": parsed.get("product_name", ""),
            "model": parsed.get("model", ""),
            "variant": parsed.get("variant", ""),
            "user_price": parsed.get("user_price"),
            "is_ambiguous": parsed.get("is_ambiguous", False),
            "needs_clarification": False,
            "exact_results": [],
            "exact_matches": [],
            "found_exact": False,
            "similar_results": [],
            "found_similar": False,
            "verdict": ""
        }
    except Exception as e:
        # Fallback if parsing fails
        return {**state, "is_ambiguous": True}

def search_exact(state: AgentState) -> AgentState:
    """Call scrapers with exact product name."""
    query = f"{state.get('product_name')} {state.get('model') or ''}".strip()
    
    # Check cache
    cached = get_cached("all", query)
    if cached:
        results = cached
    else:
        results = scrape_all_sequential(query)
        set_cache("all", query, results)
        
    return {**state, "exact_results": results}

def evaluate_results(state: AgentState) -> AgentState:
    """Evaluate matches using RapidFuzz."""
    results = state.get("exact_results", [])
    exact_m, similar_m, is_ambig = evaluate_matches(
        state.get("product_name", ""), 
        state.get("model", ""), 
        results
    )
    
    return {
        **state,
        "exact_matches": exact_m,
        "similar_results": similar_m,
        "found_exact": len(exact_m) > 0,
        "needs_clarification": is_ambig
    }

def route_decision(state: AgentState) -> str:
    """Conditional routing based on evaluation."""
    if state.get("is_ambiguous") or state.get("needs_clarification"):
        return "clarify"
    
    exact_count = len(state.get("exact_matches", []))
    if state.get("found_exact"):
        if exact_count >= 2:
            return "generate_verdict"
        else:
            return "generate_verdict_with_caution"
            
    return "search_similar"

def clarify(state: AgentState) -> AgentState:
    """Ask the user for clarification."""
    msg = "I need a bit more detail. Could you provide the specific model name or number?"
    return {**state, "verdict": msg}

def search_similar(state: AgentState) -> AgentState:
    """Broaden the search if no exact matches found."""
    # We already have similar matches from the first search
    similar = state.get("similar_results", [])
    
    # If still none, use LLM to suggest successors
    if not similar:
        prompt = f"""
        The user searched for {state.get('product_name')} {state.get('model', '')}.
        It appears to be discontinued or unavailable. 
        What is the direct successor or a highly similar current alternative model?
        Return ONLY the name of the alternative product.
        """
        response = invoke_llm_with_retry([HumanMessage(content=prompt)], temperature=0.2)
        successor = response.content.strip()
        
        cached = get_cached("all", successor)
        if cached:
            results = cached
        else:
            results = scrape_all_sequential(successor)
            set_cache("all", successor, results)
            
        exact_succ, similar_succ, _ = evaluate_matches(successor, "", results)
        similar = exact_succ + similar_succ
        
    return {**state, "similar_results": similar[:5], "found_similar": len(similar) > 0}

def generate_verdict(state: AgentState) -> AgentState:
    """Generate the final LLM verdict."""
    return _generate_llm_verdict(state, caution=False)

def generate_verdict_with_caution(state: AgentState) -> AgentState:
    """Generate verdict noting limited data."""
    return _generate_llm_verdict(state, caution=True)

def _generate_llm_verdict(state: AgentState, caution: bool) -> AgentState:
    user_query = f"{state.get('product_name')} {state.get('model') or ''} {state.get('variant') or ''}"
    user_price = state.get('user_price')
    exact_matches = state.get('exact_matches', [])
    similar = state.get('similar_results', [])
    
    prompt = f"""
    You are a Price-Worthiness AI Agent evaluating if a product is a good deal in India.
    User Query: {user_query}
    User Price: {user_price if user_price else 'Not provided'}
    
    Exact Matches Found: {json.dumps(exact_matches)}
    Similar/Alternative Products Found: {json.dumps(similar)}
    
    Caution Flag: {caution} (If True, only one exact match was found, so note limited data).
    
    Output a friendly, structured answer containing:
    1. A Markdown price comparison table (site, price, availability, rating).
    2. A verdict (worth it / overpriced / good deal / cannot judge).
    3. Reasoning.
    4. If there were errors on some sites, mention them.
    5. Always include source links in the table.
    
    If no exact matches were found, state that and present the alternatives.
    """
    
    response = invoke_llm_with_retry(
        [SystemMessage(content="You are a helpful shopping assistant."), HumanMessage(content=prompt)],
        temperature=0.0,
        max_tokens=800
    )
    
    return {**state, "verdict": response.content}

# Build the Graph
workflow = StateGraph(AgentState)

workflow.add_node("parse_input", parse_input)
workflow.add_node("search_exact", search_exact)
workflow.add_node("evaluate_results", evaluate_results)
workflow.add_node("clarify", clarify)
workflow.add_node("search_similar", search_similar)
workflow.add_node("generate_verdict", generate_verdict)
workflow.add_node("generate_verdict_with_caution", generate_verdict_with_caution)

workflow.set_entry_point("parse_input")
workflow.add_edge("parse_input", "search_exact")
workflow.add_edge("search_exact", "evaluate_results")

workflow.add_conditional_edges(
    "evaluate_results",
    route_decision,
    {
        "clarify": "clarify",
        "generate_verdict": "generate_verdict",
        "generate_verdict_with_caution": "generate_verdict_with_caution",
        "search_similar": "search_similar"
    }
)

workflow.add_edge("search_similar", "generate_verdict")
workflow.add_edge("clarify", END)
workflow.add_edge("generate_verdict", END)
workflow.add_edge("generate_verdict_with_caution", END)

# Note: We will bind the checkpointer when creating the app instance in main.py
