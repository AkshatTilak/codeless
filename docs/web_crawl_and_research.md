# Unified Web Search & Crawl Engine

Codeless includes a unified web research, crawling, and structured extraction engine powered by **Crawl4AI** and native HTTP scrapers. It allows agents to autonomously search online documentation, read public API specifications, and extract clean, token-efficient Markdown without UI noise.

---

## 1. Engine Capabilities

- **Deep Structured Crawling**: Leverages Crawl4AI to execute JavaScript, bypass basic overlays, and convert dynamic web pages into high-density Markdown.
- **Fast Text Reading**: Native HTTP reader for static documentation, batch scraping, and low-latency text extraction.
- **Search Synthesis**: Aggregates top search results across technical domains with automatic source URL citations.
- **Content Caching**: Caches fetched pages to prevent redundant network requests during a multi-turn session.

---

## 2. Agent Tools Reference

When an agent needs online context, it invokes these standard tools:

### `search_web`
Performs a search query and returns concise summaries with reference links:
```json
{
  "query": "FastAPI async lifespan context manager best practices",
  "domain": "fastapi.tiangolo.com"
}
```

### `read_url_content`
Fetches a web page and converts the HTML into clean GitHub-flavored Markdown:
```json
{
  "Url": "https://docs.pydantic.dev/latest/concepts/models/"
}
```

---

## 3. Workflow Prompts & Research Examples

### 1. Researching Latest Library APIs
```text
Search online for the latest Pydantic v2 migration guide for root_validator and update our models in src/models.py.
```

### 2. Autonomous Documentation Ingestion
```text
Crawl https://platform.openai.com/docs/guides/structured-outputs and summarize the JSON schema requirements in references/api/llm_schema.md.
```

### 3. Debugging Emerging Upstream Errors
```text
Search for GitHub issues related to 'uvicorn lifespan startup failure on windows asyncio' and suggest the appropriate event loop policy fix.
```

---

## 4. Configuration & Domain Filtering

You can customize web search preferences in your settings:
- Restrict search domains to trusted documentation sites.
- Configure custom API proxies or user-agent strings for restricted network environments.
