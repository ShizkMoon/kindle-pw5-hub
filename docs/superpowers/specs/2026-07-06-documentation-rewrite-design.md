# Hermes Documentation Rewrite Design

日期：2026-07-06

## 目标

把仓库文档从早期设想稿重写为当前 Hermes 书籍工作流的可靠说明。文档必须区分“已经实现”“配置可用”“后续计划”，避免把旧的 Calibre/MCP/模型路由设想写成当前事实。

## 范围

重写：

- `README.md`
- `docs/*.md`
- `archived/*.md`

不重写：

- `docs/superpowers/specs/*.md`
- `docs/superpowers/plans/*.md`

`docs/superpowers` 是实施留痕，只作为事实来源。

## 文档定位

- `README.md`：项目总入口，说明 Hermes 的当前能力、命令、配置、报告、发布策略和文档导航。
- `docs/architecture.md`：当前系统架构，重点写 Hermes intake、EPUB 检查、元数据增强、WebDAV 发布、KOReader 进度保护。
- `docs/pipeline.md`：书籍处理标准，说明 TXT/EPUB 输入、报告、质量门禁、元数据写入和后续 LLM 清洗方向。
- `docs/mcp-specs.md`：MCP/工具接口蓝图。明确哪些已有 Python API 可封装，哪些仍是规划。
- `docs/kindle-setup.md`：Kindle PW5 + KOReader 端配置，重点写 WebDAV、`.sdr`/docsettings 关联风险和推荐 metadata location。
- `docs/daily-reading-rhythm.md`：保留个人使用语境，但改成“工作流如何融入阅读日常”，不夸大自动化完成度。
- `docs/buying-guide.md`：设备选择备忘，围绕 KOReader、EPUB、WebDAV、进度同步风险来比较。
- `docs/apple-compatibility.md`：Apple 生态兼容性备忘，说明 iOS/iPad/macOS 与 WebDAV、EPUB、标注流的关系。
- `archived/*.md`：历史方案备忘。重写后必须在开头说明归档原因、被当前工作流替代的部分、仍可参考的部分。

## 写作原则

- 当前能力优先，未来计划后置。
- 命令和配置必须能从代码中找到对应实现。
- 避免模型名称、成本估算、MCP 工具数量这类容易过时的断言，除非明确标注为历史或计划。
- 中文口吻保持自然，少用口号式句子。
- 保留个人项目气质，但工程文档优先可执行、可维护。

## 必须反映的当前事实

- `python -m scripts.hermes_books.intake` 是当前统一入口，支持本地 TXT/EPUB。
- 运行目录为 `runs/<job-id>/`，包含 raw、draft、normalized、reports。
- `config/hermes-books.example.yaml` 定义 WebDAV、pipeline、update policy、asset enrichment、metadata enrichment、KOReader 策略。
- WebDAV 发布区分新书、append-safe、metadata-safe、风险 pending。
- 旧书 live overwrite 依赖条件写入、备份和校验；不满足条件时写入 `.pending/`。
- 元数据增强通过 `MetadataProvider` 和 `MetadataReasoner` 注入，当前实现是 provider-agnostic。
- OPF 写入保留主 identifier，可写标题、作者、出版社、ISBN、简介、标签、系列、卷号、插画师、译者、文库、发售日和封面。
- `book_folder`/`docsettings` 下要求路径和章节结构稳定；`hashdocsettings` 第一版阻断 live overwrite。
- README 和 docs 应明确 UMD/JAR 不在当前实现范围。

## 验收标准

- 所有现役和 archived 文档都有新的结构。
- 文档之间不再重复整段旧流水线说明。
- `README.md` 可以单独帮助用户理解当前怎么运行。
- `docs/architecture.md` 和 `docs/pipeline.md` 不再把未实现 MCP/大模型搜索提供商写成已完成。
- `archived/*.md` 明确是历史参考，而不是当前手册。
- Markdown 链接、代码块和标题格式检查通过。
