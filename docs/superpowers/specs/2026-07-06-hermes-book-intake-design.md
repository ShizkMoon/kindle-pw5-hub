# Hermes Book Intake MVP 设计规格

日期：2026-07-06

状态：已由用户确认设计边界，等待实现计划。

## 背景

Hermes 的长期目标是接收自然语言指令，例如“拉取某本书”，自动完成书源发现、原始文件获取、质量检查、资源补全、EPUB3 精排、WebDAV 发布，并让 KOReader 端更新旧书时尽量保留阅读进度、书签、标注和笔记。

第一版不直接实现全网搜索式的最终形态，而是先实现本地文件入口：给 Hermes 一个本地 TXT 或 EPUB，它能生成高质量 EPUB3，更新 WebDAV 远程母本，并在已有旧书时只允许低风险更新自动覆盖。

## MVP 范围

### 包含

- 输入本地 TXT 文件。
- 输入本地 EPUB 文件。
- TXT 先生成 draft EPUB3，再进入统一 EPUB 检查与标准化流程。
- EPUB 统一进行结构检查、CSS 审计、封面和插图资源检查、元数据检查、EPUBCheck 校验。
- 缺封面和缺插图时执行网络资源补全。
- 将合格 EPUB3 发布到 WebDAV `/books/`。
- 已有同书远程母本时，执行 append-safe 更新判定。
- 低风险更新自动覆盖远程母本，高风险更新进入 `.pending/`，不覆盖旧版。
- 每次处理生成 manifest、质量报告、资产报告、diff 报告和发布报告。

### 不包含

- UMD/JAR 解包。
- 通过书名和作者全网自动搜索书源。
- Kindle 端自动下载并替换本地文件。
- 破解、绕过或规避站点访问限制。
- 高风险情况下自动重写 KOReader 标注锚点。

## 关键约束

KOReader 端必须使用同目录 `.sdr` 作为书籍元数据位置。目标本地形态为：

```text
documents/books/书名 - 作者.epub
documents/books/书名 - 作者.sdr/
```

Hermes 第一版只更新 WebDAV 远程母本：

```text
/webdav/books/书名 - 作者.epub
```

Kindle 本地覆盖动作第一版由 KOReader Cloud Storage 触发。Hermes 不直接修改 Kindle 本地 `.sdr` 目录，但必须通过稳定文件名、稳定书籍标识、稳定 EPUB 内部结构来降低 KOReader 进度和标注漂移风险。

## 架构

第一版拆成 7 个模块：

```text
hermes_books/
  intake.py       任务入口：接收本地路径、书名、作者、目标路径
  sources.py      SourceProvider 抽象；MVP 只有 LocalFileSource
  inspect.py      格式、编码、元数据、章节、图片、质量问题检查
  build.py        TXT -> draft EPUB3；EPUB -> normalized EPUB3
  assets.py       封面和彩页/插图资源补全
  diff.py         新旧 EPUB append-safe 比较
  publish.py      WebDAV 上传、备份、manifest 写入
```

模块关系：

```text
LocalFileSource
  -> BookInspector
  -> DraftBuilder / EpubNormalizer
  -> AssetEnricher
  -> QualityGate
  -> AppendSafeDiff
  -> WebDavPublisher
  -> HermesManifest
```

## 数据对象

### BookJob

```json
{
  "id": "job uuid",
  "input_path": "D:/Books/input.txt",
  "input_format": "txt",
  "title": "书名",
  "author": "作者",
  "target_slug": "书名 - 作者",
  "webdav_target_path": "/books/书名 - 作者.epub",
  "asset_mode": "balanced"
}
```

### BookManifest

```json
{
  "schema_version": 1,
  "canonical_id": "normalized-title::normalized-author",
  "title": "书名",
  "author": "作者",
  "opf_identifier": "urn:hermes:...",
  "source_hash": "sha256...",
  "output_hash": "sha256...",
  "chapter_map": [],
  "image_inventory": [],
  "quality_report": {},
  "asset_report": {},
  "update_decision": "SAFE_APPEND",
  "previous_versions": []
}
```

`canonical_id` 第一版由规范化后的书名和作者生成，不使用文件 hash。后续书源搜索能力接入后，可以升级为站点 ID、ISBN、文库 ID 或其他更强标识。

## 处理流程

### TXT 输入

```text
读取原始文件并保存 raw 快照
  -> 编码检测并转为 UTF-8
  -> 垃圾行和站点噪声清理
  -> 章节识别
  -> 硬换行合并和段落规范化
  -> 生成 draft EPUB3
  -> 进入 EPUB 统一流程
```

### EPUB 统一流程

```text
解包 EPUB
  -> 读取 OPF、nav、NCX、spine、manifest
  -> 检查目录、章节、CSS、图片、封面、元数据
  -> 修复可自动修复的结构问题
  -> 执行封面和插图资源补全
  -> 输出 normalized EPUB3
  -> 运行 EPUBCheck
  -> 通过后进入更新判定和发布
```

TXT 和原始 EPUB 最终都必须经过同一套 EPUB 统一流程，确保成品标准一致。

## 资产补全

资产补全由 `assets.py` 执行。

### 检查项

- 是否缺封面。
- 封面分辨率、比例、清晰度是否过低。
- 是否存在断裂图片引用。
- 是否存在明显缺失的彩页、插图或卷首图。
- 图片是否被重复嵌入。

### 搜索与候选

Hermes 使用书名、作者、卷名、原始文件名、正文标题页和已有元数据生成检索词。候选资源必须记录：

- 来源 URL。
- 检索词。
- 下载时间。
- 图片尺寸。
- 图片 hash。
- 置信度。
- 自动采用或进入待确认的原因。

### 策略

默认使用 `balanced` 模式：

```yaml
asset_enrichment:
  mode: balanced
  auto_cover_min_confidence: 0.85
  auto_insert_illustration_min_confidence: 0.92
  require_source_url: true
  preserve_original_images: true
```

行为：

- 封面高置信度时自动补入。
- 插图只有在能匹配卷、章、文件名、原 EPUB 图片缺口或正文明确位置线索时自动插入。
- 无明确位置线索的插图只写入候选报告，不破坏正文。
- `aggressive` 模式作为实验选项，允许更积极地补彩页和插图，但必须生成回滚包和详细报告。

## Append-Safe 更新判定

Hermes 只有在更新被判定为安全时，才覆盖 WebDAV 远程母本。

### 自动覆盖条件

- `canonical_id` 相同。
- 新 EPUB 继承旧 EPUB 的 OPF identifier。
- 旧 TOC 是新 TOC 的前缀或近似前缀。
- 旧章节数量没有减少。
- 旧章节正文规范化 fingerprint 匹配率不低于 98%。
- 前若干章边界没有整体漂移。
- 旧章节 XHTML 文件名和章节 ID 尽量延续。

### 允许变化

- 追加新章节。
- 添加封面、彩页或插图。
- 改进 CSS。
- 补全元数据。
- 重建 NAV/NCX。
- 目录文字轻微修正，例如空格、全半角、标点。

### 阻断覆盖

- 章节数量减少。
- 旧章节正文 hash 大面积变化。
- 旧章节顺序变化。
- 旧章节边界重新切分。
- `canonical_id` 不一致。
- 旧 EPUB 没有可解析目录，且无法建立章节映射。

### 决策类型

```text
SAFE_APPEND     自动覆盖；主要是追加新章
SAFE_METADATA   自动覆盖；只涉及元数据、CSS、封面等非正文变化
REVIEW_MINOR    上传 pending，等待用户确认
BLOCKED_RISKY   不覆盖，只生成报告
```

## WebDAV 目录规范

```text
/webdav/books/
  书名 - 作者.epub
  书名 - 作者.hermes.json

/webdav/books/.backups/
  书名 - 作者/
    2026-07-06T103000/
      old.epub
      old.hermes.json
      diff-report.json

/webdav/books/.pending/
  书名 - 作者/
    candidate.epub
    candidate.hermes.json
    risk-report.md

/webdav/assets-cache/
  covers/
  illustrations/
  source-pages/
```

发布规则：

- 新书直接上传到 `/books/`。
- 已有旧书时，先下载旧 EPUB 和旧 manifest。
- append-safe 通过后，先写备份，再覆盖 `/books/书名 - 作者.epub` 和 manifest。
- append-safe 未通过时，只上传到 `.pending/`。
- 任何发布失败都不能删除本地产物或旧远程母本。

## 任务产物

每次处理在本地生成：

```text
runs/<job-id>/
  raw/
  draft/
  normalized/
  reports/
    quality-report.md
    epubcheck.json
    asset-report.md
    update-diff.md
    publish-report.json
```

报告必须包含一句明确的人话结论，例如：

```text
《某书》已生成 EPUB3，但未覆盖旧版。
原因：第 42 章之后章节边界整体漂移，可能导致 KOReader 标注定位错乱。
新版已放入 /books/.pending/某书/，旧版未动。
```

## 错误处理

```text
FETCH_ASSET_FAILED
  图片搜索失败，不阻塞 EPUB 生成；报告里标记缺失资源。

EPUBCHECK_FAILED
  阻塞发布；保留 normalized EPUB 和错误报告。

APPEND_DIFF_RISKY
  阻塞覆盖；上传到 .pending，不动 WebDAV 母本。

WEBDAV_UPLOAD_FAILED
  不删除本地产物；下次可 resume。

METADATA_LOW_CONFIDENCE
  不阻塞；低置信字段写入 pending review。
```

## 配置

第一版配置可放在 `config/hermes-books.yaml`：

```yaml
webdav:
  base_url: "https://example.com/webdav"
  books_path: "/books"
  username_env: "WEBDAV_USERNAME"
  password_env: "WEBDAV_PASSWORD"

pipeline:
  require_epubcheck: true
  keep_runs: true
  output_profile: "koreader"
  language: "zh"

update_policy:
  default: "append-safe"
  chapter_fingerprint_threshold: 0.98
  block_on_chapter_count_decrease: true
  block_on_reordered_existing_chapters: true

asset_enrichment:
  mode: "balanced"
  auto_cover_min_confidence: 0.85
  auto_insert_illustration_min_confidence: 0.92
  require_source_url: true
  preserve_original_images: true
```

## 测试策略

### TXT

- GBK、GB18030、UTF-8 编码输入。
- 标准“第 X 章”。
- 序章、终章、番外。
- 硬换行合并。
- 广告行清理。

### EPUB

- 缺 `nav.xhtml`。
- 缺封面。
- CSS 使用 `px` 或 `pt`。
- `spine` 和 `nav` 不一致。
- 图片引用断裂。

### 更新

- 只追加新章，期望 `SAFE_APPEND`。
- 只换封面或 CSS，期望 `SAFE_METADATA`。
- 章节减少，期望 `BLOCKED_RISKY`。
- 中间章节重排，期望 `BLOCKED_RISKY`。
- 标题轻微变化，期望 `REVIEW_MINOR` 或 `SAFE_APPEND`。

## 验收标准

- 本地 TXT 能生成 EPUB3，并重新进入 EPUB normalize 流程。
- 本地 EPUB 能被检查、修复、补封面或图片候选、重新打包。
- EPUBCheck 失败时绝不发布。
- 已有旧书时，只有 append-safe 才覆盖 WebDAV 母本。
- 风险更新进入 `.pending/`，不影响旧书。
- 每次发布都有 manifest、备份和报告。
- WebDAV 旧母本更新后，KOReader 本地同目录 `.sdr` 的保留策略不被破坏。

## 演进到最终 C

第一版的 `SourceProvider` 只实现 `LocalFileSource`。后续扩展：

```text
URLProvider
  接收书籍页面 URL，下载原始 TXT/EPUB。

SiteAdapter
  针对特定站点解析目录、下载入口和更新状态。

SearchProvider
  接收书名/作者，搜索候选书源并排序。

AssetProvider
  面向封面、彩页、插图的多源搜索和缓存。

KindleUpdater
  Kindle 端轻量更新器，检查 WebDAV manifest 并下载新版 EPUB 到本地同路径。
```

最终目标是：

```text
书名/作者
  -> 搜索来源
  -> 获取原始 TXT/EPUB
  -> 检查缺章/错位/缺图
  -> 补资源
  -> 生成 EPUB3
  -> append-safe 更新 WebDAV 母本
  -> Kindle 端自动拉取
  -> 保留 KOReader 阅读状态
```

## 参考

- KOReader User Guide: https://koreader.rocks/user_guide/
- KOReader docsettings module: https://koreader.rocks/doc/modules/docsettings.html
- KOReader `docsettings.lua`: https://raw.githubusercontent.com/koreader/koreader/master/frontend/docsettings.lua
- KOReader `readerhighlight.lua`: https://raw.githubusercontent.com/koreader/koreader/master/frontend/apps/reader/modules/readerhighlight.lua
- 本仓库架构文档：`docs/architecture.md`
- 本仓库 EPUB 处理流水线：`docs/pipeline.md`
- 本仓库 MCP 工具规范：`docs/mcp-specs.md`
