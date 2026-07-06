# Kindle PW5 与 KOReader 配置

本文只记录与 Hermes 工作流有关的 Kindle/KOReader 设置。越狱、插件安装和网络配置会随固件与 KOReader 版本变化，实际操作前应查阅 KOReader 与 WinterBreak 的最新说明。

## 目标形态

```text
Hermes -> WebDAV /books
              |
              v
        KOReader Cloud Storage
              |
              v
        本地 EPUB + .sdr/docsettings
```

Hermes 不直接写 Kindle 文件系统。它只把 EPUB、manifest 和 pending 候选放到 WebDAV。KOReader 端通过 Cloud Storage 下载或更新。

## 推荐设置

| 项 | 推荐 |
|---|---|
| 阅读器 | KOReader |
| 书籍格式 | EPUB |
| 传书方式 | KOReader Cloud Storage + WebDAV |
| Hermes 目标目录 | `/books` |
| KOReader metadata location | 优先 `book_folder` |
| 旧书更新 | 让 Hermes 判断，风险更新从 `.pending/` 手动确认 |

## WebDAV 目录

Hermes 默认发布到：

```text
/books/<书名 - 作者>.epub
/books/<书名 - 作者>.hermes.json
```

风险更新会进入：

```text
/books/.pending/<书名 - 作者>/<timestamp-hash>/
  candidate.epub
  candidate.hermes.json
  risk-report.md
```

旧版本备份会进入：

```text
/books/.backups/<书名 - 作者>/<timestamp>/
  old.epub
  old.hermes.json
```

KOReader Cloud Storage 只需要指向 WebDAV 根路径或 `/books`。如果直接指向 `/books`，日常界面更干净；如果指向根路径，可以查看 `.pending` 和 `.backups`。

Hermes 端可以通过本地 run report 管理 pending：

```powershell
python -m scripts.hermes_books.pending list --runs-root runs
python -m scripts.hermes_books.pending approve --report runs\<job-id>\reports\publish-report.json --config config/hermes-books.yaml --confirm "<candidate_hash>"
python -m scripts.hermes_books.pending reject --report runs\<job-id>\reports\publish-report.json --config config/hermes-books.yaml --confirm "<candidate_hash>"
```

批准会先备份旧书再覆盖 live 路径；拒绝只删除 pending 候选文件。

## KOReader metadata location

Hermes 的旧书覆盖策略依赖 KOReader 的 metadata 存储模式。

| 模式 | Hermes 策略 |
|---|---|
| `book_folder` | 推荐。书旁 `.sdr` 路径稳定时，metadata-only 或 append-safe 更新可以保留关联 |
| `docsettings` | 可用。需要确保 KOReader 端本地路径稳定 |
| `hashdocsettings` | 不推荐用于自动覆盖。Hermes 第一版会阻断旧书 metadata rewrite |

原因很简单：metadata rewrite 会改变 EPUB 内容 hash。`hashdocsettings` 如果按内容 hash 关联阅读状态，旧进度未必能自动找到新书。

## KOReader 样式设置

Hermes 尽量不把书锁死。推荐 KOReader 端接管正文字体和阅读参数。

| 设置 | 建议 |
|---|---|
| 忽略出版商字体 | 开启 |
| 忽略出版商字号 | 源 EPUB 排版混乱时开启 |
| 强制稳定行高 | 开启 |
| 页面刷新 | 按残影情况设置，KPW5 通常每页刷新也可以接受 |
| 字体 | 中文长读可用思源宋体、霞鹜文楷等 |

Hermes 后续的 CSS 审计也应服务这个目标：书内 CSS 负责基本结构，不剥夺 KOReader 的阅读控制。

## 插件与同步

最小可用：

- Cloud Storage：从 WebDAV 下载书。

可选：

- HighlightSync：导出标注，用于后续知识处理。
- Syncery / Syncthing 类插件：多设备同步阅读状态。
- Terminal：排障工具。

这些插件不属于 Hermes intake 的必要条件。没有它们，Hermes 仍可把 EPUB 发布到 WebDAV。

## 更新旧书的习惯

建议：

1. 新书可以直接从 `/books` 下载。
2. 旧书如果 Hermes 返回 `published`，说明发布器判断为安全更新。
3. 旧书如果进入 `.pending`，先看 `risk-report.md` 和 `update-diff.md`。
4. 如果 KOReader 正在打开某本书，不要在设备端同时改同一个文件。
5. 对 `hashdocsettings` 用户，不要绕过 Hermes pending 手动覆盖旧文件。

## 故障排查

| 问题 | 检查 |
|---|---|
| KOReader 看不到书 | WebDAV 路径是否指向 `/books`，文件是否已 `published` |
| 只有 `.pending` 没有覆盖 | 看 `publish-report.json` 和 pending 下的 `risk-report.md` |
| 旧书进度丢了 | 检查 KOReader metadata location、文件名、下载路径是否变过 |
| WebDAV 登录失败 | 检查 URL、用户名、密码和服务器证书 |
| 书籍打开异常 | 看 `quality-report.md` 和 `epubcheck.json` |

## 需要谨慎的操作

- 不要把 `.pending` 候选当成自动发布结果。
- 不要删除 `.hermes.json`，旧书更新需要它判断身份。
- 不要在没有备份的情况下手动覆盖已读旧书。
- 不要把 `hashdocsettings` 下的 metadata rewrite 当作安全更新。

## 参考

- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [KOReader docsettings 文档](https://koreader.rocks/doc/modules/docsettings.html)
- [WinterBreak](https://kindlemodding.org/)
