# 归档：Calibre 自动化备忘

归档时间：2026-07-06

这份文档记录的是 Calibre 作为书库中心时的自动化想法。当前 Hermes 工作流不再以 Calibre 为发布中心，而是用 WebDAV 上的 EPUB 和 `.hermes.json` manifest 作为远端母本。Calibre 仍可作为转换和人工管理工具，但不是当前主链路。

## 当前定位

Calibre 可以做：

- MOBI/AZW3/DOCX/HTML 到 EPUB 的预转换。
- 人工查看 metadata。
- 临时修复 EPUB。
- 作为个人书库 GUI。

Calibre 不再负责：

- 自动推送到 Kindle。
- 维护 Hermes manifest。
- 判断旧书是否安全覆盖。
- 管理 KOReader 进度关联。

## 仍可用命令

```powershell
ebook-convert input.azw3 output.epub
ebook-convert input.mobi output.epub
ebook-convert input.docx output.epub
```

转换完成后再进入 Hermes：

```powershell
python -m scripts.hermes_books.intake "D:\Books\output.epub" -t "书名" -a "作者" --config config/hermes-books.yaml
```

## 为什么不再 Calibre-first

Calibre 很适合管理书库，但旧书自动覆盖需要更多上下文：

- 远端旧 EPUB 是否仍是 Hermes 发布的版本。
- `.hermes.json` 是否存在。
- OPF identifier 是否一致。
- 章节 anchor 是否稳定。
- WebDAV 是否支持条件写入。
- KOReader metadata location 是否允许 live overwrite。

这些是 Hermes publisher 的职责，不适合藏在 Calibre 导入动作里。

## 未来可能的结合方式

- MCP 工具读取 Calibre 书库，把选中的书送入 Hermes intake。
- Hermes 成功发布后，把 manifest 或报告路径写回 Calibre 自定义字段。
- Calibre 只做人工管理界面，不绕过 Hermes 发布器。

## 历史价值

这份归档保留 Calibre CLI 和书库思路。真正发布到 KOReader 前，应以 [README.md](../README.md) 和 [docs/architecture.md](../docs/architecture.md) 为准。
