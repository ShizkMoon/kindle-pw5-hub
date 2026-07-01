# KPW5 × AI 集成方案蓝图

> 将 Kindle Paperwhite 5 纳入 dorm-workstation 多模型多 Agent 体系的全景设计。
> 这是方案架构文档，不是实施计划。具体实现步骤见各子文档。

---

## 一、全景：Kindle 在工位 AI 体系中的位置

```
┌──────────────────────────────────────────────────────────────────────┐
│                        dorm-workstation AI 体系                        │
│                                                                       │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ Hermes   │  │ Multica   │  │CherryStudio│  │ Kindle PW5 Hub  │   │
│  │ IM Agent │  │Orchestrator│  │  Desktop   │  │ (new subsystem) │   │
│  │MiniMax M3│  │ GLM-5.2   │  │  multi-LLM │  │                 │   │
│  └────┬─────┘  └─────┬─────┘  └─────┬──────┘  └───────┬─────────┘   │
│       │              │              │                   │             │
│       ▼              ▼              ▼                   ▼             │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │                    New API (API Gateway)                       │    │
│  │          ZhiPu │ DeepSeek │ MiniMax │ Kimi │ Anthropic        │    │
│  └──────────────────────────────────────────────────────────────┘    │
│       │              │              │                   │             │
│       ▼              ▼              ▼                   ▼             │
│  ┌──────────────┐   ┌──────────────────┐                         │
│  │Calibre       │   │  MCP Servers     │                         │
│  │ + AI Plugins │   │  (CalibreMCP,    │                         │
│  │              │   │   access-calibre)│                         │
│  └──────────────┘   └──────────────────┘                         │
└──────────────────────────────────────────────────────────────────────┘
```

Kindle PW5 不再是一个孤立的阅读器，而是知识摄入层的硬件终端。它通过两条管道与 AI 体系连接：

| 管道 | 方向 | 载体 |
|---|---|---|
| **内容输入** | 外部 → Kindle | Calibre / Send to Kindle / KOReader 云存储 |
| **AI 增强** | AI → 阅读体验 | AI 摘要、翻译、元数据、推荐 |

---

## 二、三条 AI 集成路线

### 路线 A：Calibre 原生 AI（最轻量）

Calibre 7.x+ 版本已**内建 AI 能力**，无需额外插件即可使用：

| 功能 | 触发方式 | 说明 |
|---|---|---|
| **Ask AI about book** | 右击"查看"按钮 → "与 AI 讨论选中书籍" | AI 分析整本书内容，回答你的问题 |
| **Similar books** | 右击书籍 → "相似书籍" | AI 基于内容推荐类似书籍 |
| **E-book Viewer Ask AI** | 选中文字 → 字典面板 → "Ask AI" 标签 | 对当前选中的段落提问 |
| **AI Metadata** | 下载元数据时自动调用 | 对网络无元数据的稀有/自出版书籍补全 |

支持的 AI Provider：Google Gemini、OpenRouter、GitHub Models、Ollama（本地）、LM Studio（本地）。

**对接 dorm-workstation**：可将 Ollama 指向本地部署的模型，或通过 OpenRouter 接入 New API 背后的模型池。零额外成本——本地跑小模型即可。

### 路线 B：CalibreMCP × Agent（中等深度）

[calibremcp](https://github.com/sandraschi/calibremcp) 是一个 **FastMCP 3.2 服务器**，将 Calibre 书库暴露为 21 个 MCP 工具，Agent 可以直接操作：

**核心能力：**

```
Agent 说 "帮我找关于机器学习的书，作者不是中国人"
→ calibremcp 语义搜索 → 返回匹配书籍

Agent 说 "这本书讲了什么，用 200 字总结"
→ calibremcp 读取内容 → 调 LLM 生成摘要

Agent 说 "把我标注过的书都打上 #已读 标签"
→ calibremcp 批量更新元数据

Agent 说 "在我的书库里找出所有需要翻译的书"
→ calibremcp 搜索 + 元数据分析
```

**架构：**

```
CherryStudio / Claude Code (Agent)
    │
    ▼ MCP Protocol (stdio or HTTP)
calibremcp (FastMCP Server)
    │
    ├── Calibre metadata.db (直接读取)
    ├── LanceDB (语义搜索索引)
    ├── Calibre FTS (全文搜索)
    └── Calibre Content Server (格式下载)
```

**与 dorm-workstation 现有 MCP 的对比：**

| MCP Server | 领域 | 工具数 | 状态 |
|---|---|---|---|
| caldav-mcp | 日历 | ~5 | 计划中 |
| bambu-printer-mcp | 3D 打印 | ~10 | 计划中 |
| access-calibre | 书库浏览 | 8 | 可用 |
| **calibremcp** | 书库管理+AI | 21 | **推荐** |

calibremcp 是 access-calibre 的超集——前者偏"读"（浏览书库、读章节），后者偏"管"（搜索、元数据、RAG、格式转换）。

### 路线 D：AI 翻译管线（双语阅读）

[Ebook-Translator-Calibre-Plugin](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin) 是书伴开发的 Calibre 插件（2.5K stars），支持：

- **引擎**：Google Translate、ChatGPT、Gemini、DeepL、**DeepSeek**、自定义 API
- **模式**：Advanced Mode（精细控制）/ Batch Mode（批量）
- **输出**：双语对照 EPUB（原文 + 译文并行）
- **缓存**：已翻译内容缓存，断网/失败不重复翻译

**成本估算**（一本 10 万词英文书 → 中文）：

| 引擎 | 费用 | 质量 |
|---|---|---|
| Google Translate | 免费（134 语言） | 一般 |
| DeepL Free | 免费（50 万字符/月） | 好（欧语） |
| ChatGPT (GPT-4o-mini) | ~$0.5-1 | 好 |
| DeepSeek V3 | ~¥0.5-1 | 好（中英） |
| Gemini Flash | 免费额度 | 好 |

**与 dorm-workstation 的对接**：New API 已经接了 DeepSeek，Ebook-Translator 可以直接配 DeepSeek API 走翻译管道。

**KOReader 端**：有 [Ko-Translator](https://github.com/micropescabr-dev/Ko-Translator) 插件，在 Kindle 上直接逐章翻译并注入双语 EPUB。支持 DeepL / Azure / Groq（Llama）。

---

## 三、AI 增强阅读的五个层次

参考 [reading-pipeline](https://github.com/noahnan-max/reading-pipeline) 的 5 层模型，结合 dorm-workstation 的工具链：

| 层级 | 名称 | 输入 | 输出 | 适用工具 |
|---|---|---|---|---|
| **L0** | 原始提取 | EPUB/PDF | 纯文本 + 章节目录 | Calibre + ebook-convert |
| **L1** | 焦点过滤 | L0 文本 + 研究问题 | 筛选后的相关章节 | Agent (Claude Code) |
| **L2** | 阅读笔记 | L1 内容 | 9 段式结构化笔记 | CherryStudio / Claude Code |
| **L3** | 跨书概念 | 多本书的 L2 笔记 | 概念页（收敛/分歧/综合） | Agent + knowledge store |
| **L3.5** | 主题综合 | L3 概念集群 | 权威矩阵 + 新书协议 | Agent + 人工审核 |
| **L4** | 可调用技能 | L3.5 综合输出 | Skill 文件 | skill-creator → 注册 |

**L2 笔记的 9 段结构**（标准化输出格式）：

1. 元数据（书名、作者、版本、阅读日期）
2. 一句话总结（≤50 字）
3. 核心论点（3-5 条）
4. 关键框架/模型（10-15 个概念）
5. 重要引用（≤10 条，注明章节出处）
6. 与我已知的关联（链接到其他笔记）
7. 可操作见解（我可以用它做什么）
8. 未解答的问题（后续研究方向）
9. 评分与推荐（★1-5，推荐给谁）

---

## 四、多模型路由策略（读书场景）

参考 dorm-workstation 的 5 模型分工和成本优化经验，为读书相关任务设计路由：

| 任务 | 推荐模型 | 原因 | 预估成本 |
|---|---|---|---|
| 电子书摘要（快速） | GLM-4.7 (轻量) | 萃取模式，速度快，成本低 | ~¥0.05/本 |
| 电子书摘要（深度） | GLM-5.2 | 需要推理和综合，质量优先 | ~¥0.5/本 |
| 标注聚类/标签建议 | DeepSeek V4-Pro | 文本分类任务，DeepSeek 便宜 | ~¥0.1/批 |
| 双语翻译（英文书） | DeepSeek V3 + 术语表 | 中英翻译 DeepSeek 质量好 | ~¥0.5-1/本 |
| 书籍推荐 | MiniMax M3 | 对话型任务 | ~¥0.01/次 |
| 封面 OCR / 元数据提取 | Kimi K2.7 / GLM-4.7 | 视觉模型 | ~¥0.02/张 |
| 跨书综合/概念生成 | GLM-5.2 (非高峰) | 需要深度推理 | ~¥0.3/次 |

**两阶段管道**（参考 book-summary-plugin 的 Haiku+Sonnet 模式）：

```
阶段 1: 快速模型（GLM-4.7 / DeepSeek-V3）
  → 提取关键段落、去除噪音、格式整理
  → 成本低、速度快

阶段 2: 强推理模型（GLM-5.2 / Sonnet）
  → 对阶段 1 的输出做深度综合
  → 生成结构化笔记、跨书连接
  → 只在需要深度理解时触发

成本节省: ~46%，时间节省: ~70%
```

---

## 五、Hermes 集成：Kindle 的 IM 命令

Hermes 作为常驻 IM Agent（MiniMax M3 驱动），可以承接 Kindle 相关命令：

### 5.1 推送类命令

```
用户 (WeChat): "把今天的少数派早报推到 Kindle"
→ Hermes → Calibre news download → calibre-smtp → Kindle

用户 (WeChat): "推送这个链接到 Kindle: https://..."
→ Hermes → 抓取网页 → 转 EPUB → calibre-smtp → Kindle

用户 (WeChat): "把我 D:\Books\ 里新下的 3 本书发到 Kindle"
→ Hermes → SSH 到 PC → 查找新文件 → ebook-convert → USB 拷贝或推送
```

### 5.2 查询类命令

```
用户 (WeChat): "我的 Kindle 上有什么书还没读"
→ Hermes → CalibreMCP 查询 → 列出未读书目

用户 (WeChat): "书库里有没有关于认知心理学的书"
→ Hermes → CalibreMCP 语义搜索 → 返回结果

用户 (WeChat): "最近一周我标注了什么"
→ Hermes → CalibreMCP 标注查询 → 返回标注摘要
```

### 5.3 定时任务

```
Hermes Cron:
  每天 07:30 → 晨间简报含"昨天 Kindle 阅读进度"
  每天 20:00 → "今日 RSS 摘要已推送到 Kindle"
  每周一 09:00 → "上周阅读报告"（阅读时长、新增标注、待处理笔记数）
```

---

## 六、Calibre 书库作为 RAG 知识源

dorm-workstation 的 AI 体系可以把 Calibre 书库当作一个**私有知识库**来做 RAG：

### 6.1 技术栈

```
Calibre Library (E:\CalibreLibrary\)
    │
    ├── calibremcp → LanceDB 索引（元数据语义搜索）
    │                  ↓
    │              Agent 搜索: "有没有关于分布式系统的书？"
    │
    ├── Calibre FTS → 全文短语搜索
    │                  ↓
    │              Agent 搜索: "哪本书提到了 Paxos 算法？"
    │
    └── 自定义 RAG Pipeline（可选）
        ├── 分块: ebook-convert → TXT → 按章节分割
        ├── 嵌入: Cohere / OpenAI embeddings
        ├── 存储: LanceDB / ChromaDB / Qdrant
        └── 检索: Agent 调 MCP → 相关知识块 → LLM 回答
```

### 6.2 Calibre 作为独立 RAG 知识源

Calibre 书库本身就是一个完整的知识源——它同时包含书的原始内容和通过标注工具（如 My Clippings.txt 或 KOReader 标注）导出的个人阅读数据。Agent 在做 RAG 时可以：
- 通过 calibremcp 语义搜索书的内容
- 通过标注文件查询个人阅读视角
- 结合两者生成更精准的回答

无需额外的第三方知识库，Calibre 即可作为独立的 RAG 后端。

---

## 七、Calibre 插件生态全景

### 7.1 官方 + 社区 AI 插件

| 插件 | 开发者 | 功能 | 状态 |
|---|---|---|---|
| **Calibre 内建 AI** | Kovid Goyal | Ask AI, Similar Books, Discuss | ✅ 已发布 |
| **AI Metadata Plugin** | Digital Assassins | LLM 提取基本元数据 | ✅ GitHub 可用 |
| **AI Tag Extractor** | Digital Assassins | 自定义字段提取 + 分类 | ✅ GitHub 可用 |
| **AI Vision Metadata** | MobileRead 社区 | 封面 OCR → 元数据（多 AI Provider） | ✅ 已发布 |
| **Ebook Translator** | BookFere (书伴) | 全书翻译（DeepSeek/GPT/DeepL） | ✅ 2.4.1 版 |
| **CalibreMCP Plugin** | sandraschi | GUI 集成 MCP（扩展元数据编辑） | ✅ 可用 |

### 7.2 KOReader 生态插件

| 插件 | 功能 |
|---|---|
| **Ko-Translator** | 逐章翻译 + 双语 EPUB 注入 |
| **ChatGPT 插件** | 选中文字 → 与 ChatGPT 讨论（需 API key） |
| **News Downloader** | RSS → HTML 离线阅读 |
| **Wallabag** | 稍后读服务同步 |
| **Calibre 无线传书** | Wi-Fi 直接接收 Calibre 发送的书 |
| **File Browser** | 浏览器拖拽上传文件到 Kindle |
| **SSH Server** | SFTP 传书 + 远程文件管理 |

---

## 八、成本概览

### 一次性投入

| 项目 | 费用 | 备注 |
|---|---|---|
| Calibre 软件 | 免费 | 开源 |
| CalibreMCP | 免费 | 开源 |
| KOReader | 免费 | 开源 |

### 按用量计费（AI API）

| 操作 | 频率估计 | 单次成本 | 月成本 |
|---|---|---|---|
| 深度书籍摘要 | 2-3 本/月 | ~¥0.5 | ~¥1.5 |
| 批量标注聚类 | 每周 1 次 | ~¥0.1 | ~¥0.4 |
| 双语翻译（长书） | 1 本/月 | ~¥1 | ~¥1 |
| 元数据补全 | 10 本书/月 | ~¥0.02 | ~¥0.2 |
| 语义搜索 | 日常 | 极低（嵌入已缓存） | ~¥0 |
| 书籍推荐 | 日常 | ~¥0.01 | ~¥0.3 |
| **合计** | | | **≈¥3-5/月** |

> 对比 dorm-workstation 的月均 AI 成本（~¥944-994），读书相关的 AI 开销几乎可以忽略不计。

---

## 九、隐私与安全考量

遵循 dorm-workstation 的 defense-in-depth 原则：

| 层级 | 措施 |
|---|---|
| **书籍数据** | Calibre 书库存本地（D 盘或 NAS），不上传云端 |
| **标注数据** | 本地存储（My Clippings.txt / KOReader 标注文件），不上传云端 |
| **AI 处理** | 通过 New API 网关统一管理 API key，不暴露原始 key 给各插件 |
| **翻译内容** | 如需翻译敏感/个人书籍，优先用本地 Ollama 模型，不出机器 |
| **备份** | Calibre 书库 → dorm-workstation 备份体系（daily + SHA256） |

---

## 十、实施优先级建议

按投入产出比排序：

| 优先级 | 项目 | 投入 | 产出 | 时间 |
|---|---|---|---|---|
| **P0** | Calibre 原生 AI 功能启用 | 5 分钟配置 Ollama | 即时有 AI 问答 | 本周 |
| **P1** | CalibreMCP 部署 | 安装配置 | Agent 可操作书库 | 本周 |
| **P2** | Ebook-Translator 插件 | 安装+API key | 双语阅读 | 本月 |
| **P2** | AI 标注处理工作流 | 写 prompt + 注册为 Skill | 标注 → 笔记自动化 | 本月 |
| **P3** | Hermes Kindle 命令 | 开发 Hermes 工具 | IM 控制 Kindle | 下月 |
| **P3** | 书库 RAG 管线 | 建索引+嵌入 | Agent 以书库为知识源 | 下月 |
| **P4** | 5 层阅读蒸馏体系 | 全套流程开发 | 系统性知识积累 | 长期迭代 |

---

## 参考

- [Calibre What's New (AI features)](https://calibre-ebook.com/whats-new)
- [calibremcp (sandraschi fork)](https://github.com/sandraschi/calibremcp)
- [Digital Assassins Calibre AI Plugins](https://github.com/digitalassassins/Calibre-eBook-Artificial-Intelligence-Plugins-Toolkit)
- [book-summary-plugin (Claude Code)](https://github.com/mfalgorythmic/book-summary-plugin)
- [reading-pipeline (5-layer)](https://github.com/noahnan-max/reading-pipeline)
- [Ebook-Translator-Calibre-Plugin](https://github.com/bookfere/Ebook-Translator-Calibre-Plugin)
- [llmreader (Karpathy-style LLM co-reading)](https://github.com/yongkangc/llmreader)
