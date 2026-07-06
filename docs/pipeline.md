# 书籍处理管线

Hermes 的管线目标很窄：把本地 TXT/EPUB 变成可以放心放进 KOReader 的 EPUB，并在覆盖旧书前判断是否会破坏阅读进度和标注关联。

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
  reports/         所有报告
```

重要报告：

| 文件 | 内容 |
|---|---|
| `quality-report.md` | 章节、图片、封面、质量问题摘要 |
| `asset-report.json` | 封面/插图候选与采用结果 |
| `metadata-report.json` | 元数据 evidence、decision、冲突和 KOReader guard；进入 metadata 阶段后生成 |
| `metadata-report.md` | 人可读元数据报告；进入 metadata 阶段后生成 |
| `epubcheck.json` | EPUBCheck 结果或跳过原因 |
| `update-diff.md` | 旧书与候选书的差异和发布决策；新书不一定有 |
| `manifest.json` | Hermes manifest，随书发布 |
| `publish-report.json` | 发布状态 |

## 阶段

### 1. 源文件快照

`LocalFileSource` 复制输入文件到 `raw/`，计算 source hash。后续步骤不直接改原始文件。

### 2. EPUB 构建与规范化

TXT 输入先经过 `build_draft_from_txt()` 生成 draft EPUB。EPUB 输入和 draft EPUB 都会通过 `normalize_existing_epub()` 进入统一结构。规范化会尽量保留源 EPUB 的 OPF 版本和阅读结构，不主动升级为 EPUB3，除非后续实现能保证 nav/spine 完整。

### 3. EPUB 检查

`inspect_epub()` 提取：

- 书名、作者、OPF identifier。
- 章节列表。
- 图片清单。
- 封面状态。
- CSS 和资源引用。
- 章节正文、结构、资源 fingerprint。

检查结果用于质量报告、manifest 和旧书差异比较。

### 4. 元数据增强

当 `metadata_enrichment.mode` 不是 `off` 且调用方传入 provider/reasoner 时，Hermes 会构造 `MetadataClues`：

- 用户输入的 title/author。
- OPF identifier。
- 已有 metadata。
- 前若干章节标题。
- 是否缺封面。

provider 返回 evidence，reasoner 返回 decision。只有通过配置门禁的字段会写入 OPF。写入后立刻重新 inspect，并记录 `reader_structure_stable`。

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

### 5. 资源增强

`AssetEnricher` 可以为缺封面的书规划候选资源。高置信封面可自动采用，插图目前只进入 pending 规划，不自动插入正文。

### 6. EPUBCheck

如果 `pipeline.require_epubcheck` 为 true，EPUBCheck 未通过会阻断发布。找不到 Java 或 EPUBCheck jar 时，状态为 `skipped`；在严格模式下同样阻断。

### 7. 远端状态读取

发布前读取：

```text
/books/<slug>.epub
/books/<slug>.hermes.json
```

远端任一状态不可判断，就不覆盖旧书。

### 8. 差异判断

`compare_for_update()` 的核心规则：

- canonical id 不一致：阻断。
- 新章节数少于旧章节数：阻断。
- 旧章节前缀的正文、结构、资源、href、item id 有变化：阻断。
- 旧章节完全稳定且新章节更多：`SAFE_APPEND`。
- 旧章节完全稳定且章节数相同：`SAFE_METADATA`。

OPF identifier 不一致会在 intake 层再次阻断。

### 9. KOReader 发布保护

元数据写入改变了 EPUB 文件 hash。对 `book_folder` 和 `docsettings` 来说，只要路径、canonical id、章节结构稳定，旧书覆盖可以接受。对 `hashdocsettings` 来说，旧进度绑定可能依赖内容 hash，因此第一版一律 pending。

### 10. WebDAV 发布

新书直接创建。旧书安全更新需要：

- 旧 EPUB 和 manifest 都可读。
- WebDAV 客户端支持条件写入。
- 准备期间远端未被修改。
- 备份写入成功。
- 覆盖后校验通过。

失败时进入 `.pending/` 或 `pending-local`。

## 大模型清洗的接入方式

后续大模型可以接入，但要遵守同一条原则：模型做判断，确定性代码做写入。

建议分三层：

1. 报告层：模型判断章节边界、疑似广告、缺章、错位、段落异常，只生成 report。
2. 候选层：把可自动修复项输出成结构化 patch，例如删除第 N 行广告、合并某一段落。
3. 写入层：Hermes 应用 patch，重新 inspect，并和旧版本比较。

不要让模型直接输出整章改写文本。轻小说和网文本来就有大量短段落、对话换行和空行节奏，段落合并必须保守。可以让模型判断“这是广告/导航/站点模板”，但是否删除仍由证据、位置和规则共同决定。

## 质量标准

当前管线要求：

- 可被 `ebooklib` 读取。
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
