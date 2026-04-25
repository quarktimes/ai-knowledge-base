# Memory 对 AI 生成代码的影响对比

> 对比维度：命名风格、docstring、日志方式、错误处理、文件位置
>
> 示例场景：实现一个获取 GitHub 仓库信息的工具函数

## 对比表格

| 维度 | 无 Memory（每次独立生成） | 有 Memory（基于项目上下文） |
|------|--------------------------|----------------------------|
| **命名风格** | `fetchRepoData()`、`get_info_from_github()` — 混用 camelCase 和 snake_case，风格不统一 | `get_repo_info()` — 始终遵循项目已有的 `snake_case` 约定 + PEP 8 |
| **Docstring** | 缺乏 docstring，或使用 `# 注释` 简单说明 | Google 风格 docstring，包含完整的 `Args:` / `Returns:` / `Raises:` 章节 |
| **日志方式** | 使用 `print()` 或 `print(f"...")` 输出调试信息 | 使用 `logging` 模块：`logger.info()`、`logger.warning()`、`logger.error()` |
| **错误处理** | `try/except Exception as e: print(e)` — 笼统捕获，静默吞掉异常 | 精确区分 HTTP 状态码（403/404/200），对每种错误返回不同日志级别和返回值 |
| **文件位置** | 随意放置在入口文件或 `main.py` 中 | 按照项目结构放入 `utils/github_api.py`，与现有模块布局一致 |

## 结论

有 Memory 生成的代码在**一致性**和**可维护性**上有显著优势。以本项目为例，无 Memory 时每次生成的代码可能混用命名风格（camelCase vs snake_case）、缺少文档和类型注解、依赖 `print()` 调试、粗粒度错误处理。而有 Memory 时，AI 能够感知项目已有约定（`AGENTS.md` 中的 PEP 8、Google docstring、logging 规范等），生成的代码与项目现有风格浑然一体，无需二次重构即可纳入代码库。长期来看，Memory 机制是保持代码库整洁、减少技术债的关键基础设施。
