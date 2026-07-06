# MCP 与工具接口规划

本文是未来 MCP 封装草案，不是当前已部署清单。当前可运行能力在 `scripts/hermes_books/`，稳定入口是 Python API 和 CLI。MCP 的目标是把这些能力暴露给 Hermes 或其他 Agent，而不是另写一套并行逻辑。

## 状态约定

| 状态 | 含义 |
|---|---|
| 已实现 | Python 模块和测试已存在，可以被 MCP 封装 |
| 可封装 | 能力存在，但还没有 MCP server |
| 规划 | 需要新实现或接外部服务 |
| 暂缓 | 需求明确，但当前不做 |

## 当前可封装能力

| 能力 | 状态 | 代码入口 |
|---|---|---|
| 本地 TXT/EPUB intake | 已实现 | `scripts.hermes_books.intake.run_intake` |
| EPUB 检查与质量报告 | 已实现 | `scripts.hermes_books.inspect.inspect_epub` |
| append-safe / metadata-safe diff | 已实现 | `scripts.hermes_books.diff.compare_for_update` |
| WebDAV 发布与 pending fallback | 已实现 | `scripts.hermes_books.publish.WebDavPublisher` |
| 元数据 evidence/decision 框架 | 已实现 | `scripts.hermes_books.metadata` |
| OPF metadata 写入 | 已实现 | `scripts.hermes_books.opf_metadata.apply_metadata_to_epub` |
| 封面候选自动采用 | 已实现 | `scripts.hermes_books.assets` |
| 真实网络元数据搜索 provider | 规划 | 待实现 |
| LLM reasoner | 规划 | 待实现 |
| KOReader sidecar migration | 暂缓 | 待单独设计 |

## 建议 MCP Server

### `hermes-books`

第一优先级。封装当前 intake 主线。

#### `book_intake`

输入：

```json
{
  "input_path": "D:\\Books\\raw.epub",
  "title": "书名",
  "author": "作者",
  "config_path": "config/hermes-books.yaml",
  "runs_root": "runs"
}
```

输出：

```json
{
  "job_id": "...",
  "output_epub": "runs/.../normalized/book.epub",
  "manifest": "runs/.../reports/manifest.json",
  "publish": {
    "status": "published",
    "path": "/books/书名 - 作者.epub"
  }
}
```

约束：

- 只接收本地路径。
- 不默认联网。
- 不隐藏 pending 原因。
- 返回 reports 路径，而不是把长报告塞进响应。

#### `book_inspect`

封装 `inspect_epub()`。用于人工查看 EPUB 结构，不触发发布。

输入：

```json
{ "epub_path": "D:\\Books\\book.epub" }
```

输出应包含：

- OPF identifier。
- 章节数量。
- 图片数量。
- 是否缺封面。
- quality issue 摘要。

#### `book_compare`

封装 `compare_for_update()`。用于在发布前解释为什么某个候选会 pending。

输入：

```json
{
  "old_epub": "old.epub",
  "old_manifest": "old.hermes.json",
  "new_epub": "new.epub",
  "new_manifest": "new.hermes.json"
}
```

输出：

```json
{
  "decision": "SAFE_METADATA",
  "reasons": ["existing chapter fingerprints unchanged"],
  "matched_existing_chapters": 12
}
```

### `metadata-enricher`

第二优先级。它不直接写 EPUB，只负责 evidence 和 decision。

#### `metadata_search`

状态：规划。

职责：

- 接收 `MetadataClues`。
- 从书店、出版社、图书数据库或搜索 API 获取候选事实。
- 返回 `MetadataEvidence[]`。

不做：

- 不裁决哪个字段可信。
- 不下载正文内容。
- 不直接修改 EPUB。

#### `metadata_resolve`

状态：规划。

职责：

- 接收 clues 和 evidence。
- 调用大模型或规则引擎。
- 返回结构化 `MetadataResolution`。

必须输出字段级：

- `field`
- `old_value`
- `new_value`
- `action`: `apply`、`report` 或 `block`
- `confidence`
- `evidence_ids`
- `reason`

### `koreader-bridge`

第三优先级。现在只写设计，不实现。

可能工具：

| 工具 | 状态 | 说明 |
|---|---|---|
| `list_books` | 规划 | 从 WebDAV `/books` 和 `.pending` 列书 |
| `get_pending_updates` | 规划 | 展示候选 EPUB、risk report 和 manifest |
| `approve_pending_update` | 暂缓 | 需要强确认，不能自动覆盖 |
| `get_highlights` | 规划 | 从 HighlightSync/WebDAV 导出的标注文件读取 |
| `get_progress` | 暂缓 | KOReader 本地状态格式和同步方式需单独确认 |
| `migrate_docsettings` | 暂缓 | 只有 hashdocsettings live overwrite 需要，风险高 |

## 工具设计原则

1. MCP 工具只编排已有 Python 能力。
2. 任何会覆盖旧书的操作必须暴露 decision 和 reason。
3. 所有候选更新都要保留本地 report。
4. 大模型只产出结构化 decision，不直接写文件。
5. KOReader sidecar 不作为普通 metadata 写入的一部分。

## 与旧设想的差异

旧文档把 Calibre、metadata-enricher、koreader-bridge、模型路由写成了一整套已部署体系。现在的实际路线更小，也更稳：

- 先把 Hermes Python 管线跑可靠。
- 再把稳定函数封装成 MCP。
- 最后接入搜索、LLM 和 KOReader 端状态迁移。

这个顺序能避免 MCP server 成为另一套难以测试的业务逻辑。
