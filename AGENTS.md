# AI Knowledge Base Agent System

## 项目概述

自动化采集 GitHub Trending 和 Hacker News 上 AI/LLM/Agent 领域的技术动态，通过 LLM 分析提取关键信息并结构化存储为知识条目，最后推送到 Telegram / 飞书等多渠道，构建持续更新的 AI 知识库。

## 技术栈

| 类别       | 选型                        |
| ---------- | --------------------------- |
| 语言       | Python 3.12                 |
| Agent 框架 | OpenCode + 国产大模型       |
| 工作流编排 | LangGraph                   |
| 爬虫框架   | OpenClaw                    |

## 编码规范

- **风格**: PEP 8, `snake_case` 命名
- **文档**: Google 风格 docstring
- **日志**: 使用 `logging` 模块，禁止裸 `print()`
- **类型**: 所有函数必须标注类型注解
- **提交**: Conventional Commits（`feat:` / `fix:` / `chore:`）

## 项目结构

```
.opencode/
├── agents/          # Agent 定义文件（采集/分析/整理）
├── skills/          # OpenCode Skill 文件
└── package.json
knowledge/
├── raw/             # 爬虫原始数据（JSON）
└── articles/        # 分析后的知识条目（JSON）
```

## 知识条目 JSON 格式

```json
{
  "id": "uuid-v4",
  "title": "文章标题",
  "source_url": "原文链接",
  "source_type": "github_trending | hacker_news",
  "summary": "AI 生成的中文摘要（200字以内）",
  "tags": ["LLM", "Agent", "RAG"],
  "status": "pending | published | archived",
  "created_at": "2026-04-24T12:00:00+08:00",
  "updated_at": "2026-04-24T12:00:00+08:00"
}
```

## Agent 角色概览

| 角色     | 职责                     | 触发方式     | 输出                                |
| -------- | ------------------------ | ------------ | ----------------------------------- |
| 采集者   | 爬取 GitHub Trending / HN | 定时 / 手动  | `knowledge/raw/{source}_{timestamp}.json` |
| 分析者   | LLM 提取摘要与标签        | 新原始数据   | `knowledge/articles/{id}.json`      |
| 分发者   | 推送到 Telegram / 飞书    | 新知识条目   | 渠道消息 / 更新状态字段             |

## 红线（绝对禁止）

- 禁止将 API Key、Token 等敏感信息硬编码到代码中
- 禁止对原始数据源进行高频爬取（需遵守 robots.txt）
- 禁止在无人工审核的情况下自动分发高危 / 争议内容
- 禁止修改知识条目的 `id` 和 `created_at` 字段（一旦写入只读）
- 禁止在 Agent 之间产生循环触发
