"""LangGraph 工作流共享状态定义。

遵循"报告式通信"原则 — 字段存储结构化摘要而非原始数据，
每个节点只消费和产出自己需要的子集，降低节点间耦合。
"""

from typing import Any, TypedDict


class KBState(TypedDict):
    """AI 知识库自动化工作流的全局共享状态。

    数据流：sources → analyses → articles
    审核循环：review_feedback → review_passed → iteration
    成本追踪：cost_tracker 贯穿全流程。
    """

    sources: list[dict[str, Any]]
    """采集到的原始数据条目列表（报告式摘要）。

    每条包含:
      title: str      — 项目/文章标题
      url: str        — 原始链接
      source: str     — 来源标识（github_trending / hacker_news / rss）
      popularity: int — 热度（Star 数 / 点数）
      summary: str    — 简短摘要（50 字内）
    """

    analyses: list[dict[str, Any]]
    """LLM 分析后的结构化结果列表（与 sources 一一对应）。

    每条包含:
      title: str        — 同源标题
      analysis:
        summary: str    — 中文分析摘要（150-200 字）
        highlights: list[str] — 1-3 个亮点
        score: int      — 综合评分 1-10
        tags: list[str] — 建议标签
    """

    articles: list[dict[str, Any]]
    """格式化、去重后的标准知识条目。

    每条符合 knowledge/articles/ 的 JSON schema:
      id: str         — 唯一标识
      title: str      — 标题
      source_url: str — 原文链接
      source_type: str— 来源类型
      summary: str    — 最终摘要
      tags: list[str] — 标签列表
      score: int      — 质量评分
      status: str     — 状态 (draft)
      created_at: str — ISO 8601 时间戳
      updated_at: str — ISO 8601 时间戳
    """

    review_feedback: str
    """Supervisor 的审核反馈意见。

    格式自由的文本，描述当前 analyses 或 articles 的质量问题，
    供上游节点在下一次迭代中参考改进。
    空字符串表示首次迭代或无需反馈。
    """

    review_passed: bool
    """审核是否通过。

    True  — 质量达标，工作流可进入下一阶段
    False — 需要重做（iteration < 3 时触发循环）
    """

    iteration: int
    """当前审核循环次数（从 1 开始）。

    每次 supervisor 节点运行后递增。
    超过 3 次时即使 review_passed=False 也强制进入下一阶段。
    """

    cost_tracker: dict[str, Any]
    """Token 用量与成本追踪摘要（报告式）。

    {                                                                    
      "total_calls": int,        -- LLM 调用总次数
      "total_tokens": int,       -- Token 总量
      "total_cost": float,       -- 预估总成本（元）
      "by_provider": {           -- 按 provider 汇总
        "deepseek": {"calls": int, "tokens": int, "cost": float},
        ...
      }
    }
    """
