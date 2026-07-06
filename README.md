# Kindle PW5 Hub

Kindle PW5 + KOReader 的个人书务工作流。这个仓库现在的主线不是“Kindle 折腾指南”，而是 Hermes 书籍入库管线：本地 TXT/EPUB 进入统一处理流程，生成面向 KOReader 的 EPUB，检查章节和资源稳定性，再通过 WebDAV 发布到阅读端。

当前实现已经覆盖本地 intake、EPUB 检查、元数据增强、WebDAV 发布、风险更新 pending 和 KOReader 进度保护。大模型搜索、章节级清洗、缺章补全、UMD/JAR 支持还没有接入主流程，文档里会把这些明确标为后续方向。

## 当前能力

Hermes intake 可以做这些事：

- 接收本地 `.txt` 或 `.epub`。
- 为每次运行创建 `runs/<job-id>/` 工作区，保存 raw、draft、normalized 和 reports。
- TXT 自动生成 EPUB 初稿；EPUB 会被规范化并注入 Hermes 样式资源。
- 检查章节、图片、CSS、OPF identifier、封面状态和 reader-facing 指纹。
- 生成 `quality-report.md`、`asset-report.json`、`epubcheck.json`、`manifest.json`、`publish-report.json`。
- 通过 provider/reasoner 注入元数据证据和裁决，自动写入 OPF metadata 与封面。
- 发布到 WebDAV `/books`，风险更新进入 `/books/.pending/`，不直接覆盖旧书。
- 在 KOReader `hashdocsettings` 模式下阻断旧书 live overwrite，避免 EPUB 内容 hash 改变后丢失进度关联。

目前不做：

- 不抓取 UMD/JAR。
- 不自动补全文本正文或缺章。
- 不让大模型直接改写正文。
- 不迁移 KOReader 本地 `.sdr` 或 hashdocsettings sidecar。
- 不依赖 Send to Kindle、Whispersync 或亚马逊云。

## 快速开始

复制示例配置：

```powershell
Copy-Item config\hermes-books.example.yaml config\hermes-books.yaml
```

设置 WebDAV 凭据：

```powershell
$env:WEBDAV_USERNAME = "koreader"
$env:WEBDAV_PASSWORD = "your-password"
```

运行本地 TXT/EPUB intake：

```powershell
python -m scripts.hermes_books.intake "D:\Books\raw.txt" -t "书名" -a "作者" --config config/hermes-books.yaml
python -m scripts.hermes_books.intake "D:\Books\raw.epub" -t "书名" -a "作者" --config config/hermes-books.yaml
```

正常跑到检查阶段后，重点看这些文件：

```text
runs/<job-id>/reports/quality-report.md
runs/<job-id>/reports/publish-report.json
runs/<job-id>/reports/manifest.json
```

如果启用了元数据增强并且流程进入 metadata 阶段，还会有 `metadata-report.json` 和 `metadata-report.md`。已有远端旧书、远端状态异常或更新被阻断时，会额外生成 `update-diff.md`。

`publish-report.json` 的 `status` 是最直接的结果：

| status | 含义 |
|---|---|
| `published` | 已发布到 WebDAV 目标路径 |
| `pending` | 候选书已放入 `.pending/`，旧书没有被覆盖 |
| `pending-local` | 远端 pending 上传失败，本地 reports 保留原因 |
| `blocked` | 质量门禁阻断发布 |

## 配置重点

示例配置在 [config/hermes-books.example.yaml](config/hermes-books.example.yaml)。

```yaml
webdav:
  base_url: "https://example.com/webdav"
  books_path: "/books"
  username_env: "WEBDAV_USERNAME"
  password_env: "WEBDAV_PASSWORD"

pipeline:
  require_epubcheck: true
  output_profile: "koreader"
  language: "zh"

metadata_enrichment:
  mode: "aggressive"      # off | report-only | aggressive
  require_evidence_url: true
  write_epub_metadata: true
  write_cover: true

koreader:
  metadata_location: "book_folder"   # book_folder | docsettings | hashdocsettings
  hashdocsettings_policy: "block"
```

建议 KOReader 端优先使用 `book_folder`。如果你已经启用了 `hashdocsettings`，Hermes 第一版会把旧书元数据改写放入 pending，不做 live overwrite。

## 元数据增强

元数据增强由两个可注入接口组成：

- `MetadataProvider.search(clues)`：返回带 URL、来源、字段事实和置信度的 evidence。
- `MetadataReasoner.resolve(clues, evidence)`：融合 evidence，输出字段级 `MetadataDecision`。

只有满足配置阈值、证据完整且 action 为 `apply` 的字段会写入 EPUB。写入范围包括：

- `dc:title`
- `dc:creator`
- `dc:publisher`
- `dc:description`
- `dc:subject`
- 额外 ISBN identifier
- `hermes:series`
- `hermes:volume`
- `hermes:original_title`
- `hermes:illustrators`
- `hermes:translators`
- `hermes:imprint`
- `hermes:published_date`
- 封面资源和 OPF cover metadata

Hermes 会保留 OPF 主 identifier、WebDAV 文件名和 `canonical_id`。写入后会重新 inspect EPUB；如果章节 href、item id、正文 fingerprint、结构 fingerprint 或资源 fingerprint 漂移，旧书发布会被阻断。

## 发布策略

Hermes 把远端 `/books/书名 - 作者.epub` 当作阅读母本。发布前会读取旧 EPUB 和旧 `.hermes.json` manifest，比较章节和 reader-facing 结构。

| 决策 | 处理 |
|---|---|
| `NEW_BOOK` | 远端不存在时发布新书 |
| `SAFE_APPEND` | 旧章节稳定，只追加新章节时允许覆盖 |
| `SAFE_METADATA` | 章节和资源稳定，只有元数据变化时允许覆盖 |
| `BLOCKED_RISKY` | 写入 `.pending/`，旧书保持原样 |
| `REVIEW_MINOR` | 预留人工确认路径，发布器按 pending 处理 |

旧书覆盖依赖 WebDAV 条件写入和备份。远端状态读不到、manifest 缺失、OPF identifier 不一致、旧 EPUB 解析失败、并发修改、KOReader hashdocsettings 风险都会进入 pending。

## 文档地图

| 文档 | 作用 |
|---|---|
| [系统架构](docs/architecture.md) | 当前 Hermes 书务系统的模块、数据流和安全边界 |
| [处理管线](docs/pipeline.md) | TXT/EPUB 输入、检查、元数据增强、发布和后续 LLM 清洗方向 |
| [MCP 规格](docs/mcp-specs.md) | 把当前 Python 能力封装成工具接口的规划 |
| [Kindle/KOReader 配置](docs/kindle-setup.md) | 阅读端配置、WebDAV、metadata location 与进度保护 |
| [阅读节律](docs/daily-reading-rhythm.md) | 这套系统在日常阅读中的使用方式 |
| [设备选择](docs/buying-guide.md) | KPW5、KPW6、Kobo 与 Apple 设备的阅读工作流差异 |
| [Apple 兼容性](docs/apple-compatibility.md) | iPhone/iPad/Mac 接入现有 EPUB/WebDAV/标注流的方式 |
| [归档文档](archived/) | 旧方案备忘，保留参考，不作为当前手册 |

## 开发验证

常用验证命令：

```powershell
python -m unittest tests.hermes_books.test_assets tests.hermes_books.test_build_txt tests.hermes_books.test_diff tests.hermes_books.test_inspect tests.hermes_books.test_intake tests.hermes_books.test_metadata tests.hermes_books.test_models_config tests.hermes_books.test_opf_metadata tests.hermes_books.test_publish tests.hermes_books.test_sources
python -m compileall scripts\hermes_books tests\hermes_books
python -m scripts.hermes_books.intake --help
git diff --check HEAD
```

## 关联项目

| 仓库 | 说明 |
|---|---|
| [dorm-workstation](https://github.com/ShizkMoon/dorm-workstation) | 物理工位、设备布局和宿舍环境 |
| [ai-workstation](https://github.com/ShizkMoon/ai-workstation) | AI 网关、模型路由、云端工具链和日常自动化 |

## 参考

- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [EPUBCheck](https://github.com/w3c/epubcheck)
- [ebooklib](https://github.com/aerkalov/ebooklib)
- [Calibre Manual](https://manual.calibre-ebook.com/)
- [OpenCC](https://github.com/BYVoid/OpenCC)
- [WinterBreak](https://kindlemodding.org/)
