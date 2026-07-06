# Apple 生态兼容性

本文评估 iPhone、iPad 和 Mac 如何接入 Hermes 书务工作流。结论很简单：Apple 设备可以很好地做管理端、检查端和补充阅读端，但不会替代 KOReader 作为 Hermes 的主要阅读目标。

## Hermes 与 Apple 的关系

Hermes 输出的是：

```text
EPUB
.hermes.json
reports
WebDAV /books
WebDAV /.pending
```

这些东西和平台无关。Apple 设备只要能访问 WebDAV、打开 EPUB、查看 Markdown/JSON，就能参与流程。

## iPhone

适合：

- 快速查看 `publish-report.json` 或 `metadata-report.md`。
- 在外面确认某本书是否已经 published。
- 临时阅读短章节。
- 接收 Hermes 后续可能发出的通知。

不适合：

- 长时间阅读。
- 调整 EPUB 排版。
- 复用 KOReader `.sdr` 进度。

## iPad

适合：

- 阅读图文书、技术书、PDF。
- 检查 EPUB 封面、目录、插图。
- 查看 `.pending` 候选，做人工确认。
- 做笔记和批注。

风险：

- iPad 阅读 App 的标注格式不一定能回到 KOReader。
- 同一本 EPUB 在不同 App 中的进度状态通常不互通。
- 如果 App 会改写 EPUB 文件，不能再把它当 Hermes 候选源。

## Mac

适合：

- 作为 Hermes 开发和管理端。
- 跑 Python、Calibre、EPUBCheck、Sigil。
- 挂载 WebDAV，查看 `/books`、`.pending`、`.backups`。
- 批量处理源文件。

如果未来把 Hermes 部署到 Mac，核心命令不需要变：

```bash
python -m scripts.hermes_books.intake "/path/to/book.epub" -t "书名" -a "作者" --config config/hermes-books.yaml
```

需要适配的是路径、环境变量、Java/EPUBCheck 安装和 WebDAV 证书。

## Readest 与 KOReader Sync

Readest、KOReader Sync Server 这类方案可以作为跨设备阅读同步的候选，但它们不是当前 Hermes 主链路。要接入时需要单独验证：

- EPUB 文件身份如何计算。
- 进度 anchor 是否能跨 App 保持。
- 标注导出格式是否稳定。
- 与 KOReader `book_folder`、`docsettings`、`hashdocsettings` 的关系。

在没有验证前，不能假设 iPad/iPhone 阅读进度会自动和 Kindle KOReader 合并。

## 推荐用法

| 设备 | 角色 |
|---|---|
| Kindle PW5 + KOReader | 主力长读 |
| iPhone | 状态查看、通知、轻量阅读 |
| iPad | PDF/图文书、候选 EPUB 检查 |
| Mac | 开发、批处理、WebDAV 管理 |

Apple 设备接进来后，Hermes 仍应保持 EPUB + WebDAV 的中立输出。不要为了某个 App 改掉主线格式。

## 接入清单

1. 在 Apple 设备上配置 WebDAV 客户端。
2. 能读取 `/books` 和 `.pending`。
3. 选择不会自动改写 EPUB 的阅读 App。
4. 标注导出先作为独立实验，不混进 KOReader 标注管线。
5. 多设备同步先从“同一本 EPUB 文件”开始，不急着同步阅读状态。

## 不建议

- 不建议用 Apple Books 作为 Hermes 主库。
- 不建议把 iCloud 当 WebDAV 替代品。
- 不建议让多个阅读 App 同时改同一个 EPUB。
- 不建议在没有 sidecar 迁移策略时追求全设备进度统一。

Apple 生态可以很好地补位，但 Hermes 的安静中心仍然是：生成干净 EPUB，放到 WebDAV，让 KOReader 阅读。
