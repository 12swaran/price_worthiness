import json
import re
from html import escape
from datetime import datetime, timezone
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage

from app.utils.llm import invoke_llm_with_retry
from app.utils.matching import evaluate_matches
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
    simple_query = last_message.strip()
    if (re.fullmatch(r"[\w\s+./-]{2,100}", simple_query)
            and not re.search(r"\b(?:it|this|that|worth|price|cost|buy|under|compare|versus|vs|for|at)\b", simple_query, re.I)):
        # Plain product searches do not need an LLM to reinterpret the model name.
        return {
            **state, "product_name": simple_query, "model": "", "variant": "",
            "user_price": None, "is_ambiguous": False, "needs_clarification": False,
            "exact_results": [], "exact_matches": [], "found_exact": False,
            "similar_results": [], "found_similar": False, "verdict": ""
        }
    
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
    product = (state.get("product_name") or "").strip()
    model = (state.get("model") or "").strip()
    # The parser can put "17" in both fields; avoid searching "iPhone 17 17".
    query = product if not model or model.lower() in product.lower() else f"{product} {model}".strip()
    results = scrape_all_sequential(query) if query else []
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
    """Only show alternatives that were actually found on retailer pages."""
    similar = state.get("similar_results", [])[:5]
    return {**state, "similar_results": similar[:5], "found_similar": len(similar) > 0}

def generate_verdict(state: AgentState) -> AgentState:
    """Format the live retailer listings."""
    return _generate_llm_verdict(state, caution=False)

def generate_verdict_with_caution(state: AgentState) -> AgentState:
    """Format listings while noting limited data."""
    return _generate_llm_verdict(state, caution=True)

def _generate_llm_verdict(state: AgentState, caution: bool) -> AgentState:
    """Format observed prices directly so an LLM cannot invent prices or links."""
    user_query = f"{state.get('product_name')} {state.get('model') or ''} {state.get('variant') or ''}".strip()
    user_price = state.get('user_price')
    exact_matches = state.get('exact_matches', [])
    similar = state.get('similar_results', [])

    lines = [f"### Live listings for {escape(user_query)}"]
    if exact_matches:
        listings = exact_matches
    else:
        lines.append("I couldn't verify an exact listing with a price and product link right now.")
        listings = similar
        if listings:
            lines.append("These are related listings from the same search, not exact matches:")

    if listings:
        lines.extend(["", "| Store | Product | Price | Link |", "|---|---|---:|---|"])
        site_counts = {}
        for item in sorted(listings, key=lambda row: row["price"]):
            site = item["site"]
            if site_counts.get(site, 0) >= 4 or sum(site_counts.values()) >= 12:
                continue
            site_counts[site] = site_counts.get(site, 0) + 1
            title = escape(item["title"]).replace("|", "\\|").replace("\n", " ")
            lines.append(f'| {escape(site)} | {title} | ₹{item["price"]:,.0f} | [View product](<{item["url"]}>) |')

    try:
        offered_price = float(str(user_price).replace(",", "")) if user_price is not None else None
    except ValueError:
        offered_price = None

    if exact_matches and offered_price is not None:
        lowest = min(item["price"] for item in exact_matches)
        difference = offered_price - lowest
        if difference > 0:
            lines.append(f"\nYour offered price is ₹{difference:,.0f} above the lowest listing shown (₹{lowest:,.0f}).")
        else:
            lines.append(f"\nYour offered price is ₹{abs(difference):,.0f} at or below the lowest listing shown (₹{lowest:,.0f}).")
    elif exact_matches:
        lines.append("\nShare the price you're being offered if you want a direct comparison.")

    if caution:
        lines.append("Only one exact listing was found, so the price comparison is limited.")
    errors = [item["site"] for item in state.get("exact_results", []) if item.get("error")]
    if errors:
        lines.append(f"Searches unavailable for: {', '.join(dict.fromkeys(errors))}.")
    lines.append(f"Checked {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Prices may change; confirm on the retailer page.")
    return {**state, "verdict": "\n".join(lines)}

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
