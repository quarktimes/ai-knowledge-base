"""LangGraph 工作流图定义。

线性流水线 + 审核循环：
  collect → analyze → organize → review
                                  ├── passed  → save → END
                                  └── failed  → organize (重做)
"""

import logging
import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from langgraph.graph import END, StateGraph

from workflows.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
from workflows.state import KBState


logger = logging.getLogger(__name__)


def _review_router(state: KBState) -> str:
    """审核结果路由：passed → save, failed → organize."""
    if state.get("review_passed", False):
        logger.info("[Router] review_passed=True → save")
        return "save"
    logger.info("[Router] review_passed=False → organize (iteration=%d)", state.get("iteration", 0))
    return "organize"


def build_graph() -> Any:
    """构建并编译 LangGraph 工作流。

    Returns:
        编译后的 StateGraph app，可通过 app.invoke() 执行。
    """
    graph = StateGraph(KBState)

    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    graph.set_entry_point("collect")

    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    graph.add_conditional_edges(
        "review",
        _review_router,
        {"save": "save", "organize": "organize"},
    )

    graph.add_edge("save", END)

    app = graph.compile()
    logger.info("[Graph] 工作流构建完成")
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    app = build_graph()

    initial: KBState = {
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "cost_tracker": {},
    }

    logger.info("[Main] 开始执行工作流")
    for step_output in app.stream(initial):
        for node_name, output in step_output.items():
            if node_name == "collect":
                count = len(output.get("sources", []))
                logger.info("[Main] collect → %d sources", count)
            elif node_name == "analyze":
                count = len(output.get("analyses", []))
                tracker = output.get("cost_tracker", {})
                cost = tracker.get("total_cost", 0) if isinstance(tracker, dict) else 0
                logger.info("[Main] analyze → %d analyses (cost=%.4f)", count, cost)
            elif node_name == "organize":
                count = len(output.get("articles", []))
                logger.info("[Main] organize → %d articles", count)
            elif node_name == "review":
                passed = output.get("review_passed", False)
                iteration = output.get("iteration", 0)
                logger.info("[Main] review → passed=%s (iteration=%d)", passed, iteration)
            elif node_name == "save":
                logger.info("[Main] save → 写入完成")

    logger.info("[Main] 工作流执行完毕")
