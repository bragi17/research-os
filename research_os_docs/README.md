# Research OS 设计与实施包

生成日期：2026-03-16  
文档用途：作为 `Research OS` 的产品需求文档（PRD）、系统设计文档（SDD）与实施计划，供产品、后端、算法、前端、平台与测试团队直接评审和落地。

---

## 1. 包内文档

1. `01_PRD.md`  
   产品目标、范围、用户场景、功能需求、非功能需求、交互与验收标准。

2. `02_Architecture_and_Data_Model.md`  
   系统架构、技术栈、服务划分、数据模型、API、事件流、存储设计、可观测性与安全策略。

3. `03_Agents_Workflows_and_Prompts.md`  
   Agent 拆分、端到端工作流、节点状态、提示词模板、JSON Schema、检索与创新点生成算法细节。

4. `04_Delivery_Plan_and_Backlog.md`  
   分阶段建设计划、Sprint 拆解、测试与评估方案、上线流程、组织分工与风险控制。

5. `05_SemanticScholar_API_Integration_Update.md`  
   基于 Semantic Scholar 官方 API 的方案增强文档，补充在线检索、推荐扩展、引文语义边、snippet evidence、本地镜像与增量同步实施细节。

6. `99_References.md`  
   公开技术文档与外部参考资料列表，方便实施团队对照验证。

---

## 2. 推荐阅读顺序

- 第一步：看 `01_PRD.md`，统一产品定义、边界与成功标准
- 第二步：看 `02_Architecture_and_Data_Model.md`，明确系统如何搭建
- 第三步：看 `03_Agents_Workflows_and_Prompts.md`，明确自动科研真正怎么跑
- 第四步：看 `04_Delivery_Plan_and_Backlog.md`，安排研发节奏、团队协作和验收
- 第五步：看 `05_SemanticScholar_API_Integration_Update.md`，把 S2 接入方案、限流策略、在线/离线双态检索与数据镜像设计对齐
- 第六步：需要对照外部能力时，看 `99_References.md`

---

## 3. 一页结论（建议直接给团队对齐）

### 3.1 产品定位

Research OS 不是“聊天式论文助手”，而是一个**可持续运行、可实时观察、可中断恢复、证据可追溯**的自动科研操作系统。  
它的目标不是只回答一个问题，而是围绕一个研究方向持续执行以下循环：

- 接收研究主题与种子论文
- 解析全文、抽取段落与 claim
- 自动扩展引用链与相关论文池
- 构建 RAG 与 citation / claim graph
- 聚类、找矛盾、找空白
- 生成并批判创新点
- 输出综述、研究路线图、实验建议
- 全程你只观察，只有在命中策略时才需要介入

### 3.2 基线实现建议（最可落地）

**首发版本（MVP / v1.0）推荐：**

- 后端：Python 3.12 + FastAPI
- 前端：Next.js + TypeScript
- 工作流：LangGraph
- 持久化：Postgres 16
- 向量检索：pgvector + Postgres `tsvector` 混合检索
- 缓存 / 队列：Redis
- 对象存储：S3 / MinIO
- PDF 解析：GROBID + PyMuPDF
- 学术数据源：OpenAlex + Semantic Scholar + Crossref + Unpaywall
- LLM：OpenAI Responses API（长任务用 background mode；开放网络研究子任务可接 deep research 能力）
- 图分析：Phase 1 先存在 Postgres 边表；Phase 2 再复制到 Neo4j 做高级图分析
- 可观测性：OpenTelemetry + Langfuse（或同类 tracing）+ Prometheus/Grafana

### 3.3 为什么这样选

- **LangGraph** 适合先把 agent 状态图、持久化、中断恢复跑起来
- **Postgres + pgvector** 最省工程复杂度，适合前期快速落地
- **GROBID** 适合学术 PDF 结构化解析
- **OpenAlex / S2 / Crossref / Unpaywall** 组合可以覆盖元数据、引用关系、推荐、开放获取
- **OpenAI Responses API** 适合多步 tool orchestration；长任务可切 background mode
- **Neo4j / Qdrant** 不建议 Day 1 就上，建议在吞吐与图分析需求上来后再演进

### 3.4 一个核心原则

这个系统必须是：

- **默认自动执行**
- **策略触发才暂停**
- **任何结论都要有证据链**
- **任何步骤都能中断和恢复**
- **任何创新点都要先过 prior-art 与反证检查**

---

## 4. 推荐的实施策略

### Phase 0：做“闭环最小样机”，不要一开始追求大而全

先打通最小闭环：

1. 用户输入主题 + 3~10 篇种子论文
2. 自动解析与入库
3. 自动扩展 30~100 篇相关论文
4. 自动生成结构化综述与创新点卡片
5. 前端能实时看进度、看证据、暂停、恢复

### Phase 1：把“自动跑起来”做到稳定

重点不是“更聪明”，而是：

- 长任务不丢
- 节点可重试
- 任何输出可回溯
- 证据绑定到段落 / 页码 / paper_id
- 出错时可恢复而不是重头跑

### Phase 2：把“创新点质量”做起来

不是让模型自由发挥，而是：

- 先找主题簇
- 再找矛盾和盲点
- 再生成候选 hypothesis
- 再做 prior-art 检查、可行性检查、实验设计检查
- 最后形成 innovation cards

---

## 5. 交付建议

建议你把这套包按下面方式发给团队：

- `01_PRD.md` 给产品、技术负责人、前端负责人
- `02_Architecture_and_Data_Model.md` 给后端、平台、数据工程
- `03_Agents_Workflows_and_Prompts.md` 给算法 / Agent / 搜索 / LLM 工程师
- `04_Delivery_Plan_and_Backlog.md` 给研发经理、测试、项目管理
- `99_References.md` 给需要做技术验证的负责人

如果团队希望直接开工，优先把以下 5 个 Epic 建起来：

1. 研究任务与运行控制台
2. 论文解析与证据入库
3. 学术检索与引用扩展
4. 结构化总结 / 争议分析 / 创新点生成
5. 中断恢复 / tracing / 评估

---

## 6. 实施注意事项

- 不要把系统做成“一个超大 prompt 的万能 agent”
- 不要只做普通向量库，不做结构化 evidence graph
- 不要只做论文摘要，不抽取 limitation / assumption / failure mode
- 不要在没有停止条件的情况下无限扩展论文
- 不要把“创新点”当成一次性 brainstorm 结果
- 不要忽略 prompt injection、版权与来源可信度

---

## 7. 文档约定

- `Run`：一次研究任务的完整执行实例
- `Step`：Run 内某一个可恢复、可重试的节点
- `Paper`：规范化后的论文主记录
- `Chunk`：用于检索的段落 / 小节片段
- `Claim`：从论文中抽取的结构化断言
- `Evidence`：支持某个结论的原文证据
- `Hypothesis`：候选创新点或研究假设
- `Coverage`：对某个主题空间的覆盖程度
- `Saturation`：继续检索带来的边际信息增益是否已明显下降

---

## 8. 最后建议

如果你的团队规模有限，最稳的路径不是一开始就做“终极多智能体平台”，而是：

- 先做 **单工作流、多节点、强审计** 的 v1
- 再逐步增加更复杂的图分析、对抗检索、自动实验设计
- 把复杂度花在“可恢复与可解释”上，而不是花在“看起来很 agentic”上

这套文档默认就是按这个顺序设计的。
