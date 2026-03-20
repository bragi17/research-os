# 99. References —— 外部参考资料与技术决策依据

生成日期：2026-03-16  
说明：本文件用于帮助实施团队验证本方案中涉及的外部技术能力与接口约束。下面列的是在设计阶段重点参考的公开文档或官方说明。

---

## 1. OpenAI

### 1.1 Responses API Overview
用途：
- 作为统一模型接口
- 支持 stateful interactions、tool calling、built-in tools

链接：
- https://developers.openai.com/api/reference/responses/overview

### 1.2 Background mode
用途：
- 长任务异步执行
- 适合多分钟级研究子任务

链接：
- https://developers.openai.com/api/docs/guides/background

### 1.3 Deep Research Guide
用途：
- 了解 deep research 模式的长任务特征
- `max_tool_calls` 控制工具调用数
- background mode / webhook 建议

链接：
- https://developers.openai.com/api/docs/guides/deep-research

---

## 2. LangGraph / Durable Execution

### 2.1 LangGraph Durable Execution
用途：
- 理解 checkpoint、pause/resume、idempotent task 设计

链接：
- https://docs.langchain.com/oss/python/langgraph/durable-execution

### 2.2 LangGraph Human-in-the-loop / interrupt
用途：
- 设计用户中断、审批、恢复语义
- 使用 `interrupt()` 与 `Command(resume=...)`

链接：
- https://github.langchain.ac.cn/langgraph/agents/human-in-the-loop/

---

## 3. Temporal（生产升级参考）

### 3.1 Temporal Workflows
用途：
- 当需要更强 durable workflow、跨服务长期编排时作为升级参考

链接：
- https://docs.temporal.io/workflows

---

## 4. 学术数据源

### 4.1 OpenAlex
用途：
- works 元数据
- 引用 / 被引 / topic / OA location
- 搜索、过滤、排序、分组

链接：
- https://developers.openalex.org/
- https://developers.openalex.org/api-reference/works

### 4.2 Semantic Scholar Recommendations API
用途：
- 基于已知论文做推荐扩展
- 作为相似论文和相关工作扩展补充源

链接：
- https://api.semanticscholar.org/api-docs/recommendations

### 4.3 Crossref REST API
用途：
- DOI 与学术元数据校对
- funding / license / relationships / abstracts 等字段补充

链接：
- https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- https://api.crossref.org/

### 4.4 Unpaywall REST API
用途：
- 判断 OA 状态
- 获取开放获取全文线索
- 记录 license 与 OA provenance

链接：
- https://unpaywall.org/products/api

---

## 5. PDF 解析

### 5.1 GROBID Documentation
用途：
- 学术论文 PDF 的结构化解析
- 段落、章节、参考文献、图表说明、坐标信息提取

链接：
- https://grobid.readthedocs.io/en/latest/Introduction/

---

## 6. 检索与图分析

### 6.1 Qdrant Hybrid Queries
用途：
- 当 corpus 规模增大时，作为 vector 检索与 hybrid / multi-stage query 升级方向

链接：
- https://qdrant.tech/documentation/concepts/hybrid-queries/

### 6.2 Neo4j Documentation
用途：
- 图数据建模、Cypher 查询、图数据科学与向量索引相关能力
- 用于 citation/claim graph 的高级分析与可视化升级

链接：
- https://neo4j.com/docs/

---


## 6.3 arXiv API Access / User Manual
用途：
- 设计 arXiv 检索与元数据接入
- 了解可通过 API 做论文查询与获取基础元数据

链接：
- https://info.arxiv.org/help/api/index.html
- https://info.arxiv.org/help/api/user-manual.html

## 6.4 arXiv Viewing / Source / Unpacking
用途：
- 确认论文 Source 下载形态
- 支持 figure/source extraction pipeline 设计
- 为图文并茂展示与内部教学用途提供技术参考

链接：
- https://info.arxiv.org/help/view.html
- https://info.arxiv.org/help/unpack.html
- https://info.arxiv.org/help/license/reuse.html

## 6.5 OpenAI Cookbook: Deep Research API
用途：
- 参考 Deep Research 风格的研究型工作流
- 评估 multi-step research agent 的交互方式与输出形式

链接：
- https://developers.openai.com/cookbook/examples/deep_research_api/introduction_to_deep_research_api
- https://developers.openai.com/cookbook/examples/deep_research_api/introduction_to_deep_research_api_agents

## 7. 本方案与参考资料的映射关系

| 本方案中的决策 | 参考资料 |
|---|---|
| 长任务异步执行与 webhook 设计 | OpenAI Background mode / Deep Research |
| Responses API 作为统一模型接口 | Responses API Overview |
| LangGraph checkpoint 与 interrupt 机制 | LangGraph Durable Execution / HIL |
| 生产级 durable workflow 升级路线 | Temporal Workflows |
| OpenAlex 作为主学术图谱来源 | OpenAlex Works API |
| Semantic Scholar 做 recommendations 扩展 | Semantic Scholar Recommendations API |
| Crossref 做 DOI / metadata resolve | Crossref REST API |
| Unpaywall 做 OA 检查 | Unpaywall REST API |
| GROBID 解析学术 PDF | GROBID Documentation |
| Qdrant 作为后续检索升级方案 | Qdrant Hybrid Queries |
| Neo4j 作为图分析升级方案 | Neo4j Documentation |

---

## 8. 实施团队阅读建议

### 产品 / 研发负责人优先看
- OpenAI Background mode
- LangGraph Durable Execution
- OpenAlex Works API

### 后端 / 平台优先看
- LangGraph Durable Execution
- Temporal Workflows
- Crossref REST API
- Unpaywall REST API

### 算法 / Agent 工程师优先看
- Responses API Overview
- Deep Research Guide
- OpenAlex Works API
- Semantic Scholar Recommendations API

### 检索 / 图工程优先看
- Qdrant Hybrid Queries
- Neo4j Documentation

---

## 9. 备注

1. 外部 API 的配额、字段与可用性可能变化，落地时应通过适配器层做隔离。  
2. 首版不要把系统设计死在某一个模型名、某一个数据库或某一个学术源上。  
3. 参考资料的作用是验证能力边界，而不是限制你们的工程实现。  
4. 生产环境中，所有外部依赖都应有：
   - retry
   - timeout
   - cache
   - circuit breaker
   - graceful degradation
