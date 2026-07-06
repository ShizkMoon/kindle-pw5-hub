# Hermes 激进元数据增强设计规格

日期：2026-07-06

状态：已由用户确认核心边界：优先实现激进自动写入；KOReader `hashdocsettings` 第一版默认阻断 live overwrite，后续单独做 sidecar migration。

## 背景

Hermes Book Intake MVP 已经能把本地 TXT/EPUB 规范化为 EPUB、检查章节和资源指纹，并通过 WebDAV 以 append-safe 策略发布到 KOReader 工作流。下一阶段需要把“元数据补全”从报告型辅助能力推进为自动写入能力：结合本地文件线索、大模型判断和网络搜索证据，自动补齐标准书名、原题、系列、卷号、作者、插画师、译者、出版社、文库、ISBN、发售日、简介、标签和封面。

用户明确希望先实现激进自动写入，而不是只做保守报告。因此本规格的目标是：默认积极写入 EPUB 元数据和封面，但把 KOReader 阅读进度、书签、标注关联保护作为发布前硬门槛。

## 设计目标

- 大模型和网络搜索用于识别、融合、裁决元数据。
- 自动写入 EPUB OPF/DC metadata、Calibre/series 扩展 metadata、封面资源和 manifest 增强字段。
- 每个写入字段都保留来源证据、置信度、冲突信息和应用决策。
- 写入后必须重新检查 EPUB，确认正文、章节结构、spine、章节 href、章节 item id 没有漂移。
- WebDAV live overwrite 只在 KOReader 进度关联风险可接受时发生。
- 不把大模型自然语言输出直接写入正文。
- 不让模型自由改写章节标题、正文、目录结构；本阶段只处理书籍级 metadata 和封面。

## 非目标

- 不实现正文清洗、广告删除、段落合并。
- 不实现缺章正文补全。
- 不实现 UMD/JAR 支持。
- 不直接修改 Kindle 本地 `.sdr` 或 `docsettings` 文件。
- 不在第一版支持 KOReader `hashdocsettings` 模式下的自动 live overwrite。
- 不把联网搜索结果中的正文或盗版内容写入 EPUB。

## KOReader 进度关联约束

KOReader 会保存书籍阅读状态、标注、笔记和阅读设置。常见配置下，它们与书籍路径、书名旁 `.sdr` 目录或集中 docsettings 记录相关。`hashdocsettings` 模式还会依赖文档内容 hash。元数据自动写入会改变 EPUB 文件内容，因此必须按 KOReader metadata 模式控制发布策略。

新增配置：

```yaml
koreader:
  metadata_location: "book_folder"   # book_folder | docsettings | hashdocsettings
  aggressive_metadata_requires_stable_path: true
  hashdocsettings_policy: "block"     # block
```

第一版策略：

- `book_folder`：允许激进 metadata live overwrite，但必须保持 WebDAV 目标路径、文件名、`canonical_id` 稳定。
- `docsettings`：允许激进 metadata live overwrite，但必须保持目标路径稳定，并在 report 中提示本地设备路径也需稳定。
- `hashdocsettings`：阻断 live overwrite，发布到 `.pending/`，因为任何 EPUB 内容变化都会改变文档 hash，无法保证 KOReader 自动关联旧进度。

后续如果要支持 `hashdocsettings`，需要新增 Kindle 端或 WebDAV 端 sidecar migration 能力，读取旧 docsettings/`.sdr`，按 KOReader 规则迁移到新文档 hash。该能力不属于本阶段。

## 架构

新增模块：

```text
scripts/hermes_books/metadata.py
  MetadataProvider        网络搜索/本地测试 provider 协议
  MetadataReasoner        大模型融合/裁决协议
  MetadataEnricher        编排抽取、搜索、裁决、写入、报告
  MetadataReport          完整审计报告
  MetadataDecision        单字段写入决策

scripts/hermes_books/opf_metadata.py
  apply_metadata_to_epub  以结构化方式修改 OPF metadata 和封面
  preserve_identity       保留 OPF identifier / canonical_id / target path
```

修改模块：

```text
scripts/hermes_books/config.py
  增加 metadata_enrichment 和 koreader 配置。

scripts/hermes_books/intake.py
  在 asset enrichment 前后接入 metadata enrichment。
  写入 metadata-report.json 和 metadata-report.md。
  将 metadata_report 写入 manifest。

scripts/hermes_books/diff.py
  明确 metadata-only 改动仍需检查 KOReader 发布策略。

scripts/hermes_books/publish.py
  根据 KOReader guard 阻断 hashdocsettings 下的 live overwrite。
```

数据流：

```text
inspect normalized EPUB
  -> collect local metadata clues
  -> provider.search(clues)
  -> reasoner.resolve(clues, candidates)
  -> apply high-confidence decisions to EPUB
  -> inspect rewritten EPUB
  -> verify no reader-structure drift
  -> write metadata reports
  -> continue update diff and publish
```

## 配置

新增默认配置：

```yaml
metadata_enrichment:
  mode: "aggressive"          # off | report-only | aggressive
  auto_apply_min_confidence: 0.86
  require_evidence_url: true
  allow_single_source_fields: true
  block_on_conflicting_identity: true
  preserve_target_path: true
  preserve_canonical_id: true
  write_epub_metadata: true
  write_cover: true
  write_description: true
  write_subjects: true

koreader:
  metadata_location: "book_folder"
  aggressive_metadata_requires_stable_path: true
  hashdocsettings_policy: "block"
```

字段策略：

- 自动写入：`title`、`original_title`、`series`、`volume`、`authors`、`illustrators`、`translators`、`publisher`、`imprint`、`isbn`、`published_date`、`description`、`subjects`、`cover`.
- 保留不变：`canonical_id`、WebDAV target path、原 OPF identifier。
- 只报告不自动应用：会改变书籍身份的冲突结论，例如“这其实是另一卷”或“作者完全不同”。

## 大模型与搜索接口

`MetadataProvider` 负责返回候选 evidence，不直接裁决：

```python
class MetadataProvider(Protocol):
    def search(self, clues: MetadataClues) -> list[MetadataEvidence]:
        ...
```

`MetadataReasoner` 负责融合 evidence，必须返回结构化结果：

```python
class MetadataReasoner(Protocol):
    def resolve(self, clues: MetadataClues, evidence: list[MetadataEvidence]) -> MetadataResolution:
        ...
```

离线测试用 `StaticMetadataProvider` 和 `StaticMetadataReasoner`。真实联网 provider 后续可接 New API、搜索 API、Amazon/BookWalker/出版社页面解析器。

模型输出必须满足：

- JSON schema 可验证。
- 每个字段包含 `value`、`confidence`、`evidence_ids`、`action`。
- `action` 只能是 `apply`、`report`、`block`。
- `confidence < auto_apply_min_confidence` 时不能自动写入。
- `require_evidence_url = true` 时，缺 URL 的字段不能自动写入。

## 写入规则

OPF 写入：

- `dc:title` 写标准标题，但 manifest 保留原始输入标题和 enriched title。
- `dc:creator` 写作者列表，保留角色信息。
- `dc:publisher` 写出版社或文库上级出版社。
- `dc:identifier` 原值保留；ISBN 作为额外 identifier 写入。
- `dc:description` 写简介。
- `dc:subject` 写标签。
- series、volume、original_title、illustrator、translator、imprint 写入 `meta` 扩展字段。

封面写入：

- 只在 `write_cover = true` 且候选 evidence 达到阈值时自动写入。
- 如果已有封面，保留旧封面资源，不删除。
- 新封面使用唯一路径，例如 `images/hermes-metadata-cover.jpg`。
- OPF manifest 标记 `properties="cover-image"`。
- EPUB2 cover meta 同步更新。

写入后校验：

- 重新 `inspect_epub()`。
- 旧章节 fingerprint、structure_fingerprint、resource_fingerprint 不应因 metadata 写入变化。
- spine itemref fingerprint 不应变化。
- 章节 href 和 item id 不应变化。
- OPF identifier 不应变化。
- 若任何 reader-facing 结构漂移，metadata 写入产物进入 `.pending/`，不 live overwrite。

## 发布规则

新增 `metadata_publish_guard`：

```text
if metadata_enrichment.mode == aggressive:
  if koreader.metadata_location == hashdocsettings:
    decision = BLOCKED_RISKY
    reason = "KOReader hashdocsettings cannot preserve progress after EPUB content hash changes"
  elif target_path_changed or canonical_id_changed:
    decision = BLOCKED_RISKY
    reason = "aggressive metadata changed path-sensitive identity"
  elif reader_structure_changed:
    decision = BLOCKED_RISKY
    reason = "metadata rewrite changed reader-facing EPUB structure"
  else:
    allow SAFE_METADATA publish
```

`SAFE_METADATA` live overwrite 仍需 WebDAV publisher 的条件写入、备份、回滚和 pending fallback。

## 报告

新增：

```text
runs/<job-id>/reports/
  metadata-report.json
  metadata-report.md
```

`metadata-report.json` 格式：

```json
{
  "mode": "aggressive",
  "status": "applied",
  "koreader_guard": {
    "metadata_location": "book_folder",
    "stable_target_path": true,
    "stable_canonical_id": true,
    "live_publish_allowed": true
  },
  "decisions": [
    {
      "field": "illustrators",
      "old_value": [],
      "new_value": ["いみぎむる"],
      "action": "apply",
      "confidence": 0.95,
      "evidence_ids": ["bookwalker-1"],
      "reason": "high confidence store metadata"
    }
  ],
  "conflicts": []
}
```

`metadata-report.md` 必须有人话结论：

```text
已自动补全《某书》的作者、插画师、系列和封面。
未修改 WebDAV 文件名和 canonical_id，因此 book_folder 模式下可保留 KOReader .sdr 关联。
```

## 错误处理

- `METADATA_SEARCH_FAILED`：不阻塞 EPUB 生成；记录 provider 错误，继续原始 metadata。
- `METADATA_REASONER_INVALID_JSON`：不写入；记录错误，继续发布普通 normalized EPUB。
- `METADATA_CONFLICTING_IDENTITY`：阻断 live overwrite，进入 `.pending/`。
- `METADATA_APPLY_FAILED`：不发布改写产物，回退到未改写 EPUB。
- `KOREADER_HASHDOCSETTINGS_BLOCKED`：进入 `.pending/`，旧书不覆盖。
- `METADATA_REWRITE_STRUCTURE_DRIFT`：进入 `.pending/`。

## 测试策略

单元测试：

- 静态 provider 返回高置信标题、原题、系列、卷号、插画师、ISBN，期望写入 OPF 和 manifest。
- 低置信字段进入 report，不写入 OPF。
- 无 evidence URL 且配置要求 URL 时不写入。
- 冲突身份字段触发 `BLOCKED_RISKY`。
- 已有 OPF identifier 保持不变。
- 自动写封面时旧封面资源保留，新封面路径唯一。
- 写入 metadata 后章节 fingerprint、structure、href、item id 不变。
- `book_folder` 模式允许 `SAFE_METADATA`。
- `docsettings` 模式允许 `SAFE_METADATA` 并报告路径稳定要求。
- `hashdocsettings` 模式阻断 live overwrite。
- reasoner 返回非法 JSON 时不中断主流程。

集成测试：

- `run_intake()` 注入静态 metadata provider/reasoner，生成 `metadata-report.json` 和 `metadata-report.md`。
- 新书 aggressive metadata 写入后可发布。
- 旧书 aggressive metadata 改写在 `book_folder` 下可走 safe metadata publish。
- 旧书 aggressive metadata 改写在 `hashdocsettings` 下进入 pending。

## 验收标准

- 默认配置支持 aggressive metadata enrichment。
- 大模型/网络搜索可通过 provider/reasoner 注入，不把实现绑定到单一供应商。
- 离线测试覆盖全部自动写入和阻断路径。
- 每个自动写入字段都有 evidence、confidence、action 和 reason。
- EPUB OPF metadata 和封面可以自动更新。
- 自动写入不会改变 WebDAV target path、`canonical_id`、OPF identifier。
- KOReader `hashdocsettings` 下不会 live overwrite。
- 所有发布路径仍保留现有 WebDAV 条件写入、备份、回滚和 pending fallback。

## 后续演进

- 增加真实搜索 provider：Amazon Japan、BookWalker、出版社页面、OpenLibrary、Google Books、中文百科。
- 增加 New API reasoner，通过 JSON schema 强制结构化输出。
- 增加 KOReader sidecar migrator，支持 `hashdocsettings` 下的受控迁移。
- 将章节目录对照、缺章检测和插图定位接入同一 evidence/reasoner 框架。

## 参考

- KOReader User Guide: https://koreader.rocks/user_guide/
- KOReader docsettings module: https://koreader.rocks/doc/modules/docsettings.html
- Hermes Book Intake 设计规格：`docs/superpowers/specs/2026-07-06-hermes-book-intake-design.md`
- Hermes Book Intake 实现计划：`docs/superpowers/plans/2026-07-06-hermes-book-intake.md`
