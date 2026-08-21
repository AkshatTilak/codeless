"""Unit tests for consolidated multi-action tools (cron, task, worktree, mcp_resource, web)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from codeless.mcp.client import McpResourceInfo
from codeless.tools.base import ToolExecutionContext
from codeless.tools.cron_tool import CronTool, CronToolInput
from codeless.tools.mcp_resource_tool import McpResourceTool, McpResourceToolInput
from codeless.tools.task_tool import TaskTool, TaskToolInput
from codeless.tools.web_tool import WebTool, WebToolInput, _extract_structured_html
from codeless.tools.worktree_tool import WorktreeTool, WorktreeToolInput


@pytest.mark.asyncio
async def test_cron_tool_crud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test full CRUD operations on consolidated CronTool."""
    cron_file = tmp_path / "cron_jobs.json"
    monkeypatch.setattr("codeless.services.cron.get_cron_registry_path", lambda: cron_file)

    tool = CronTool()
    ctx = ToolExecutionContext(cwd=tmp_path)

    # 1. is_read_only
    assert tool.is_read_only(CronToolInput(action="list")) is True
    assert (
        tool.is_read_only(CronToolInput(action="create", name="x", schedule="* * * * *")) is False
    )
    assert tool.is_read_only(CronToolInput(action="delete", name="x")) is False
    assert tool.is_read_only(CronToolInput(action="toggle", name="x", enabled=False)) is False

    # 2. List empty
    res = await tool.execute(CronToolInput(action="list"), ctx)
    assert not res.is_error
    assert "No cron jobs configured" in res.output

    # 3. Create job
    res = await tool.execute(
        CronToolInput(action="create", name="backup", schedule="0 0 * * *", command="echo backup"),
        ctx,
    )
    assert not res.is_error
    assert "Created cron job 'backup'" in res.output

    # 4. List job
    res = await tool.execute(CronToolInput(action="list"), ctx)
    assert "backup" in res.output
    assert "[on]" in res.output

    # 5. Toggle job
    res = await tool.execute(CronToolInput(action="toggle", name="backup", enabled=False), ctx)
    assert not res.is_error
    assert "now disabled" in res.output

    # 6. Delete job
    res = await tool.execute(CronToolInput(action="delete", name="backup"), ctx)
    assert not res.is_error
    assert "Deleted cron job backup" in res.output


@pytest.mark.asyncio
async def test_task_tool_operations(tmp_path: Path):
    """Test background TaskTool actions: create, list, get, output, stop, update."""
    tool = TaskTool()
    ctx = ToolExecutionContext(cwd=tmp_path)

    # 1. is_read_only
    assert tool.is_read_only(TaskToolInput(action="list")) is True
    assert tool.is_read_only(TaskToolInput(action="get", task_id="t1")) is True
    assert tool.is_read_only(TaskToolInput(action="output", task_id="t1")) is True
    assert (
        tool.is_read_only(TaskToolInput(action="create", description="d", command="echo 1"))
        is False
    )
    assert tool.is_read_only(TaskToolInput(action="stop", task_id="t1")) is False
    assert tool.is_read_only(TaskToolInput(action="update", task_id="t1")) is False

    # 2. Create shell task
    res = await tool.execute(
        TaskToolInput(action="create", description="sample test", command="echo 'TEST_OUTPUT_123'"),
        ctx,
    )
    assert not res.is_error
    assert "Created task" in res.output
    task_id = res.output.split()[2]

    # 3. List tasks
    res = await tool.execute(TaskToolInput(action="list"), ctx)
    assert task_id in res.output

    # 4. Get task
    res = await tool.execute(TaskToolInput(action="get", task_id=task_id), ctx)
    assert not res.is_error
    assert task_id in res.output

    # 5. Update task
    res = await tool.execute(
        TaskToolInput(action="update", task_id=task_id, description="updated sample"), ctx
    )
    assert not res.is_error
    assert f"Updated task {task_id}" in res.output


@pytest.mark.asyncio
async def test_worktree_tool(tmp_path: Path):
    """Test WorktreeTool permissions and listing."""
    tool = WorktreeTool()
    ctx = ToolExecutionContext(cwd=tmp_path)

    assert tool.is_read_only(WorktreeToolInput(action="list")) is True
    assert tool.is_read_only(WorktreeToolInput(action="enter", branch="feat")) is False
    assert tool.is_read_only(WorktreeToolInput(action="exit", path="/some/path")) is False

    # List in non-git directory returns error gracefully
    res = await tool.execute(WorktreeToolInput(action="list"), ctx)
    assert res.is_error
    assert "git repository" in res.output


@pytest.mark.asyncio
async def test_mcp_resource_tool():
    """Test McpResourceTool list and read."""
    manager = MagicMock()
    manager.list_resources.return_value = [
        McpResourceInfo(
            server_name="srv1", uri="file:///data.txt", name="data", description="sample data"
        )
    ]
    manager.read_resource = AsyncMock(return_value="resource payload content")

    tool = McpResourceTool(manager)
    ctx = ToolExecutionContext(cwd=Path.cwd())

    assert tool.is_read_only(McpResourceToolInput(action="list")) is True
    assert (
        tool.is_read_only(
            McpResourceToolInput(action="read", server="srv1", uri="file:///data.txt")
        )
        is True
    )

    # List
    res = await tool.execute(McpResourceToolInput(action="list"), ctx)
    assert not res.is_error
    assert "srv1:file:///data.txt" in res.output

    # Read
    res = await tool.execute(
        McpResourceToolInput(action="read", server="srv1", uri="file:///data.txt"), ctx
    )
    assert not res.is_error
    assert "resource payload content" in res.output


@pytest.mark.asyncio
async def test_web_tool_structured_extraction():
    """Test HTML to Markdown and metadata extraction in WebTool."""
    html_doc = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sample Article Title</title>
        <meta name="description" content="This is an article description.">
    </head>
    <body>
        <header><nav><a href="/home">Home</a></nav></header>
        <main>
            <h1>Main Heading</h1>
            <p>Here is a paragraph with a <a href="https://example.com/guide">link to guide</a>.</p>
            <ul>
                <li>Point 1</li>
                <li>Point 2</li>
            </ul>
            <pre><code>print("hello world")</code></pre>
        </main>
        <footer><p>Footer notice</p></footer>
    </body>
    </html>
    """

    extracted = _extract_structured_html(
        html_doc, base_url="https://example.com/post", output_format="markdown"
    )
    assert extracted["title"] == "Sample Article Title"
    assert extracted["description"] == "This is an article description."
    assert "# Main Heading" in extracted["content"]
    assert "[link to guide](https://example.com/guide)" in extracted["content"]
    assert 'print("hello world")' in extracted["content"]
    assert "Footer notice" not in extracted["content"]
    assert "https://example.com/guide" in extracted["links"]

    # Test WebTool permissions & inputs
    web_tool = WebTool()
    assert web_tool.is_read_only(WebToolInput(action="crawl", url="https://example.com")) is True
    assert web_tool.is_read_only(WebToolInput(action="search", query="test")) is True
    assert web_tool.is_read_only(WebToolInput(action="fetch", url="https://example.com")) is True


@pytest.mark.asyncio
async def test_web_tool_crawl4ai_runner(monkeypatch: pytest.MonkeyPatch):
    """Test crawl4ai engine execution in WebTool."""
    from codeless.tools.web_tool import _run_crawl4ai

    # Test with mock AsyncWebCrawler
    mock_result = MagicMock()
    mock_result.markdown = "# Extracted via Crawl4AI\n\nArticle content here."
    mock_result.status_code = 200

    mock_crawler = AsyncMock()
    mock_crawler.__aenter__.return_value = mock_crawler
    mock_crawler.arun.return_value = mock_result

    monkeypatch.setattr("crawl4ai.AsyncWebCrawler", lambda *args, **kwargs: mock_crawler)

    res = await _run_crawl4ai("https://example.com", max_chars=1000)
    assert res is not None
    assert "Engine: crawl4ai" in res
    assert "Extracted via Crawl4AI" in res
