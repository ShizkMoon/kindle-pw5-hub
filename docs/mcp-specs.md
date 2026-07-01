# MCP Tool Specifications

> Kindle PW5 管线所需的 MCP Server 工具定义。
> 实现语言：Python (FastMCP 3.x)，全部通过 New API 调用模型。

---

## 一、epub-processor

### 概述

EPUB 处理管线 MCP Server。运行在 ☁️ 云服务器。

### 工具

#### `epub_validate`

```
描述: 对 EPUB 文件运行 EPUBCheck，返回结构化结果
参数:
  - path: string (EPUB 文件路径)
返回:
  {
    "valid": true/false,
    "errors": [{"type": "ERROR", "file": "...", "line": 0, "message": "..."}],
    "warnings": [...],
    "info": [...]
  }
实现: subprocess 调 java -jar epubcheck.jar --json
```

#### `epub_fix_common`

```
描述: 自动修复常见 EPUB 格式问题
参数:
  - path: string
  - fixes: ["manifest", "broken_links", "date_format", "css_syntax"]
返回:
  {
    "fixed_count": 5,
    "fixes_applied": ["manifest: 2 missing items added", ...],
    "remaining_issues": [...]
  }
实现: ebooklib 读写 + 规则修复
```

#### `epub_convert`

```
描述: 任意格式 → EPUB (包装 ebook-convert)
参数:
  - input_path: string
  - output_path: string
  - options: {base_font_size, remove_paragraph_spacing, ...}
返回:
  {
    "success": true,
    "output_path": "...",
    "input_format": "TXT",
    "output_size_kb": 1234
  }
实现: subprocess 调 ebook-convert
```

#### `epub_chapter_detect`

```
描述: 检测 TXT 文件的章节结构，支持 AI 辅助
参数:
  - path: string (TXT 文件)
  - use_ai: bool (正则失败时是否启用 AI)
返回:
  {
    "format": "chinese_chapter",
    "chapters": [
      {"index": 0, "title": "第一章 重逢", "start_line": 42},
      ...
    ],
    "ai_assisted": false,
    "confidence": 0.95
  }
实现:
  1. 正则匹配 "第[0-9零一二三四五六七八九十百千万]+[章回卷节]"
  2. 失败 + use_ai → New API → GLM-4.7 分析文本结构
```

#### `epub_css_audit`

```
描述: AI 审查 EPUB 的 CSS，识别排版问题
参数:
  - path: string (EPUB 文件)
返回:
  {
    "issues": [
      {"severity": "HIGH", "file": "style.css:42", "issue": "Uses px units for font-size", "fix": "..."},
      ...
    ],
    "suggested_css": "...",
    "stats": {"total_rules": 120, "px_usage": 15, "conflicts": 3}
  }
实现:
  1. ebooklib 提取全部 CSS
  2. 规则检查 (px/pt 单位、body 锁定、line-height < 1.2、em 水平边距)
  3. AI (GLM-4.7) 深度审查 → 生成修复建议
```

#### `epub_inject_css`

```
描述: 注入标准化 CSS 到 EPUB
参数:
  - path: string
  - mode: "append" | "replace"
  - css: string (可选，不提供则使用内置标准 CSS)
返回: {"success": true, "rules_added": 45}
实现: ebooklib 注入标准 CSS 模板
```

---

## 二、metadata-enricher

### 概述

元数据多源查询 + AI 交叉验证 + Calibre 写入。

### 工具

#### `isbn_lookup`

```
描述: ISBN → 多源元数据并行查询
参数:
  - isbn: string
  - sources: ["google", "openlibrary", "goodreads"]
返回:
  {
    "isbn": "9787544270878",
    "sources": {
      "google": {"title": "...", "authors": [...], "description": "...", "cover_url": "...", "published_date": "...", "publisher": "...", "page_count": 256},
      "openlibrary": {...},
      "goodreads": {"rating": 4.2, "tags": [...]}
    },
    "query_time_ms": 850
  }
实现: aiohttp 并行请求各 API
```

#### `search_metadata`

```
描述: 标题+作者 → 模糊搜索元数据
参数:
  - title: string
  - author: string (可选)
  - lang: "zh" | "en"
返回: [{source, title, authors, confidence, isbn, ...}]
实现: Google Books API + Open Library API 模糊搜索
```

#### `cross_validate`

```
描述: 多源元数据 AI 交叉验证 + 冲突解决
参数:
  - metadata_sources: [{source, fields}]
返回:
  {
    "merged": {"title": "...", "authors": [...], ...},
    "conflicts": [
      {"field": "page_count", "values": [256, 272, 0], "resolved": 256, "confidence": 0.9, "reasoning": "..."}
    ],
    "ai_model": "glm-4.7",
    "cost": 0.008
  }
实现:
  1. 字段逐一比较各源
  2. 规则: ISBN→权威源优先、日期→LoC 优先、描述→长度+质量
  3. AI (GLM-4.7) 处理高冲突字段
```

#### `enrich_book`

```
描述: 单书元数据补全并写入 Calibre
参数:
  - book_id: int (Calibre book ID)
  - auto_apply: bool (高置信度自动写入)
返回: {applied_fields: [...], pending_review: [...], confidence: 0.85}
实现: calibredb + calibremcp API
```

#### `batch_enrich`

```
描述: 批量为书库中缺少元数据的书籍补全
参数:
  - limit: int (最大处理数)
  - min_confidence: float (自动应用阈值)
返回: {processed: 42, enriched: 38, skipped: 4, total_cost: 0.15}
实现: calibremcp find_books_needing_enrichment → 逐个 enrich_book
```

---

## 三、koreader-bridge

### 概述

Agent ↔ KOReader 直连桥接。运行在 ☁️ 云服务器，通过 WebDAV/SSH 与 Kindle 通信。

### 工具

#### `koreader_list_devices`

```
描述: 扫描网络中 KOReader 设备
返回: [{device_id, ip, last_seen, syncery_status, battery}]
实现: Syncthing API + mDNS
```

#### `koreader_get_highlights`

```
描述: 从 WebDAV 拉取指定书的标注
参数:
  - device_id: string
  - book_hash: string (可选，不提供则拉取所有新标注)
返回: {book_title, highlights: [{text, chapter, timestamp, note}], export_format: "json"}
实现: WebDAV GET → 解析 KOReader JSON
```

#### `koreader_push_book`

```
描述: 推送 EPUB 到 KOReader
参数:
  - book_path: string
  - device_id: string
返回: {success: true, uploaded_to: "webdav://koreader/books/xxx.epub"}
实现: 上传到 WebDAV /koreader/books/
```

#### `koreader_get_stats`

```
描述: 获取阅读统计
参数:
  - device_id: string
  - period: "today" | "week" | "month"
返回: {reading_time_minutes: 120, pages_read: 340, books_finished: 2, current_books: [...]}
实现: KOReader 统计插件 WebDAV 同步 → 解析
```

---

## 部署

所有 MCP Server 通过 `uv` 或 `pip` 安装，以 stdio 或 HTTP transport 连接到 Agent（CherryStudio / Claude Code）。

```json
// CherryStudio .mcp.json 示例
{
  "mcpServers": {
    "epub-processor": {
      "command": "python",
      "args": ["-m", "epub_processor.server"],
      "env": { "NEW_API_URL": "https://api.example.com", "NEW_API_KEY": "sk-xxx" }
    },
    "metadata-enricher": {
      "command": "python",
      "args": ["-m", "metadata_enricher.server"],
      "env": { "NEW_API_URL": "https://api.example.com", "NEW_API_KEY": "sk-xxx" }
    }
  }
}
```

## 依赖

```
pip install fastmcp ebooklib charset-normalizer opencc aiohttp
```
