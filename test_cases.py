import asyncio
import sys
import codecs
from langchain_core.messages import HumanMessage
from app.graph import workflow

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())

async def run_test(message: str, description: str):
    print(f"\n{'='*50}")
    print(f"TEST: {description}")
    print(f"INPUT: {message}")
    print(f"{'='*50}")
    
    app = workflow.compile()
    
    config = {"configurable": {"thread_id": "test_thread"}}
    
    initial_state = {
        "messages": [HumanMessage(content=message)],
    }
    
    final_state = app.invoke(initial_state, config)
    
    print("\n--- STATE SUMMARY ---")
    print(f"Product: {final_state.get('product_name')} {final_state.get('model')}")
    print(f"Exact Matches: {len(final_state.get('exact_matches', []))}")
    print(f"Similar Matches: {len(final_state.get('similar_results', []))}")
    print("\n--- VERDICT ---")
    print(final_state.get('verdict', 'No verdict generated.'))


async def main():
    # Test 1: Exact match available
    await run_test("is the iPhone 15 128gb worth 65000 in india?", "Exact match available")
    
    # Test 2: No exact match, successor/alternative
    await run_test("Evaluate the price of iPhone 17 Pro 256GB at 150000 rupees", "No exact match, fallback to successor")

    # Test 3: Ambiguous query requiring clarification
    await run_test("are these headphones a good deal for 500?", "Ambiguous query")

if __name__ == "__main__":
    asyncio.run(main())
