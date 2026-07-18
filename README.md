# Kindle PW5 Hub

Kindle PW5 + KOReader 的个人书务工作流。这个仓库现在的主线不是“Kindle 折腾指南”，而是 Hermes 书籍入库管线：本地 TXT/EPUB 进入统一处理流程，生成面向 KOReader 的 EPUB，检查章节和资源稳定性，再通过 WebDAV 发布到阅读端。

当前实现已经覆盖本地 intake、EPUB 检查、元数据增强、WebDAV 发布、风险更新 pending、pending 人工处理、清洗成本规划报告和 KOReader 进度保护。真实大模型搜索、章节级自动改写、缺章补全、UMD/JAR 支持还没有接入主流程，文档里会把这些明确标为后续方向。

## 在 Agent-native 工作站中的位置

本仓库是阅读数据面和书务规则的事实源。代码中的 `Hermes intake` 是已经存在的本地 Python 管线；云端 Hermes 通过 Tailscale/SSH 唤起本地 Codex/Agent、接收文件和回报状态，是重装后的目标编排方式，当前不能因为名字相同就写成已经接通。

目标分工如下：

- **Windows 数据面** 保存源 TXT/EPUB、逐次运行目录、报告、WebDAV 配置和阅读相关登录态；确定性工具在本机转换、检查、比较和发布。
- **Hermes** 在手机端接收“处理这本书”或查询 pending，电脑离线时只保存任务并标记未执行，恢复在线后重新核对文件 hash 与任务时效。
- **本地 Codex** 读取本仓库、配置与报告，解释失败、维护代码和测试，并决定使用哪条现有管线；它不直接改写书籍正文。
- **本地 Agent 运行层** 执行 intake、EPUBCheck、WebDAV 探测和结果复核；旧书风险仍进入 pending，不因自动托管而放宽门禁。

日常体验应是白天把格式劳动交给系统，晚上阅读时系统静默。`published` 表示管线完成了发布动作，`pending` 表示旧书受到保护；只有重新读取远端结果后才能进一步写成 verified，不能把“已接收”“已排队”或命令退出当成书已到达阅读端。

## 当前能力

Hermes intake 可以做这些事：

- 接收本地 `.txt` 或 `.epub`。
- 为每次运行创建 `runs/<job-id>/` 工作区，保存 raw、draft、normalized 和 reports。
- TXT 自动生成 EPUB 初稿；EPUB 会被规范化并注入 Hermes 样式资源。
- 检查章节、图片、CSS、OPF identifier、封面状态和 reader-facing 指纹。
- 生成 `quality-report.md`、`asset-report.json`、`epubcheck.json`、`manifest.json`、`publish-report.json`。
- 生成 `cleaning-report.json` / `cleaning-report.md`，先做正文清洗成本规划和报告占位，不改正文。
- 通过 provider/reasoner 注入元数据证据和裁决，自动写入 OPF metadata 与封面。
- 发布到 WebDAV `/books`，风险更新进入 `/books/.pending/`，不直接覆盖旧书。
- 通过 `scripts.hermes_books.pending` 查看、批准或拒绝 `.pending/` 候选。
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

成功进入 EPUB 检查后的运行还会有 `metadata-report.json`、`metadata-report.md`、`cleaning-report.json` 和 `cleaning-report.md`。如果源文件在检查前失败，Hermes 也会写出 skipped metadata/cleaning 报告，方便排障。已有远端旧书、远端状态异常或更新被阻断时，会额外生成 `update-diff.md`。

`publish-report.json` 的 `status` 是最直接的结果：

| status | 含义 |
|---|---|
| `published` | 已发布到 WebDAV 目标路径 |
| `pending` | 候选书已放入 `.pending/`，旧书没有被覆盖 |
| `pending-local` | 远端 pending 上传失败，本地 reports 保留原因 |
| `blocked` | 质量门禁阻断发布 |

## 处理 Pending

先列出本地 runs 里记录过的远端 pending 候选：

```powershell
python -m scripts.hermes_books.pending list --runs-root runs
```

查看某次候选：

```powershell
python -m scripts.hermes_books.pending show --report runs\<job-id>\reports\publish-report.json --config config/hermes-books.yaml
```

确认批准或拒绝时必须带 `publish-report.json` 里的 `candidate_hash`：

```powershell
python -m scripts.hermes_books.pending approve --report runs\<job-id>\reports\publish-report.json --config config/hermes-books.yaml --confirm "<candidate_hash>"
python -m scripts.hermes_books.pending reject --report runs\<job-id>\reports\publish-report.json --config config/hermes-books.yaml --confirm "<candidate_hash>"
```

`approve` 会先备份旧 `/books/<slug>.epub` 和 `.hermes.json`，再把候选提升到 live 路径。`reject` 只删除 `.pending/` 下的候选文件。

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
  allow_single_source_fields: true
  block_on_conflicting_identity: true
  write_epub_metadata: true
  write_cover: true

koreader:
  metadata_location: "book_folder"   # book_folder | docsettings | hashdocsettings
  hashdocsettings_policy: "block"

text_cleaning:
  mode: "report-only"     # off | report-only
  max_input_chars: 120000
  max_estimated_cost_cny: 1.0
  enable_model_calls: false
```

建议 KOReader 端优先使用 `book_folder`。如果你已经启用了 `hashdocsettings`，Hermes 第一版会把旧书元数据改写放入 pending，不做 live overwrite。

`pipeline.keep_runs`、`pipeline.output_profile`、`metadata_enrichment.preserve_target_path`、`metadata_enrichment.preserve_canonical_id` 目前是保留配置；它们记录目标策略，不伪装成已经改变行为的开关。

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

真实网络搜索 provider 和 LLM reasoner 还没有默认上线。当前主流程只使用调用方显式注入的 provider/reasoner。

## 正文清洗报告

`text_cleaning` 当前是 report-only 框架。默认不会调用模型，也不会修改正文；它会根据 EPUB 检查得到的章节文字量估算输入规模、预算和模型路由。

成本规划遵循 ai-workstation 思路：

| 路由 | 用途 |
|---|---|
| 规则/EPUB inspect | 免费前置过滤 |
| MiniMax/M3 或轻量模型 | 后续接入时用于广告、模板、章节异常分类 |
| DeepSeek 长上下文 | 人工触发的长篇结构分析 |
| GPT-5.5 级别模型 | 高价值最终复核，需显式批准 |

后续如果接入模型，模型也只应输出结构化 findings/patch 候选；实际删除广告、合并段落或移动章节必须由 Hermes 确定性代码执行并重新检查。

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
python -m unittest tests.hermes_books.test_assets tests.hermes_books.test_build_txt tests.hermes_books.test_cleaning tests.hermes_books.test_diff tests.hermes_books.test_inspect tests.hermes_books.test_intake tests.hermes_books.test_metadata tests.hermes_books.test_models_config tests.hermes_books.test_opf_metadata tests.hermes_books.test_pending tests.hermes_books.test_publish tests.hermes_books.test_sources
python -m compileall scripts\hermes_books tests\hermes_books
python -m scripts.hermes_books.intake --help
python -m scripts.hermes_books.pending --help
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
