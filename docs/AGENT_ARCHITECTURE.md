# Research OS — Agent & Workflow Architecture

> 本文档描述项目中所有 Agent、工具函数、系统提示词、工作流拓扑和数据流。
> 供快速理解系统逻辑、迭代升级和 debug 使用。
> 最后更新：2026-03-22

---

## 1. Agent 总览

### 1.1 正式 Agent 类

| Agent | 文件 | 领域 | LLM Tier | 触发方式 |
|-------|------|------|----------|---------|
| **PaperTagAgent** | `apps/worker/agents/paper_tag_agent.py` | 论文标签提取 (L1) | MEDIUM | research 阶段自动 / 入库时 |
| **PaperAnalysisAgent** | `apps/worker/agents/paper_analysis_agent.py` | 论文深度分析 (L2) | HIGH | 用户手动触发 |
| **Mode Router** | `apps/worker/modes/router.py` | 意图分类 | 无 (规则) | run 创建时 |

### 1.2 隐式 Agent（LLM 节点函数）

每个 mode graph 节点函数 = 一个隐式 agent（system prompt + LLM 调用 + 结果解析）。

| 模式 | 节点数 | LLM 调用节点数 | 文件 |
|------|:---:|:---:|------|
| Atlas (A) | 8 | 5 | `apps/worker/modes/atlas.py` |
| Frontier (B) | 7 | 5 | `apps/worker/modes/frontier.py` |
| Divergent (C) | 7 | 5 | `apps/worker/modes/divergent.py` |
| Review (X) | 3 | 2 | `apps/worker/modes/review.py` |

---

## 2. 所有系统提示词

### 2.1 Atlas Mode (5 prompts)

| 变量名 | 节点函数 | 用途 | 输出 JSON keys |
|--------|---------|------|---------------|
| `_ATLAS_PLAN_SYSTEM` | `plan_atlas` | 规划领域探索范围 | domain_boundaries, sub_directions, aliases, queries |
| `_TIMELINE_SYSTEM` | `build_timeline` | 构建研究时间线 | timeline[{year, title, significance, phase}] |
| `_TAXONOMY_SYSTEM` | `build_taxonomy` | 构建分类树 | root_label, views{by_method, by_task, by_modality}, mindmap |
| `_READING_PATH_SYSTEM` | `generate_reading_path` | 生成阅读路径 | learning_goals, reading_path[{paper_id, reason, difficulty, week}] |
| `_ATLAS_SYNTHESIS_SYSTEM` | `synthesize_atlas` | 综合生成领域地图 | atlas_markdown, mindmap, mode_b_entry_points |

### 2.2 Frontier Mode (5 prompts)

| 变量名 | 节点函数 | 用途 | 输出 JSON keys |
|--------|---------|------|---------------|
| `_SCOPE_SYSTEM` | `scope_definition` | 定义子领域边界 | definition, exclusions, venue_whitelist, benchmark_list, query_templates |
| `_SCOPE_PRUNING_SYSTEM` | `scope_pruning` | 论文相关性评分 | scores[{paper_id, relevance, keep}], method_groups, warnings |
| `_COMPARISON_SYSTEM` | `comparison_build` | 方法对比矩阵 | methods[{name, innovation, datasets}], benchmark_panel |
| `_PAIN_MINING_SYSTEM` | `pain_mining` | 痛点提取 | pain_points[{statement, pain_type, severity}], future_work |
| `_FRONTIER_SUMMARY_SYSTEM` | `frontier_summary` | 前沿总结 | frontier_markdown, key_findings, entry_points, pain_point_package |

### 2.3 Divergent Mode (5 prompts)

| 变量名 | 节点函数 | 用途 | 输出 JSON keys |
|--------|---------|------|---------------|
| `_NORMALIZE_PAIN_SYSTEM` | `normalize_pain_package` | 痛点抽象为问题签名 | problem_signatures[{task, input_modality, failure_modes}] |
| `_ANALOGICAL_RETRIEVAL_SYSTEM` | `analogical_retrieval` | 跨领域检索查询生成 | queries[{query, target_domain}], search_strategy |
| `_METHOD_TRANSFER_SYSTEM` | `method_transfer_screening` | 方法迁移评估 | [{external_method, transfer_feasibility, failed_assumptions}] |
| `_FEASIBILITY_SYSTEM` | `feasibility_review` | 实验可行性评估 | [{data_available, compute_reasonable, go_no_go}] |
| `_IDEA_PORTFOLIO_SYSTEM` | `idea_portfolio` | 创新点排序 | ranked_ideas, portfolio_summary, recommended_next_steps |

### 2.4 Review Mode (2 prompts)

| 变量名 | 节点函数 | 用途 |
|--------|---------|------|
| `_REFINE_SYSTEM` | `refine_output` | 报告精修 |
| `_EXPORT_SYSTEM` | `export_results` | 导出生成 (Markdown/JSON/BibTeX) |

### 2.5 独立 Agent (2 prompts)

| 变量名 | Agent 类 | 用途 |
|--------|---------|------|
| `TAG_SYSTEM_PROMPT` | `PaperTagAgent` | L1 标签提取 (field/keywords/methods/paragraph_tags) |
| `ANALYSIS_SYSTEM_PROMPT` | `PaperAnalysisAgent` | L2 深度分析 (motivation/math/experiments/review) |

### 2.6 共享模板 (10 prompts in `libs/prompts/templates.py`)

| PromptName | 用途 | 调用者 |
|-----------|------|--------|
| `PLANNER` | 研究计划分解 | atlas `plan_atlas`, frontier `scope_definition` |
| `CLAIM_EXTRACTION` | 论文断言提取 | `base.py:extract_claims()` |
| `PAPER_SUMMARY` | 论文结构化阅读卡 | `base.py:resolve_and_read_paper()` |
| `CONTRADICTION_JUDGE` | 断言关系判断 | divergent 模式 |
| `INNOVATION_GENERATION` | 创新假设生成 | divergent `idea_composition` |
| `VERIFIER` | 假设验证/批判 | divergent `prior_art_check` |
| `QUERY_REWRITE` | 学术搜索查询生成 | 各模式检索阶段 |
| `CLUSTER_LABELING` | 论文簇标签生成 | atlas/frontier 分析阶段 |
| `GAP_ANALYSIS` | 研究空白识别 | frontier `pain_mining` |
| `REPORT_GENERATION` | 研究报告编译 | review `export_results` |

**总计：23 个系统提示词**

---

## 3. 工具函数清单 (Deterministic, No LLM)

### 3.1 学术搜索

| 函数 | 文件 | 输入 → 输出 |
|------|------|------------|
| `search_academic_sources()` | `modes/base.py` | (topic, queries) → (ids, queries, errors, title_map) |
| `rerank_search_results()` | `modes/base.py` | (query, titles, ids) → reranked_ids |

### 3.2 论文解析

| 函数 | 文件 | 输入 → 输出 |
|------|------|------------|
| `resolve_and_read_paper()` | `modes/base.py` | (pid, gateway) → (summary, claims, cost, errors) |
| `extract_claims()` | `modes/base.py` | (title, text, gateway) → claims[] |
| `parse_paper()` | `services/parser/__init__.py` | (identifier) → ParsedPaper |
| `get_arxiv_latex_source()` | `services/parser/arxiv_source.py` | (arxiv_id) → (main_tex, dir, files) |

### 3.3 向量 & 重排序

| 函数 | 文件 | 输入 → 输出 |
|------|------|------------|
| `embed_paper_chunks()` | `services/library/tools_embedding.py` | texts[] → vectors[](1024-dim) |
| `rerank_papers()` | `services/library/tools_embedding.py` | (query, docs) → [{index, score}] |

### 3.4 论文库

| 函数 | 文件 | 输入 → 输出 |
|------|------|------------|
| `insert_library_paper()` | `services/library/tools_db.py` | data → row |
| `search_library_vectors()` | `services/library/tools_db.py` | (embedding, limit) → papers[] |
| `search_library_text()` | `services/library/tools_db.py` | (query, limit) → papers[] |
| `library_prefetch()` | `services/library/prefetch.py` | (topic, keywords) → library_seeds[] |

### 3.5 LLM 基础设施

| 函数 | 文件 | 说明 |
|------|------|------|
| `gateway.chat()` | `llm_gateway.py` | 原始 LLM 调用 |
| `gateway.chat_json()` | `llm_gateway.py` | JSON 输出 (structured output + prompt fallback) |
| `gateway.chat_structured()` | `llm_gateway.py` | Pydantic model 输出 (LangChain function calling) |

---

## 4. 工作流拓扑

### 4.1 总体执行流

```
用户创建 Run → Redis Queue → Worker Runner
    ↓
_execute_run():
    1. get_run() from DB
    2. determine mode
    3. library_prefetch() → library_seeds
    4. _run_mode_graph(mode, ..., library_seeds)
         ├─ atlas:    8 节点 StateGraph
         ├─ frontier: 7 节点 StateGraph (可循环)
         ├─ divergent: 7 节点 StateGraph
         └─ review:   3 节点 StateGraph
    5. _persist_results() → pain_points + papers + context_bundle → DB
    6. publish events
```

### 4.2 Frontier 详细流

```
scope_definition → candidate_retrieval → [check] → scope_pruning
    → deep_reading → [check] → comparison_build → pain_mining
    → [loop?] → frontier_summary → END

deep_reading 内部 (5 并发):
    resolve_and_read_paper()
        → 解析 LaTeX/GROBID
        → LLM 摘要 (PAPER_SUMMARY)
        → LLM 断言提取 (CLAIM_EXTRACTION)
        → PaperTagAgent (L1 标签)
```

### 4.3 论文入库流

```
Research Results 页面
    ↓ 用户点击 "Add to Library"
POST /library/papers {title, arxiv_id, paper_tags?}
    ├─ 有 paper_tags? → 直接复用 (零 token 消耗) → light_analyzed
    ├─ 有 arxiv_id? → 下载 LaTeX → PaperTagAgent → light_analyzed
    └─ 都没有? → light_analyzed (无标签)

Library 详情页
    ↓ 用户点击 "Run Deep Analysis"
POST /library/papers/{id}/analyze
    → 读取 LaTeX/raw → PaperAnalysisAgent → deep_analyzed
```

---

## 5. 文件结构

```
apps/worker/
├── agents/                        # 正式 Agent 类
│   ├── __init__.py
│   ├── paper_tag_agent.py         # L1: 标签提取 (TAG_SYSTEM_PROMPT)
│   └── paper_analysis_agent.py    # L2: 深度分析 (ANALYSIS_SYSTEM_PROMPT)
├── modes/                         # 模式图 + 隐式 Agent 节点
│   ├── base.py                    # 共享: ModeGraphState, 工具函数, emit_progress
│   ├── router.py                  # Mode 0: 意图分类 (规则, 无 LLM)
│   ├── atlas.py                   # Mode A: 8 节点, 5 prompts
│   ├── frontier.py                # Mode B: 7 节点, 5 prompts
│   ├── divergent.py               # Mode C: 7 节点, 5 prompts
│   └── review.py                  # Mode X: 3 节点, 2 prompts
├── llm_gateway.py                 # LLM 调用层 (chat/chat_json/chat_structured)
├── runner.py                      # Worker 编排器
└── task_queue.py                  # Redis 队列

libs/prompts/
└── templates.py                   # 10 个共享 prompt 模板

services/
├── library/                       # 论文库工具 (deterministic)
│   ├── tools_db.py                # DB CRUD + 向量搜索
│   ├── tools_embedding.py         # Tongyi embedding + rerank
│   ├── tools_storage.py           # 文件存储 (/data/)
│   └── prefetch.py                # library_prefetch
├── embedding.py                   # Tongyi EmbeddingService
├── parser/                        # LaTeX/GROBID 解析
│   ├── __init__.py                # parse_paper()
│   ├── latex_parser.py            # LaTeX → ParsedPaper
│   ├── arxiv_source.py            # arXiv 源码下载
│   └── grobid_client.py           # GROBID PDF 解析
├── storage.py                     # MinIO/本地存储
└── export.py                      # 报告导出
```

---

## 6. 快速 Debug 指南

```bash
# 查看 run 的所有进度事件
curl -s http://localhost:8000/api/v1/runs/{id}/events?limit=100 | python3 -c "
import sys,json
for e in reversed(json.load(sys.stdin)['events']):
    if e['event_type'].startswith('progress.'):
        print(f'{e[\"payload\"].get(\"action\",\"?\"):15s} {e[\"payload\"].get(\"message\",\"\")[:70]}')
"

# 查看 LLM 调用日志
grep "structured_output\|llm_call_complete\|json_parse" /tmp/ros-worker.log | tail -20

# 查看论文库状态
curl -s http://localhost:8000/api/v1/library/stats

# 查看 API 错误
tail -20 /tmp/ros-api.log | grep "error\|ERROR\|500"
```
