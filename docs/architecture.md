# 系统架构

本文记录当前 Kindle PW5 Hub 的实际架构。主线是 Hermes book intake：本地书籍文件进入统一处理管线，生成适合 KOReader 的 EPUB，通过 WebDAV 发布，并尽量保护旧书的阅读进度、书签和标注关联。

## 边界

当前实现聚焦三件事：

- 书籍文件处理：TXT/EPUB 输入、EPUB 规范化、质量检查、报告生成。
- 元数据增强：provider/reasoner 给出证据和字段决策，Hermes 写入 OPF。
- 远端发布：WebDAV 条件写入、旧书比较、pending fallback、KOReader 保护。

不在当前实现内：

- 自动从站点抓取 UMD/JAR。
- 自动修正文正文、补缺章、改章节标题。
- 修改 Kindle 本地 `.sdr`、`docsettings` 或 hashdocsettings。
- 完整 MCP server 封装。
- Calibre 作为发布母库。

Calibre、MCP 和大模型搜索仍是重要方向，但现在的可靠执行入口是 `python -m scripts.hermes_books.intake`。

## 模块

```text
scripts/hermes_books/
  models.py          BookJob、BookManifest、UpdateDecision
  config.py          HermesConfig 与 YAML 配置解析
  sources.py         本地源文件快照与 runs 工作区
  build.py           TXT 草稿 EPUB 构建、EPUB 规范化
  inspect.py         EPUB 结构、章节、图片、CSS 和指纹检查
  diff.py            旧书与候选书的 append-safe / metadata-safe 比较
  assets.py          封面候选规划与自动采用
  metadata.py        MetadataProvider / MetadataReasoner / MetadataReport
  opf_metadata.py    OPF metadata 与封面写入
  publish.py         WebDAV 客户端、条件发布、备份、pending
  intake.py          主编排与 CLI
```

配置入口：

```text
config/hermes-books.example.yaml
```

测试覆盖：

```text
tests/hermes_books/
```

## 数据流

```text
local txt/epub
  -> LocalFileSource snapshot
  -> draft EPUB if TXT
  -> normalized EPUB
  -> inspect_epub
  -> metadata enrichment
  -> optional asset enrichment
  -> quality report + epubcheck
  -> existing remote probe
  -> append/metadata diff
  -> KOReader publish guard
  -> WebDAV publish or pending
```

每次运行都有自己的目录：

```text
runs/<job-id>/
  raw/
  draft/
  normalized/
  assets-cache/
  reports/
```

`reports/` 是审计边界。即使远端不可用或发布失败，本地也会保留失败原因。

## 配置模型

`HermesConfig` 分为六组：

| 组 | 作用 |
|---|---|
| `webdav` | 远端基础 URL、书籍路径、凭据环境变量 |
| `pipeline` | EPUBCheck 是否为硬门禁、输出 profile、语言 |
| `update_policy` | 章节 fingerprint 阈值、章节减少/重排阻断 |
| `asset_enrichment` | 封面和插图候选采用策略 |
| `metadata_enrichment` | 元数据增强模式、阈值、写入开关 |
| `koreader` | KOReader metadata location 和 hashdocsettings 策略 |

配置解析目前是简单 YAML 子集解析，适合这个项目的固定配置文件，不是通用 YAML 解析器。

## 检查与指纹

Hermes 不只比较正文文本。对旧书更新来说，KOReader 进度和标注常常依赖 reader-facing anchor，所以比较范围更宽：

- 章节数量。
- spine 顺序。
- 章节 href。
- item id。
- 章节可见文本 fingerprint。
- XHTML 结构 fingerprint。
- 图片、CSS、`url()`、`@import` 等资源 fingerprint。
- OPF identifier。

这些信息写入 manifest 和 quality report。旧书有任何前缀章节漂移，`diff.py` 会返回 `BLOCKED_RISKY`。

## 元数据增强

元数据增强被拆成三个层次：

1. `MetadataProvider` 搜索证据。证据包含来源、URL、字段事实和置信度。
2. `MetadataReasoner` 融合证据。它返回字段级 `MetadataDecision`，每个 decision 包含旧值、新值、action、confidence、evidence ids 和 reason。
3. `MetadataEnricher` 应用配置门禁。低置信、缺 URL、`report-only`、`off`、冲突身份都会被阻断或只报告。

OPF 写入在 `opf_metadata.py` 中完成。它保留主 identifier，只追加或替换书籍级 metadata。封面写入会保留旧封面资源，使用唯一的新路径，并同步 EPUB3 `cover-image` 与 EPUB2 cover meta。

## WebDAV 发布

发布器只做两类直接写入：

- 新书：目标 EPUB 和 manifest 都不存在，使用 `If-None-Match` 语义创建。
- 旧书安全更新：旧 EPUB 和 manifest 都可读，更新决策为 `SAFE_APPEND` 或 `SAFE_METADATA`，并且客户端支持现有目标条件覆盖。

旧书覆盖前会写备份：

```text
/books/.backups/<slug>/<timestamp>/
  old.epub
  old.hermes.json
```

风险更新进入：

```text
/books/.pending/<slug>/<timestamp-hash>/
  candidate.epub
  candidate.hermes.json
  risk-report.md
```

这样 KOReader 本地已经下载的旧书不会被无声替换。

## KOReader 保护

`koreader.metadata_location` 是发布策略的重要输入：

| 模式 | 策略 |
|---|---|
| `book_folder` | 文件名、路径、canonical id 和章节结构稳定时允许 metadata-safe 覆盖 |
| `docsettings` | 与 `book_folder` 类似，但要求设备端实际路径也保持稳定 |
| `hashdocsettings` | 第一版阻断旧书 live overwrite，因为 EPUB 内容 hash 会改变 |

Hermes 现在不迁移 KOReader sidecar。未来如果要支持 `hashdocsettings` live overwrite，需要读取旧 hash 的 docsettings，再按 KOReader 的规则迁移到新 hash。

## 故障模式

| 故障 | 行为 |
|---|---|
| 源 EPUB 解析失败 | 生成 blocked 报告，不发布 |
| EPUBCheck 失败且 `require_epubcheck=true` | 阻断发布 |
| 远端状态不可读 | 本地报告 + pending |
| 旧 manifest 缺失或不可读 | pending |
| 旧 EPUB 不可读 | pending |
| OPF identifier 不一致 | pending |
| 条件写入失败 | pending 或 pending-local |
| metadata rewrite 改变章节结构 | pending |
| hashdocsettings 旧书 metadata rewrite | pending |

## 后续架构方向

下一步应该保持同样的边界感：

- 搜索 provider：Amazon、BookWalker、出版社页面、OpenLibrary、Google Books 等只返回 evidence。
- LLM reasoner：只输出结构化 JSON decision，不直接写文件。
- 正文清洗：先做报告和 diff，不直接自动改正文。
- KOReader sidecar migration：单独实现、单独测试，不能混进 OPF 元数据写入。
- MCP 封装：把稳定 Python API 暴露出去，而不是重写一套并行逻辑。
