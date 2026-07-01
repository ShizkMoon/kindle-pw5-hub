# Calibre 自动化方案

> Calibre 对 Agent 的兼容性评估与自动化工作流设计。

---

## 一、概览：Calibre 的 Agent 接口全景

Calibre 虽然以 GUI 闻名，但**所有核心功能都有 CLI 对应**，天然适合被 Agent/脚本调用。不需要模拟鼠标点击。

| 工具 | 用途 | Agent 调用方式 |
|---|---|---|
| `ebook-convert` | 格式转换引擎 | 子进程调用 |
| `calibredb` | 书库 CRUD | 子进程调用（支持 JSON 输出） |
| `calibre-smtp` | 邮件推送 | 子进程调用 |
| `calibre-server` | HTTP 内容服务 | 启动后走 AJAX API |
| `calibre-debug` | Python 脚本执行 | 直接在 Calibre 环境跑 Python |

---

## 二、关键 CLI 用法

### 2.1 calibredb（书库管理）

```powershell
# JSON 输出（Agent 可解析）
calibredb list --fields=id,title,authors,formats --search "tag:未读" --for-machine

# 添加书籍
calibredb add "C:\Downloads\book.epub" --library-path "E:\CalibreLibrary"

# 批量更新元数据
calibredb set_metadata 42 --field title:"新书名" --field authors:"作者名"

# 连接远程 Content Server
calibredb list --with-library "http://localhost:8080/#mylibrary" --username user --password pass

# 导出
calibredb export 42 --dont-save-cover --library-path "E:\CalibreLibrary"
```

### 2.2 ebook-convert（格式转换）

```powershell
# 基础转换
ebook-convert input.epub output.azw3

# 针对 KPW5 优化
ebook-convert input.epub output.azw3 `
  --output-profile generic_eink_hd `
  --base-font-size 12 `
  --remove-paragraph-spacing `
  --change-justification justify

# 查所有可用选项（随输入/输出格式不同而变化）
ebook-convert input.epub output.azw3 -h
```

### 2.3 calibre-smtp（邮件推送）

```powershell
calibre-smtp -s "邮件主题" `
  -a book.epub `
  -r "kindle@example.com" `
  --attachment "book.epub" `
  user@gmail.com kindle_xxx@kindle.com "邮件正文"
```

---

## 三、Content Server HTTP API

启动 `calibre-server` 后暴露的 AJAX API（返回 JSON）：

```
GET  /ajax/books/{library_id}              → 所有书籍列表
GET  /ajax/book/{book_id}/{library_id}     → 单书元数据（含封面URL）
GET  /ajax/search/{library_id}?query=xxx   → 搜索
GET  /get/{format}/{book_id}/{library}     → 下载指定格式文件
GET  /opds                                 → OPDS 目录（阅读器可直接用）
```

Agent 可以通过 HTTP 直接调：

```powershell
# 启动服务
calibre-server --port 8080 --enable-local-write "E:\CalibreLibrary"

# Agent 调用
curl "http://localhost:8080/ajax/books/0"
curl "http://localhost:8080/get/EPUB/42/0" -o book.epub
```

`--enable-local-write` 允许本机进程（包括 calibredb）通过 server 写入书库，解决了 SQLite 并发锁的问题。

---

## 四、Python API（最深度集成）

```python
from calibre.library import db

# 打开书库
library = db('E:/CalibreLibrary').new_api

# 搜索
ids = library.search('author:"鲁迅"')

# 获取元数据
mi = library.get_metadata(42)
print(mi.title, mi.authors)

# 添加书籍
from calibre.ebooks.metadata.meta import get_metadata
mi = get_metadata(open('book.epub', 'rb'), 'epub')
library.add_books([(mi, {'EPUB': '/path/to/book.epub'})])

# 导出格式
library.copy_format_to(42, 'EPUB', '/output/path.epub')
```

线程安全、文档齐全。适合写 Agent 插件或后台服务时直接 import。

---

## 五、第三方封装（已有轮子）

| 项目 | 语言 | 特点 |
|---|---|---|
| **[access-calibre](https://github.com/kybernetikos/access-calibre)** | JS | **MCP Server**，Claude 可直接搜索书库、读章节 |
| **[calibre-rest](https://github.com/kencx/calibre-rest)** | Python | REST API 包装 calibredb |
| **[calibre-api](https://github.com/tanadelgigante/calibre-api)** | Python/FastAPI | 独立服务，token 认证 |
| **[node-calibre-api](https://github.com/denouche/node-calibre-api)** | JS/Docker | Docker 化转换 API |
| **[Calibre-Web-Automated](https://github.com/crocodilestick/Calibre-Web-Automated)** | Python | Calibre-Web 增强版，自带自动转换 |

对于 CherryStudio + Multica 的 Agent 协作场景，`access-calibre` 的 MCP Server 最值得关注——配置后 Agent 可以直接搜索你的 Calibre 书库。

---

## 六、自动化工作流设计

### 6.1 下载 → 入库 → 推送（全自动）

```
┌──────────────────────────────────────────────────────────┐
│  监控文件夹 (D:\Downloads\Books\)                           │
│      │                                                    │
│      ▼ 新 .epub 出现                                       │
│  ebook-convert → AZW3（针对 KPW5 优化）                     │
│      │                                                    │
│      ▼                                                    │
│  calibredb add → 自动入库 E:\CalibreLibrary               │
│      │                                                    │
│      ▼                                                    │
│  calibredb set_metadata → 补全元数据（可选：调豆瓣API）      │
│      │                                                    │
│      ▼                                                    │
│  判断：是否主力阅读？                                       │
│    ├─ 是 → USB 拷贝 .azw3 到 Kindle:\documents\            │
│    └─ 否 → calibre-smtp 推送到 Kindle 邮箱                 │
└──────────────────────────────────────────────────────────┘
```

### 6.2 实现方式

**方案 A：PowerShell FileSystemWatcher（Windows 原生）**

```powershell
$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = "D:\Downloads\Books"
$watcher.Filter = "*.epub"
$watcher.EnableRaisingEvents = $true

Register-ObjectEvent $watcher "Created" -Action {
    $path = $Event.SourceEventArgs.FullPath
    $out = [System.IO.Path]::ChangeExtension($path, ".azw3")
    ebook-convert $path $out --output-profile generic_eink_hd
    calibredb add $out --library-path "E:\CalibreLibrary"
}
```

**方案 B：Scoop 装 inotifywait + Bash 脚本（跨平台风格）**

**方案 C：Python watchdog + calibre API（最灵活）**

### 6.3 部署考量

- SQLite 并发限制：**不要在 Calibre GUI 运行时用 calibredb 写同一书库**
- 解决方案：始终通过 Content Server + `--enable-local-write` 访问，或确保 GUI 关闭
- 批量转换时注意 CPU 占用：`ebook-convert` 是单线程的，可以串行处理

---

## 七、Agent 兼容性评级

| 维度 | 评分 | 说明 |
|---|---|---|
| CLI 完整性 | ⭐⭐⭐⭐⭐ | 所有核心功能有 CLI，参数详尽 |
| JSON 输出 | ⭐⭐⭐⭐ | calibredb 支持 `--for-machine`，HTTP API 返回 JSON |
| 远程操作 | ⭐⭐⭐⭐ | Content Server + calibredb 远程连接 |
| Python API | ⭐⭐⭐⭐⭐ | 完整、线程安全、文档齐全 |
| 生态封装 | ⭐⭐⭐⭐ | 已有 MCP Server + REST 包装 |
| Windows 兼容 | ⭐⭐⭐⭐ | CLI 全可用，Scoop 一键安装 |

**结论：Calibre 是少数"设计时就考虑了脚本化"的开源 GUI 软件。** Agent 集成成本很低——直接走 CLI 或 HTTP API 即可，不需要桌面自动化那套脆弱方案。

---

## 参考

- [Calibre CLI 文档](https://manual.calibre-ebook.com/generated/en/cli-index.html)
- [calibredb 文档](https://manual.calibre-ebook.com/generated/en/calibredb.html)
- [Calibre DB API 文档](https://manual.calibre-ebook.com/db_api.html)
- [Calibre & EPUB: The Developer's Field Guide](https://bubble.ro/2026/06/18/calibre-epub-the-developers-field-guide/)
