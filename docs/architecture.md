# System Architecture

> Kindle PW5 × dorm-workstation AI 体系集成架构。工程规格，非规划文档。

## 前置决策

| 决策 | 状态 |
|---|---|
| Kindle 越狱 | ✅ 已确认，WinterBreak 方案 |
| 主力阅读器 | KOReader（Kindle 原生系统保留备用） |
| 唯一格式 | EPUB（任何输入→EPUB→KOReader） |
| 亚马逊云 | 不使用（无 Whispersync、Send to Kindle） |
| AI 骨干 | New API + 5 模型路由 + MCP 生态 |
| 运行平台 | ☁️ 云服务器 (2C2G) + 💻 Windows 本机 |

---

## 系统拓扑

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Cloud Server (2C2G Docker)                        │
│                                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐    │
│  │ New API  │  │ Nginx    │  │ WebDAV   │  │  Calibre CLI      │    │
│  │ :3000    │  │ :443     │  │ :8181    │  │  (headless)       │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘    │
│       │             │             │                   │              │
│       ▼             ▼             ▼                   ▼              │
│  Model Routing  TLS Term    KOReader ↔ PC       ebook-convert       │
│  GLM/DS/MM/Kimi Rate Limit  Book/Notes Sync     calibredb           │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Agent Runtime (CherryStudio / Claude Code via SSH)            │   │
│  │  - EPUB processing orchestration                               │   │
│  │  - Metadata enrichment pipeline                                │   │
│  │  - KOReader highlight ingestion                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
          │                                      │
          │ Tailscale                             │ HTTPS
          ▼                                      ▼
┌──────────────────────┐           ┌──────────────────────────┐
│   Windows Laptop     │           │     Kindle PW5            │
│                      │           │                           │
│  - Calibre GUI       │           │  KOReader (primary)       │
│  - Sigil (GUI fix)   │           │  Kindle Native (backup)   │
│  - KOSyncthing+ peer │           │                           │
│  - Multica daemon    │           │  Syncery (Syncthing)      │
│                      │           │  HighlightSync (WebDAV)   │
└──────────────────────┘           │  Cloud Storage (WebDAV)   │
                                   └──────────────────────────┘
```

---

## 数据流

### A. 书籍入库流

```
Source → Calibre Ingest → EPUB Processing → Metadata → KOReader

Detail:
  Any format (TXT/MOBI/AZW3/PDF/EPUB/HTML)
    → ebook-convert → EPUB (standardized)
    → EPUBCheck → validation
    → AI chapter detection (TXT only)
    → ebooklib → structural fixes
    → Metadata pipeline (ISBN → multi-source → AI merge → calibredb)
    → Calibre library (EPUB master)
    → WebDAV upload → KOReader Cloud Storage download
    → Agent notification (Hermes via WeChat if IM channel active)
```

### B. 标注回流

```
KOReader → HighlightSync → WebDAV → Agent Pipeline → Local Store

Detail:
  KOReader reading annotations (.sdr/metadata.epub.lua)
    → HighlightSync auto-merge → WebDAV push
    → Agent cron (daily 22:00) → pull JSON from WebDAV
    → Phase 1 (GLM-4.7): dedup, filter, format
    → Phase 2 (GLM-5.2): synthesize, cross-link, generate notes
    → Write to local knowledge store
    → Cleanup processed files from WebDAV
```

### C. 按需修复流

```
User Request → Agent Analysis → Fix Strategy → Execution → Verification

Detail:
  "Fix the formatting of D:\Books\messy.epub"
    → EPUBCheck → identify issues
    → Agent CSS audit (GLM-4.7) → generate fix script
    → ebooklib → apply fixes programmatically
    → [if complex] Sigil Automate List → GUI repair
    → EPUBCheck re-validate
    → Output fix report
```

---

## MCP 服务矩阵

### 已部署

| MCP Server | 工具数 | 职责 |
|---|---|---|
| **calibremcp** | 21 | Calibre 书库 CRUD、语义搜索、元数据、格式转换 |

### 计划开发

| MCP Server | 工具 | 优先级 |
|---|---|---|
| **epub-processor** | `epub_validate`, `epub_fix_common`, `epub_convert`, `epub_chapter_detect`, `epub_css_audit` | P1 |
| **metadata-enricher** | `isbn_lookup`, `search_metadata`, `cross_validate`, `enrich_book`, `batch_enrich` | P1 |
| **koreader-bridge** | `list_devices`, `get_highlights`, `get_progress`, `sync_to_pc`, `push_book` | P2 |

详见 `docs/mcp-specs.md`。

---

## 多模型路由

| 任务 | 模型 | 触发条件 | 成本/次 |
|---|---|---|---|
| 章节识别 (TXT) | GLM-4.7 | 正则失败时 | ~¥0.005 |
| CSS 审查 | GLM-4.7 | 每次 EPUB 入库 | ~¥0.01 |
| 元数据交叉验证 | GLM-4.7 + 规则 | 每次新书 | ~¥0.02 |
| 标注 → 笔记 (阶段 1) | GLM-4.7 | 每日 | ~¥0.1/周 |
| 标注 → 笔记 (阶段 2) | GLM-5.2 | 阶段 1 完成后 | ~¥0.3/本 |
| 双语翻译 | DeepSeek V3 | 按需 | ~¥0.5/本 |
| 封面 OCR | Kimi K2.7 | 按需 | ~¥0.02/张 |

**两阶段管道**：轻量模型做萃取（GLM-4.7 / DeepSeek V3），强推理模型做综合（GLM-5.2）。成本节省 ~46%，速度提升 ~70%。

---

## 部署清单

### Cloud Server

```yaml
# 追加到 dorm-workstation deploy/docker-compose.yml
webdav:
  image: bytemark/webdav
  ports: "127.0.0.1:8181:80"
  environment:
    AUTH_TYPE: Digest
    USERNAME: koreader
    PASSWORD: ${WEBDAV_PASSWORD}

calibre:
  image: linuxserver/calibre
  ports: "127.0.0.1:8080:8080"
  volumes:
    - ./calibre/config:/config
    - ./calibre/library:/books
```

### Windows Laptop

```powershell
# Calibre (GUI + CLI)
scoop install calibre

# EPUBCheck
# Download from https://github.com/w3c/epubcheck/releases

# Dependencies for scripts
pip install ebooklib charset-normalizer opencc
```

### Kindle (KOReader)

```
Plugins to install after jailbreak + KOReader:
  - Syncery (Syncthing sync)
  - HighlightSync (WebDAV highlight sync)
  - Cloud Storage (WebDAV book download)
  - KOSyncthing+ (Syncthing daemon)

Style Tweaks to enable:
  - Ignore publisher font families
  - Enforce steady line heights
```

---

## 成本

| 类别 | 月费 |
|---|---|
| AI API (New API 模型路由) | ~¥3-4 |
| WebDAV 容器 | ¥0 (复用已有服务器) |
| Calibre / KOReader / Sigil | ¥0 (开源) |
| **合计** | **~¥3-4/月** |

---

## 参考

- [calibremcp](https://github.com/sandraschi/calibremcp)
- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [EPUBCheck (W3C)](https://github.com/w3c/epubcheck)
- [ebooklib](https://github.com/aerkalov/ebooklib)
- [Sigil Plugin Framework](https://github.com/Sigil-Ebook/Sigil/blob/master/docs/Sigil_Plugin_Framework_rev15.epub)
