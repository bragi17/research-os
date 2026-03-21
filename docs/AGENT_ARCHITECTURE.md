# Research OS — Agent & Workflow Architecture

> 本文档描述项目中所有 Agent、工具函数、工作流拓扑、数据流和领域边界。
> 供快速理解系统逻辑、迭代升级和 debug 使用。

---

## 1. Agent 清单

### 1.1 正式 Agent（有独立类定义）

| Agent | 文件 | 领域 | 输入 | 输出 | 调用的工具 |
|-------|------|------|------|------|-----------|
| **PaperTagAgent** | `apps/worker/agents/paper_tag_agent.py` | 论文分析 | `paper_text: str`, `metadata: dict` | `PaperTagResult` (field, sub_field, keywords, methods, datasets, benchmarks, paragraph_tags) | `gateway.chat_structured()` |
| **Mode Router** | `apps/worker/modes/router.py` | 意图分类 | `user_input: str` | `ResearchMode` enum | 无 (纯规则匹配) |

### 1.2 隐式 Agent（节点函数内嵌 LLM 调用）

每个 mode graph 的节点函数实际上是一个"隐式 Agent"——它包含 system prompt + LLM 调用 + 结果解析。

#### Atlas Mode (Mode A) — 8 节点

| 节点 | LLM Tier | 功能 | 工具调用 |
|------|----------|------|---------|
| `plan_atlas` | HIGH | 规划领域探索范围 | 无 |
| `retrieve_classics` | — | 搜索经典+代表论文 | `search_academic_sources()` |
| `build_timeline` | MEDIUM | 构建研究时间线 | 无 |
| `build_taxonomy` | HIGH | 构建分类树 (方法/任务/模态) | 无 |
| `read_representatives` | HIGH | 深度阅读代表论文 | `resolve_and_read_paper()` → `PaperTagAgent` |
| `extract_figures` | — | 提取关键图示 (存根) | 无 |
| `generate_reading_path` | MEDIUM | 生成分层阅读路径 | 无 |
| `synthesize_atlas` | HIGH | 综合生成领域地图 | 无 |

#### Frontier Mode (Mode B) — 7 节点

| 节点 | LLM Tier | 功能 | 工具调用 |
|------|----------|------|---------|
| `scope_definition` | HIGH | 定义子领域边界和约束 | 无 |
| `candidate_retrieval` | — | 多源搜索 + 引用链扩展 + rerank | `search_academic_sources()`, `rerank_search_results()`, `S2.get_citations/references()` |
| `scope_pruning` | MEDIUM | LLM 相关性评分 + 方法多样性 | 无 |
| `deep_reading` | HIGH | 并行阅读论文 (5并发) | `resolve_and_read_paper()` × N (asyncio.gather) |
| `comparison_build` | HIGH | 生成方法对比矩阵 | 无 |
| `pain_mining` | HIGH+MED | 提取痛点 + gap 分析 | 无 |
| `frontier_summary` | HIGH | 生成前沿总结 + 入口建议 | 无 |

#### Divergent Mode (Mode C) — 7 节点

| 节点 | LLM Tier | 功能 | 工具调用 |
|------|----------|------|---------|
| `normalize_pain_package` | HIGH | 痛点标准化为问题签名 | 无 |
| `analogical_retrieval` | MEDIUM | 跨领域类比检索 | `search_academic_sources()` |
| `method_transfer_screening` | HIGH | 评估方法迁移可行性 | 无 |
| `idea_composition` | HIGH | 生成创新 idea cards | 无 |
| `prior_art_check` | HIGH | 反查已有工作 | `search_academic_sources()` |
| `feasibility_review` | HIGH | 评估实验可行性 | 无 |
| `idea_portfolio` | HIGH | 排序 idea 组合 | 无 |

#### Review Mode (Mode X) — 3 节点

| 节点 | LLM Tier | 功能 |
|------|----------|------|
| `load_context` | — | 加载上下文 |
| `refine_output` | HIGH | 精修输出 |
| `export_results` | MEDIUM | 生成导出格式 |

---

## 2. 工具函数清单 (Deterministic, No LLM)

### 2.1 学术搜索工具

| 工具 | 文件 | 输入 | 输出 |
|------|------|------|------|
| `search_academic_sources` | `modes/base.py` | topic, queries, keywords | (candidate_ids, executed_queries, errors, title_map) |
| `rerank_search_results` | `modes/base.py` | query, paper_titles, paper_ids | reranked_ids |

### 2.2 论文解析工具

| 工具 | 文件 | 输入 | 输出 |
|------|------|------|------|
| `resolve_and_read_paper` | `modes/base.py` | paper_id, gateway | (summary, claims, cost, errors) |
| `parse_paper` | `services/parser/__init__.py` | identifier | ParsedPaper |
| `get_arxiv_latex_source` | `services/parser/arxiv_source.py` | arxiv_id | source_path |
| `parse_latex` | `services/parser/latex_parser.py` | latex_text | LatexDocument |

### 2.3 向量 & 重排序工具

| 工具 | 文件 | 输入 | 输出 |
|------|------|------|------|
| `embed_paper_chunks` | `services/library/tools_embedding.py` | texts[] | vectors[] (1024-dim) |
| `rerank_papers` | `services/library/tools_embedding.py` | query, documents | [{index, relevance_score}] |

### 2.4 论文库工具

| 工具 | 文件 | 输入 | 输出 |
|------|------|------|------|
| `insert_library_paper` | `services/library/tools_db.py` | data dict | inserted row |
| `search_library_vectors` | `services/library/tools_db.py` | query_embedding, limit | papers with similarity |
| `search_library_text` | `services/library/tools_db.py` | query string | papers (ILIKE title) |
| `library_prefetch` | `services/library/prefetch.py` | topic, keywords | library_seeds[] |

### 2.5 存储工具

| 工具 | 文件 | 输入 | 输出 |
|------|------|------|------|
| `save_latex_source` | `services/library/tools_storage.py` | arxiv_id, archive_path | stored_path |
| `save_uploaded_pdf` | `services/library/tools_storage.py` | file_bytes, filename | stored_path |

### 2.6 LLM 基础设施

| 工具 | 文件 | 输入 | 输出 |
|------|------|------|------|
| `gateway.chat()` | `apps/worker/llm_gateway.py` | messages, tier | {content, usage} |
| `gateway.chat_json()` | `apps/worker/llm_gateway.py` | messages, tier, schema | parsed dict |
| `gateway.chat_structured()` | `apps/worker/llm_gateway.py` | Pydantic model class, messages | model instance |

---

## 3. 工作流拓扑

### 3.1 总体执行流

```
用户创建 Run (API)
    ↓
Redis Queue (lpush)
    ↓
Worker Runner (blpop)
    ↓
_execute_run()
    ├── 1. 读取 Run 配置 (DB)
    ├── 2. 确定 mode (job.mode or run.mode)
    ├── 3. Library Prefetch (向量匹配库内论文)
    ├── 4. _run_mode_graph()
    │       ├── 构建 ModeGraphState
    │       ├── 创建 mode-specific StateGraph
    │       ├── 编译 + MemorySaver checkpointer
    │       └── ainvoke (执行所有节点)
    ├── 5. 判断最终状态 (completed/paused/failed)
    ├── 6. _persist_results() → DB (pain_points, context_bundle)
    └── 7. 发布完成事件 (Redis pubsub + DB)
```

### 3.2 Frontier 模式详细流

```
scope_definition
    │ emit: start → llm_call → done
    ↓
candidate_retrieval
    │ emit: start → searching → search_done → reranking → reranked → citation_lookup → done
    │ tools: search_academic_sources(), rerank_search_results(), S2.get_citations()
    ↓
[check_should_continue] → scope_pruning or END
    │ emit: start → reranking → reranked
    ↓
deep_reading
    │ emit: start → batch → reading 1/N → reading 2/N → ...
    │ tools: resolve_and_read_paper() × N (parallel, 5 concurrent)
    │         └→ PaperTagAgent (Level 1 tags)
    ↓
[check_should_continue] → comparison_build or END
    │ emit: start
    ↓
pain_mining
    │ emit: start
    ↓
[loop check] → candidate_retrieval (if pending_queries > 0 && saturation < 0.8)
             → frontier_summary (otherwise)
    │ emit: start
    ↓
END → _persist_results() → run.completed event
```

### 3.3 模式间数据传递

```
Atlas (Mode A)
    输出: taxonomy_tree, timeline_data, reading_path, context_bundle
    ↓ spawn → 选择子方向
Frontier (Mode B)
    输入: context_bundle (从 Atlas 继承的分类+论文)
    输出: comparison_matrix, pain_points, gaps, pain_point_package
    ↓ spawn → 选择痛点
Divergent (Mode C)
    输入: pain_point_package (从 Frontier 继承)
    输出: idea_cards, feasibility_notes, prior_art_flags
```

---

## 4. ModeGraphState 关键字段流

| 字段 | 写入者 | 读取者 | 类型 |
|------|--------|--------|------|
| `topic` | Runner 初始化 | 所有节点 | str |
| `keywords` | Runner 初始化 | 检索节点 | list[str] |
| `seed_paper_ids` | Runner 初始化 | candidate_retrieval | list[str] |
| `library_seeds` | Runner (prefetch) | candidate_retrieval, deep_reading | list[dict] |
| `pending_queries` | plan/scope 节点 | retrieval 节点 | list[dict] |
| `candidate_paper_ids` | retrieval 节点 | pruning/reading 节点 | list[str] |
| `selected_paper_ids` | pruning 节点 | deep_reading | list[str] |
| `read_paper_ids` | reading 节点 | summary/synthesis 节点 | list[str] |
| `context_bundle` | 每个节点 (累积) | 下游节点, _persist_results | dict[str, Any] |
| `pain_points` | pain_mining | summary, idea_composition | list[dict] |
| `comparison_matrix` | comparison_build | pain_mining, summary | list[dict] |
| `gaps` | pain_mining | summary, divergent | list[dict] |
| `idea_cards` | idea_composition | prior_art, feasibility, portfolio | list[dict] |
| `report_markdown` | synthesis 节点 | Runner persistence | str |
| `current_cost_usd` | 所有 LLM 节点 | check_should_continue | float |
| `should_stop` | summary 节点 | LangGraph 条件边 | bool |

---

## 5. 可观测性状态

| 模块 | emit_progress | 结构化日志 | Token 追踪 | trace_id |
|------|:---:|:---:|:---:|:---:|
| **Frontier** | ✅ 23 calls | ✅ | ⚠️ 部分 | ❌ |
| **Atlas** | ❌ 0 calls | ✅ | ⚠️ 部分 | ❌ |
| **Divergent** | ❌ 0 calls | ✅ | ⚠️ 部分 | ❌ |
| **Review** | ❌ 0 calls | ✅ | ⚠️ 部分 | ❌ |
| **Runner** | ✅ (library) | ✅ | ⚠️ chat() only | ❌ |
| **PaperTagAgent** | ❌ | ✅ | ❌ (chat_structured 不追踪) | ❌ |

**待修复**:
1. Atlas/Divergent/Review 添加 `emit_progress` (用户无法看到这三种模式的实时进度)
2. `chat_structured()` 需要追踪 token 使用量
3. `trace_id` 从 `_execute_run` 生成，传递到所有 `emit_progress` 和 `create_event`

---

## 6. 测试覆盖

### 有测试的模块
- Schemas (run, multimode, library): 23 tests
- Parsers (latex, arxiv): 23 tests
- Embedding service: 14 tests
- Library tools (db, storage, embedding, prefetch): 29 tests
- Mode router: 13 tests
- PaperTagAgent: 3 tests
- API endpoints (v1, v2, library): ~63 tests
- E2E workflow: 11 tests
- **Total: ~227 tests**

### 无测试的关键模块 (需要补充)
- `runner.py` — 核心编排器
- `llm_gateway.py` — LLM 调用层
- `base.py` — 共享工具函数
- 所有 mode graph 节点函数 (atlas, frontier, divergent, review)
- 学术 API 适配器 (S2, OpenAlex, Crossref)

---

## 7. DDD 改进方向

### 当前问题

1. **base.py 是 God Module (645行)** — 混合了状态定义、搜索编排、论文阅读、LLM 包装、成本估算、进度发射
2. **context_bundle 无类型** — `dict[str, Any]` 无 schema，不同模式存不同 key，拼写错误会静默失败
3. **节点函数混合编排和领域逻辑** — 每个节点同时负责"问什么"和"怎么调用"

### 建议重构方向

```
# 目标：按领域边界拆分

services/
├── academic/                    # 学术搜索领域
│   ├── search.py               # 从 base.py 提取 search_academic_sources
│   ├── resolve.py              # 从 base.py 提取 resolve_and_read_paper
│   └── citation.py             # S2 引用链扩展
├── library/                    # 论文库领域 (已完成)
│   ├── tools_db.py
│   ├── tools_storage.py
│   ├── tools_embedding.py
│   └── prefetch.py
├── analysis/                   # 论文分析领域
│   ├── tagger.py               # PaperTagAgent
│   ├── deep_analyzer.py        # Level 2 深度分析 Agent
│   └── claim_extractor.py      # 从 base.py 提取 extract_claims
└── embedding.py                # 向量基础设施

apps/worker/
├── modes/
│   ├── state.py                # ModeGraphState + 类型化的 ContextBundle
│   ├── shared.py               # check_should_continue, emit_progress
│   ├── atlas.py                # 节点函数只负责"问什么"
│   ├── frontier.py
│   ├── divergent.py
│   └── review.py
└── runner.py                   # 纯编排
```

每个 Agent 遵循:
```python
class Agent:
    async def plan(self, input) -> Plan:    # LLM 决策
        ...
    async def execute(self, plan) -> Result: # 调用工具
        ...
    async def run(self, input) -> Output:   # plan + execute
        plan = await self.plan(input)
        return await self.execute(plan)
```
---

## 8. 快速 Debug 指南

### 查看 run 执行链路
```bash
# 查看某个 run 的所有事件 (按时间排序)
curl -s http://localhost:8000/api/v1/runs/{run_id}/events?limit=100 | python3 -c "
import sys, json
for e in reversed(json.load(sys.stdin)['events']):
    print(f'{e[\"timestamp\"][-12:]} {e[\"event_type\"]:45s} {e.get(\"payload\",{}).get(\"message\",\"\")[:60]}')
"

# 查看 worker 日志中某个 run 的所有活动
grep "run_id={run_id}" /tmp/ros-worker.log
```

### 查看 LLM 调用
```bash
# 所有 LLM 调用 (成功)
grep "llm_call_complete\|structured_output_complete" /tmp/ros-worker.log

# JSON 解析失败
grep "json_parse_failed\|structured_output_failed" /tmp/ros-worker.log

# Token 总量
grep "worker.run_finished" /tmp/ros-worker.log | grep "total_tokens"
```

### 查看论文库状态
```bash
curl -s http://localhost:8000/api/v1/library/stats
```
