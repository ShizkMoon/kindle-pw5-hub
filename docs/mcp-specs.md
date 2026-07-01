# MCP 工具规范 —— Kindle PW5 电子书管线

> 本文档定义 CherryOps（我的 AI 智能体）所需的全部 MCP 工具规范。
> 所有 MCP Server 以 Python (FastMCP 3.x) 实现，部署在 ☁️ 云服务器，AI 推理均通过 New API 网关统一调度。

---

## 0. 架构概览 —— New API 模型路由

### 智能体如何调用 AI 能力

CherryOps 运行在 Windows 笔记本或云服务器上，通过 CherryStudio / Claude Code 宿主程序接入。当需要 AI 推理时，不会直接调用任何模型厂商的 API，而是通过以下链路统一路由：

```
CherryOps (智能体)
  │
  ├─ MCP 协议调用各个工具
  │   ├── epub-processor (电子书处理)
  │   ├── metadata-enricher (元数据补全)
  │   └── koreader-bridge (KOReader 桥接)
  │
  └─ 每个 MCP Server 内部，凡需要 AI 推理的场景
      │
      └── 统一调用 New API 网关
          │
          ├── 智谱 GLM-5.2 —— 长文本章节分析、CSS 规则生成
          ├── 智谱 GLM-4.7 —— 元数据交叉验证、章节结构检测
          ├── DeepSeek V4 —— 批量元数据推断、文本清洗
          ├── MiniMax M3  —— 书籍摘要、内容理解
          └── Kimi K2.7   —— 封面文字识别、多模态视觉处理
```

### New API 网关配置

所有 MCP Server 通过以下环境变量接入 New API：

| 环境变量 | 说明 |
|---|---|
| `NEW_API_URL` | New API 网关地址，例如 `https://api.your-domain.com` |
| `NEW_API_KEY` | New API 的 API Key |
| `NEW_API_DEFAULT_MODEL` | 默认模型，例如 `glm-4.7`（可在工具调用时覆盖） |

每个工具在需要 AI 能力时，会通过 `openai` 兼容接口向 New API 发送请求。New API 根据请求中的 `model` 参数，自动路由到对应的后端模型（智谱、DeepSeek、MiniMax、Kimi 等），无需每个 MCP Server 分别管理多套 API Key。

### 我的电子书工作流

CherryOps 需要以下三类 MCP 能力来支撑完整的 Kindle PW5 电子书管线：

1. **电子书处理**（epub-processor）—— 格式验证、自动修复、章节检测、CSS 审计与注入
2. **元数据补全**（metadata-enricher）—— ISBN 查询、标题搜索、AI 交叉验证、批量入库
3. **Kindle 桥接**（koreader-bridge）—— 设备发现、标注拉取、书籍推送、阅读统计

以下各节详细定义每个 MCP Server 的工具接口。

---

## 一、电子书处理器（epub-processor）

### 概述

EPUB 处理管线的 MCP Server，运行在 ☁️ 云服务器上。CherryOps 用它来验证书籍格式、自动修复常见问题、检测章节结构以及标准化 CSS 排版。所有 AI 辅助功能（章节检测回退、CSS 审计）通过 New API 调用智谱 GLM-4.7 / GLM-5.2 完成。

### 工具

#### `epub_validate`

```
功能: 对 EPUB 文件运行 EPUBCheck 校验，返回结构化诊断结果。CherryOps 在每次格式转换后调用此工具，确保输出合规。
参数:
  - path: string —— EPUB 文件的绝对路径
返回:
  {
    "valid": true/false,                      // 是否通过校验
    "errors": [
      {
        "type": "ERROR",                      // 严重程度: ERROR | WARNING | INFO
        "file": "OEBPS/chapter1.xhtml",       // 出错文件
        "line": 42,                           // 出错行号
        "message": "未找到资源引用"             // 错误详情
      }
    ],
    "warnings": [...],                        // 警告列表
    "info": [...]                             // 提示信息列表
  }
实现: subprocess 调用 java -jar epubcheck.jar --json，解析 JSON 输出
```

#### `epub_fix_common`

```
功能: 自动修复常见的 EPUB 格式问题，减少手工干预。CherryOps 在校验失败后调用此工具快速修复。
参数:
  - path: string —— EPUB 文件路径
  - fixes: string[] —— 要执行的修复类型，可选值:
      "manifest"       —— 补充 OPF manifest 中缺失的资源引用
      "broken_links"   —— 修复损坏的内部链接
      "date_format"    —— 规范化日期格式为 ISO 8601
      "css_syntax"     —— 修复 CSS 语法错误
返回:
  {
    "fixed_count": 5,                                      // 修复了的问题数量
    "fixes_applied": ["manifest: 2 个缺失项已补充", ...],   // 已应用的修复列表
    "remaining_issues": [...]                              // 修复后仍存在的问题
  }
实现: ebooklib 读写 EPUB，逐项应用规则修复
```

#### `epub_convert`

```
功能: 将任意格式（TXT、MOBI、AZW3、HTML 等）转换为 EPUB，包装 Calibre 的 ebook-convert 命令行工具。CherryOps 用它做入仓前的格式统一。
参数:
  - input_path: string —— 输入文件路径
  - output_path: string —— 输出 EPUB 路径
  - options: object —— 转换选项:
      base_font_size: number        基础字号（默认 12）
      remove_paragraph_spacing: boolean  移除段间距
      insert_blank_line: boolean    段间插入空行
      chapter_mark: string          章节检测规则（"pagebreak" | "linebreak" | "none"）
返回:
  {
    "success": true,
    "output_path": "/path/to/output.epub",
    "input_format": "TXT",
    "output_size_kb": 1234
  }
实现: subprocess 调用 ebook-convert，传递对应参数
```

#### `epub_chapter_detect`

```
功能: 检测 TXT 文件的章节结构，正则匹配优先，失败时可回退到 AI 分析。CherryOps 在处理网文 / 自排版 TXT 时依赖此工具自动划分章节。
参数:
  - path: string —— TXT 文件路径
  - use_ai: boolean —— 正则匹配失败时是否启用 AI 辅助（通过 New API 调用 GLM-4.7 分析文本结构）
返回:
  {
    "format": "chinese_chapter",                    // 章节格式: "chinese_chapter" | "numeric" | "custom"
    "chapters": [
      {
        "index": 0,                                 // 章节序号
        "title": "第一章 重逢",                      // 章节标题
        "start_line": 42                            // 起始行号
      }
    ],
    "ai_assisted": false,                           // 是否使用了 AI 辅助
    "confidence": 0.95                              // 置信度（AI 辅助时反映模型信心）
  }
实现:
  1. 正则匹配 "第[零一二三四五六七八九十百千万0-9]+[章回卷节]" 模式
  2. 若匹配失败且 use_ai=true → 调用 New API（GLM-4.7）分析文本结构，返回章节边界
  3. 对 AI 结果做后处理：合并连续相似标题、去重、编号归一化
```

#### `epub_css_audit`

```
功能: 对 EPUB 内部 CSS 进行全面审计，结合规则引擎和 AI 分析识别排版问题。CherryOps 用它确保推送至 Kindle 的书籍排版符合 PW5 墨水屏阅读标准。
参数:
  - path: string —— EPUB 文件路径
返回:
  {
    "issues": [
      {
        "severity": "HIGH",                          // 严重程度: HIGH | MEDIUM | LOW
        "file": "OEBPS/styles/style.css:42",         // 文件及行号
        "issue": "使用 px 单位指定字体大小，无法跟随 Kindle 用户字号设置",
        "fix": "将 font-size: 16px 替换为 font-size: 1em"
      }
    ],
    "suggested_css": "/* AI 生成的优化 CSS */",      // AI 建议的完整 CSS
    "stats": {
      "total_rules": 120,                            // 总规则数
      "px_usage": 15,                                // 使用 px 单位的规则数
      "pt_usage": 3,                                 // 使用 pt 单位的规则数
      "body_lock": true,                             // 是否锁定了 body 字体
      "line_height_issues": 5,                       // line-height 过小的规则数
      "em_margin_issues": 2                          // 使用 em 做水平边距的规则数
    }
  }
实现:
  1. ebooklib 提取 EPUB 内全部 CSS 文件
  2. 规则引擎检查: px/pt 单位使用、body 字体锁定、line-height < 1.2、em 水平边距、绝对定位
  3. 调用 New API（GLM-5.2）深度审查 CSS 质量，生成修复建议和优化后的完整 CSS
```

#### `epub_inject_css`

```
功能: 将标准化 CSS 注入 EPUB，覆盖或追加样式。CherryOps 在 CSS 审计后调用此工具，统一所有书籍的排版基线。
参数:
  - path: string —— EPUB 文件路径
  - mode: "append" | "replace" —— 追加模式（保留原样式，追加新规则）或替换模式（完全替换）
  - css: string (可选) —— 自定义 CSS 内容，不提供则使用内置的 Kindle PW5 标准 CSS 模板
返回:
  {
    "success": true,
    "rules_added": 45                                // 注入的 CSS 规则数
  }
实现: ebooklib 读取 EPUB，将 CSS 注入到每个 HTML 文件的 <head> 或替换原有样式表
```

---

## 二、元数据补全器（metadata-enricher）

### 概述

多源元数据查询 + AI 交叉验证 + Calibre 写入的 MCP Server。CherryOps 用它来为书库中的书籍自动补全标题、作者、封面、简介、标签等元数据。所有 AI 交叉验证通过 New API 调用 GLM-4.7 完成。

### 工具

#### `isbn_lookup`

```
功能: 根据 ISBN 并行查询多个数据源的元数据。CherryOps 在获取书籍 ISBN 后首选此工具，一次拿到多源结果供交叉验证。
参数:
  - isbn: string —— 10 位或 13 位 ISBN
  - sources: string[] —— 查询源列表，可选值:
      "google"        —— Google Books API（权威度最高）
      "openlibrary"   —— Open Library API（覆盖广，中文书较少）
      "goodreads"     —— Goodreads（评分和标签补充）
返回:
  {
    "isbn": "9787544270878",
    "sources": {
      "google": {
        "title": "百年孤独",
        "authors": ["加西亚·马尔克斯"],
        "description": "...",
        "cover_url": "https://books.google.com/...",
        "published_date": "2011-06-01",
        "publisher": "南海出版公司",
        "page_count": 256
      },
      "openlibrary": {
        "title": "...",
        "authors": [...],
        "description": "...",
        "cover_url": "...",
        "published_date": "...",
        "publisher": "...",
        "page_count": 272
      },
      "goodreads": {
        "rating": 4.2,
        "tags": ["文学", "魔幻现实主义", "经典"],
        "title": "...",
        "authors": [...]
      }
    },
    "query_time_ms": 850                            // 总查询耗时（毫秒）
  }
实现: aiohttp 并行请求各 API，汇总结果。对 Goodreads 使用网页抓取（无官方 API）。
```

#### `search_metadata`

```
功能: 通过标题 + 作者模糊搜索元数据，适用于没有 ISBN 的书籍。CherryOps 在 ISBN 缺失时使用此工具补全元数据。
参数:
  - title: string —— 书籍标题
  - author: string (可选) —— 作者名，提供后提升准确率
  - lang: "zh" | "en" —— 搜索语言，影响 API 查询参数
返回:
  [
    {
      "source": "google",                          // 数据来源
      "title": "百年孤独",
      "authors": ["加西亚·马尔克斯"],
      "confidence": 0.92,                          // 匹配置信度
      "isbn": "9787544270878",                     // 匹配到的 ISBN（如有）
      "description": "...",
      "cover_url": "...",
      "published_date": "...",
      "publisher": "..."
    }
  ]
实现: Google Books API + Open Library API 模糊搜索，按置信度排序返回
```

#### `cross_validate`

```
功能: 对多源元数据结果进行 AI 交叉验证和冲突解决。CherryOps 在拿到多个数据源的元数据后调用此工具，获得一份经过 AI 验证的统一元数据。
参数:
  - metadata_sources: array —— 各数据源的元数据对象，格式同 isbn_lookup 的 sources 字段
返回:
  {
    "merged": {
      "title": "百年孤独",
      "authors": ["加西亚·马尔克斯"],
      "description": "...",
      "cover_url": "...",
      "published_date": "2011-06-01",
      "publisher": "南海出版公司",
      "page_count": 256,
      "tags": ["文学", "魔幻现实主义", "经典"]
    },
    "conflicts": [
      {
        "field": "page_count",                     // 冲突字段
        "values": [256, 272, 0],                   // 各源的值
        "resolved": 256,                           // 解决后的值
        "confidence": 0.9,                         // 解决置信度
        "reasoning": "Google Books 数据来自出版商，权威度最高；272 可能含前言目录页"
      }
    ],
    "ai_model": "glm-4.7",                         // 使用的 AI 模型
    "cost": 0.008                                  // AI 调用费用（美元）
  }
实现:
  1. 逐字段比较各数据源的值
  2. 规则引擎先行处理: ISBN 匹配字段以 Google Books 为权威源、出版日期以 LoC 为优先、描述取最长且质量最高的
  3. 高冲突字段（多源差异大且无明确规则）→ 调用 New API（GLM-4.7）进行语义级判断
  4. 合并冲突解决结果生成最终统一元数据
```

#### `enrich_book`

```
功能: 对单本书籍执行元数据补全并写入 Calibre。CherryOps 用它完成逐本书的自动化元数据入库。
参数:
  - book_id: int —— Calibre 书库中的书籍 ID
  - auto_apply: boolean —— 高置信度字段是否自动写入（低于阈值的字段标记为待审核）
返回:
  {
    "applied_fields": ["title", "authors", "description", "publisher"],
    "pending_review": [
      {
        "field": "tags",
        "suggested_value": ["文学", "经典"],
        "reason": "置信度 0.65，低于自动写入阈值 0.8"
      }
    ],
    "confidence": 0.85                              // 整体置信度
  }
实现: 先通过 calibremcp 获取书籍现有元数据 → isbn_lookup / search_metadata 查源 → cross_validate 验证 → calibredb set_metadata 写入
```

#### `batch_enrich`

```
功能: 批量扫描书库中缺少元数据的书籍并逐一补全。CherryOps 用它做全库元数据体检和批量修复。
参数:
  - limit: int —— 单次最大处理数量（防止 API 费用过高）
  - min_confidence: float —— 自动写入的最低置信度阈值（建议 0.8）
返回:
  {
    "processed": 42,                                // 扫描到的缺元数据书籍数
    "enriched": 38,                                 // 成功补全的书籍数
    "skipped": 4,                                   // 跳过的书籍数（无匹配结果）
    "total_cost": 0.15,                             // 总 AI 调用费用（美元）
    "details": [
      {"book_id": 12, "status": "enriched", "fields_added": 5},
      {"book_id": 47, "status": "skipped", "reason": "无匹配数据源"}
    ]
  }
实现: calibremcp find_books_needing_enrichment 扫描 → 逐个调用 enrich_book
```

---

## 三、KOReader 桥接器（koreader-bridge）

### 概述

CherryOps 与 Kindle 上 KOReader 之间的桥梁 MCP Server，运行在 ☁️ 云服务器上，通过 WebDAV / Syncthing 与 Kindle 通信。CherryOps 用它来：发现设备、拉取标注笔记、推送处理好的书籍、查询阅读进度。

### 工具

#### `koreader_list_devices`

```
功能: 扫描网络中正在运行 KOReader 的 Kindle 设备。CherryOps 在执行任何设备相关操作前先调用此工具确认设备在线。
参数: 无
返回:
  [
    {
      "device_id": "kindle-pw5-01",                 // 设备唯一标识
      "device_name": "我的 Kindle",                  // 设备显示名称
      "ip": "192.168.1.100",                        // 局域网 IP
      "last_seen": "2026-07-02T14:30:00+08:00",     // 最后在线时间
      "syncthing_status": "connected",              // Syncthing 连接状态
      "battery": 85                                 // 电量百分比
    }
  ]
实现: Syncthing REST API 查询 + mDNS 服务发现
```

#### `koreader_get_highlights`

```
功能: 通过 WebDAV 拉取指定书籍的标注和读书笔记。CherryOps 用它定期同步阅读笔记到 Obsidian 知识库。
参数:
  - device_id: string —— 设备标识
  - book_hash: string (可选) —— 书籍文件哈希，不提供则拉取所有新增标注
返回:
  {
    "device_id": "kindle-pw5-01",
    "book_title": "百年孤独",
    "book_hash": "a1b2c3d4...",
    "highlights": [
      {
        "text": "多年以后，面对行刑队，奥雷里亚诺·布恩迪亚上校将会回想起父亲带他去见识冰块的那个遥远的下午。",
        "chapter": "第一章",
        "position": "page:1",                       // KOReader 内部位置
        "timestamp": "2026-07-01T22:15:00+08:00",   // 标注时间
        "note": "经典开篇",                          // 用户手动添加的笔记
        "type": "highlight"                         // 类型: highlight | bookmark | note
      }
    ],
    "export_format": "json"
  }
实现: WebDAV GET 请求拉取 KOReader 的 highlights JSON 文件 → 解析并按时间排序
```

#### `koreader_push_book`

```
功能: 将处理好的 EPUB 推送到 KOReader 设备。CherryOps 在完成电子书处理和元数据补全后调用此工具，将成品推送到 Kindle。
参数:
  - book_path: string —— 本地 EPUB 文件路径
  - device_id: string —— 目标设备标识
返回:
  {
    "success": true,
    "book_title": "百年孤独",
    "uploaded_to": "/koreader/books/百年孤独.epub",  // WebDAV 目标路径
    "file_size_kb": 1024
  }
实现: 通过 WebDAV PUT 上传到设备的 /koreader/books/ 目录
```

#### `koreader_get_stats`

```
功能: 获取设备的阅读统计数据。CherryOps 用它生成阅读周报/月报，跟踪阅读习惯。
参数:
  - device_id: string —— 设备标识
  - period: "today" | "week" | "month" —— 统计周期
返回:
  {
    "device_id": "kindle-pw5-01",
    "period": "week",
    "reading_time_minutes": 720,                    // 总阅读时长（分钟）
    "pages_read": 340,                              // 阅读页数
    "books_finished": 2,                            // 本周读完的书籍数
    "current_books": [
      {
        "title": "百年孤独",
        "progress_percent": 42,                     // 阅读进度百分比
        "last_read": "2026-07-02T08:30:00+08:00"
      }
    ],
    "avg_reading_speed": 280                        // 平均阅读速度（字/分钟）
  }
实现: KOReader 统计插件通过 Syncthing 同步到云服务器 → 解析统计 JSON 文件
```

---

## 部署配置

所有 MCP Server 通过 `uv` 或 `pip` 安装，以 stdio 或 HTTP transport 协议连接到 CherryOps 的宿主程序（CherryStudio / Claude Code）。

CherryOps 的 MCP 配置示例（CherryStudio 的 `.mcp.json` 或 Claude Code 的 `mcp.json`）：

```json
{
  "mcpServers": {
    "epub-processor": {
      "command": "python",
      "args": ["-m", "epub_processor.server"],
      "env": {
        "NEW_API_URL": "https://api.your-domain.com",
        "NEW_API_KEY": "sk-xxx",
        "NEW_API_DEFAULT_MODEL": "glm-4.7"
      }
    },
    "metadata-enricher": {
      "command": "python",
      "args": ["-m", "metadata_enricher.server"],
      "env": {
        "NEW_API_URL": "https://api.your-domain.com",
        "NEW_API_KEY": "sk-xxx",
        "NEW_API_DEFAULT_MODEL": "glm-4.7"
      }
    },
    "koreader-bridge": {
      "command": "python",
      "args": ["-m", "koreader_bridge.server"],
      "env": {
        "KOBO_WEBDAV_URL": "http://192.168.1.100:8080",
        "SYNCTHING_API_KEY": "xxx"
      }
    }
  }
}
```

## 依赖安装

```bash
pip install fastmcp ebooklib charset-normalizer opencc aiohttp
```
