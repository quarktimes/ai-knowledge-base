"""LangGraph 工作流节点函数。

每个节点是纯函数：接收 KBState，返回 dict（部分状态更新）。
5 个节点覆盖采集 → 分析 → 整理 → 审核 → 保存全流程。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workflows.model_client import accumulate_usage, chat, chat_json
from workflows.state import KBState


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ARTICLES_DIR = BASE_DIR / "knowledge" / "articles"

GITHUB_API = "https://api.github.com/search/repositories"
GITHUB_QUERY = "AI OR LLM OR Agent OR RAG in:name,description,topics"

ANALYZE_SYSTEM = (
    "You are an AI knowledge analyst. Given a tech item, produce a structured "
    "JSON analysis with these fields:\n"
    '  "summary": Chinese summary (150-200 chars) covering core value and use cases\n'
    '  "highlights": array of 1-3 key highlights in Chinese\n'
    '  "score": integer 1-10 (9-10=groundbreaking, 7-8=directly useful, 5-6=worth knowing, 1-4=low value)\n'
    '  "tags": array of 2-5 English tags from [LLM, Agent, RAG, Framework, Deployment, Automation, Multi-Agent, Coding, Platform, Tool, Open-Source, Memory, Reasoning, Search, Evaluation, Fine-Tuning, Multimodal, Voice, Document, Security, Testing, API, Workflow, MCP, Inference, Training]\n\n'
    "Respond with ONLY valid JSON, no markdown fences, no extra text."
)

ORGANIZE_FIX_SYSTEM = (
    "You are a knowledge base editor. Revise the following article based on "
    "the review feedback. Improve the summary, tags, and structure as needed.\n\n"
    "Respond with the COMPLETE updated JSON article (same schema), no markdown fences."
)

REVIEW_SYSTEM = (
    "You are a quality reviewer. Evaluate the articles on four dimensions:\n"
    "  summary_quality (1-10): accuracy, completeness, clarity of summaries\n"
    "  tag_accuracy (1-10):   relevance and precision of tags\n"
    "  classification (1-10): appropriateness of source type and scoring\n"
    "  consistency (1-10):    coherence across all articles\n\n"
    "Respond with ONLY valid JSON:\n"
    '{"passed": true/false, "overall_score": <float>, '
    '"scores": {"summary_quality": <int>, "tag_accuracy": <int>, '
    '"classification": <int>, "consistency": <int>}, '
    '"feedback": "specific improvement suggestions"}'
)


def _github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or None


def collect_node(state: KBState) -> dict[str, Any]:
    """调用 GitHub Search API 采集 AI 相关仓库。

    Args:
        state: 当前工作流状态。

    Returns:
        包含 sources 字段的部分状态更新。
    """
    logger.info("[CollectNode] 开始采集 GitHub 数据")

    query = GITHUB_QUERY
    encoded = urllib.parse.quote(query)
    url = f"{GITHUB_API}?q={encoded}&sort=stars&order=desc&per_page=10"

    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
    token = _github_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    sources: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        for repo in data.get("items", []):
            desc = repo.get("description") or ""
            sources.append({
                "title": repo["full_name"],
                "url": repo["html_url"],
                "source": "github_trending",
                "popularity": repo.get("stargazers_count", 0),
                "summary": desc.strip()[:200],
            })
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        logger.error("[CollectNode] GitHub API 请求失败: %s", e)

    logger.info("[CollectNode] 采集完成，共 %d 条", len(sources))
    return {"sources": sources}


def analyze_node(state: KBState) -> dict[str, Any]:
    """用 LLM 对每条数据生成中文摘要、标签、评分。

    Args:
        state: 当前工作流状态（需包含 sources）。

    Returns:
        包含 analyses 和 cost_tracker 的部分状态更新。
    """
    sources = state.get("sources", [])
    if not sources:
        logger.warning("[AnalyzeNode] 无数据可分析")
        return {"analyses": [], "cost_tracker": state.get("cost_tracker", {})}

    logger.info("[AnalyzeNode] 开始分析 %d 条数据", len(sources))

    analyses: list[dict[str, Any]] = []
    tracker = state.get("cost_tracker", {})

    for i, item in enumerate(sources):
        logger.info("[AnalyzeNode] 分析 [%d/%d]: %s", i + 1, len(sources), item["title"])
        prompt = (
            f"Title: {item['title']}\n"
            f"URL: {item['url']}\n"
            f"Source: {item['source']}\n"
            f"Description: {item.get('summary', '')[:200]}"
        )

        try:
            result, usage = chat_json(prompt, system=ANALYZE_SYSTEM)
            tracker = accumulate_usage(tracker, usage)
        except RuntimeError as e:
            logger.warning("[AnalyzeNode] 分析失败 [%d/%d]: %s", i + 1, len(sources), e)
            result = {}

        analyses.append({
            "title": item["title"],
            "analysis": {
                "summary": result.get("summary", item.get("summary", "")),
                "highlights": result.get("highlights", []),
                "score": result.get("score", 5),
                "tags": result.get("tags", []),
            },
        })

    logger.info("[AnalyzeNode] 分析完成，成功 %d/%d", len(analyses), len(sources))
    return {"analyses": analyses, "cost_tracker": tracker}


def organize_node(state: KBState) -> dict[str, Any]:
    """过滤低分条目、去重、按反馈修正。

    Args:
        state: 当前工作流状态（需包含 analyses）。

    Returns:
        包含 articles 和 cost_tracker 的部分状态更新。
    """
    analyses = state.get("analyses", [])
    if not analyses:
        logger.warning("[OrganizeNode] 无数据可整理")
        return {"articles": [], "cost_tracker": state.get("cost_tracker", {})}

    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    tracker = state.get("cost_tracker", {})

    logger.info(
        "[OrganizeNode] 开始整理 %d 条数据 (iteration=%d, has_feedback=%s)",
        len(analyses), iteration, bool(feedback),
    )

    seen_urls: set[str] = set()
    articles: list[dict[str, Any]] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    existing = _load_existing_article_urls()

    for item in analyses:
        analysis = item.get("analysis", {})
        score = analysis.get("score", 5)

        if score < 6:
            logger.debug("[OrganizeNode] 过滤低分条目: %s (score=%d)", item["title"], score)
            continue

        url = item.get("title", "")  # title used as URL key for dedup in sources
        source_item = _find_source(state.get("sources", []), item["title"])
        source_url = source_item.get("url", "") if source_item else ""
        source_type = source_item.get("source", "github_trending") if source_item else "github_trending"

        if source_url in seen_urls or source_url in existing:
            logger.debug("[OrganizeNode] 跳过重复: %s", item["title"])
            continue
        seen_urls.add(source_url)

        tags = list(analysis.get("tags", []))
        if "github" not in tags and source_type == "github_trending":
            tags.append("github")

        article = {
            "id": str(uuid.uuid4()),
            "title": item["title"],
            "source_url": source_url,
            "source_type": source_type,
            "summary": analysis.get("summary", ""),
            "tags": tags,
            "score": score,
            "status": "draft",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        articles.append(article)

    # 如有审核反馈，调用 LLM 做定向修正
    if iteration > 0 and feedback and articles:
        logger.info("[OrganizeNode] 根据审核反馈修正 %d 篇文章", len(articles))
        articles, tracker = _fix_articles(articles, feedback, tracker)

    logger.info("[OrganizeNode] 整理完成，共 %d 篇文章", len(articles))
    return {"articles": articles, "cost_tracker": tracker}


def _load_existing_article_urls() -> set[str]:
    if not ARTICLES_DIR.is_dir():
        return set()
    urls: set[str] = set()
    for fpath in ARTICLES_DIR.glob("*.json"):
        if fpath.name == "index.json":
            continue
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("source_url"):
                urls.add(data["source_url"])
        except (json.JSONDecodeError, OSError):
            continue
    return urls





def _find_source(sources: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    for s in sources:
        if s.get("title") == title:
            return s
    return None


def _fix_articles(
    articles: list[dict[str, Any]],
    feedback: str,
    tracker: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fixed: list[dict[str, Any]] = []
    for art in articles:
        prompt = (
            f"Original article:\n{json.dumps(art, ensure_ascii=False, indent=2)}\n\n"
            f"Review feedback:\n{feedback}\n\n"
            f"Return the complete updated JSON article."
        )
        try:
            result, usage = chat_json(prompt, system=ORGANIZE_FIX_SYSTEM)
            tracker = accumulate_usage(tracker, usage)
            if isinstance(result, dict) and result.get("title"):
                result["id"] = art["id"]
                result["created_at"] = art["created_at"]
                result["updated_at"] = timestamp = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S+00:00"
                )
                fixed.append(result)
                continue
        except RuntimeError:
            logger.warning("[OrganizeNode] 修正失败，保留原文: %s", art["title"])
        fixed.append(art)
    return fixed, tracker


def review_node(state: KBState) -> dict[str, Any]:
    """LLM 四维度审核文章质量。

    Args:
        state: 当前工作流状态（需包含 articles）。

    Returns:
        包含审核结果和 iteration 的部分状态更新。
    """
    articles = state.get("articles", [])
    if not articles:
        logger.warning("[ReviewNode] 无文章可审核")
        return {
            "review_feedback": "",
            "review_passed": True,
            "iteration": state.get("iteration", 0) + 1,
            "cost_tracker": state.get("cost_tracker", {}),
        }

    iteration = state.get("iteration", 0)
    tracker = state.get("cost_tracker", {})

    # iteration >= 2 强制通过
    if iteration >= 2:
        logger.info("[ReviewNode] 迭代次数 %d >= 2，强制通过", iteration)
        return {
            "review_feedback": "已超过最大迭代次数，自动通过",
            "review_passed": True,
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    logger.info("[ReviewNode] 开始审核 %d 篇文章 (iteration=%d)", len(articles), iteration)

    preview = "\n\n".join(
        f"--- Article {i + 1} ---\n{json.dumps(a, ensure_ascii=False, indent=2)}"
        for i, a in enumerate(articles)
    )
    prompt = f"Review the following articles:\n\n{preview}"

    try:
        result, usage = chat_json(prompt, system=REVIEW_SYSTEM)
        tracker = accumulate_usage(tracker, usage)

        scores = result.get("scores", {})
        overall = float(result.get("overall_score", 0))
        feedback = str(result.get("feedback", ""))
        passed = bool(result.get("passed", False))

        logger.info(
            "[ReviewNode] 得分: accuracy=%d, tags=%d, class=%d, consistency=%d, overall=%.1f",
            scores.get("summary_quality", 0),
            scores.get("tag_accuracy", 0),
            scores.get("classification", 0),
            scores.get("consistency", 0),
            overall,
        )
    except RuntimeError as e:
        logger.warning("[ReviewNode] 审核失败: %s", e)
        overall = 0
        feedback = ""
        passed = False

    return {
        "review_feedback": feedback,
        "review_passed": passed,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


def save_node(state: KBState) -> dict[str, Any]:
    """将 articles 写入 knowledge/articles/ 目录并更新索引。

    Args:
        state: 当前工作流状态（需包含 articles）。

    Returns:
        空 dict（纯副作用节点）。
    """
    articles = state.get("articles", [])
    if not articles:
        logger.warning("[SaveNode] 无文章可保存")
        return {}

    logger.info("[SaveNode] 开始保存 %d 篇文章", len(articles))

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    index_entries: list[dict[str, Any]] = []
    for art in articles:
        slug = art["title"].lower().strip()
        slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in slug)
        slug = slug.strip("-")[:80]
        date_part = art["created_at"][:10]
        filename = f"{date_part}-gh-{slug}.json"
        filepath = ARTICLES_DIR / filename

        filepath.write_text(
            json.dumps(art, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        index_entries.append({
            "id": art["id"],
            "title": art["title"],
            "source_url": art["source_url"],
            "filename": filename,
        })
        logger.debug("[SaveNode] 已保存: %s", filename)

    # 更新 index.json
    index_path = ARTICLES_DIR / "index.json"
    existing_index: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            existing_index = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(existing_index, list):
                existing_index = []
        except (json.JSONDecodeError, OSError):
            existing_index = []

    seen_ids = {e["id"] for e in existing_index}
    for entry in index_entries:
        if entry["id"] not in seen_ids:
            existing_index.append(entry)
            seen_ids.add(entry["id"])

    index_path.write_text(
        json.dumps(existing_index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("[SaveNode] 索引已更新: %s (%d 条)", index_path, len(existing_index))
    logger.info("[SaveNode] 保存完成，共 %d 篇文章", len(articles))
    return {}
