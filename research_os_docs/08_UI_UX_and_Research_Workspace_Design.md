# 08. UI/UX and Research Workspace Design —— 页面设计、信息架构与交互方案

版本：v1.0  
日期：2026-03-20  
适用对象：产品经理、设计师、前端工程师、后端工程师、PI/业务评审

---

## 1. 文档目标

本文件定义 Research OS 的页面结构、信息架构、交互流、组件层级与设计原则，重点解决：

1. 如何把系统做成类似“科研工作台”，而不是单一聊天页。  
2. 如何让左侧层级树承载研究领域/主题/子方向。  
3. 如何在右侧展示实时研究过程、图文并茂结果与交互反馈。  
4. 如何支持三大模式的无缝切换与串联。  
5. 如何让用户在“看结果”和“打断系统”之间来回切换但不迷路。

---

## 2. 核心设计原则

### 2.1 工作台优于聊天框

Research OS 的主界面不应只是一个消息流，而是一个**可观察、可控制、可追问的研究工作台**。

### 2.2 左侧是结构，右侧是证据与推理

- 左侧：领域树、主题树、运行历史、结果资产索引  
- 右侧：报告、图示、时间线、对比表、痛点、创新点、聊天交互

### 2.3 主结果固定，交互是增强而不是替代

用户首先看到应是**系统化结果**，而不是一长串对话。对话是用来：
- 追问
- 缩范围
- 重排结果
- 触发新 run

### 2.4 图文并茂必须是一等公民

图示、表格、架构图、时间线、分类树、mind map 不能埋在附件里，而要成为页面中心组件。

### 2.5 结果对象化，避免一次性输出

页面上所有结果都要是“对象”：
- 领域
- 子方向
- 论文
- 图示
- benchmark
- pain point
- idea card

这样才能支持拖拽、串联、再利用、发起下一模式。

---

## 3. 页面整体架构

建议采用 **三栏式研究工作台**，但视觉上以“两大主区域 + 抽屉”为主：

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 顶部导航 / Workspace 标题 / Mode 切换 / 搜索 / 当前 Run 状态          │
├───────────────┬───────────────────────────────────────┬──────────────┤
│ 左侧研究树     │ 右侧主内容区                           │ 右侧辅助抽屉 │
│               │                                       │ （可收起）   │
│ - 领域层级     │ - 报告视图 / 时间线 / 对比表 / 图示      │ - 引文        │
│ - 子方向       │ - 论文卡片 / benchmark / mind map      │ - 聊天追问    │
│ - Run 历史     │ - pain points / idea cards             │ - 过滤器      │
│ - 资产索引     │ - 实时进度与中断控制                    │ - 原文片段    │
└───────────────┴───────────────────────────────────────┴──────────────┘
```

建议宽度：
- 左栏：280~320 px
- 中间主画布：自适应
- 右抽屉：360~420 px，可折叠

---

## 4. 信息架构（Information Architecture）

## 4.1 一级信息架构

1. **Workspace 首页**  
2. **领域研究树**  
3. **单个 Run 页面**  
4. **论文详情页**  
5. **图示 / Figure Viewer**  
6. **Benchmark / Dataset 面板**  
7. **Idea Board**  
8. **导出与汇报页面**

## 4.2 左侧导航树结构

建议左栏分四个 section：

### 4.2.1 Research Atlas

- 大领域
- 子方向
- 技术路线
- benchmark 视图
- 阅读路径

### 4.2.2 Runs

- 最近运行中的任务
- 已完成任务
- 收藏任务

### 4.2.3 Assets

- 论文
- 图示
- mind maps
- pain points
- idea cards
- 导出报告

### 4.2.4 Personal Notes

- 用户手写注释
- pin 住的论文
- 排除项
- 待办

---

## 5. 顶部导航设计

顶部建议包含：

- Workspace 名称
- 当前模式标识（A / B / C / X）
- 全局搜索栏
- “新建研究”按钮
- “从当前结果派生新模式”按钮
- 当前 run 状态条（Running / Paused / Completed）
- 模式切换入口
- 导出入口

### 5.1 顶部状态条要显示什么

实时显示：
- 当前阶段
- 已处理论文数
- 新增图示数
- 当前候选 pain points / ideas 数量
- 是否等待用户输入

---

## 6. 三大模式的主页面形态

## 6.1 Mode A 页面形态：Atlas 教学页

Mode A 页面不应像普通搜索结果页，而应更像“交互式综述课件”。

### 主内容布局建议

1. 顶部：领域定义卡片  
2. 其下：时间线  
3. 其下：分类树 / mind map  
4. 其下：代表论文卡片墙  
5. 其下：各子方向展开内容  
6. 底部：阅读路径与下一步建议

### 推荐组件

- `DomainHeroCard`
- `TimelineRail`
- `TaxonomySwitchTabs`
- `MindMapCanvas`
- `RepresentativePaperGrid`
- `FigureGallery`
- `ReadingPathBoard`
- `NextStepRecommendations`

### 交互动作

- 点击子方向节点 → 展开小方向详解
- 点击代表论文 → 打开论文详情抽屉
- 点击“深入这个方向” → 进入 Mode B
- 点击“加入阅读清单” → 存到个人路径

## 6.2 Mode B 页面形态：前沿综述与对比页

Mode B 应该强调“高质量小同行论文综述 + 对比分析”。

### 主内容布局建议

1. 顶部：子领域定义与过滤条件  
2. 其下：核心论文池概览  
3. 其下：方法分类 / benchmark 面板  
4. 其下：论文对比表  
5. 其下：pain points 板  
6. 其下：future work 与切入点建议  
7. 底部：进入 Mode C 的按钮与候选 pain packages

### 推荐组件

- `ScopeSummaryBar`
- `CorePaperStrip`
- `BenchmarkPanel`
- `MethodClusterBoard`
- `PaperComparisonTable`
- `PainPointBoard`
- `FutureWorkPanel`
- `EntryPointAdvisor`
- `SendToModeCActionBar`

### 交互动作

- 锁定/排除论文
- 按 venue、年份、benchmark、方法过滤
- 钉住某个 pain point
- 一键“对这个痛点发散”进入 Mode C

## 6.3 Mode C 页面形态：创新工作台

Mode C 页面应强调“问题抽象—外领域映射—创新 idea 卡片”的工作流。

### 主内容布局建议

1. 顶部：当前 problem signature  
2. 其下：analogical domains 地图  
3. 其下：外领域候选方法池  
4. 其下：idea cards 列表 / 看板  
5. 其下：prior-art 风险提示  
6. 底部：实验草案与下一步行动

### 推荐组件

- `ProblemSignaturePanel`
- `AnalogicalMapCanvas`
- `TransferMethodGallery`
- `IdeaCardBoard`
- `PriorArtWarningList`
- `ExperimentSketchPanel`

### 交互动作

- 限定只从某领域找灵感
- 排除某类方法
- 调整 ideas 的激进度
- 将某个 idea 回送 Mode B 做补文献检索

---

## 7. 右侧辅助抽屉设计

右侧抽屉建议统一承载“上下文和控制”，不要与主内容抢位置。

建议采用三个 tab：

### 7.1 Chat / Ask

用于：
- 追问
- 改写
- 追加任务
- 请求更多图示 / 更多经典 / 更多近期论文

### 7.2 Evidence

用于：
- 原文片段
- 引用来源
- PDF 页码
- 图示出处
- 证据追溯

### 7.3 Controls

用于：
- 暂停 / 恢复
- tighten scope / expand scope
- venue filter
- benchmark filter
- rerun stage

---

## 8. 论文详情页设计

点击任一论文卡片时，应打开一个“论文详情抽屉”或二级页面。

推荐区块：

1. 标题 + 作者 + venue + 年份  
2. 一句话总结  
3. 核心创新点  
4. 关键图示  
5. 方法讲解  
6. datasets / metrics  
7. 实验亮点  
8. limitations / future work  
9. 与当前 workspace 的关系  
10. 操作按钮：加入阅读清单 / 设为 seed / 排除 / 对比 / 送入 Mode C

---

## 9. 图示与 Figure Viewer 设计

因为你的系统强调图文并茂，所以需要专门的图示查看器。

## 9.1 Figure Viewer 组件能力

- 大图预览
- 展示图 caption
- 展示图所属论文和页码
- 展示“这张图表达什么”教学说明
- 对比多个论文的同类图
- 下载引用信息 / 复制到报告

## 9.2 图示类型标签

建议系统自动打标签：
- `architecture`
- `pipeline`
- `qualitative_result`
- `benchmark_table`
- `dataset_example`
- `failure_case`

## 9.3 图示在主页面中的位置

- Mode A：作为教学解释重点出现
- Mode B：作为方法和实验对比证据出现
- Mode C：用于说明借鉴来源与目标问题的相似性

---

## 10. Mind Map 与知识图视图

你的需求里非常强调“思维导图一样的综述总结”，建议前端同时支持：

1. **树形 mind map**：适合教学与汇报  
2. **Graph view**：适合专家看关联与跨域迁移  
3. **Outline view**：适合导出文档与列表阅读

### 10.1 建议技术实现

- 前端图谱渲染：React Flow / Cytoscape.js / D3（二选一或组合）
- mind map 与 graph 共用后端 `mindmap_json / graph_json`

### 10.2 节点点击行为

- 领域节点 → 打开子方向页
- 论文节点 → 打开论文详情
- pain point 节点 → 在右侧显示支撑证据
- idea card 节点 → 打开实验草案

---

## 11. “实时反馈”如何体现在 UI

系统不能让用户只看到“正在研究，请等待”。建议：

### 11.1 运行进度条不只显示百分比

还要显示：
- 当前阶段名称
- 已处理论文数量
- 已发现核心分支数
- 已抽出的图示数
- 已识别 pain point 数
- 当前建议用户是否介入

### 11.2 中间产物实时落屏

随着 run 进行，界面应逐步出现：
- 论文卡片
- 分类节点
- 时间线节点
- 图示
- 对比表行
- pain point 卡
- idea card

### 11.3 “为什么系统这样做”的可解释提示

每个重要动作旁边附一句话：
- “加入这篇，因为它被 3 篇核心种子论文共同引用”
- “排除这篇，因为 benchmark 不匹配”
- “提取这张图，因为它最能解释该方法主干结构”

---

## 12. 模式切换与串联交互

## 12.1 从 Mode A 到 B

在 Mode A 的分类树、代表论文卡片、阅读路径中提供 CTA：
- “深入这个子方向”
- “以这些论文为种子进入前沿模式”

## 12.2 从 Mode B 到 C

在 pain point 卡片、future work 面板上提供 CTA：
- “围绕这个痛点发散创新”
- “把这组痛点送入跨域迁移模式”

## 12.3 从 Mode C 回 B

在 idea card 上提供 CTA：
- “为这个 idea 补查小同行相关工作”
- “对这个组合做 prior-art 深查”

---

## 13. 页面路由建议

建议路由：

- `/workspaces`
- `/workspaces/:workspaceId`
- `/workspaces/:workspaceId/runs/:runId`
- `/workspaces/:workspaceId/papers/:paperId`
- `/workspaces/:workspaceId/figures/:figureId`
- `/workspaces/:workspaceId/ideas/:ideaId`
- `/workspaces/:workspaceId/export/:bundleId`

---

## 14. 核心前端组件清单

### 14.1 通用组件

- `WorkspaceHeader`
- `LeftResearchTree`
- `RunStatusBar`
- `RightDrawer`
- `EvidencePanel`
- `ChatPanel`
- `ControlPanel`

### 14.2 Mode A 组件

- `AtlasOverviewCard`
- `TimelineRail`
- `TaxonomyTree`
- `MindMapCanvas`
- `RepresentativePaperCard`
- `FigureGallery`
- `ReadingPathStepper`

### 14.3 Mode B 组件

- `ScopeChipBar`
- `PaperPoolOverview`
- `BenchmarkPanel`
- `MethodComparisonTable`
- `PainPointBoard`
- `FutureWorkPanel`
- `EntryPointCards`

### 14.4 Mode C 组件

- `ProblemSignatureCard`
- `AnalogicalGraph`
- `TransferMethodCard`
- `IdeaCardBoard`
- `PriorArtFlagPanel`
- `ExperimentSketchCard`

---

## 15. 前后端交互建议

### 15.1 首屏加载

首屏应先加载：
- workspace 基础信息
- 左侧树
- 当前 run 摘要
- 主结果骨架

然后通过 SSE 补：
- 新论文
- 新图示
- 新 pain point
- 新 idea card

### 15.2 缓存策略

- 领域树、已完成 run 摘要：可缓存
- 活动 run 详情：SSE + 局部更新
- 图示：CDN/object storage
- 大表格：分页与虚拟滚动

---

## 16. 移动端与桌面端建议

此类系统优先桌面端；移动端仅建议支持：
- 查看结果
- 简单追问
- 暂停/恢复 run
- 收藏论文

完整的图谱、对比表和图示学习体验应优先桌面端设计。

---

## 17. 可用性与可理解性建议

1. 默认展示“结果结构”，不要默认展示“聊天记录”。  
2. 任何复杂视图都要能切换成列表视图。  
3. 对新手，默认隐藏过深的技术细节，可点击“展开专家视图”。  
4. 任何图示都要有简洁教学说明。  
5. 任何生成的创新点都要显示来源与风险。

---

## 18. MVP 页面优先级建议

### MVP 必须做

- 左侧研究树
- 单个 run 页面
- Mode A 主结果页
- Mode B 主结果页
- 论文详情抽屉
- 右侧聊天/证据/控制抽屉
- SSE 实时进度

### V1.1 建议补做

- Mode C 专属创新工作台
- Figure Viewer
- mind map 与 graph 双视图
- 导出汇报页

### V2 再考虑

- 多用户协作标注
- 导师评论流
- 看板式团队研究管理

---

## 19. 与其他文档的联动

- 本文件配合 `06_Multi_Mode_Research_Agents_and_Execution_Design.md` 使用：前者定义模式与 Agent，后者定义页面呈现。  
- 本文件配合 `07_Runtime_Paths_State_Machines_and_API_Contracts.md` 使用：前者定义交互与界面行为，后者定义后端事件与状态机。  
- 本文件配合 `02_Architecture_and_Data_Model.md` 使用：补充前端需要的对象模型与 API。

---

## 20. 最终建议

把 Research OS 页面设计成：

- **左边：研究树与历史上下文**  
- **中间：图文并茂的研究结果主画布**  
- **右边：实时问答、证据追溯与控制抽屉**

这样它既保留了 ChatGPT 式自然交互，又真正具备“科研操作系统”的组织能力。对你的三大模式来说，这种工作台形态会明显优于单一聊天页，也更适合作为团队内部长期使用的平台。
