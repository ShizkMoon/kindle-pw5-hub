# 系统架构

本文记录当前 Kindle PW5 Hub 的实际架构。主线是 Hermes EPUB 精制：本地书籍文件先经过确定性排版优化与联网证据补全，生成适合 KOReader 的 EPUB，再通过 WebDAV 发布，并尽量保护旧书的阅读进度、书签和标注关联。

## 与 AI 工作站的分层

这里的 `scripts/hermes_books` 是本仓库已经实现的本地书务代码，不等于云端 Hermes 已经能够远程托管 Windows。重装后的目标链路是：

```text
手机请求 / 文件
  -> 云端 Hermes：判断时效、电脑在线状态与队列
  -> Tailscale + SSH：只传任务和状态
  -> 本地 Codex：读取仓库、配置、旧书状态与报告
  -> 本地 Agent 运行层：调用 scripts/hermes_books 和确定性检查
  -> Windows 本地文件 / WebDAV
  -> KOReader 阅读端
  -> 结果按 received / queued / published / pending / blocked / verified 回报
```

Windows 承担数据面，因为源文件、运行报告、WebDAV 凭据和阅读端上下文都在本地；Hermes 只承担编排和简短状态；Codex 承担理解、维护与故障解释。SSH 不是权限来源，自动托管也不改变旧书覆盖、正文修改和标注保护规则。

当前可验证的是下面的 Python 管线与测试。Hermes → SSH → 本地 Codex 的远程链路、每日标注回流和真实模型 provider 仍是 planned，部署后必须分别验收。

## 边界

当前实现聚焦三件事：

- 书籍文件处理：TXT/EPUB 输入、EPUB 结构规范化、KOReader 排版 profile、排版审计和质量报告。
- 元数据增强：Google Books/Open Library provider 给出带 URL 的证据，确定性 reasoner 裁决后写入 OPF 和封面。
- 正文清洗规划：report-only 成本估算和 findings 框架，不修改正文。
- 远端发布：WebDAV 条件写入、旧书比较、pending fallback、pending 人工处理、KOReader 保护。

不在当前实现内：

- 自动从站点抓取 UMD/JAR。
- 自动修正文正文、补缺章、改章节标题。
- 从零售站或任意网页抓取元数据、封面和正文插图。
- 使用大模型直接裁决或改写 EPUB。
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
  typography.py      KOReader 文学排版 profile、相对单位改写与排版审计
  inspect.py         EPUB 结构、章节、图片、CSS 和指纹检查
  diff.py            旧书与候选书的 append-safe / metadata-safe 比较
  assets.py          封面采用、人工候选 manifest 与插图 pending 复核
  metadata.py        MetadataProvider / MetadataReasoner / MetadataReport
  online_metadata.py Google Books/Open Library provider、确定性共识、缓存与封面下载
  opf_metadata.py    OPF metadata 与封面写入
  cleaning.py        正文清洗 report-only 规划与成本估算
  publish.py         WebDAV 客户端、条件发布、备份、pending
  pending.py         从 publish-report 管理远端 pending 候选
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
  -> typography normalization + audit
  -> inspect_epub
  -> online evidence + deterministic metadata enrichment
  -> optional asset enrichment
  -> text cleaning report
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
  evidence-cache/
  reports/
```

`reports/` 是审计边界。即使远端不可用或发布失败，本地也会保留失败原因。

共享联网响应位于 `runs/.online-cache/metadata/`；每次运行会把实际使用的原始响应复制到自己的 `evidence-cache/`，避免报告只剩不可复核的结论。

## 配置模型

`HermesConfig` 分为九组：

| 组 | 作用 |
|---|---|
| `webdav` | 远端基础 URL、书籍路径、凭据环境变量 |
| `pipeline` | EPUBCheck 是否为硬门禁、输出 profile、语言 |
| `typography` | 排版模式、KOReader profile、相对单位改写和失败门禁 |
| `update_policy` | 章节 fingerprint 阈值、章节减少/重排阻断 |
| `asset_enrichment` | 封面和插图候选采用策略 |
| `metadata_enrichment` | 元数据增强模式、阈值、写入开关 |
| `online_enrichment` | Google Books/Open Library、超时、缓存、匹配阈值和下载上限 |
| `koreader` | KOReader metadata location 和 hashdocsettings 策略 |
| `text_cleaning` | 正文清洗报告、模型调用禁用开关、预算和路由 |

配置解析目前是简单 YAML 子集解析，适合这个项目的固定配置文件，不是通用 YAML 解析器。

当前已经生效的保守配置包括：`pipeline.language`、`metadata_enrichment.allow_single_source_fields`、`metadata_enrichment.block_on_conflicting_identity` 和 `koreader.hashdocsettings_policy`。`keep_runs`、`output_profile`、`preserve_target_path`、`preserve_canonical_id` 仍是保留项。

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

## 排版精制

`typography.py` 提供 `koreader-literary` profile，并把 CSS、`<style>` 和内联 style 中的 px/pt 字号与行高换算为 `em`。它不会改正文文字、合并段落或重命名章节资源。

排版报告区分实际修改和遗留问题。profile 缺失、正文仍有固定字号等 HIGH 问题可以直接阻断发布；嵌入字体、旧 `<font>` 和重复换行保留为审计提示。这样“EPUBCheck 合法”和“实际排版可用”成为两个独立门禁。

## 元数据增强

元数据增强被拆成三个层次：

1. `MetadataProvider` 搜索证据。证据包含来源、URL、字段事实和置信度。
2. `MetadataReasoner` 融合证据。它返回字段级 `MetadataDecision`，每个 decision 包含旧值、新值、action、confidence、evidence ids 和 reason。
3. `MetadataEnricher` 应用配置门禁。低置信、缺 URL、`report-only`、`off`、冲突身份都会被阻断或只报告。

OPF 写入在 `opf_metadata.py` 中完成。它保留主 identifier，只追加或替换书籍级 metadata。封面写入会保留旧封面资源，使用唯一的新路径，并同步 EPUB3 `cover-image` 与 EPUB2 cover meta。

`online_metadata.py` 已实现 Google Books 与 Open Library 查询。响应按 URL hash 缓存；每条 `MetadataEvidence` 保留来源、记录 URL、字段事实和置信度。`DeterministicMetadataReasoner` 优先补空字段，保留已有冲突值，并要求 ISBN 至少得到两个来源的一致支持才自动写入。

封面只从内置来源的 HTTPS 地址下载，限制响应体积并检查 JPEG/PNG/GIF/WebP 文件签名。任一来源失败只记录到 metadata report，不会让另一来源的有效证据失效。LLM reasoner、零售站 provider 和插图自动定位仍未实现。

`CuratedAssetManifestProvider` 是插图联网搜索与 EPUB 写入之间的人工边界。它接收带 `source_url`、记录页、权利说明、卷册和章节提示的 JSON 候选；`AssetEnricher` 对 illustration 一律输出 pending，不下载或改写章节。

## 正文清洗报告

`cleaning.py` 是 report-only 层。它根据检查结果估算文本规模、token 数和 ai-workstation 风格的模型路由预算。默认 `enable_model_calls=false`，没有 analyzer 时状态为 `planned`。

后续 analyzer 可以返回 `advertisement`、`site_boilerplate`、`chapter_boundary`、`missing_chapter`、`paragraph_anomaly`、`illustration_marker` 等 findings。Hermes 不让 analyzer 直接改 EPUB。

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

`pending.py` 提供人工处理入口。它从本地 `runs/*/reports/publish-report.json` 读取 pending path 和 candidate hash，批准时先写备份，再把 `candidate.epub` 和 `candidate.hermes.json` 提升到 live 路径；拒绝时删除 pending 候选文件。

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
| 检查前失败 | 写 skipped metadata/cleaning 报告 |
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

- 搜索 provider：在现有 Google Books/Open Library 之上增加出版社、BookWalker 等高质量来源，但继续只返回 evidence。
- LLM reasoner：只输出结构化 JSON decision，不直接写文件。
- 正文清洗：先做报告和 diff，不直接自动改正文。
- KOReader sidecar migration：单独实现、单独测试，不能混进 OPF 元数据写入。
- MCP 封装：把稳定 Python API 暴露出去，而不是重写一套并行逻辑。
