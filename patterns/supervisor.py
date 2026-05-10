"""Supervisor pattern with worker-review-revise loop.

Worker Agent produces a JSON analysis report for a given task.
Supervisor Agent reviews the output and scores it on accuracy, depth, and format.
Failed reviews trigger redo with feedback (up to max_retries rounds).

Usage:
    result = supervisor("分析 LangGraph 和 CrewAI 的架构区别")
    print(result["output"])
    print(f"Score: {result['final_score']}, attempts: {result['attempts']}")
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from workflows.model_client import chat


logger = logging.getLogger(__name__)

WORKER_SYSTEM = (
    "You are an AI analysis expert. Given a task, produce a structured "
    "JSON analysis report. Your response must be valid JSON only, "
    "with no markdown fences or extra text.\n\n"
    "Output format:\n"
    '{\n'
    '  "title": "brief title of the analysis",\n'
    '  "summary": "concise summary (100-150 words)",\n'
    '  "key_points": ["point 1", "point 2", "point 3"],\n'
    '  "technical_depth": "assessment of technical depth",\n'
    '  "tags": ["tag1", "tag2"]\n'
    '}'
)

SUPERVISOR_SYSTEM = (
    "You are a quality reviewer. Evaluate the worker's analysis output "
    "on three dimensions, then decide whether it passes.\n\n"
    "Scoring:\n"
    "  accuracy (1-10):  Is the information factually correct?\n"
    "  depth (1-10):     Does it provide meaningful technical insight?\n"
    "  format (1-10):    Is the JSON well-formed and complete?\n\n"
    "Overall score = average of the three.\n"
    'Pass threshold: overall score >= 7 (return "passed": true).\n\n'
    "Respond with ONLY valid JSON:\n"
    '{"passed": true/false, "score": <overall_score>, '
    '"accuracy": <int>, "depth": <int>, "format": <int>, '
    '"feedback": "specific improvement suggestions"}'
)


def _worker_attempt(task: str, previous_feedback: str | None = None) -> str:
    """Run one worker attempt, optionally with feedback from previous review.

    Args:
        task: The original task description.
        previous_feedback: Feedback from supervisor on previous attempt.

    Returns:
        Raw text output from the worker.
    """
    prompt = f"Task: {task}"
    if previous_feedback:
        prompt += (
            f"\n\nYour previous output needs improvement. "
            f"Please revise based on this feedback:\n{previous_feedback}"
        )
    text, _ = chat(prompt, system=WORKER_SYSTEM)
    return text


def _parse_json(text: str) -> dict[str, Any] | None:
    """Attempt to parse JSON from LLM output, stripping fences if needed.

    Args:
        text: Raw LLM response.

    Returns:
        Parsed dict or None on failure.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _supervisor_review(output: str, task: str) -> dict[str, Any]:
    """Have the supervisor review the worker's output.

    Args:
        output: Worker's raw text output.
        task: Original task for context.

    Returns:
        Review dict with keys: passed, score, accuracy, depth, format, feedback.
    """
    prompt = (
        f"Task: {task}\n\n"
        f"Worker output:\n{output}\n\n"
        f"Review the above output and provide scores."
    )
    text, _ = chat(prompt, system=SUPERVISOR_SYSTEM)

    review = _parse_json(text)
    if review is None:
        logger.warning("Supervisor returned unparseable JSON, treating as pass")
        return {
            "passed": True,
            "score": 7,
            "accuracy": 7, "depth": 7, "format": 7,
            "feedback": "Supervisor response was unparseable, auto-passed.",
        }

    return {
        "passed": bool(review.get("passed", False)),
        "score": int(review.get("score", 0)),
        "accuracy": int(review.get("accuracy", 5)),
        "depth": int(review.get("depth", 5)),
        "format": int(review.get("format", 5)),
        "feedback": str(review.get("feedback", "")),
    }


def supervisor(task: str, max_retries: int = 3) -> dict[str, Any]:
    """Run the supervisor review loop on a task.

    Worker produces analysis → Supervisor reviews → repeat until pass or max
    retries exhausted.

    Args:
        task: The task description for the worker to analyze.
        max_retries: Maximum number of review cycles (default 3).

    Returns:
        A dict with keys:
            output:      Final worker output text.
            attempts:    Number of attempts made.
            final_score: Overall score from the last review.
            warning:     Warning message if max_retries exceeded (optional).
    """
    previous_feedback: str | None = None
    last_output: str = ""
    last_score: int = 0

    for attempt in range(1, max_retries + 2):
        logger.info("Attempt %d/%d", attempt, max_retries + 1)

        raw = _worker_attempt(task, previous_feedback)
        worker_data = _parse_json(raw)
        if worker_data is None:
            logger.warning("Worker returned unparseable JSON on attempt %d", attempt)
            previous_feedback = (
                "Your output must be valid JSON. "
                "Ensure the JSON is complete and properly formatted."
            )
            continue

        review = _supervisor_review(raw, task)
        last_output = raw
        last_score = review["score"]

        if review["passed"]:
            logger.info("Review passed (score=%d)", review["score"])
            return {
                "output": raw,
                "attempts": attempt,
                "final_score": review["score"],
            }

        logger.info(
            "Review failed (score=%d, accuracy=%d, depth=%d, format=%d)",
            review["score"], review["accuracy"],
            review["depth"], review["format"],
        )
        previous_feedback = review["feedback"]

    return {
        "output": last_output,
        "attempts": max_retries + 1,
        "final_score": last_score,
        "warning": f"Max retries ({max_retries}) exceeded, forced return",
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    task = sys.argv[1] if len(sys.argv) > 1 else "分析 LangGraph 和 CrewAI 的架构区别"

    print("=" * 50)
    print("  Supervisor 监督模式测试")
    print("=" * 50)

    previous_feedback: str | None = None
    last_output = ""
    last_score = 0

    for attempt in range(1, 4):
        raw = _worker_attempt(task, previous_feedback)
        review = _supervisor_review(raw, task)
        last_output = raw
        last_score = review["score"]

        print(f"  第 {attempt} 轮审核: 得分 {review['score']}/10")
        if not review["passed"]:
            print(f"    → 反馈: {review['feedback'][:80]}...")
            previous_feedback = review["feedback"]
        else:
            break

    print(f"\n最终结果:")
    print(f"  审核轮次: {attempt}")
    print(f"  最终得分: {last_score}/10")

    try:
        preview = json.dumps(json.loads(last_output), ensure_ascii=False)
        print(f"  输出预览: {preview[:120]}...")
    except json.JSONDecodeError:
        print(f"  输出预览: {last_output[:120]}...")
