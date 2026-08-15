import os
import time
import asyncio
from typing import Any
from langchain_groq import ChatGroq
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

# Global ChatGroq instance
_llm_instance: ChatGroq = None

def init_llm(api_key: str = None) -> ChatGroq:
    global _llm_instance
    if api_key:
        os.environ["GROQ_API_KEY"] = api_key
    
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY is not set.")
    
    # Using llama-3.3-70b-versatile as requested
    _llm_instance = ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.0,
        max_tokens=800,
        max_retries=0  # We handle retries via tenacity to have better control
    )
    return _llm_instance

def get_llm() -> ChatGroq:
    global _llm_instance
    if _llm_instance is None:
        init_llm()
    return _llm_instance

# Retry decorator for Groq API rate limits (HTTP 429)
@retry(
    wait=wait_exponential(multiplier=1, min=5, max=15),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
def invoke_llm_with_retry(messages: list, temperature: float = 0.0, max_tokens: int = 800) -> Any:
    llm = get_llm()
    llm.temperature = temperature
    llm.max_tokens = max_tokens
    return llm.invoke(messages)

def update_api_key(new_key: str):
    init_llm(new_key)
