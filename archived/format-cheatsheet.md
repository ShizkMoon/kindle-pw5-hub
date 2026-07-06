# 归档：Kindle 格式速查表

归档时间：2026-07-06

这份速查表来自早期 Kindle/Calibre 工作流。当前 Hermes 主线只接受本地 TXT/EPUB，并统一输出 EPUB。其他格式仍有参考价值，但应在进入 Hermes 前完成转换。

## 当前规则

```text
Hermes intake: TXT/EPUB -> EPUB -> WebDAV -> KOReader
```

不再把 AZW3、MOBI、PDF、DOCX 直接写成 Hermes 输入能力。

## 格式建议

| 源格式 | 现在怎么处理 |
|---|---|
| TXT | 直接进入 Hermes |
| EPUB | 直接进入 Hermes |
| MOBI/AZW3 | 先用 Calibre 转 EPUB |
| PDF | 如果是论文/扫描件，优先用 KOReader 或专用 PDF 工具；不建议强转小说 EPUB |
| DOCX/HTML | 先转 EPUB，再进入 Hermes |
| UMD/JAR | 暂缓 |

## 仍有用的命令

Calibre 转换示例：

```powershell
ebook-convert input.azw3 output.epub
ebook-convert input.mobi output.epub
ebook-convert input.docx output.epub
```

Hermes intake：

```powershell
python -m scripts.hermes_books.intake "D:\Books\book.epub" -t "书名" -a "作者" --config config/hermes-books.yaml
```

## 不再推荐

- 为 Kindle 原生系统生成 AZW3 作为主格式。
- 使用 Send to Kindle 作为自动化主链路。
- 多格式并行维护同一本书。

多格式会让阅读状态、标注和版本管理变复杂。Hermes 的选择是把复杂度收敛到 EPUB。

## 转换后的检查

不管源格式是什么，进入 Hermes 后都应看：

- `quality-report.md`
- `epubcheck.json`
- `manifest.json`
- `publish-report.json`

旧书更新还要看 `update-diff.md` 和 `.pending` 风险报告。
