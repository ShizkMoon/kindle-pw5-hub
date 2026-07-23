# 书籍处理管线

Hermes 的管线目标是 EPUB 精制：把本地 TXT/EPUB 做成排版稳定、元数据可追溯、适合 KOReader 阅读的 EPUB，并在覆盖旧书前判断是否会破坏阅读进度和标注关联。

当前入口：

```powershell
python -m scripts.hermes_books.intake "D:\Books\raw.txt" -t "书名" -a "作者" --config config/hermes-books.yaml
python -m scripts.hermes_books.intake "D:\Books\raw.epub" -t "书名" -a "作者" --config config/hermes-books.yaml
```

## 输入

| 输入 | 当前处理 |
|---|---|
| TXT | 构建 draft EPUB，再进入规范化和检查 |
| EPUB | 直接规范化后检查 |
| UMD/JAR | 暂不支持 |
| MOBI/AZW3/PDF/DOCX | 不在 Hermes intake 当前范围；可先用 Calibre 转 EPUB |

TXT 的当前实现偏保守：它能把文本包装为 EPUB，但还不是完整的“网文智能清洗器”。章节级广告删除、段落判断、缺章检测、插图定位会放到后续 LLM 清洗阶段。

## 运行目录

```text
runs/<job-id>/
  raw/             原始输入快照
  draft/           TXT 转出的 EPUB 初稿
  normalized/      规范化后的 EPUB
  assets-cache/    封面等候选资源缓存
  evidence-cache/  本次联网元数据响应的证据副本
  reports/         所有报告
```

跨运行复用的联网响应缓存在 `runs/.online-cache/metadata/`，单次运行仍保留自己的证据副本。

重要报告：

| 文件 | 内容 |
|---|---|
| `quality-report.md` | 章节、图片、封面、质量问题摘要 |
| `typography-report.json` | 排版 profile、确定性修改计数、评分和问题清单 |
| `typography-report.md` | 人可读排版审计报告 |
| `asset-report.json` | 封面/插图候选与采用结果 |
| `asset-report.md` | 候选来源、尺寸、权利说明、卷册和章节提示的人工复核清单 |
| `metadata-report.json` | 元数据 evidence、decision、冲突和 KOReader guard；检查前失败时写 skipped |
| `metadata-report.md` | 人可读元数据报告；检查前失败时写 skipped |
| `cleaning-report.json` | 正文清洗报告和成本规划；默认不调用模型、不改正文 |
| `cleaning-report.md` | 人可读正文清洗报告 |
| `epubcheck.json` | EPUBCheck 结果或跳过原因 |
| `update-diff.md` | 旧书与候选书的差异和发布决策；新书不一定有 |
| `manifest.json` | Hermes manifest，随书发布 |
| `publish-report.json` | 发布状态 |

## 阶段

### 1. 源文件快照

`LocalFileSource` 复制输入文件到 `raw/`，计算 source hash。后续步骤不直接改原始文件。

### 2. EPUB 构建与规范化

TXT 输入先经过 `build_draft_from_txt()` 生成 draft EPUB。EPUB 输入和 draft EPUB 都会通过 `normalize_existing_epub()` 进入统一结构。规范化会尽量保留源 EPUB 的 OPF 版本、主 identifier、章节 href、item id 和 spine，不主动升级为 EPUB3。

### 3. 排版规范化与审计

默认 `typography.mode=normalize`，当前 `koreader-literary` profile 会：

- 把 CSS、`<style>` 和内联 style 中的 px/pt 字号换算为 `em`。
- 把 px/pt 绝对行高换算为相对 `em`。
- 为所有可读文档挂接统一 profile，改善中文缩进、行距、标题、图片、表格、ruby 和代码块表现。
- 保留正文文字、段落节点和留白，不做段落合并或章节改写。

排版审计会检查 profile 是否完整挂接、是否残留固定字号、是否存在嵌入字体和遗留 `<font>`/重复 `<br>`。高风险问题在 `block_on_failure=true` 时阻断发布。`audit-only` 只报告，`off` 跳过。

### 4. EPUB 检查

`inspect_epub()` 提取：

- 书名、作者、OPF identifier。
- 章节列表。
- 图片清单。
- 封面状态。
- CSS 和资源引用。
- 章节正文、结构、资源 fingerprint。

检查结果用于质量报告、manifest 和旧书差异比较。

### 5. 联网元数据与封面增强

当 `metadata_enrichment.mode` 不是 `off` 时，Hermes 会构造 `MetadataClues`。启用 `online_enrichment.enabled` 或 CLI `--online-enrichment` 后，内置 provider 查询 Google Books 与 Open Library；调用方仍可注入其他 provider/reasoner：

- 用户输入的 title/author。
- OPF identifier。
- 已有 metadata。
- 前若干章节标题。
- 是否缺封面。

provider 返回带记录 URL 的 evidence；确定性 reasoner 根据书名/作者匹配、来源一致性和字段风险返回 decision。只有通过配置门禁的字段会写入 OPF。已有值冲突不会自动覆盖，单来源 ISBN 只报告；写入后立刻重新 inspect，并记录 `reader_structure_stable`。

可写字段：

| 字段 | OPF 位置 |
|---|---|
| `title` | `dc:title` |
| `authors` | `dc:creator` |
| `publisher` | `dc:publisher` |
| `description` | `dc:description` |
| `subjects` | `dc:subject` |
| `isbn` | 额外 `dc:identifier` |
| `series`、`volume`、`original_title` | `meta property="hermes:*"` |
| `illustrators`、`translators`、`imprint`、`published_date` | `meta property="hermes:*"` |
| `cover` | 新封面资源 + manifest cover metadata |

配置开关 `write_cover`、`write_description`、`write_subjects` 会真正控制写入。

Google Books 匿名请求遇到配额限制时会记录错误并继续使用 Open Library；可以通过 `GOOGLE_BOOKS_API_KEY` 提供 API key。封面下载只接受内置可信来源的 HTTPS URL，并验证响应体积和图片文件签名。

### 6. 资源增强

元数据 provider 负责当前内置的联网封面补全。`AssetEnricher` 继续承载可注入资源候选；CLI `--asset-candidates <json>` 可导入人工或 Agent 筛选的官方页面候选。插图即使达到高置信也只进入 pending 规划，不自动插入正文。当前没有内置插图搜索 provider，因为卷册、章节、剧透和来源权利仍需人工核对。

### 7. 正文清洗报告

`CleaningPlanner` 会读取检查结果中的章节文字量，写出 `cleaning-report.json` 和 `cleaning-report.md`。默认状态是 `planned`：Hermes 只估算输入字符数、token 数、预算和路由，不调用模型，也不改 EPUB。

如果调用方显式注入 analyzer，它可以返回结构化 findings，例如：

- 疑似站点模板。
- 疑似广告。
- 章节边界异常。
- 缺章/错位线索。
- 段落异常。
- 插图占位标记。

轻小说和网文常见短段落、单行对白和留白节奏，所以段落异常只能报告，不能直接当作需要合并的错误。

### 8. EPUBCheck

如果 `pipeline.require_epubcheck` 为 true，EPUBCheck 未通过会阻断发布。找不到 Java 或 EPUBCheck jar 时，状态为 `skipped`；在严格模式下同样阻断。

### 9. 远端状态读取

发布前读取：

```text
/books/<slug>.epub
/books/<slug>.hermes.json
```

远端任一状态不可判断，就不覆盖旧书。

### 10. 差异判断

`compare_for_update()` 的核心规则：

- canonical id 不一致：阻断。
- 新章节数少于旧章节数：阻断。
- 旧章节前缀的正文、结构、资源、href、item id 有变化：阻断。
- 旧章节完全稳定且新章节更多：`SAFE_APPEND`。
- 旧章节完全稳定且章节数相同：`SAFE_METADATA`。

OPF identifier 不一致会在 intake 层再次阻断。

### 11. KOReader 发布保护

元数据写入改变了 EPUB 文件 hash。对 `book_folder` 和 `docsettings` 来说，只要路径、canonical id、章节结构稳定，旧书覆盖可以接受。对 `hashdocsettings` 来说，旧进度绑定可能依赖内容 hash，因此第一版一律 pending。

### 12. WebDAV 发布

新书直接创建。旧书安全更新需要：

- 旧 EPUB 和 manifest 都可读。
- WebDAV 客户端支持条件写入。
- 准备期间远端未被修改。
- 备份写入成功。
- 覆盖后校验通过。

失败时进入 `.pending/` 或 `pending-local`。

### 13. Pending 人工处理

远端 pending 候选可以通过本地 run report 管理：

```powershell
python -m scripts.hermes_books.pending list --runs-root runs
python -m scripts.hermes_books.pending show --report runs\<job-id>\reports\publish-report.json --config config/hermes-books.yaml
python -m scripts.hermes_books.pending approve --report runs\<job-id>\reports\publish-report.json --config config/hermes-books.yaml --confirm "<candidate_hash>"
python -m scripts.hermes_books.pending reject --report runs\<job-id>\reports\publish-report.json --config config/hermes-books.yaml --confirm "<candidate_hash>"
```

`approve` 会先写 `/books/.backups/<slug>/<timestamp>/`，再把 pending candidate 提升到 `/books/<slug>.epub` 和 `/books/<slug>.hermes.json`。`reject` 只删除 pending 目录中的候选文件。

## 大模型清洗的接入方式

当前已经有 report-only 框架，但没有默认模型调用。后续大模型可以接入，仍要遵守同一条原则：模型做判断，确定性代码做写入。

建议分三层：

1. 报告层：模型判断章节边界、疑似广告、缺章、错位、段落异常，只生成 report。当前 `cleaning-report.*` 就是这一层。
2. 候选层：把可自动修复项输出成结构化 patch，例如删除第 N 行广告、合并某一段落。
3. 写入层：Hermes 应用 patch，重新 inspect，并和旧版本比较。

不要让模型直接输出整章改写文本。轻小说和网文本来就有大量短段落、对话换行和空行节奏，段落合并必须保守。可以让模型判断“这是广告/导航/站点模板”，但是否删除仍由证据、位置和规则共同决定。

## 质量标准

当前管线要求：

- 可被 `ebooklib` 读取。
- 所有可读文档挂接同一 KOReader 排版 profile。
- 字号和行高不再依赖 px/pt 固定单位。
- OPF identifier 稳定。
- spine 章节可枚举。
- XHTML 章节有可计算 fingerprint。
- 图片和 CSS 资源引用可追踪。
- 旧书更新不改变旧章节 reader anchor。
- 所有风险都有报告，不静默覆盖。

面向 KOReader 的 CSS 原则：

- 正文不嵌入大体积 CJK 字体。
- 尽量使用相对单位。
- 不把字号和行高锁死在正文元素上。
- 保留 KOReader 用户端样式微调空间。

这些 CSS 原则目前是处理标准，不是完整自动 CSS 审计实现。真正的 CSS LLM 审计应作为后续独立阶段接入。
