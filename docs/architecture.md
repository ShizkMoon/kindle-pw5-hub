# 系统架构

> Kindle PW5 x 云工作站 AI 增强书务体系集成架构。本文档为工程规格，非泛泛规划。

## 前置决策

| 决策 | 状态 |
|---|---|
| Kindle 越狱 | ✅ 已确认，WinterBreak 方案 |
| 主力阅读器 | KOReader（Kindle 原生系统保留备用） |
| 唯一格式 | EPUB（任何输入 → EPUB → KOReader） |
| 亚马逊云 | 不使用（无 Whispersync、Send to Kindle） |
| AI 骨干 | New API 网关 + 多模型智能路由 + MCP 生态 |
| 运行平台 | ☁️ 云服务器 (2C2G Docker) + 💻 Windows 笔记本 |
| MCP 服务器 | calibremcp (21 工具) 已部署；epub-processor / metadata-enricher / koreader-bridge 规划中 |

---

## AI 管线总览：智能驱动每一步

本体系的核心设计理念是：**AI 不是附加功能，而是贯穿整个书务流程的驱动引擎**。每本书从入库到阅读再到笔记输出的全生命周期，均由 AI 管线自动编排。

### 管线的三个层次

```
┌──────────────────────────────────────────────────────────────────┐
│                    第 3 层：综合推理 (GLM-5.2)                     │
│   跨章节笔记合成 · 主题关联发现 · 个人知识图谱构建                   │
├──────────────────────────────────────────────────────────────────┤
│                    第 2 层：语义理解 (DeepSeek V4)                    │
│   双语翻译 · 长文本章节边界识别                                     │
├──────────────────────────────────────────────────────────────────┤
│                    第 1 层：快速萃取 (GLM-4.7 / DeepSeek V4)        │
│   章节检测 · CSS 审查 · 元数据交叉验证 · 标注去重格式化              │
└──────────────────────────────────────────────────────────────────┘
```

### 核心原则

1. **分层路由**：轻量模型做粗加工（第 1 层），强推理模型做深度合成（第 2/3 层）。成本节省约 46%，速度提升约 70%。
2. **MCP 优先**：所有工具能力通过 MCP 协议暴露，Agent 无需感知底层实现即可编排复杂书务操作。
3. **无感自动化**：书籍入库后，AI 管线自动完成格式清洗、章节识别、元数据补全、CSS 注入——用户只看到一个干净的 EPUB 出现在 KOReader 中。
4. **标注闭环**：KOReader 中的划线和笔记通过 WebDAV 自动回流，AI 管线每日定时将它们合成为结构化笔记，存入本地知识库。

### AI 驱动流程总览

```
来源文件 (TXT/MOBI/AZW3/PDF/EPUB)
    │
    ▼
[AI 格式判定] ── 识别输入类型，确定处理策略
    │
    ▼
[转换标准化] ── ebook-convert → EPUB 初稿
    │
    ▼
[AI 章节检测] ── GLM-4.7 语义分析（TXT 无结构输入专用）
    │                                      正规失败时降级
    ▼
[AI CSS 审查] ── GLM-4.7 审核并注入阅读优化样式表
    │
    ▼
[结构验证] ── EPUBCheck → ebooklib 自动修复
    │
    ▼
[AI 元数据补全] ── 多源查询 → GLM-4.7 交叉验证 → 写入 EPUB
    │
    ▼
[MCP 入库] ── calibremcp → Calibre 书库（EPUB 母本）
    │
    ▼
[WebDAV 推送] ── KOReader 云端下载 → 开始阅读
    │
    ▼
┌─────────────────────────────────────────┐
│  阅读中：标注回流循环                      │
│                                           │
│  KOReader 划线 → HighlightSync            │
│      → WebDAV 推送                        │
│      → Agent 定时拉取 (每日 22:00)         │
│      → 第 1 层：GLM-4.7 去重/筛选/格式化   │
│      → 第 2 层：GLM-5.2 合成/关联/笔记生成 │
│      → 写入本地知识库                      │
│      → 清理 WebDAV 已处理文件              │
└─────────────────────────────────────────┘
```

---

## 系统拓扑

```
┌─────────────────────────────────────────────────────────────────────┐
│                     云服务器 (2C2G Docker)                           │
│                                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐    │
│  │ New API  │  │ Nginx    │  │ WebDAV   │  │  Calibre CLI      │    │
│  │ :3000    │  │ :443     │  │ :8181    │  │  (无头模式)       │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘    │
│       │             │             │                   │              │
│       ▼             ▼             ▼                   ▼              │
│  模型智能路由   TLS 终止     KOReader ↔ PC       ebook-convert       │
│  GLM/DS/MM/Kimi  速率限制    书籍/笔记同步        calibredb           │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Agent 运行时 (CherryStudio / Claude Code 通过 SSH)            │   │
│  │  - EPUB 处理编排                                               │   │
│  │  - 元数据补全管线                                              │   │
│  │  - KOReader 标注摄取与合成                                     │   │
│  │  - 定时任务调度 (cron: 每日 22:00 标注回流)                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
          │                                      │
          │ Tailscale                             │ HTTPS
          ▼                                      ▼
┌──────────────────────┐           ┌──────────────────────────┐
│   Windows 笔记本      │           │     Kindle PW5            │
│                      │           │                           │
│  - Calibre GUI       │           │  KOReader (主力阅读)       │
│  - Sigil (GUI 修复)   │           │  Kindle 原生 (备用)        │
│  - KOSyncthing+ 节点 │           │                           │
│  - Multica 守护进程   │           │  Syncery (Syncthing 同步) │
│                      │           │  HighlightSync (WebDAV)    │
│                      │           │  Cloud Storage (WebDAV)    │
└──────────────────────┘           └──────────────────────────┘
```

---

## 数据流

### A. 书籍入库流（AI 增强）

```
来源 → Calibre 接收 → EPUB 处理管线 → 元数据补全 → KOReader

详细步骤:
  任意格式 (TXT/MOBI/AZW3/PDF/EPUB/HTML)
    → AI 格式判定，选择最优转换策略
    → ebook-convert → EPUB 标准化
    → EPUBCheck → 结构验证
    → AI 章节检测 (GLM-4.7，TXT 输入专用；正则匹配失败时降级为语义识别)
    → OpenCC 简繁转换 (若源文件为繁体)
    → AI CSS 审查 (GLM-4.7) → 注入 KOReader 优化样式表
    → ebooklib → 结构修复 (目录生成、NCX 修正、spine 排序)
    → 元数据管线 (ISBN 检索 → 豆瓣/Google Books/OpenLibrary 多源查询 → GLM-4.7 交叉验证 → calibredb 写入)
    → Calibre 书库 (EPUB 母本)
    → WebDAV 上传 → KOReader Cloud Storage 下载
    → Agent 通知 (IM 通道活跃时通过 Hermes 推送至微信)
```

### B. 标注回流（AI 合成）

```
KOReader → HighlightSync → WebDAV → Agent 管线 → 本地知识库

详细步骤:
  KOReader 阅读标注 (.sdr/metadata.epub.lua)
    → HighlightSync 自动合并 → WebDAV 推送
    → Agent cron (每日 22:00) → 从 WebDAV 拉取 JSON
    → 阶段 1 (GLM-4.7): 去重、筛选、格式化、语言检测
    → 阶段 2 (GLM-5.2): 跨章节合成、主题关联发现、生成结构化笔记
    → 写入本地知识库 (Obsidian/Markdown)
    → 清理 WebDAV 上已处理的标注文件
```

### C. 按需修复流（AI 辅助）

```
用户请求 → Agent 分析 → 修复策略 → 执行 → 验证

详细步骤:
  例："修复 D:\Books\乱码.epub 的排版"
    → EPUBCheck → 识别问题清单
    → Agent CSS 审查 (GLM-4.7) → 生成修复脚本
    → ebooklib → 程序化应用修复
    → [复杂情况] Sigil Automate List → GUI 手动精修
    → EPUBCheck 重新验证
    → 输出修复报告 (问题数 / 已修复 / 需人工)
```

---

## 模型路由策略

所有 LLM 调用通过 New API (API 网关) 统一路由，按任务特征自动选择最优模型。

### 模型清单

| 模型 | 来源 | 核心能力 | 适用场景 |
|---|---|---|---|
| **GLM-5.2** | 智谱 | 强推理、长文本综合 | 跨章节笔记合成、主题关联 |
| **GLM-4.7** | 智谱 | 轻量、高性价比、中文优化 | 章节检测、CSS 审查、元数据验证 |
| **DeepSeek V4** | DeepSeek | 双语翻译、长文本分析 | 章节边界识别、结构化提取、双语翻译 |
| **MiniMax M3** | MiniMax | 多模态理解 | 封面分析、插图描述 |
| **Kimi K2.7** | Moonshot | 视觉识别、OCR | 封面文字识别、扫描件处理 |

### 任务路由表

| 任务 | 首选模型 | 降级模型 | 触发条件 | 估算成本/次 |
|---|---|---|---|---|
| 章节识别 (TXT) | GLM-4.7 | DeepSeek V4 | 正则匹配失败时 | ~¥0.005 |
| CSS 审查与注入 | GLM-4.7 | — | 每次 EPUB 入库 | ~¥0.01 |
| 元数据交叉验证 | GLM-4.7 + 规则引擎 | — | 每本新书入库 | ~¥0.02 |
| 标注 → 笔记 (阶段 1) | GLM-4.7 | — | 每日定时 | ~¥0.1/周 |
| 标注 → 笔记 (阶段 2) | GLM-5.2 | — | 阶段 1 完成后 | ~¥0.3/本 |
| 双语翻译 | DeepSeek V4 | GLM-5.2 | 按需触发 | ~¥0.5/本 |
| 封面 OCR | Kimi K2.7 | MiniMax M3 | 按需触发 | ~¥0.02/张 |
| 长文本章节分析 | DeepSeek V4 | GLM-5.2 | TXT > 50万字 | ~¥0.08/次 |

### 路由策略设计理念

- **分层降级**：每个任务均有首选和降级模型，API 网关自动检测可用性并切换。
- **成本优先**：能用 GLM-4.7 解决的问题不上 GLM-5.2，能用 DeepSeek V4 解决的问题不上 GLM-5.2。
- **两阶段管道**：轻量模型做萃取（GLM-4.7），强推理模型做综合（GLM-5.2 / DeepSeek V4）。成本节省约 46%，速度提升约 70%。

---

## MCP 服务矩阵

MCP 优先架构意味着：所有工具能力以 MCP Server 形式暴露，Agent (CherryStudio / Claude Code) 通过标准协议调用，无需硬编码工具集成。

### 已部署

| MCP Server | 工具数 | 职责 |
|---|---|---|
| **calibremcp** | 21 | Calibre 书库 CRUD、语义搜索、元数据读写、格式批量转换、书库统计 |

### 规划开发

| MCP Server | 核心工具 | 优先级 | 预计工具数 |
|---|---|---|---|
| **epub-processor** | `epub_validate`, `epub_fix_common`, `epub_convert`, `epub_chapter_detect`, `epub_css_audit`, `epub_inject_css`, `epub_toc_rebuild` | P1 | 7+ |
| **metadata-enricher** | `isbn_lookup`, `search_metadata`, `cross_validate`, `enrich_book`, `batch_enrich`, `cover_ocr` | P1 | 6+ |
| **koreader-bridge** | `list_devices`, `get_highlights`, `get_progress`, `sync_to_pc`, `push_book`, `get_reading_stats` | P2 | 6+ |

详见 `docs/mcp-specs.md`。

---

## 脚本管线

5 个 Python 脚本覆盖从原始文件到 KOReader 就绪 EPUB 的完整链路：

```
scripts/
├── txt2epub/
│   └── pipeline.py              网文 TXT → EPUB 全自动管线
│       · AI 章节检测 (GLM-4.7)
│       · 正则卷/章/节识别
│       · OpenCC 简繁转换
│       · KOReader 优化 CSS 注入
│       · 目录自动生成
├── epub_fix/
│   ├── validate.py              EPUBCheck 包装器，输出结构化问题清单
│   └── fix_common.py            EPUB 结构常见问题自动修复
│       · spine 排序 · NCX 修正 · 资源引用修复 · 元数据补全
├── metadata/
│   └── enrich.py                ISBN → 多源元数据查询 + AI 交叉验证
│       · 豆瓣 / Google Books / OpenLibrary
│       · GLM-4.7 数据融合 · calibredb 自动写入
└── koreader_sync/
    └── sync_highlights.py       KOReader 标注同步 + AI 合成导出
        · WebDAV 拉取 · GLM-4.7 去重格式化 · 本地 Markdown 输出
```

---

## TXT 网文专项管线

这是本体系最核心的特色能力——将动辄数百万字的无结构 TXT 网文自动转化为排版精良的 EPUB。

### 处理流程

```
原始 TXT (GBK/UTF-8)
    │
    ▼
[编码检测] ── charset-normalizer → UTF-8 标准化
    │
    ▼
[卷章识别 - 第 1 轮] ── 正则匹配 (第X卷/第X章/Chapter/Section/序/跋/番外)
    │
    ├── 匹配率 > 85% → 通过，直接生成目录结构
    │
    └── 匹配率 < 85% → 降级
            │
            ▼
        [卷章识别 - 第 2 轮] ── AI 语义分析 (GLM-4.7)
            │  输入: 全文前 5% + 疑似章节标题行列表
            │  输出: 章节边界列表 + 层级关系
            │
            ▼
        [人工确认] ── Agent 输出识别结果，用户一键确认或微调
    │
    ▼
[简繁转换] ── OpenCC → 统一简体中文
    │
    ▼
[CSS 注入] ── 注入 KOReader 优化样式表:
    · 强制行高 1.6em
    · 忽略出版方字体族，使用 KOReader 默认衬线
    · 段落首行缩进 2em，段间距 0.5em
    · 章节标题层级化样式
    │
    ▼
[EPUB 生成] ── ebooklib → 结构化 EPUB
    · NCX 目录 + NAV 目录 (双目录兼容)
    · 封面占位 (元数据补全后替换)
    · spine 线性阅读顺序
    │
    ▼
[验证] ── EPUBCheck → 0 错误 0 警告
```

---

## 部署清单

### 云服务器

```yaml
# 追加到云工作站 deploy/docker-compose.yml
webdav:
  image: bytemark/webdav
  ports: "127.0.0.1:8181:80"
  environment:
    AUTH_TYPE: Digest
    USERNAME: koreader
    PASSWORD: ${WEBDAV_PASSWORD}
  volumes:
    - ./webdav/data:/data
    - ./webdav/books:/books

calibre:
  image: linuxserver/calibre
  ports: "127.0.0.1:8080:8080"
  volumes:
    - ./calibre/config:/config
    - ./calibre/library:/books
```

### Windows 笔记本

```powershell
# Calibre (GUI + CLI)
scoop install calibre

# EPUBCheck (W3C 验证工具)
# 下载地址: https://github.com/w3c/epubcheck/releases

# Python 脚本依赖
pip install ebooklib charset-normalizer opencc pillow lxml

# MCP 客户端
# CherryStudio 内置 MCP 支持，或在 Claude Code 中配置 mcp.json
```

### Kindle (KOReader)

```
越狱后安装 KOReader，推荐安装如下插件:
  - Syncery (Syncthing 同步)
  - HighlightSync (WebDAV 标注同步)
  - Cloud Storage (WebDAV 书籍下载)
  - KOSyncthing+ (Syncthing 守护进程)

KOReader 样式调整建议:
  - 忽略出版方字体族
  - 强制统一行高
  - 启用连页模式 (连续滚动)
```

---

## 成本

| 类别 | 月费 |
|---|---|
| AI API (New API 多模型路由) | ~¥3-4 |
| WebDAV 容器 | ¥0 (复用已有服务器) |
| Calibre / KOReader / Sigil / EPUBCheck | ¥0 (全开源) |
| **合计** | **~¥3-4/月** |

> 成本基于个人阅读量估算 (月均入库 8-12 本，日均有标注回流)。批量处理或长篇小说翻译场景下月费不超过 ¥10。

---

## 参考

- [calibremcp](https://github.com/sandraschi/calibremcp)
- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [EPUBCheck (W3C)](https://github.com/w3c/epubcheck)
- [ebooklib](https://github.com/aerkalov/ebooklib)
- [Sigil Plugin Framework](https://github.com/Sigil-Ebook/Sigil/blob/master/docs/Sigil_Plugin_Framework_rev15.epub)
- [OpenCC](https://github.com/BYVoid/OpenCC)
- [WinterBreak Jailbreak](https://kindlemodding.org/)
