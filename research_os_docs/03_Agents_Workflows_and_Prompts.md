# 03. Agents, Workflows and Prompts —— Research OS 自治工作流与提示词设计

版本：v1.0  
日期：2026-03-16  
适用对象：Agent 工程师、算法工程师、检索工程师、后端工程师、评测工程师

---

## 1. 设计目标

本文件定义 Research OS 的自治研究循环如何具体执行，包括：

- Agent 拆分
- LangGraph 节点设计
- 状态结构
- 提示词模板
- JSON 输出约束
- 检索与扩展算法
- 矛盾检测与创新点生成机制
- 自动暂停与恢复逻辑
- 失败重试和降级策略

核心原则：**系统不是“问一个问题，给一个答案”，而是“围绕一个 topic 持续构建研究图谱并不断校正自身结论”。**

---

## 2. Agent 设计总览

## 2.1 为什么要多 Agent，但不能过度多 Agent

本系统需要拆 Agent，不是为了“看起来高级”，而是为了：

- 每一步输入输出 schema 清晰
- 便于审计、缓存、重试、替换
- 便于选择不同模型成本层级
- 便于做分阶段评估

但也不能拆成 20 个彼此不断对话的小 agent，那会导致：

- 状态爆炸
- 成本高
- 难以 debug
- 难以保证证据链

### 建议：8 个逻辑 Agent，1 个编排器

1. Planner Agent
2. Ingestion Agent
3. Scholar Retrieval Agent
4. Dedup & Ranking Agent
5. Reading Agent
6. Synthesis Agent
7. Innovation Agent
8. Verifier / Critic Agent

这些 Agent 不一定是 8 个独立进程；在实现上可以是 8 组节点与 prompt 模块。

---

## 2.2 各 Agent 职责

### 1) Planner Agent

输入：

- 研究主题
- 用户约束
- 种子论文元数据
- 输出目标

输出：

- 研究问题分解
- 检索策略
- 停止条件
- coverage targets
- 初始关键词集
- auto-pause 策略实例化

### 2) Ingestion Agent

输入：

- PDF / DOI / arXiv / title

输出：

- canonical paper record
- parsed document tree
- chunks
- claims
- reference list
- limitations / future work / assumptions

### 3) Scholar Retrieval Agent

输入：

- research plan
- seed paper graph
- current coverage gaps

输出：

- candidate papers
- source provenance
- query trace
- relatedness signals

### 4) Dedup & Ranking Agent

输入：

- candidate pool
- current corpus
- current topic coverage map

输出：

- deduplicated candidate set
- priority queue for deep reading
- diversity-aware ranking

### 5) Reading Agent

输入：

- selected papers
- available full text / abstract-only state

输出：

- structured summary
- paper claims
- evidence spans
- experimental settings
- limitations and failures

### 6) Synthesis Agent

输入：

- paper summaries
- claims
- citation graph
- cluster map

输出：

- topic clusters
- landscape summary
- contradictions
- gaps
- emerging themes

### 7) Innovation Agent

输入：

- gaps
- contradictions
- future work signals
- underexplored cross-cluster pairs

输出：

- innovation cards / hypotheses
- why-now explanation
- experiment sketch
- novelty rationale

### 8) Verifier / Critic Agent

输入：

- hypothesis candidate
- relevant papers and claims
- search results for prior art

输出：

- novelty downgrade / upgrade
- feasibility assessment
- risks
- continue-search or finalize decision

---

## 3. 运行时状态设计

## 3.1 RunState（建议使用 Pydantic）

```python
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal

class Budget(BaseModel):
    max_runtime_minutes: int = 90
    max_new_papers: int = 150
    max_fulltext_reads: int = 40
    max_tool_calls: int = 80
    max_estimated_cost_usd: float = 30.0

class Policy(BaseModel):
    auto_pause_on_missing_key_fulltext: bool = True
    auto_pause_on_low_confidence_hypothesis: bool = True
    auto_pause_on_budget_hit: bool = True
    auto_pause_on_retrieval_drift: bool = True

class QueryPlan(BaseModel):
    query_text: str
    source_names: List[str]
    intent: Literal["seed_expand", "citation_expand", "gap_fill", "prior_art_check"]
    priority: int = 1

class CoverageTarget(BaseModel):
    dimension: Literal["task", "method", "dataset", "metric", "year", "venue"]
    key: str
    min_papers: int = 3

class CandidatePaper(BaseModel):
    paper_id: Optional[str] = None
    title: str
    doi: Optional[str] = None
    year: Optional[int] = None
    source_name: str
    score_signals: Dict[str, float] = Field(default_factory=dict)

class HypothesisCandidate(BaseModel):
    title: str
    statement: str
    type: str
    support_evidence_ids: List[str] = Field(default_factory=list)
    oppose_evidence_ids: List[str] = Field(default_factory=list)
    novelty_score: float = 0.0
    feasibility_score: float = 0.0
    risk_score: float = 0.0

class RunState(BaseModel):
    run_id: str
    topic: str
    goal_type: str
    user_constraints: Dict = Field(default_factory=dict)
    budget: Budget
    policy: Policy
    seed_paper_ids: List[str] = Field(default_factory=list)
    research_questions: List[str] = Field(default_factory=list)
    query_queue: List[QueryPlan] = Field(default_factory=list)
    candidate_papers: List[CandidatePaper] = Field(default_factory=list)
    selected_paper_ids: List[str] = Field(default_factory=list)
    coverage_targets: List[CoverageTarget] = Field(default_factory=list)
    coverage_map: Dict = Field(default_factory=dict)
    saturation_score: float = 0.0
    active_cluster_ids: List[str] = Field(default_factory=list)
    contradictions: List[Dict] = Field(default_factory=list)
    hypotheses: List[HypothesisCandidate] = Field(default_factory=list)
    pause_reason: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    metrics: Dict = Field(default_factory=dict)
```

---

## 3.2 关键状态字段解释

- `research_questions`：Planner 生成的可执行子问题
- `query_queue`：待执行检索任务队列
- `coverage_targets`：系统认为必须覆盖的主题维度
- `coverage_map`：当前已覆盖情况
- `saturation_score`：信息增益是否已经降低到停止阈值
- `contradictions`：已识别的矛盾与张力列表
- `hypotheses`：当前创新点池
- `pause_reason`：为什么暂停
- `metrics`：累计 papers、reads、tokens、tool calls 等

---

## 4. LangGraph 节点设计

## 4.1 推荐节点图

```mermaid
flowchart TD
    A[plan_research] --> B[ingest_seed_papers]
    B --> C[resolve_seed_metadata]
    C --> D[extract_seed_claims]
    D --> E[build_initial_queries]
    E --> F[search_sources]
    F --> G[merge_dedup_candidates]
    G --> H[rank_candidates]
    H --> I{need_more_coverage?}
    I -- yes --> F
    I -- no --> J[select_for_deep_read]
    J --> K[deep_read_papers]
    K --> L[update_graph_and_clusters]
    L --> M[detect_contradictions]
    M --> N[generate_hypotheses]
    N --> O[verify_hypotheses]
    O --> P{continue_search?}
    P -- yes --> Q[generate_gap_fill_queries]
    Q --> F
    P -- no --> R[compile_outputs]
    R --> S[final_quality_check]
    S --> T[complete_run]
```

---

## 4.2 每个节点的输入 / 输出 / 失败策略

### `plan_research`

输入：
- 用户 topic
- seeds
- goal_type
- budget
- policy

输出：
- research_questions
- query seeds
- coverage_targets
- stop criteria

失败策略：
- 如果模型输出结构化 JSON 失败，重试 2 次
- 若仍失败，使用规则模板 fallback：
  - 研究问题分解模板
  - 默认 coverage 目标
  - 默认 budget policy

---

### `ingest_seed_papers`

输入：
- file ids / doi / arxiv ids / titles

输出：
- `paper` records
- `paper_version`
- raw parse artifact pointers

失败策略：
- 文件解析失败时标记 `parse_status=failed`
- 尝试 metadata-only fallback
- 若 seed 可用论文少于最小阈值，触发 Gate 暂停

---

### `resolve_seed_metadata`

输入：
- references from parser
- title, authors, year

输出：
- canonical ids
- merged source records
- OA/fulltext info

失败策略：
- DOI 优先
- 无 DOI 时用 normalized title + year + first author 召回候选
- 若匹配分数低，不强行合并；保留 unresolved reference

---

### `extract_seed_claims`

输入：
- chunked seed papers

输出：
- claims
- evidence spans
- future work / limitation records
- concept candidates

失败策略：
- JSON 失败重试
- 若某 chunk 太长或 parser 污染，先 summary 再 claim extract
- 对低质量 chunk 标注 `low_parse_confidence`

---

### `build_initial_queries`

输入：
- topic
- research_questions
- seed paper methods/datasets/keywords
- cited works

输出：
- query queue

建议生成 4 类 query：
1. 主题直查
2. seed 扩展
3. limitation/future work 导向
4. 负向/反证导向

---

### `search_sources`

输入：
- query plan

输出：
- raw candidates from source adapters

策略：
- 并发查询多个学术源
- 每个源单独限流
- 每次只取元数据与 OA 状态，不立刻全文深读

---

### `merge_dedup_candidates`

输入：
- raw candidate list

输出：
- canonical candidate set

去重优先级：
1. DOI exact match
2. OpenAlex / S2 / arXiv exact id
3. normalized title similarity + year
4. title similarity + first author similarity

---

### `rank_candidates`

输入：
- dedup candidates
- seed similarity
- graph proximity
- current coverage gaps

输出：
- ordered deep-read queue

详细打分见后文。

---

### `need_more_coverage?`

判断逻辑：
- coverage targets 是否满足
- saturation 是否过低
- top hypotheses 是否证据不足
- 预算是否还允许继续扩展

---

### `select_for_deep_read`

输入：
- ranked queue
- budget remaining
- already read papers

输出：
- selected paper ids

策略：
- 70% exploit（高相关）
- 30% explore（补齐空白簇 / 新近论文 / 反证论文）

---

### `deep_read_papers`

输入：
- selected papers
- fulltext availability

输出：
- paper structured summaries
- claims
- methods/datasets/metrics/failures
- citation context enrichment

如果无全文：
- metadata + abstract-only 模式
- 不抽取高置信 claim
- 但仍保留为 prior-art reference

---

### `update_graph_and_clusters`

输入：
- papers
- claims
- relations

输出：
- updated clusters
- topic labels
- cluster summaries
- coverage map update

---

### `detect_contradictions`

输入：
- claims
- cluster summaries
- result claims on same subject/task/metric

输出：
- contradiction set
- condition-difference notes
- uncertainty flags

---

### `generate_hypotheses`

输入：
- contradictions
- gaps
- underexplored combinations
- future work mentions
- negative results

输出：
- candidate innovation cards

---

### `verify_hypotheses`

输入：
- innovation cards
- corpus
- fresh prior-art queries

输出：
- updated novelty / feasibility / risk scores
- reject / hold / continue-search / finalize

---

### `compile_outputs`

输入：
- final paper set
- clusters
- contradictions
- hypotheses
- evidence

输出：
- Markdown report
- JSON graph snapshot
- CSV paper list
- BibTeX

---

### `final_quality_check`

检查项：

- 输出 JSON/Markdown 结构完整
- 至少 N 条关键结论有 evidence
- 最终 innovation cards 均经过 verify
- 所有引用 paper 都能在 paper table 中定位
- report 中无明显无证据断言

---

## 5. 检索与扩展算法

## 5.1 Query Generation 策略

### 输入来源

- 用户主题
- 种子论文 title / abstract / keywords
- seed claims
- seed limitations
- seed future work
- current gaps
- contradictions

### Query 模板库

#### 模板 A：主题直查

- `{topic}`
- `{topic} survey`
- `{topic} recent advances`
- `{topic} benchmark`

#### 模板 B：方法扩展

- `{method} for {task}`
- `{method} + {dataset}`
- `{method} limitation`

#### 模板 C：引用扩展

- papers cited by seed
- papers citing seed
- papers recommended from seed set
- co-cited papers around seed cluster

#### 模板 D：空白点导向

- `{assumption} relaxation in {task}`
- `{metric} neglected in {topic}`
- `negative results of {method}`

#### 模板 E：反证导向

- `failure mode {method}`
- `{method} robustness issue`
- `{method} does not improve {metric}`

---

## 5.2 Candidate Ranking 公式（建议首版）

定义：

- `S_semantic`：语义相关度
- `S_keyword`：关键词命中
- `S_citation`：与种子图的距离 / proximity
- `S_impact`：引用影响力（需归一化，避免过度偏好老论文）
- `S_recency`：新近性
- `S_diversity`：补齐覆盖空白的奖励
- `S_trust`：来源可信度
- `S_access`：全文可用性
- `S_contradiction`：是否可能提供反证或边界条件

建议首版公式：

```text
S_total =
  0.24 * S_semantic +
  0.12 * S_keyword +
  0.14 * S_citation +
  0.08 * S_impact +
  0.10 * S_recency +
  0.12 * S_diversity +
  0.08 * S_trust +
  0.06 * S_access +
  0.06 * S_contradiction
```

### 说明

- 不是只看相关度
- 必须给 diversity 和 contradiction 留权重，否则系统只会不断读“同类 SOTA”
- 不建议让引用数主导排序，否则新论文和小众路线会被压死

---

## 5.3 Coverage 与 Saturation

### Coverage Map 维度（建议）

- 任务
- 方法家族
- 数据集
- 指标
- 年份
- 发表 venue
- 是否有负结果 / limitation
- 是否有系统综述 / benchmark 论文

### 例子

```json
{
  "task": {"multi_agent_memory": 9, "self_correction": 7},
  "method": {"retrieval_memory": 5, "reflective_memory": 2, "graph_memory": 1},
  "dataset": {"gsm8k": 4, "agentbench": 3},
  "negative_results": {"present": 2}
}
```

### Saturation Score

建议计算三个子项：

1. **新增论文信息增益**
   - 新 papers 带来新 concept / new claim / new contradiction 的比例

2. **query 收敛度**
   - 多轮 query 的 top results 是否高度重复

3. **hypothesis 收敛度**
   - 新生成 hypothesis 是否大多只是已有 hypothesis 的变体

建议当连续 2~3 轮 `saturation_score < threshold` 时停止扩展。

---

## 6. 论文深读设计

## 6.1 全文与摘要模式分离

### Fulltext Mode

适用于：
- 用户上传
- 合法 OA 下载
- 已有可解析 PDF

可抽取：
- claim
- evidence
- section summaries
- methods / experiments / limitations

### Abstract-only Mode

适用于：
- 找不到全文但 metadata 完整
- 作为 prior-art / landscape 补充

限制：
- 只能生成低置信摘要
- 不能作为强 evidence 支撑核心结论
- 可以用于 novelty 检查和相关工作覆盖

---

## 6.2 Chunk 策略

建议双层 chunk：

### Parent Chunk
- 粒度：section / subsection
- 目标长度：1000~1800 tokens
- 用途：高层理解与摘要

### Child Chunk
- 粒度：paragraph / paragraph group
- 目标长度：250~400 tokens
- overlap：40~80 tokens
- 用途：精确 evidence 与 claim 抽取

### 特殊 chunk 类型

- abstract
- title
- figure caption
- table caption
- reference context（正文中引用上下文）
- limitation snippet
- future work snippet

---

## 6.3 Claim 抽取 Schema

建议所有 claims 都走统一 schema：

```json
{
  "claim_type": "result",
  "claim_text": "Reflective memory improves long-horizon agent performance on benchmark X under constrained context windows.",
  "subject_text": "reflective memory",
  "predicate_text": "improves",
  "object_text": "long-horizon agent performance",
  "conditions": [
    "benchmark X",
    "constrained context windows"
  ],
  "polarity": "positive",
  "confidence": 0.87,
  "evidence_quote": "....",
  "evidence_page_start": 6,
  "evidence_page_end": 6
}
```

### claim_type 枚举

- `problem_statement`
- `method`
- `result`
- `comparison`
- `limitation`
- `assumption`
- `future_work`
- `dataset`
- `metric`
- `failure_mode`
- `threat_to_validity`

---

## 7. 聚类与矛盾发现

## 7.1 主题聚类

首版推荐流程：

1. 取 paper-level summary embedding
2. 与 citation proximity 做融合相似度
3. 用层次聚类或 Leiden（如果已经有图）
4. 对每个簇生成：
   - cluster label
   - representative papers
   - shared assumptions
   - dominant datasets/metrics
   - open questions

### 簇命名 Prompt 目标

不是生成漂亮标题，而是生成对研究真正有用的标签，例如：

- `Reflective memory with explicit self-critique`
- `External retrieval memory for long-horizon planning`
- `Benchmark-centric evaluation papers`
- `Negative or bounded results under token constraints`

---

## 7.2 矛盾发现算法

### 第一步：候选 claim 配对

候选条件：

- 同一 task / method / metric 空间
- 同类 claim_type（多为 result / limitation）
- subject 相同或高度相似
- polarity 不同，或 result 差异明显

### 第二步：条件归一化

把 claim 中的条件解析为：

- dataset
- metric
- compute budget
- context length
- training regime
- model scale
- evaluation setting

### 第三步：NLI / LLM 关系判断

输出之一：

- `contradicts`
- `appears_consistent_but_conditions_differ`
- `refines`
- `insufficient_information`

### 第四步：人类可读解释

必须生成可审计 note：

- 矛盾是“结论冲突”还是“边界条件不同”
- 哪一方证据更强
- 是否需要更多论文验证

### Contradiction JSON

```json
{
  "src_claim_id": "c1",
  "dst_claim_id": "c2",
  "relation_type": "contradicts",
  "confidence": 0.78,
  "rationale": "Both claims evaluate reflective memory on long-horizon tasks, but one reports gains only under small context windows while the other shows no benefit under larger context and stronger base models."
}
```

---

## 8. 创新点生成机制

## 8.1 不允许“裸 brainstorm”

Innovation Agent 不能只根据主题自由发散。必须从以下结构性输入中生成：

- 研究簇之间的未连接区域
- 明确的 limitation
- 反证和失败模式
- 被反复提到但未系统解决的问题
- 指标 / 数据集 /部署约束上的错配
- 具有可组合潜力的方法组件

---

## 8.2 创新点生成的五类模板

### 模板 1：Cluster Bridge

把两个文献簇桥接起来：

- 簇 A 在做 memory compression
- 簇 B 在做 self-correction
- 当前几乎没有工作把两者结合

### 模板 2：Assumption Relaxation

放宽一个隐藏假设：

- 现有方法默认同步、多轮上下文充足
- 真实环境是异步、预算受限

### 模板 3：Metric Gap

现有 SOTA 只优化 accuracy，不优化：

- latency
- cost
- robustness
- long-context stability

### 模板 4：Negative Result Exploitation

已有工作已暴露失败模式，但没人系统解决。

### 模板 5：Transfer to Neglected Setting

某方法在 A 领域成熟，但在 B 场景基本没人用。

---

## 8.3 Innovation Card Schema

```json
{
  "title": "Reflective memory compression for budget-constrained multi-agent planning",
  "statement": "Combine explicit reflective summaries with compressed external memory to reduce context growth while preserving self-correction signals across long trajectories.",
  "type": "cluster_bridge",
  "why_now": "Current reflective systems grow context too quickly and retrieval systems lose corrective history.",
  "supporting_evidence": [
    "claim_1",
    "claim_2"
  ],
  "opposing_evidence": [
    "claim_8"
  ],
  "novelty_score": 0.81,
  "feasibility_score": 0.72,
  "risk_score": 0.41,
  "expected_experiments": [
    "compare against retrieval-only memory",
    "measure latency, token cost, and long-horizon success"
  ],
  "likely_rejection_risks": [
    "could be seen as engineering combination",
    "may depend on benchmark-specific context limits"
  ]
}
```

---

## 8.4 创新点评分建议

### Novelty Score

考虑：

- 现有语料中类似 hypothesis 的密度
- title/abstract/claim 相似 prior-art 的存在
- 是否跨 cluster
- 是否解决显著冲突或空白

### Feasibility Score

考虑：

- 是否已有数据集与 baseline
- 是否可在合理算力下验证
- 是否依赖闭源数据 / 不可得资源
- 是否能给出清晰实验设计

### Risk Score

考虑：

- prior-art 被漏检的概率
- 是否只是显而易见组合
- 是否已有负结果指向不可行
- 评估设计是否容易被质疑

建议最终排序：
```text
Priority = 0.40*Novelty + 0.30*Evidence + 0.20*Feasibility - 0.10*Risk
```

---

## 9. Verifier / Critic 设计

## 9.1 两阶段验证

### 阶段一：内部验证

基于本地 corpus 检查：

- hypothesis 是否已有高相似 claim
- 反证是否被忽略
- 支持证据是否过于薄弱
- 是否缺少必要前置方法

### 阶段二：外部 prior-art 检索

重新构造针对 hypothesis 的检索：

- title-like queries
- method + task + constraint queries
- negative queries（是否已有 failure）
- newer papers boost

输出：

- strongest similar prior art
- similarity reason
- novelty downgrade reason
- 是否建议继续搜索更多文献

---

## 9.2 何时拒绝一个创新点

以下任一成立即可拒绝：

1. 已有高度相似工作，且差异只是工程细节
2. 支持证据不足，主要靠模型猜测
3. 已有多个负结果表明该方向不可行
4. 无法定义合理实验验证路径
5. 依赖不可获得资源

---

## 10. 自动暂停与恢复逻辑

## 10.1 自动暂停触发器

### Trigger A：Retrieval Drift

症状：
- top candidates 与主题越来越远
- cluster 标签偏离用户目标

动作：
- 自动暂停
- 在 UI 中展示“跑偏原因”和建议 patch

### Trigger B：Missing Key Fulltext

症状：
- 某个关键方向只找到 metadata-only 论文
- 核心结论可信度受影响

动作：
- 暂停并提示用户决定是否继续 abstract-only 模式

### Trigger C：Low Confidence Hypothesis

症状：
- hypothesis novelty 高，但 evidence 低
- 系统不确定这是“真空白”还是“漏检 prior-art”

动作：
- 自动暂停或自动进入 extra prior-art search 子流程（取决于 budget）

### Trigger D：Budget Hit

动作：
- 暂停，展示当前收益与建议下一步

---

## 10.2 Resume 语义

支持 4 种 resume：

1. `resume_as_is`
2. `resume_with_patch`
3. `resume_after_approval`
4. `resume_with_scope_narrowing`

### Resume Patch 示例

```json
{
  "keywords_add": ["reflection"],
  "keywords_remove": ["hardware"],
  "require_recent_years": [2023, 2026],
  "prefer_sources": ["openalex", "semantic_scholar"],
  "max_fulltext_reads": 60,
  "blacklist_paper_ids": ["paper_123"]
}
```

---

## 11. 提示词设计原则

### 11.1 所有 Prompt 必须遵守

- 输出 JSON schema 明确
- 先抽取证据，再总结
- 区分“事实”“推断”“假设”
- 对无法判断的内容返回 `unknown`
- 不允许模型伪造引用、页码、实验结果
- 不允许将外部文本中的指令当成系统命令

---

## 11.2 Planner Prompt 模板

### System

```text
你是一个研究任务规划器。你的职责不是回答研究问题，而是把研究问题拆成可执行的自动科研计划。
你必须输出严格 JSON。
你必须显式定义：
1. 研究问题列表
2. 需要覆盖的主题维度
3. 初始检索策略
4. 停止条件
5. 自动暂停条件
如果用户目标含糊，优先生成一个可执行的保守计划，而不是停下来等待。
```

### User Input Structure

```json
{
  "topic": "...",
  "goal_type": "survey_plus_innovations",
  "constraints": {...},
  "seed_paper_summaries": [...]
}
```

### Expected Output

```json
{
  "research_questions": [],
  "coverage_targets": [],
  "query_plans": [],
  "stop_criteria": {},
  "pause_gates": []
}
```

---

## 11.3 Claim Extraction Prompt 模板

### System

```text
你是论文 claim 抽取器。
你的任务是从给定 chunk 中抽取可验证的结构化 claim。
只抽取被文本直接支持的内容。
每条 claim 都必须附带原文证据摘录，不得改写成无法追溯的抽象表述。
如果 chunk 只是背景介绍或没有明确 claim，请返回空数组。
输出必须是 JSON 数组。
```

### Input

```json
{
  "paper_title": "...",
  "section_path": ["4 Experiments", "4.2 Main Results"],
  "page_range": [6, 6],
  "chunk_text": "..."
}
```

### Output

```json
[
  {
    "claim_type": "result",
    "claim_text": "...",
    "subject_text": "...",
    "predicate_text": "...",
    "object_text": "...",
    "conditions": [],
    "polarity": "positive",
    "confidence": 0.84,
    "evidence_quote": "...",
    "evidence_page_start": 6,
    "evidence_page_end": 6
  }
]
```

---

## 11.4 Paper Summary Prompt 模板

### System

```text
你是研究阅读代理。
请基于给定论文内容输出结构化阅读卡，而不是写散文式摘要。
必须覆盖：
- problem
- method
- assumptions
- experimental setup
- main results
- limitations
- future work
- reusable components
每一项都需要尽量绑定来自原文的证据片段 ID。
如果没有足够证据，不要猜测，返回 unknown。
```

---

## 11.5 Contradiction Judge Prompt 模板

### System

```text
你是论文结论关系判断器。
给定两条 claim，请判断它们是：
- contradicts
- conditionally_consistent
- refines
- duplicates
- insufficient_information
你必须特别关注：
- 数据集是否不同
- 指标是否不同
- 预算 / 规模 / context 是否不同
- 是否只是表面矛盾，实际条件不同
输出 JSON，不要解释成散文。
```

---

## 11.6 Innovation Prompt 模板

### System

```text
你是研究创新点生成器。
你不能自由发散。
你只能基于以下输入生成候选创新点：
1. 明确的 gaps
2. contradictions
3. future_work
4. negative_results
5. underexplored cluster bridges
每个创新点必须包含：
- hypothesis
- why_now
- expected value
- supporting evidence ids
- opposing evidence ids
- likely rejection risks
如果输入不足以支持创新点，请返回空数组。
```

---

## 11.7 Verifier Prompt 模板

### System

```text
你是研究假设验证器。
你的任务不是帮候选创新点说服人，而是尽量找理由推翻它。
检查：
- 是否已有相似 prior art
- 是否只是平凡组合
- 是否忽视了负结果
- 是否缺乏实验可行性
- 是否证据不足
输出 JSON：
- verdict
- novelty_adjustment
- feasibility_adjustment
- risk_adjustment
- continue_search
- rationale
```

---

## 12. 模型层策略

## 12.1 模型分层建议

### Tier A：高推理模型
用于：
- planner
- synthesis
- innovation
- verifier

### Tier B：中成本结构化模型
用于：
- claim extraction
- paper structured summary
- contradiction classification
- lightweight rerank

### Tier C：embedding / reranker
用于：
- vector retrieval
- clustering embeddings
- title/abstract similarity

原则：

- 不要所有步骤都用最贵模型
- 先把重计算花在 high-value nodes
- 所有结构化输出都要 schema 校验

---

## 12.2 何时用 Responses API 背景任务

适合：

- 单次 deep synthesis 很长
- prior-art web/tool research 可能持续十几分钟
- 需要 `max_tool_calls` 控制工具调用上限
- 需要 webhook 或轮询获取异步完成结果

不适合：

- 只需毫秒级同步返回的简单抽取
- 可以在 worker 中快速完成的普通节点

---

## 13. 缓存、重试与降级

## 13.1 缓存层次

1. **source query cache**
   - query hash -> raw source results

2. **metadata resolve cache**
   - normalized title + year -> canonical paper id

3. **embedding cache**
   - text hash + embedding model -> vector

4. **LLM structured output cache**
   - prompt hash + input hash + model -> parsed JSON

5. **hypothesis verify cache**
   - hypothesis hash -> prior-art check result

---

## 13.2 重试策略

### 外部 API

- HTTP 429 / 5xx 指数退避
- source-level circuit breaker
- 每源独立 concurrency limit

### LLM JSON 失败

- 首次失败：重试同 prompt
- 第二次失败：注入 validator error message
- 第三次失败：切到 fallback prompt 或低温参数

### 解析失败

- GROBID 失败 -> PyMuPDF fallback
- 全文不可得 -> abstract-only

---

## 13.3 降级策略

| 场景 | 降级方案 |
|---|---|
| 全文不可得 | metadata + abstract only |
| 引文解析差 | 只用 title/author/year resolve |
| claim 抽取失败 | 先做 section summary，再抽取 |
| graph 关系不足 | 临时只用语义 + metadata 检索 |
| 高推理模型超时 | 分而治之，切小任务 |

---

## 14. 评测与质量门禁

## 14.1 节点评测

### 解析层
- 标题抽取正确率
- 引用解析成功率
- chunk 有效率（非污染文本占比）

### 检索层
- Precision@K
- Recall@K
- Diversity coverage

### 阅读层
- 结构化摘要完整率
- claim evidence alignment

### 创新点层
- hypothesis 可审计率
- prior-art 漏检率
- 人工可继续推进接受率

---

## 14.2 关键质量门禁

以下不通过则不能标记 Run 为 completed：

1. 核心结论 evidence coverage 不足
2. report 中引用 paper 不存在
3. innovation cards 未经过 verify
4. JSON 结构不合法
5. 关键节点失败但未显式记录降级

---

## 15. 伪代码：自治研究主循环

```python
def autonomous_research_loop(state: RunState) -> RunState:
    state = plan_research(state)
    state = ingest_seed_papers(state)
    state = resolve_seed_metadata(state)
    state = extract_seed_claims(state)
    state = build_initial_queries(state)

    while True:
        if should_pause(state):
            state.pause_reason = compute_pause_reason(state)
            return state

        if should_stop(state):
            break

        state = search_sources(state)
        state = merge_dedup_candidates(state)
        state = rank_candidates(state)

        if need_more_coverage(state):
            state = maybe_generate_gap_fill_queries(state)

        selected = select_for_deep_read(state)
        if not selected:
            break

        state = deep_read_papers(state, selected)
        state = update_graph_and_clusters(state)
        state = detect_contradictions(state)
        state = generate_hypotheses(state)
        state = verify_hypotheses(state)

    state = compile_outputs(state)
    state = final_quality_check(state)
    return state
```

---

## 16. 样例：一次完整 Run 的中间产物

### Step 1：Planner 输出

- 研究问题 4 个
- coverage target 12 个
- 初始 query 10 条

### Step 2：种子入库

- 解析 6 篇 PDF
- 成功 5 篇
- 失败 1 篇，退化为 metadata-only

### Step 3：候选扩展

- OpenAlex 结果 120
- Semantic Scholar 结果 80
- Crossref resolve 30
- 合并后去重为 146 篇

### Step 4：首轮深读

- 选择 20 篇
- 全文可得 12 篇
- abstract-only 8 篇

### Step 5：中间发现

- 形成 4 个 cluster
- 发现 3 个矛盾
- 发现 2 个潜在高价值空白

### Step 6：创新点候选

- 生成 7 个
- verify 后保留 3 个
- 2 个被 prior-art 否决
- 2 个被判证据不足，需要继续搜索

---

## 17. 工程实现建议

### 17.1 Prompt 与 Schema 版本化

所有 prompt 必须存表：

- prompt_name
- prompt_version
- prompt_hash
- schema_version
- rollout_status

原因：

- 同一个 Run 的输出必须可追溯到具体 prompt
- 后续改 prompt 时才能做 A/B test 与回放

### 17.2 不要让 LLM 直接改数据库

LLM 只输出结构化建议。  
真正的写库动作由应用层做：

1. 校验 JSON schema
2. 校验字段合法性
3. 生成 internal ids
4. 执行 upsert
5. 写入 audit log

### 17.3 不要把“最终报告生成”当成最后一大 prompt

应该先有：

- structured summaries
- contradiction list
- hypothesis cards
- evidence packs

然后再由报告生成器根据这些结构化对象拼装 Markdown。  
这样最终报告可控、可验证、可重复导出。

---

## 18. 结论

要让自动科研流程真正“自动”，关键不是让模型更会写，而是让系统具备以下能力：

1. **围绕 topic 持续构建和修正研究图谱**
2. **在每一步都输出结构化、可追溯对象**
3. **在出现歧义、证据不足、预算触顶时自动暂停**
4. **将创新点生成置于 gaps / contradictions / prior-art verification 的闭环中**

只要这个闭环成立，Research OS 就不是一次性的聊天工具，而是真正能跑起来的自治研究系统。
