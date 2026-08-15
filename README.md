# Price-Worthiness AI Agent

A robust, multi-agent AI shopping assistant that evaluates whether a product is worth its price by scraping 5 major Indian e-commerce platforms (Amazon.in, Flipkart, Reliance Digital, Croma, Vijay Sales).

## Features
- **LangGraph Orchestration**: Complex state machine to handle exact matches, similarities, ambiguities, and caching.
- **LLM Powered**: Groq API (`llama-3.3-70b-versatile`) parses input and generates natural language verdicts.
- **Parallel Scraping**: Uses Playwright to scrape retailers simultaneously.
- **Fuzzy Matching**: Uses RapidFuzz to match product variants accurately.

## Installation

1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install Playwright browsers:
   ```bash
   playwright install chromium
   ```

4. Set up environment variables:
   Copy `.env.example` to `.env` and optionally set your `GROQ_API_KEY`. (You can also enter this in the UI).

## Running the Application

Start the FastAPI server using Uvicorn:

```bash
uvicorn app.main:app --reload
```

Open your browser and navigate to `http://127.0.0.1:8000`.

## Architecture Note
This application runs the synchronous Playwright API inside FastAPI `ThreadPoolExecutor` workers to avoid async conflicts and fulfill the "sync Playwright" requirement.
