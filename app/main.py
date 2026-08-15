import os
import sqlite3
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# LangGraph dependencies
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage

# Internal imports
from app.utils.llm import update_api_key
from app.utils.cache import clear_cache
from app.graph import workflow

# Load environment variables
load_dotenv()

# Initialize FastAPI
app = FastAPI(title="Price-Worthiness AI Agent (API)")

# Add CORS Middleware to allow requests from the Netlify frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For production, replace "*" with the Netlify URL
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connect SqliteSaver for LangGraph memory
conn = sqlite3.connect("checkpoints.sqlite", check_same_thread=False)
checkpointer = SqliteSaver(conn)

# Compile graph with checkpointer
agent_app = workflow.compile(checkpointer=checkpointer)

# Models
class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default_thread"

class ChatResponse(BaseModel):
    response: str

class ApiKeyRequest(BaseModel):
    api_key: str

# Routes
@app.get("/")
def read_root():
    return {"status": "Price-Worthiness API is running."}

@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
        
    config = {"configurable": {"thread_id": req.thread_id}}
    
    # We retrieve the current state if it exists
    state = agent_app.get_state(config)
    
    messages = []
    if state and state.values and "messages" in state.values:
        messages = state.values["messages"]
        
    # Append the new human message
    messages.append(HumanMessage(content=req.message))
    
    # Run the graph
    try:
        final_state = agent_app.invoke({"messages": messages}, config=config)
        verdict = final_state.get("verdict", "I'm sorry, I couldn't generate a verdict.")
        return ChatResponse(response=verdict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/update-api-key")
def update_api_key_endpoint(req: ApiKeyRequest):
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    
    try:
        update_api_key(req.api_key)
        return {"status": "success", "message": "API key updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clear-cache")
def clear_cache_endpoint():
    clear_cache()
    return {"status": "success", "message": "Cache cleared"}
