# 05. Semantic Scholar API Integration Update —— 基于 Semantic Scholar 官方 API 的 Research OS 检索、引文图谱与本地镜像增强方案

版本：v1.1  
日期：2026-03-19  
适用对象：架构师、后端工程师、检索工程师、数据工程师、Agent 工程师、平台工程师  
关联文档：`01_PRD.md` / `02_Architecture_and_Data_Model.md` / `03_Agents_Workflows_and_Prompts.md` / `04_Delivery_Plan_and_Backlog.md`

---

## 0. 执行摘要

### 0.1 结论

你已经拿到 Semantic Scholar API Key，这非常值得纳入 Research OS 的核心方案。  
**推荐决策：将 Semantic Scholar（后文简称 S2）升级为 Research OS 的“主在线学术发现与引文图谱提供者”，但不要把它设计成唯一数据后端。**

原因很直接：

1. S2 官方同时提供：
   - `Academic Graph API`：论文、作者、引用、参考文献、元数据、开放获取信息等
   - `Recommendations API`：基于 seed papers 的推荐
   - `Datasets API`：全量数据集下载与增量 diffs
   - `Snippet Search`：直接检索论文标题/摘要/正文片段  
   这几套能力正好覆盖 Research OS 的“找论文 -> 扩图 -> 深读 -> 证据绑定 -> 创新点分析”的主链路。[S2-1][S2-2][S2-3]

2. S2 的引用接口不只是返回“谁引用了谁”，还可以返回：
   - `contexts`
   - `intents`
   - `isInfluential`  
   这对你原方案里“不是只看 citation edge，而是看引用语义、引用上下文和影响力”的目标很关键。[S2-4][S2-5]

3. S2 官方还支持：
   - `paper/search/bulk` 的大规模布尔召回
   - `paper/batch` 的批量 hydrate
   - `datasets` 的本地镜像
   - `diffs` 的增量更新  
   因此它既适合在线检索，也适合规模化本地索引建设。[S2-3][S2-6]

### 0.2 但必须注意一个关键约束

**不要把“有 API Key”误解为“可以直接拿 S2 当高吞吐在线数据库”。**  
官方教程与 Overview 都强调：推荐始终带上 API Key，请求头是大小写敏感的 `x-api-key`；同时，带 key 的账户初始速率是 **1 request per second across all endpoints**。未认证请求虽然共享一个更高的公共池，但会受到公共流量影响，生产系统不应该依赖它。[S2-2][S2-7]

这意味着新的正确架构不是：

> Agent 直接疯狂打 S2 接口，边跑边在线扩整张图。

而是：

> **在线模式：S2 API 做高价值检索、seed 扩展、批量补全、局部图扩展**  
> **离线模式：S2 Datasets + Diffs 做本地镜像与大规模图谱/索引更新**

也就是说，**S2 非常适合做你的“主 scholarly graph provider”，但前提是采用“在线 API + 本地镜像”的双层模式。**

### 0.3 对原 Research OS 的核心修改

相对你原方案，建议新增或修改如下：

- 将 `SemanticScholarAdapter` 升级为 **`S2 Gateway` 独立服务**
- 在检索路径中优先用：
  - `paper/search/bulk` 做布尔召回
  - `paper/search` 做小规模高质量相关性搜索
  - `recommendations` 做 seed 扩展
  - `citations/references` 做局部图扩展
  - `paper/batch` 做批量 hydrate
  - `snippet/search` 做证据补片
- 将本地数据层新增为：
  - `S2 papers`
  - `S2 abstracts`
  - `S2 citations`
  - `S2 paper-ids`
  - `S2 embeddings-specter_v2`
  - 可选 `S2 s2orc_v2`
- 图边新增字段：
  - `contexts`
  - `intents`
  - `is_influential`
  - `source_provider = 's2_api' | 's2_dataset'`
- Agent 工作流新增：
  - `seed 正负样本推荐扩展`
  - `citation-context aware rerank`
  - `snippet evidence fallback`
  - `provider-level rate limiter / batch hydrator / dataset sync`
- 架构层面新增“provider token bucket + query cache + local mirror sync job”

---

## 1. 为什么 S2 会显著增强你的原方案

你原方案的核心目标有四件事：

1. 用户给方向和参考文献
2. Agent 自动扩展相关论文池
3. 把全文段落和 claim 放进 RAG / graph
4. 基于引文关系和论文内容做总结、矛盾分析、创新点生成

S2 对这四步的增强分别是：

### 1.1 对“找论文”的增强

S2 不是只有关键词搜索。它实际上提供三种不同性质的找论文方式：

- `paper/search`：带相关性排序的搜索，适合少量高质量结果
- `paper/search/bulk`：适合批量召回，支持布尔逻辑、短语、前缀、模糊、短语间距等 query syntax
- `recommendations`：基于 seed paper 或正负样本 paper 列表做推荐  
  这三者的组合，可以把你原来的“关键词 + OpenAlex 相似项”方案，提升为“关键词召回 + seed 扩展 + 图邻域扩展”的三路召回体系。[S2-3][S2-8][S2-9]

### 1.2 对“扩图”的增强

你原来就想利用引用关系继续 deep research。  
S2 的优势是它不仅能拿到 reference / citation 列表，还能拿到：

- 哪段文本里提到了被引文（`contexts`）
- 这次引用是什么意图（`intents`）
- 这次引用是否被判定为“影响力引用”（`isInfluential`）  
  这就使得“引文图谱”从普通的无语义边，升级成“带语义的 citation edge”。[S2-4][S2-5][S2-6]

### 1.3 对“证据检索”的增强

S2 的 `snippet/search` 可以直接从标题、摘要和正文片段中返回与查询最相关的大约 500 词左右的文本片段，并且还能附带 paper 基本信息、section、sentence spans、ref mentions 等结构。  
这非常适合：

- 在没有 PDF / PDF 解析失败时补证据
- 在 RAG 之前快速验证某个 claim 是否值得入队深读
- 给 synthesis / critic agent 提供“查询到证据片段”的能力  
  这项能力本身就能减少大量无效全文解析。[S2-10]

### 1.4 对“规模化”的增强

S2 Datasets API 不是只能下全量，还能：
- 列出 releases
- 拿 latest release
- 下载指定 dataset
- 使用 `diffs/{start}/to/{end}/{dataset}` 做增量更新  
  这意味着你可以把 S2 建成一个**持续更新的本地 scholarly warehouse**，不必每次都在线扫图。[S2-3][S2-6]

---

## 2. 官方 API 能力地图与在 Research OS 中的定位

下面是建议你直接纳入实施方案的接口分层。

### 2.1 第一层：在线检索与图扩展

| 接口 | 官方定位 | 你系统中的用途 | 关键限制 / 注意点 |
|---|---|---|---|
| `GET /graph/v1/paper/search` | relevance search | 小规模高质量结果；前台即时查询；候选集合精修 | 最多返回 1,000 个 relevance-ranked 结果；更大查询请用 bulk 或 datasets。[S2-8] |
| `GET /graph/v1/paper/search/bulk` | bulk retrieval | 大规模召回主入口；适合后台批量找论文 | 单次最多 1,000 条；可继续用 token 分页；总计最多 10,000,000 条；不返回 nested citation/reference 数据。[S2-9] |
| `GET /graph/v1/paper/search/match` | title match | seed 论文标题归一化；补 DOI / paperId / corpusId | 单篇 closest title match。[S2-9] |
| `POST /graph/v1/paper/batch` | batch hydrate | 批量补论文元数据；批量拿 authors / abstract / counts / openAccess / embeddings 等 | 单次最多 500 个 ids；响应最大 10MB；批量字段里 citation/reference 最多 9999。[S2-11] |
| `GET /graph/v1/paper/{paper_id}` | single paper details | 种子论文规范化；高价值节点详情 | 支持多种 ID 格式（DOI/ARXIV/CorpusId/URL 等）。[S2-4][S2-12] |
| `GET /graph/v1/paper/{paper_id}/citations` | citing papers | 向前扩图（谁引用了这篇） | 支持 pagination、publicationDateOrYear、`contexts/intents/isInfluential` 字段。[S2-4] |
| `GET /graph/v1/paper/{paper_id}/references` | cited papers | 向后扩图（这篇引用了谁） | 支持 pagination、`contexts/intents/isInfluential`。[S2-5] |
| `POST /recommendations/v1/papers` | multi-seed recommendations | 基于 positive / negative paperIds 的受控扩展 | limit 最大 500；非常适合你的 seed-guided deep research。[S2-1][S2-13] |
| `GET /recommendations/v1/papers/forpaper/{paper_id}` | single-seed recommendations | 单种子快速扩展 | `from` 支持 `recent` / `all-cs`。[S2-13] |
| `GET /graph/v1/snippet/search` | snippet search | 证据片段检索；没有 PDF 时的 fallback；快速 claim 验证 | 必须提供 query；limit 默认 10，最大 1000；不支持特殊 query syntax。[S2-10] |

### 2.2 第二层：离线镜像与本地图谱建设

| 接口 / 数据集 | 你系统中的用途 | 说明 |
|---|---|---|
| `GET /datasets/v1/release/` | 获取所有 release | 用于数据同步控制面。[S2-6] |
| `GET /datasets/v1/release/latest` | 获取最新 release 元信息 | 用于调度器判断是否需要同步；官方可用 release 列表在我检索时已更新到 2026-03-10。[S2-14] |
| `GET /datasets/v1/release/{id}/dataset/{dataset}` | 下载指定数据集 | 需要 API Key；返回预签名下载链接。[S2-3][S2-15] |
| `GET /datasets/v1/diffs/{start}/to/{end}/{dataset}` | 增量同步 | 用于每周 / 每日增量更新本地仓库。[S2-6][S2-15] |
| `papers` | 本地论文主表 | title/authors/date/venue/counts 等核心元数据。[S2-16] |
| `abstracts` | 本地摘要库 | 用于无需全文时的快速语义筛选。[S2-16] |
| `citations` | 本地引文边表 | 含 contexts / intents / influential，价值极高。[S2-16] |
| `paper-ids` | ID 映射表 | `paperId <-> corpusId <-> sha` 等映射。[S2-16] |
| `embeddings-specter_v2` | 论文级向量 | 用于 paper-to-paper graph 检索和相似召回。[S2-16] |
| `s2orc_v2`（可选） | 解析后的正文 | 当你要做大规模全文级分析时启用；成本较高。[S2-16] |
| `authors` / `publication-venues`（可选） | 作者 / venue 分析 | 适合做作者群体、venue 趋势和权威性建模。[S2-16] |

---

## 3. 对原架构文档的结构性修改建议

本节可以直接作为对 `02_Architecture_and_Data_Model.md` 的补丁。

### 3.1 新增一个独立服务：`s2-gateway`

不建议继续把 S2 仅作为一个薄薄的 Adapter。  
建议把它升级为独立服务，因为它会负责：

- API key 认证与轮换
- provider 级限流
- 批量聚合
- 响应缓存
- provider 级错误分类
- online API 与 offline mirror 的统一读入口
- 统一 ID 解析（DOI / ArXiv / URL / title -> S2 paperId / corpusId）

建议服务职责如下：

```text
s2-gateway
├── identity-resolver
├── search-client
├── recommendations-client
├── citation-graph-client
├── snippet-client
├── dataset-sync-client
├── rate-limit-manager
├── response-cache
└── provider-health-monitor
```

### 3.2 在原“Scholar Search Adapter Layer”基础上新增的分层

原文档中的 `Scholar Search Adapter Layer` 建议拆成两层：

#### A. Provider Connectors（供应商直连层）
- `OpenAlexConnector`
- `SemanticScholarConnector`
- `CrossrefConnector`
- `UnpaywallConnector`

#### B. Scholar Fusion Layer（融合层）
- `PaperIdentityResolver`
- `CandidateFusionService`
- `CitationGraphMergeService`
- `EvidenceSourcePlanner`
- `ProviderScoreNormalizer`

这样做的原因是：  
S2 在你的系统里将不再只是“另一个 metadata provider”，而是“高优先级的图谱 provider + 在线推荐 provider + 数据镜像 provider”。

### 3.3 新增“在线与离线双态”设计

建议把外部学术数据访问分成两种模式：

#### 在线模式（Online Discovery Mode）
适合：
- 用户刚发起任务
- 新 topic 首次探索
- 需要快速围绕 seed papers 扩展
- 需要拿 citation contexts / intents
- 需要 snippet evidence

#### 离线模式（Mirror / Warehouse Mode）
适合：
- 大规模回溯历史文献
- 高频 agent 自动跑批
- 复杂图分析
- 大范围聚类和 prior-art 覆盖检测
- 降低外部 API 依赖与成本

系统应由 `Scholar Access Policy` 自动决定当前 step 使用哪种模式，而不是让 agent 自己随意选。

---

## 4. 新的端到端检索与扩图流程

这一节可直接替换原工作流中“retrieval + expansion”部分。

### 4.1 Step A：Seed 论文规范化

输入可能是：
- DOI
- arXiv ID
- S2 paperId
- 论文标题
- URL
- PDF 中解析出来的 title

#### 建议流程

1. **如果已有 DOI / ArXiv / URL / corpusId**
   - 直接调用 `GET /graph/v1/paper/{paper_id}`
   - 支持多种 ID 格式，包括 `DOI:...`、`ARXIV:...`、`CorpusId:...`、`URL:...`。[S2-4][S2-12]

2. **如果只有 title**
   - 先走 `GET /graph/v1/paper/search/match?query=...`
   - 拿 closest title match
   - 若 `matchScore` 低于阈值，再转 OpenAlex / Crossref 做交叉校验。[S2-9]

3. 统一产出：
   - `s2_paper_id`
   - `s2_corpus_id`
   - `external_ids`
   - `doi`
   - `title_normalized`

#### 规范化后建议写表

```sql
create table provider_paper_identity (
  internal_paper_uid uuid not null,
  provider text not null,              -- 'semantic_scholar'
  provider_paper_id text,
  provider_corpus_id bigint,
  doi text,
  arxiv_id text,
  url text,
  title_hash text,
  is_primary boolean not null default false,
  raw_payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (internal_paper_uid, provider)
);
```

### 4.2 Step B：主召回入口改为 `paper/search/bulk`

官方文档明确建议：  
在大多数情况下，`paper/search/bulk` 比 `paper/search` 更适合作为批量检索入口；`paper/search` 更重、更偏相关性排序，而 bulk 更适合大规模取回基础 paper data。[S2-2][S2-9]

#### 为什么适合你的系统

你的系统是 autonomous research workflow，不是用户手动翻 10 条搜索结果。  
因此更需要的是：

- 可持续分页
- 可用布尔语法控制召回边界
- 可结合年份 / 领域 / OA / venue / citation count 过滤
- 能快速给后续 reranker / graph expander 一个大的候选池

#### bulk query syntax 你可以直接纳入 query rewrite agent

官方支持：

- `+` AND
- `|` OR
- `-` NOT
- `"` phrase
- `*` prefix
- `()` precedence
- `~N` 编辑距离或 phrase slop  
  例如：
- `"retrieval augmented generation" + benchmark -survey`
- `(graph neural network | GNN) + citation`
- `"multi agent"~3 + research`  
  这些语法非常适合把 Planner 产出的 research sub-questions 翻成精细检索表达式。[S2-9]

#### 推荐的 bulk 检索策略

对每个 research topic，自动生成 3 类 query：

1. **概念覆盖 query**
   - 面向主题边界
   - 例：`("retrieval augmented generation" | rag) + evaluation`

2. **方法路线 query**
   - 面向 algorithm family
   - 例：`(reranker | retriever) + "citation recommendation"`

3. **问题/缺口 query**
   - 面向 known limitation
   - 例：`"hallucination" + benchmark + "retrieval augmented generation"`

并对每个 query 自动加过滤：

- `year=2022-`
- `fieldsOfStudy=Computer Science`
- `publicationTypes=Conference,JournalArticle,Review`
- `openAccessPdf`
- `minCitationCount=5`（可按主题动态调整）

### 4.3 Step C：用 `paper/search` 做小规模高质量精修

虽然 bulk 应该成为主召回入口，但 `paper/search` 仍然有价值。  
建议它只用于两种场景：

1. **前台即时搜索**
   - 用户点开某个子主题，想看“最相关的前 20 篇”
2. **精修 rerank**
   - 在 bulk 候选里选出一个较小范围后，再用 relevance search 做精修

原因：
- `paper/search` 是 relevance-ranked
- 但最多只能返回 1000 个结果
- 更适合小范围高相关，而不是全量扩展。[S2-8]

### 4.4 Step D：把 `recommendations` 纳入标准扩展流程

这是对原方案最关键的增强之一。

#### 多 seed 推荐接口

`POST /recommendations/v1/papers`  
请求体支持：
- `positivePaperIds`
- `negativePaperIds`  
返回按相关性降序的推荐论文；`limit` 最大 500。[S2-13]

#### 为什么比“相似 embedding 邻居”更强

你原来可以自己做 embedding 相似召回，但 S2 的 recommendation 是基于它自己的学术图谱和模型做出的推荐，通常会比纯向量近邻更贴近真实学术邻域。  
尤其是当你已经有了 2~5 篇“我想要的方向”和 1~3 篇“虽然关键词像，但其实不是我要的方向”的样本时，negative seeds 很有用。

#### 在 Research OS 中的建议用法

- Planner / Retrieval Agent 自动维护：
  - `positive_seed_papers`
  - `negative_seed_papers`
- 每一轮扩展时：
  1. 先取 top-K positive papers
  2. 加入已确认 noise papers 作为 negative seeds
  3. 调用 recommendations
  4. 将结果与 bulk search 结果做 union
  5. rerank 去重

#### 适合自动构造的 negative seeds

- 同关键词但不同应用域
- 同 benchmark 但不同 task
- 综述 / commentary / editorial
- 用户手工判定“跑偏”的论文
- verifier 判断“低价值噪声”的论文

### 4.5 Step E：将 `citations` / `references` 扩图做成“语义边增强”

官方 `citations` 和 `references` 端点都支持拿到：
- `contexts`
- `intents`
- `isInfluential`
并支持分页。[S2-4][S2-5]

#### 这会改变你的图设计

原来的 citation edge 可能只有：

```json
{
  "src_paper_id": "...",
  "dst_paper_id": "...",
  "edge_type": "cites"
}
```

现在建议升级为：

```json
{
  "src_paper_uid": "...",
  "dst_paper_uid": "...",
  "provider": "semantic_scholar",
  "edge_direction": "src_cites_dst",
  "contexts": ["..."],
  "intents": ["..."],
  "is_influential": true,
  "source_endpoint": "references",
  "retrieved_at": "2026-03-19T12:00:00Z",
  "raw_payload": {}
}
```

#### 在 ranking 中怎么用这些字段

- `is_influential = true`：提高 edge 权重
- `contexts` 与当前 research query 高相似：提高 edge 权重
- `intents` 反映“不是简单背景引用”：提高 edge 权重
- 同时出现在多篇 high-confidence papers 的高权重边：继续提高

> 这样，图扩展就不是“谁离得近就扩谁”，而是“谁在当前问题语境下被高质量、有影响力地引用”。

### 4.6 Step F：统一用 `paper/batch` 做 metadata hydrate

在 online 模式里，你会非常频繁地得到一批 candidate paper IDs。  
此时不应一个个调单篇接口，而应集中调用 `POST /graph/v1/paper/batch`。  
官方说明它支持：
- 单次最多 500 个 ids
- fields 参数可请求 authors、citations、references、embedding、openAccessPdf 等
- 但响应大小最多 10MB，且批量 nested citation/reference 最多 9999 条。[S2-11]

#### 推荐 hydrate 字段模板

对 Research OS 来说，在线 hydrate 阶段建议字段模板如下：

```text
title,abstract,year,publicationDate,venue,publicationVenue,authors,
citationCount,influentialCitationCount,referenceCount,
isOpenAccess,openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,
externalIds,tldr,embedding.specter_v2
```

说明：

- `tldr`：可作为快速摘要先验
- `embedding.specter_v2`：可作为论文级邻域特征
- `openAccessPdf`：决定是否进入全文解析队列
- `influentialCitationCount`：可作为质量信号
- `publicationVenue`：可用于 venue 权威性特征  
  官方样例与 schema 中都展示了这些字段能力。[S2-11][S2-17]

### 4.7 Step G：新增 `snippet/search` 作为证据补片层

这一步是对原 RAG 工作流很实用的加强。

#### 何时使用

1. **没有 PDF**
2. **PDF 解析失败**
3. **只想快速验证某个子问题是否值得全文深读**
4. **需要把某个 hypothesis 与原文片段快速绑定**
5. **需要找“提到某术语/方法/局限”的正文证据**

#### 推荐做法

在 Retrieval/Synthesis 阶段新增一个 `Evidence Probe` 子节点：

- 输入：query + paperIds（可选）
- 调用：`GET /graph/v1/snippet/search`
- 输出：
  - snippet text
  - section
  - sentence spans
  - ref mentions
  - paper basic info
  - score  
  这样即使论文没有开放 PDF，你仍可先用片段建立证据链。[S2-10]

---

## 5. 新的数据模型与存储设计

本节可以直接补丁到 `02_Architecture_and_Data_Model.md` 的数据设计部分。

### 5.1 核心原则

**不要把 S2 的 `paperId` 或 `corpusId` 直接当成全系统唯一主键。**

建议：

- 系统内部仍使用 `internal_paper_uid`（UUID / ULID）
- 但 S2 数据仓库层使用 `s2_corpus_id` 做 join key
- 同时保存 `s2_paper_id`
- `paper-ids` 数据集负责维护映射  
  原因是：
- API 更偏向 `paperId`
- datasets 更偏向 `corpusId`
- 你的系统还会融合 OpenAlex / Crossref / DOI / arXiv 等多源。[S2-2][S2-16]

### 5.2 新增表：S2 Provider Cache

```sql
create table s2_paper_cache (
  s2_paper_id text primary key,
  s2_corpus_id bigint,
  doi text,
  title text,
  abstract text,
  year int,
  publication_date date,
  venue text,
  publication_venue jsonb,
  authors jsonb,
  citation_count int,
  influential_citation_count int,
  reference_count int,
  is_open_access boolean,
  open_access_pdf jsonb,
  fields_of_study jsonb,
  s2_fields_of_study jsonb,
  tldr jsonb,
  specter_v2 vector(768),
  external_ids jsonb,
  raw_payload jsonb not null,
  fetched_at timestamptz not null,
  expires_at timestamptz
);
```

### 5.3 新增表：S2 Citation Edge

```sql
create table s2_citation_edges (
  edge_id uuid primary key,
  src_internal_paper_uid uuid not null,
  dst_internal_paper_uid uuid not null,
  src_s2_paper_id text,
  dst_s2_paper_id text,
  src_s2_corpus_id bigint,
  dst_s2_corpus_id bigint,
  edge_kind text not null,                  -- 'reference' | 'citation'
  is_influential boolean,
  intents jsonb,
  contexts jsonb,
  provider text not null default 'semantic_scholar',
  source_endpoint text not null,            -- references | citations | dataset
  raw_payload jsonb,
  retrieved_at timestamptz not null default now()
);
create index idx_s2_citation_edges_src on s2_citation_edges(src_internal_paper_uid);
create index idx_s2_citation_edges_dst on s2_citation_edges(dst_internal_paper_uid);
```

### 5.4 新增表：S2 Query Cache

```sql
create table s2_query_cache (
  cache_key text primary key,
  endpoint text not null,
  query_params jsonb not null,
  request_body jsonb,
  response_payload jsonb not null,
  status_code int not null,
  fetched_at timestamptz not null,
  ttl_seconds int not null
);
```

#### 建议 TTL

- `paper/{id}`：7 天
- `paper/batch`：3 天
- `search/bulk`：1 天
- `search`：12 小时
- `recommendations`：12 小时
- `citations/references`：7 天
- `snippet/search`：6 小时

### 5.5 新增表：Dataset Sync State

```sql
create table s2_dataset_sync_state (
  dataset_name text primary key,
  current_release_id text,
  last_sync_started_at timestamptz,
  last_sync_finished_at timestamptz,
  last_sync_status text,          -- success | partial | failed
  last_error text,
  meta jsonb
);
```

---

## 6. 新的检索排序与融合策略

这是把 S2 用“深”的关键，不是只接 API。

### 6.1 统一候选打分公式（建议版）

对每篇 candidate paper 计算：

```text
final_score =
  0.22 * lexical_score
+ 0.18 * semantic_query_score
+ 0.14 * recommendation_rank_score
+ 0.12 * citation_graph_proximity_score
+ 0.10 * influential_edge_score
+ 0.08 * citation_context_relevance_score
+ 0.06 * venue_authority_score
+ 0.05 * recency_score
+ 0.03 * open_access_bonus
+ 0.02 * paper_tldr_quality_prior
- 0.10 * duplicate_or_cluster_overcrowding_penalty
```

这不是唯一公式，但足够作为 MVP/PRD 级定义。

### 6.2 各项含义

#### `lexical_score`
来自：
- `paper/search/bulk` query 命中
- query 重写后的布尔表达式命中质量

#### `semantic_query_score`
来自：
- 你自己的 query embedding 与 paper embedding / abstract embedding
- 可与 `embedding.specter_v2` 联合

#### `recommendation_rank_score`
来自：
- `recommendations` 返回的排名位置  
  因为 Recommendations API 默认按相关性降序返回，所以可按 rank 映射分数；不需要强依赖显式分值。[S2-13]

#### `citation_graph_proximity_score`
来自：
- 与正向 seed 的最短路径
- 与多个 seed 的共邻程度
- 同时在 references 和 citations 邻域中出现

#### `influential_edge_score`
来自：
- 该 paper 被多少 `isInfluential=true` 的边连接
- 在当前 research 子图中的影响力边权重

#### `citation_context_relevance_score`
来自：
- `contexts` 与当前子问题 query 的相似度
- 如果某篇 paper 经常在“limitations”“evaluation”“method”语境里被提到，优先级可更高

#### `venue_authority_score`
来自：
- venue 类型、历史质量名单、是否 top conference / journal
- S2 `publicationVenue` 元数据可作为输入。[S2-17]

#### `open_access_bonus`
来自：
- `isOpenAccess`
- `openAccessPdf`
- 是否可进入全文解析

### 6.3 多样性与覆盖约束

S2 有个风险：recommendations 和 citation expansion 可能把你不断拉进同一个局部簇。  
所以 final shortlist 必须加 diversity 约束：

- 每个 method cluster 至多取 N 篇
- 每个 venue cluster 至多取 N 篇
- 每个 author neighborhood 至多取 N 篇
- 同标题 / 同 DOI / 同 preprint-version 去重
- survey / review 单独 bucket

---

## 7. 新的执行策略：在线 API 与本地镜像如何协同

### 7.1 为什么要双层

官方建议用 API key，同时官方教程也明确给出“当你需要更高请求率时，下载 datasets 并本地跑查询”的建议。[S2-2]  
这和你的 autonomous workflow 完全吻合。

### 7.2 建议的协同策略

#### Online API 负责
- 用户启动任务后的前 1~3 轮探索
- 新 topic 冷启动
- 正负 seed 推荐扩展
- 高价值论文的 citation/reference 局部扩图
- 没有 PDF 时的 snippet evidence
- 增量补全新论文 metadata

#### Local Mirror 负责
- 历史库大规模召回
- 图分析 / 社区发现 / shortest path
- prior-art 覆盖检测
- 长时间自动跑批
- 高吞吐 rerank 前的本地预筛
- provider fallback

### 7.3 推荐的数据集选择

#### MVP 必选
- `papers`
- `abstracts`
- `citations`
- `paper-ids`

#### v1.1 强烈推荐
- `embeddings-specter_v2`

#### v1.2 按需启用
- `authors`
- `publication-venues`
- `s2orc_v2`

### 7.4 存储与算力估算（按官方最新 release 描述）

我这次查到的 latest release 元信息显示：
- `papers`：200M records，30 个约 1.5GB 文件
- `abstracts`：100M records，30 个约 1.8GB 文件
- `citations`：2.4B records，30 个约 8.5GB 文件
- `embeddings-specter_v2`：120M records，30 个约 28GB 文件
- `s2orc_v2`：16M records，30 个约 6GB 文件  
  这些只是官方页面给出的分片描述，落地时你要按对象存储、压缩率、索引副本数再乘实际系统系数。[S2-16]

#### 实施建议

- 原始数据落地到对象存储：S3 / MinIO
- ETL 后落地到：
  - Postgres：主业务元数据
  - ClickHouse / DuckDB / Parquet：大规模分析（可选）
  - Neo4j：图分析（可选）
  - Qdrant / pgvector：向量检索（按阶段选）

> 如果团队当前还没上 ClickHouse，MVP 可以先不加；但如果真要吃下 `citations` 全量，长期看 ClickHouse/Parquet 分析层会比单靠 Postgres 更舒服。

### 7.5 增量同步计划

建议做一个每周定时任务：

1. 调 `GET /datasets/v1/release/`
2. 判断 latest release 是否变化
3. 对每个已同步 dataset：
   - 调 `GET /datasets/v1/diffs/{start}/to/{latest}/{dataset}`
4. 应用 update files / delete files
5. 写 `s2_dataset_sync_state`

官方教程直接给了 diffs 适用于 upsert / delete 的处理方式，完全适合工程实现。[S2-6][S2-15]

---

## 8. S2 Gateway 的工程实现细节

### 8.1 请求头与认证

所有请求默认都带：

```http
x-api-key: <YOUR_S2_API_KEY>
```

官方说明这个 header **大小写敏感**。[S2-2][S2-3]

### 8.2 Provider 级限流器

由于官方给 API key 的初始速率是 1 RPS across all endpoints，[S2-2][S2-7]  
建议做一个 provider 级 token bucket：

```python
class ProviderRateLimiter:
    provider = "semantic_scholar"
    capacity = 1
    refill_per_second = 1
```

但实际实现要再加：

- burst queue
- endpoint priority
- cancellation support
- backoff on 429
- jitter retry on 5xx
- per-tenant accounting（如果未来多租户）

### 8.3 Endpoint Priority

在 1 RPS 下，必须有优先级队列。

建议优先级从高到低：

1. 用户显式交互触发的 `paper/search` / `paper/search/match`
2. seed 归一化 `paper/{id}`
3. `recommendations`
4. `paper/batch`
5. `citations` / `references`
6. `snippet/search`
7. `datasets` 控制面接口

### 8.4 批量聚合器

`paper/batch` 是高价值接口。  
建议所有 worker 不直接调用 S2，而是发事件到 `s2_batch_hydrator`：

```json
{
  "type": "S2_BATCH_HYDRATE_REQUEST",
  "fields_key": "standard_paper_hydrate_v1",
  "paper_ids": ["...", "...", "..."]
}
```

batch hydrator 负责：
- 合并 1 秒内的多个请求
- 最多攒到 500 ids
- 命中缓存就不出网
- 统一回填结果

### 8.5 错误分类

#### `400`
一般是：
- fields 不支持
- query params 不支持
- 响应会超过 10MB  
  应视为“调用方 bug 或切分策略问题”。[S2-10]

#### `401/403`
- key 错误或权限问题

#### `404`
- paper/title not found
- 对 title match 可视为正常路径的一部分

#### `429`
- 速率限制
- 进入 backoff + reschedule

#### `5xx`
- provider 抖动
- 需要 circuit breaker + fallback 到 local mirror / alternative providers

### 8.6 Provider Health Monitor

建议每 5 分钟：
- 拉一次 S2 status page
- 记录是否 operational
- 监控 429 / 5xx 比例
- 根据 provider 健康度自动调整 search planner  
  S2 有公开状态页可用于监控和订阅。[S2-18]

---

## 9. 对 Agent 工作流的修改建议

这一节可以直接补丁到 `03_Agents_Workflows_and_Prompts.md`。

### 9.1 Retrieval Agent：新增 S2 专属子节点

原 Retrieval Agent 建议拆成：

```text
retrieval_agent
├── normalize_seed_papers
├── generate_bulk_queries
├── s2_bulk_recall
├── s2_relevance_refine
├── s2_recommendation_expand
├── s2_citation_expand
├── s2_reference_expand
├── s2_batch_hydrate
├── snippet_evidence_probe
├── candidate_fusion
└── rerank_and_dedup
```

### 9.2 Planner：增加 positive / negative seed 机制

Planner 状态新增：

```json
{
  "positive_seed_paper_ids": [],
  "negative_seed_paper_ids": [],
  "seed_clusters": [],
  "expansion_policies": {
    "enable_recommendations": true,
    "enable_citation_forward": true,
    "enable_reference_backward": true
  }
}
```

### 9.3 Reader Agent：增加“全文不可得” fallback

原来可能是：
- 有 PDF -> 解析
- 无 PDF -> 放弃或只留元数据

现在建议改成：
- 有 `openAccessPdf` -> 下载 + 解析
- 无 `openAccessPdf` 但有 `abstract` -> 摘要级阅读
- 摘要不足 -> `snippet/search` 做 evidence probe
- 仍不足 -> 标记为 `metadata_only_paper`

### 9.4 Synthesis Agent：使用 citation intent / context

Synthesis 阶段在做：
- contradiction mining
- gap analysis
- innovation hypothesis generation  
时，不应只看 paper summary，而应引入：

- 谁在什么上下文里引用了谁
- 哪些 paper 被高影响力引用
- 哪些 method 在 limitation / evaluation 的语境中反复出现

这会让“创新点”更像从文献结构中推出来，而不是 LLM 裸生成。

### 9.5 Critic Agent：新增 prior-art 邻域检查

Critic 对每个创新点候选，新增一个流程：

1. 取 hypothesis 的关键词 + supporting papers
2. 生成 3~5 个 bulk search queries
3. 取与 supporting papers 邻近的 recommendations
4. 扫 supporting papers 的 citations/references 邻域
5. 判断是否存在“已做过但表述不同”的先行工作

---

## 10. Prompt / Policy 更新建议

### 10.1 Retrieval Query Rewriter Prompt 增补

建议在检索 query 重写 prompt 里明确：

- 优先生成适合 `paper/search/bulk` 的 query
- 可以使用：
  - `+`、`|`、`-`
  - phrase quotes
  - `~N`
  - `*`
  - `()`  
- 不能把 query 写得过宽
- 需要同时输出：
  - `query`
  - `year`
  - `fieldsOfStudy`
  - `publicationTypes`
  - `openAccessPdf`
  - `minCitationCount`

#### 输出 schema 示例

```json
{
  "queries": [
    {
      "query": "\"retrieval augmented generation\" + benchmark -survey",
      "year": "2022-",
      "fieldsOfStudy": ["Computer Science"],
      "publicationTypes": ["Conference", "JournalArticle"],
      "openAccessPdf": true,
      "minCitationCount": 5
    }
  ]
}
```

### 10.2 Recommendation Expansion Prompt 增补

要求 agent 输出：

```json
{
  "positive_seed_paper_ids": ["..."],
  "negative_seed_paper_ids": ["..."],
  "reason": "..."
}
```

并加规则：
- positive seeds 最多 5 个
- negative seeds 最多 3 个
- negative seeds 必须有明确“为什么是噪声”的解释

### 10.3 Critic Prompt 增补

Critic 不只检查文本重复，还要检查：

- recommendation 邻域里是否已有相似工作
- citation/reference 2-hop 邻域里是否已有相似工作
- contexts/intents 是否显示该方向已被系统讨论过
- 是否只是现有方法的轻量重组

---

## 11. 实施路线图（可直接给团队拆任务）

### 11.1 Sprint A：S2 基础接入（1~1.5 周）

目标：
- 打通 `s2-gateway`
- 支持 API key
- 支持最基础 endpoint：
  - `paper/{id}`
  - `paper/search/match`
  - `paper/search/bulk`
  - `paper/batch`

交付：
- `SemanticScholarConnector`
- `ProviderRateLimiter`
- `ProviderResponseCache`
- `provider_paper_identity`
- `s2_paper_cache`

### 11.2 Sprint B：在线检索闭环（1.5~2 周）

目标：
- Retrieval Agent 可用 S2 完成完整在线扩展

新增：
- `recommendations`
- `citations`
- `references`
- `candidate fusion`
- `ranking v1`

交付：
- UI 中可展示：
  - 来自 bulk search 的结果
  - 来自 recommendations 的结果
  - 来自 citations/references 的结果来源标签

### 11.3 Sprint C：证据层增强（1 周）

目标：
- 补上 `snippet/search`
- 完善全文不可得 fallback

交付：
- `Evidence Probe` 节点
- `paper_snippet_evidence` 表（可选）
- synthesis / critic 可消费 snippet 证据

### 11.4 Sprint D：本地镜像（2~3 周）

目标：
- 下载并接入：
  - `papers`
  - `abstracts`
  - `citations`
  - `paper-ids`
- 支持 `diffs` 增量更新

交付：
- `s2_dataset_sync_state`
- 对象存储落盘
- ETL pipeline
- 本地查询 fallback

### 11.5 Sprint E：高级增强（后续）

可选继续加：
- `embeddings-specter_v2`
- `s2orc_v2`
- S2-only graph analytics
- provider health-aware planner
- venue / author authority modeling

---

## 12. 风险、限制与缓解措施

### 12.1 速率限制

**风险**：带 key 初始 1 RPS，不适合高并发 agent 直接在线扫图。  
**缓解**：
- provider token bucket
- batch hydrate
- query cache
- local mirror
- priority queue
- 必要时向官方申请更高 rate

### 12.2 `paper/search` 的结果上限

**风险**：relevance search 最多 1000 条。  
**缓解**：
- 主召回改用 `paper/search/bulk`
- 大主题依赖 datasets/mirror
- `paper/search` 仅做精修

### 12.3 批量接口的响应大小限制

**风险**：`paper/batch` 10MB 限制、500 ids 限制。  
**缓解**：
- 字段模板分层
- 分批 hydrate
- 大字段（citations/references）不要混进所有 batch

### 12.4 citation/reference 高度数节点

**风险**：有些经典论文度数太高。  
**缓解**：
- 高度数论文只取：
  - 最近 N 年
  - `isInfluential=true`
  - context 与 topic 高相关
  - 分页上限

### 12.5 抽象层过早耦合

**风险**：把 S2 绑死成唯一 provider。  
**缓解**：
- 保留 OpenAlex / Crossref / Unpaywall 融合层
- 内部 canonical schema 不直接暴露 provider 专属字段

### 12.6 摘要与全文可用性不一致

官方 schema 明确说明，由于法律原因，API 返回里 abstract 可能缺失，即使网页上有显示。[S2-17]  
**缓解**：
- abstract 缺失时走 snippet / OA PDF
- 把 `text_availability` / `metadata_only` 纳入下游决策

---

## 13. 对原文档的直接修改建议（可复制给团队）

### 13.1 对 `01_PRD.md` 的修改

在“外部数据源”一节，将：

> OpenAlex / Semantic Scholar / Crossref / Unpaywall

修改为：

> **Semantic Scholar（主在线图谱与推荐 provider） + OpenAlex（元数据/图谱补充） + Crossref（DOI/出版元数据校正） + Unpaywall（OA 链接补充）**

新增一句：

> 对于长时间自治研究任务，系统默认采用 “在线 S2 API + 本地镜像数据仓库” 的双层检索架构，避免在线速率限制成为主瓶颈。

### 13.2 对 `02_Architecture_and_Data_Model.md` 的修改

在 `5.5 Scholar Search Adapter Layer` 后新增：

- `S2 Gateway`
- `Provider Rate Limiter`
- `Dataset Sync Service`
- `Evidence Probe Service`

将统一 adapter 输出 schema 扩展为包含：

```json
{
  "provider_features": {
    "s2_paper_id": "...",
    "s2_corpus_id": 123,
    "influential_citation_count": 42,
    "is_open_access": true,
    "open_access_pdf": {},
    "tldr": {},
    "specter_v2_embedding": []
  }
}
```

### 13.3 对 `03_Agents_Workflows_and_Prompts.md` 的修改

在 retrieval workflow 中新增节点：

- `s2_bulk_recall`
- `s2_recommendation_expand`
- `s2_citation_expand`
- `s2_reference_expand`
- `s2_batch_hydrate`
- `snippet_evidence_probe`

在 innovation / critic 部分新增规则：

- 所有 hypothesis 在判定 novelty 前，必须经过：
  - bulk search 复检
  - recommendation 邻域复检
  - citation/reference 2-hop 复检

### 13.4 对 `04_Delivery_Plan_and_Backlog.md` 的修改

新增 Epic：

- EPIC-S2-01：S2 Gateway 与 provider policy
- EPIC-S2-02：Online retrieval + recommendation + graph expansion
- EPIC-S2-03：Snippet evidence fallback
- EPIC-S2-04：Datasets mirror + diffs sync

---

## 14. 我给你的最终建议（决策版）

### 14.1 该不该把 S2 接进来？
**应该，而且应该提升为主 provider。**

### 14.2 能不能只靠 S2 在线 API 做全自动 research？
**不建议。**  
因为官方带 key 的初始速率是 1 RPS across all endpoints，这对真正的 autonomous long-running workflow 明显不够。[S2-2][S2-7]

### 14.3 正确的设计是什么？
**S2 在线 API + S2 本地镜像 + 其他 provider 补充**。

### 14.4 对你这个 Research OS 最值钱的 5 个接口
按优先级排序：

1. `paper/search/bulk`
2. `recommendations`
3. `citations`
4. `references`
5. `paper/batch`

如果再加一个：
6. `snippet/search`

### 14.5 对创新点生成帮助最大的 S2 特性
不是“搜到更多论文”本身，而是：

- `positive / negative seed recommendations`
- `citation contexts`
- `citation intents`
- `isInfluential`
- `snippet evidence`
- `SPECTER2 paper embeddings`

---

## 15. 附：建议直接下发给团队的接口规范清单

### 15.1 必做接口封装

```text
resolve_paper_identity(input) -> S2PaperIdentity
bulk_search(query_bundle) -> List[S2PaperLite]
relevance_search(query_bundle) -> List[S2PaperRich]
recommend_from_seeds(positive_ids, negative_ids) -> List[S2PaperLite]
get_citations(paper_id, page_opts, field_opts) -> List[S2CitationEdge]
get_references(paper_id, page_opts, field_opts) -> List[S2ReferenceEdge]
batch_hydrate(paper_ids, fields_key) -> List[S2PaperRich]
search_snippets(query, filters) -> List[S2Snippet]
sync_dataset(dataset_name, start_release, end_release) -> SyncReport
```

### 15.2 建议的默认 field set

#### `paper_rich_v1`
```text
title,abstract,year,publicationDate,venue,publicationVenue,authors,
citationCount,influentialCitationCount,referenceCount,
isOpenAccess,openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,
externalIds,tldr
```

#### `paper_graph_v1`
```text
title,abstract,authors,year,citationCount,influentialCitationCount
```

#### `citation_edge_v1`
```text
contexts,intents,isInfluential,authors,abstract,year
```

#### `paper_embedding_v1`
```text
title,embedding.specter_v2
```

### 15.3 推荐的 provider policy

```yaml
provider_policy:
  primary_online_discovery: semantic_scholar
  secondary_metadata_resolver: openalex
  doi_metadata_validator: crossref
  open_access_link_provider: unpaywall

  use_cases:
    seed_normalization:
      primary: semantic_scholar
      fallback: [crossref, openalex]

    bulk_recall:
      primary: semantic_scholar_bulk_search
      fallback: [openalex_search, local_mirror]

    recommendation_expansion:
      primary: semantic_scholar_recommendations
      fallback: [local_embedding_knn]

    citation_graph_expansion:
      primary: semantic_scholar
      fallback: [openalex, local_mirror]

    evidence_probe:
      primary: semantic_scholar_snippet
      fallback: [local_rag, parsed_pdf_chunks]
```

---

## 16. 官方来源索引

[S2-1]: https://www.semanticscholar.org/product/api "Semantic Scholar API - Overview"
[S2-2]: https://www.semanticscholar.org/product/api/tutorial "Semantic Scholar API - Tutorial"
[S2-3]: https://api.semanticscholar.org/api-docs "Academic Graph API"
[S2-4]: https://api.semanticscholar.org/graph/v1/swagger.json "Academic Graph API Swagger JSON（citations / IDs / schema）"
[S2-5]: https://api.semanticscholar.org/graph/v1/swagger.json "Academic Graph API Swagger JSON（references / schema）"
[S2-6]: https://api.semanticscholar.org/api-docs/datasets "Datasets API"
[S2-7]: https://www.semanticscholar.org/product/api "Overview（API key / unauthenticated / introductory rate）"
[S2-8]: https://api.semanticscholar.org/graph/v1/swagger.json "Paper relevance search"
[S2-9]: https://api.semanticscholar.org/graph/v1/swagger.json "Paper bulk search / search match"
[S2-10]: https://api.semanticscholar.org/graph/v1/swagger.json "Snippet search"
[S2-11]: https://api.semanticscholar.org/graph/v1/swagger.json "Paper batch"
[S2-12]: https://api.semanticscholar.org/graph/v1/swagger.json "Supported paper ID formats"
[S2-13]: https://api.semanticscholar.org/api-docs/recommendations "Recommendations API"
[S2-14]: https://api.semanticscholar.org/datasets/v1/release/ "Datasets release list"
[S2-15]: https://www.semanticscholar.org/product/api/tutorial "Datasets tutorial（download links / diffs）"
[S2-16]: https://api.semanticscholar.org/datasets/v1/release/latest "Latest release metadata and dataset descriptions"
[S2-17]: https://api.semanticscholar.org/graph/v1/swagger.json "FullPaper schema"
[S2-18]: https://status.api.semanticscholar.org/ "S2 Public API Status"
