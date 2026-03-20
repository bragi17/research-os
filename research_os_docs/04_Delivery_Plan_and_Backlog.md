# 04. Delivery Plan and Backlog —— Research OS 交付计划、研发排期与评测方案

版本：v1.0  
日期：2026-03-16  
适用对象：研发经理、技术负责人、产品经理、测试负责人、平台负责人

---

## 1. 交付目标

本文档回答三个问题：

1. 这套系统如何从 0 落地到可用
2. 团队应该如何分工与按阶段交付
3. 如何评估“这套自动科研系统真的能用”

---

## 2. 建设策略总览

## 2.1 不建议的做法

- 一开始就做全量多 agent 大平台
- 一开始就引入过多基础设施组件
- 一开始就追求所有学科通用
- 一开始就做“自动实验平台 + 自动写论文 + 自动答辩”式超大目标

## 2.2 建议的做法

采用 **四层递进建设法**：

### Layer 1：跑通自治闭环
必须先打通：
- 创建任务
- 解析论文
- 自动扩展
- 深读
- 输出综述与创新点

### Layer 2：做强证据链
必须补强：
- claim / evidence
- audit trail
- source provenance
- prompt / model trace

### Layer 3：做强创新点质量
必须补强：
- contradiction mining
- gap discovery
- prior-art verification
- risk scoring

### Layer 4：做强平台性
必须补强：
- 并发
- 多租户
- 配额
- tracing
- rollout / regression / benchmark

---

## 3. 团队配置建议

## 3.1 最小可行团队（建议 5~7 人）

| 角色 | 数量 | 主要职责 |
|---|---:|---|
| 技术负责人 / 架构师 | 1 | 架构决策、数据模型、代码质量、接口边界 |
| 后端工程师 | 2 | API、workflow、存储、队列、适配器 |
| Agent / 算法工程师 | 1~2 | prompt、抽取、排序、创新点与评测 |
| 前端工程师 | 1 | 控制台、证据浏览、事件流、假设工作台 |
| 平台 / DevOps（兼职可） | 0.5~1 | 环境、部署、监控、CI/CD |
| 测试 / QA（兼职可） | 0.5~1 | 测试策略、基准集、回归测试 |

## 3.2 推荐组织方式

- 一个单独 Tech Lead 统一把关 schema 与工作流
- 不要把 parsing / retrieval / synthesis 分散在多个小组各自实现
- 把 prompt 与 schema 当成正式工程资产管理，而不是散落在代码中

---

## 4. 里程碑设计

## 4.1 建议里程碑

### M0：立项与技术验证（1~2 周）
产物：
- 目标与范围确认
- 技术栈确认
- 样例 topic case 确认
- 关键依赖验证（GROBID、外部学术 API、Responses API）

### M1：闭环 MVP（4~6 周）
产物：
- 任务创建
- 种子入库
- 自动扩展
- 深读与结构化摘要
- 基础报告输出
- 基础控制台

### M2：证据化与中断恢复（2~3 周）
产物：
- claim/evidence
- audit trail
- checkpoint/resume
- 运行事件流

### M3：矛盾与创新点引擎（3~4 周）
产物：
- cluster
- contradiction
- gap analysis
- innovation cards
- verifier

### M4：评测与上线准备（2~3 周）
产物：
- benchmark 数据集
- 回归测试
- 观测面板
- 发布 runbook

---

## 5. 分阶段建设计划（建议 14 周）

> 下面给出一个比较稳妥的 14 周计划。若团队经验较强，可压缩到 10~12 周；若团队首次搭建此类系统，建议按 14 周实施。

---

## Phase 0（Week 1~2）：Discovery 与技术 PoC

### 目标
验证最关键依赖是否可用，避免在 Week 4 以后才发现底层方案不成立。

### 交付项

#### P0-1：样本题集准备
准备 8~12 个真实研究主题，每个主题包含：

- topic 描述
- 3~10 篇种子论文
- 人工认为的代表论文集
- 人工认为的重要子路线
- 可接受创新点类型

用途：
- 后续评测
- 回归测试
- UI demo

#### P0-2：PDF 解析验证
对 30~50 篇论文跑 GROBID + PyMuPDF，记录：

- 标题抽取准确率
- reference 解析成功率
- section / paragraph 还原质量
- 两栏排版污染率

#### P0-3：外部学术源验证
验证：
- OpenAlex 搜索与字段完整性
- Semantic Scholar recommendations 是否可用
- Crossref 元数据补全效果
- Unpaywall OA 链接获取效果

#### P0-4：模型任务验证
验证：
- claim extraction JSON 稳定性
- paper summary JSON 稳定性
- hypothesis verify 的拒真率和错杀率

### 验收标准

- 至少 70% 样本论文可得到可用结构化解析
- 至少 3 个外部学术源可稳定返回结果
- 至少 3 个核心 prompt 可输出稳定 JSON
- 团队确认首版采用的技术栈

---

## Phase 1（Week 3~6）：闭环 MVP

### 目标
做出“可以真实跑完一次自动科研任务”的第一个版本。

### Epic 1：任务管理与运行控制

#### Backlog
- 创建 `research_run`
- 任务状态机
- 上传 PDF
- 运行基本事件流
- Pause / Resume API（可先做软暂停）

#### 验收
- 用户可以在 UI 上发起一个 Run
- 系统会进入 queued/running/completed 等状态
- UI 能看到基础事件

---

### Epic 2：种子论文摄取

#### Backlog
- 文件存储
- PDF 解析
- `paper`, `paper_version`, `chunk` 表落地
- metadata resolve
- 基础 reference normalize

#### 验收
- 上传 5 篇 PDF 后，系统能看到 paper cards、章节结构和 chunks

---

### Epic 3：自动扩展与排序

#### Backlog
- query builder
- OpenAlex adapter
- Semantic Scholar adapter
- Crossref adapter
- dedup merge
- 基础 ranking

#### 验收
- 输入 5 篇 seed 后，至少能扩展出 30+ 候选论文元数据
- 能给出基本排序结果

---

### Epic 4：深读与基础报告

#### Backlog
- fulltext/abstract-only 分支
- paper structured summary
- 初版 Markdown report exporter
- 论文表导出

#### 验收
- 能输出一版基础综述 Markdown
- 报告中能列出代表论文与方法分类

---

## Phase 2（Week 7~8）：证据化、审计与恢复

### 目标
把“能跑”升级成“可信、可追溯、可恢复”。

### Epic 5：claim / evidence 管线

#### Backlog
- claim schema
- evidence quote
- page span
- `claim` 表与 `claim_relation` 基础能力
- evidence browser MVP

#### 验收
- 关键摘要项都能追到 paper/chunk/evidence

---

### Epic 6：checkpoint 与恢复

#### Backlog
- LangGraph DB checkpointer
- step idempotency key
- retry policy
- failed step replay
- soft/hard pause 机制

#### 验收
- 模拟 worker 崩溃后，Run 能恢复
- 用户中断后能 resume

---

### Epic 7：审计与追踪

#### Backlog
- run_event
- prompt_hash
- model / adapter trace
- step latency & cost records
- 基础 metrics dashboard

#### 验收
- 能从 UI 或后台日志追到任一步的输入 / 输出 / 错误

---

## Phase 3（Week 9~11）：矛盾、空白与创新点引擎

### 目标
把系统从“综述生成器”升级成“研究洞察生成器”。

### Epic 8：主题聚类

#### Backlog
- paper embedding summary
- clustering
- cluster labeling
- coverage map

#### 验收
- 每次 Run 能产出主题簇与簇标签

---

### Epic 9：矛盾与 gap mining

#### Backlog
- candidate claim pair generator
- contradiction judge
- limitation/future_work aggregator
- gap detector

#### 验收
- 每个 Run 至少产出：
  - 争议点列表
  - 未覆盖区域列表
  - 为什么判定为 gap 的说明

---

### Epic 10：innovation cards + verifier

#### Backlog
- innovation generation templates
- prior-art query builder
- novelty / feasibility / risk scoring
- hypothesis workbench UI

#### 验收
- 每个 Run 至少能输出 3 个经过 verifier 的 innovation cards
- 至少每个 card 含支持证据、反证风险、实验草案

---

## Phase 4（Week 12~14）：评测、性能、上线准备

### 目标
把系统从“内部 demo”提升到“可内测使用”。

### Epic 11：评测体系

#### Backlog
- benchmark case set
- retrieval relevance annotation
- parser quality annotation
- hypothesis acceptance annotation
- regression pipeline

#### 验收
- 每次发版都能跑 benchmark
- 能比较版本提升 / 退化

---

### Epic 12：性能与成本控制

#### Backlog
- source query cache
- LLM output cache
- embedding cache
- batch ingest
- concurrency limits
- budget alarms

#### 验收
- 平均 Run 成本有上限
- 平均时长可预测
- 失败重试不会无限放大成本

---

### Epic 13：发布与 runbook

#### Backlog
- staging -> prod 流程
- oncall runbook
- data retention 策略
- backup strategy
- export & restore
- 内测文档

#### 验收
- 新环境可一键启动
- 问题排查路径明确
- 内测用户可使用

---

## 6. Sprint 级拆解（示例）

## Sprint 1
- 项目 skeleton
- 数据库 schema v1
- 文件上传
- GROBID 本地 PoC
- OpenAlex adapter v1

## Sprint 2
- `research_run` 状态机
- seed ingest pipeline
- chunking
- basic UI console
- Crossref resolve

## Sprint 3
- S2 adapter
- dedup merge
- ranking v1
- Markdown report v1

## Sprint 4
- claim extraction
- evidence binding
- event stream
- pause / resume v1

## Sprint 5
- clustering
- contradiction detector
- gap miner v1

## Sprint 6
- innovation cards
- verifier
- hypothesis UI

## Sprint 7
- benchmark pipeline
- caching
- tracing
- performance tuning

---

## 7. 任务分工建议

## 7.1 后端

负责：

- schema
- API
- workflow runtime
- adapters
- object storage
- run_event
- 导出

## 7.2 Agent / 算法

负责：

- prompt 设计
- claim extraction
- ranking signal
- contradiction judge
- innovation + verifier
- benchmark 与评测

## 7.3 前端

负责：

- composer
- live console
- evidence browser
- hypothesis workbench
- graph explorer（Phase 2）

## 7.4 平台 / DevOps

负责：

- 环境
- secrets
- deploy
- trace / metrics
- backup / restore
- 配额与成本告警

---

## 8. 测试与评测策略

## 8.1 测试分层

### 1) 单元测试
覆盖：

- dedup logic
- title normalization
- score calculation
- pause gate logic
- serialization / deserialization

### 2) 适配器集成测试
对每个外部源验证：

- 成功返回
- 字段映射
- 限流重试
- 失败时 graceful degradation

### 3) Prompt Contract Tests
固定输入 -> 验证：

- JSON 能否通过 schema
- 字段是否完整
- evidence 是否存在
- 不出现 forbidden 字段

### 4) End-to-End Tests
从创建 Run 到导出结果全链路打通。

### 5) Regression Benchmarks
对固定 case set 比较不同版本：

- retrieval quality
- evidence coverage
- innovation usefulness
- cost / latency

---

## 8.2 Benchmark 数据集建议

每个 benchmark case 包含：

- topic
- seed papers
- gold related papers（人工整理 20~50 篇）
- gold representative clusters
- gold contradictions（可选）
- gold useful hypotheses（可选）

至少覆盖 8 类 case：

1. 新兴方向
2. 已高度成熟方向
3. 容易跑偏方向
4. 负结果多的方向
5. preprint 多于正式发表的方向
6. benchmark 驱动方向
7. 多子路线并存方向
8. 与用户目标高度约束的方向

---

## 8.3 建议评估指标

### 解析层
- title exact match
- citation resolve success rate
- parse usable rate

### 检索层
- Recall@20
- Precision@20
- Cluster coverage score
- Novelty search recall（能否找出潜在已有工作）

### 分析层
- Claim evidence alignment rate
- Contradiction precision
- Gap usefulness rating

### 创新点层
- Hypothesis acceptance rate
- Prior-art miss rate
- Reviewer usefulness score（1~5）

### 平台层
- Mean run duration
- Mean cost per run
- Pause/resume success rate
- Step retry success rate

---

## 9. 发布策略

## 9.1 内测发布

建议先只面向内部研究团队或 5~10 名种子用户。

目标：
- 观察真实使用方式
- 收集哪些地方最常中断
- 看创新点是否真的有价值
- 看哪里最耗时 / 最不稳

### 内测门槛

- 至少 10 个 benchmark case 可跑通
- 核心 Run 恢复能力可用
- evidence 浏览可用
- innovation card 有 prior-art verify
- 成本可控

---

## 9.2 灰度发布

发布策略：

1. 先对部分 workspace 开启
2. 限制并发 Run
3. 限制每次最大深读数
4. 开启更严格的自动暂停策略
5. 观察 1~2 周后再放开

---

## 10. 上线运行手册（Runbook）建议

## 10.1 常见告警

- 外部学术源持续 429
- GROBID 解析失败率升高
- 某模型 JSON 失败率升高
- run_event 写入延迟
- embedding queue backlog 堆积
- 单 Run 成本异常升高

## 10.2 一线排查顺序

1. 看 run_event timeline
2. 看 step trace
3. 看外部 adapter 错误率
4. 看缓存命中
5. 看模型 JSON 失败原因
6. 看 parser 原始 artefact

## 10.3 人工干预手段

- 暂停某类 source adapter
- 临时切换 fallback model
- 限制深读并发
- 关闭某类 query 模板
- 强制进入 abstract-only 模式

---

## 11. 风险控制与决策门

## 11.1 研发过程中的关键决策门

### Gate 1：PoC 通过否
必须确认：
- 解析可用
- 学术源可用
- Prompt JSON 稳定

### Gate 2：MVP 可用否
必须确认：
- 可真实跑完一次 topic
- 输出不是空洞文本
- 用户可看到过程

### Gate 3：创新点模块上线否
必须确认：
- verifier 已接入
- 不会裸生成
- prior-art 搜索效果可接受

### Gate 4：对外发布否
必须确认：
- benchmark 稳定
- 恢复可用
- 成本告警到位
- 基础安全与权限完整

---

## 11.2 常见失败模式与应对

| 失败模式 | 现象 | 应对 |
|---|---|---|
| 解析污染 | chunk 杂乱、claim 无法抽取 | parser fallback + section 清洗 |
| 检索漂移 | 候选越来越偏题 | retrieval drift gate + query rewrite |
| 同源重复 | 同一论文多次进入队列 | canonical merge + title fingerprint |
| 创新点空泛 | hypothesis 像 brainstorm | 强制 verifier + evidence minimum |
| 成本失控 | 单 Run 读太多论文 | budget gates + top-k reading |
| 用户不信任 | 不知道系统为什么这么做 | event timeline + evidence browser |

---

## 12. 建议的仓库结构

```text
research-os/
  apps/
    api/
    worker/
    web/
  libs/
    schemas/
    prompts/
    adapters/
    ranking/
    evaluation/
  services/
    parser/
    llm_gateway/
    retrieval/
  infra/
    docker/
    k8s/
    terraform/
  scripts/
    benchmark/
    migration/
  docs/
    product/
    architecture/
    runbooks/
```

---

## 13. 版本路线图（上线后）

## v1.1
- 更好的 coverage map
- 更好的 prior-art 检查
- 更稳定的 evidence browser

## v1.2
- 周期性 topic refresh
- 团队共享研究空间
- graph explorer

## v1.5
- Neo4j 图投影
- 更复杂的桥接发现算法
- 更细粒度权限与配额

## v2.0
- Temporal 化或更强 durable workflow
- 多项目知识复用
- 自动 proposal 生成
- 半自动实验设计接口

---

## 14. 最终建议

Research OS 这类系统最容易犯的错误，是把大量时间花在“让 agent 看起来很聪明”，却没有花在：

- 运行可恢复
- 数据可沉淀
- 证据可追溯
- 版本可回归
- 创新点可被批判

所以交付优先级必须是：

### 第一优先级
- 闭环
- 状态机
- 数据模型
- 审计

### 第二优先级
- evidence
- contradiction
- innovation verifier

### 第三优先级
- 图探索高级能力
- 大规模扩容
- 更复杂多 agent 协作

---

## 15. 项目经理视角的一句话总结

如果这 14 周只能保证三件事，请优先保证：

1. 系统能自动跑完一个真实研究任务  
2. 关键结论都能追到证据  
3. 用户能在任何时刻看见、暂停、恢复和纠偏  

只要这三件事站住，Research OS 就已经具备产品价值；之后的复杂能力，都只是建立在这个底座上的迭代。
