# Kindle 格式速查表

> **仅保留两种格式：EPUB（主） + KFX（副）。** 越狱后 KOReader 原生读取 EPUB，KFX 为可选的增强排版输出。

---

## 一、格式策略

| 格式 | 角色 | 可编辑 | KOReader 读取 | 原生系统读取 | 生成位置 |
|---|---|---|---|---|---|
| **EPUB** | 主格式、唯一源 | ✅ | ✅ 完美 | ❌ | ☁️ 云服务器 / 💻 Windows |
| **KFX** | 副格式、只读输出 | ❌ | ❌ | ✅ 增强排版 | 💻 Windows only |

**核心原则**：EPUB 是 Single Source of Truth。所有处理（元数据、排版修复、CSS 清理）都在 EPUB 上执行。KFX 仅在需要原生系统阅读时才生成，生成后无法编辑。

### KOReader 格式支持摘要

| 格式 | 支持程度 |
|---|---|
| EPUB | ✅ 完美原生支持（含自定义字体、CSS、脚注） |
| PDF | ✅ 支持，含智能重排（自动裁边+横屏+连续翻页） |
| MOBI / AZW3 | ✅ 可读取 |
| KFX | ❌ 不支持 |
| DJVU, CBZ, FB2, TXT, HTML, DOCX, RTF, MD | ✅ 全部支持 |

---

## 二、EPUB 处理工具链

### 2.1 标准化

```powershell
# ebook-convert EPUB → EPUB（可在 ☁️ 云服务器 或 💻 Windows 执行）
ebook-convert input.epub normalized.epub `
  --output-profile generic_eink_hd `
  --base-font-size 12 `
  --remove-paragraph-spacing `
  --change-justification justify
```

### 2.2 验证

```bash
# EPUBCheck (W3C 官方验证器，可在 ☁️ 云服务器 或 💻 Windows 执行)
java -jar epubcheck.jar book.epub
# 输出: "No errors or warnings detected" 或详细错误列表
```

### 2.3 程序化修复

```python
# ebooklib (Python 库，可在 ☁️ 云服务器 或 💻 Windows 执行)
import ebooklib
from ebooklib import epub

book = epub.read_epub('input.epub')
# 读写文件: book.get_items(), book.add_item()
# 修改元数据: book.set_title(), book.add_author()
# 操作 CSS: 遍历 items 找到 .css → set_content()
epub.write_epub('output.epub', book)
```

### 2.4 GUI 深度修复

Sigil Automate Lists（💻 Windows GUI only）——串联插件+EPUBCheck，一键批量执行复杂修复序列。适用于 CSS 深度清理、ToC 重建等需要人工判断的操作。

---

## 三、KFX 生成（可选）

```
EPUB → Calibre KFX Output 插件 → Kindle Previewer 3 → KPF → KFX
```

**硬约束：**
- Kindle Previewer 3 是 Amazon 桌面 GUI 程序，**仅 Windows/macOS**
- 无官方 Linux 支持（Wine Docker 方案 `yshalsager/calibre-with-kfx` 存在但不稳定）
- 转换速度慢：一本小说约 48 秒（比 MOBI/AZW3 慢 10 倍）

```powershell
# Calibre KFX Output 的 CLI 调用方式 (💻 Windows only)
calibre-debug -r "KFX Output" -- input.epub output.kfx
```

### KFX 参数

| 参数 | 作用 |
|---|---|
| `--pages N` | 生成近似页码（0 = 自动） |
| `--book` | 标记为 EBOK（否则 PDOC） |
| `--asin BXXXXXXXXX` | 设置 ASIN（启用 Goodreads 集成） |
| `--timeout` | 超时停止（>15 分钟视为异常） |

### KFX 产出判断

| 场景 | 是否需要生成 KFX |
|---|---|
| 日常 KOReader 阅读 | ❌ EPUB 即可 |
| 切回原生系统阅读 | ✅ 生成 KFX |
| 归档/收藏 | ✅ EPUB（可编辑）+ KFX（最佳排版） |
| 共享给非越狱 Kindle 用户 | ✅ 生成 KFX 或让对方自行转换 |

---

## 四、传书方式

越狱后不使用亚马逊云服务，传书全部走本地方式：

| 方式 | 传输格式 | 最大文件 | 配置难度 |
|---|---|---|---|
| **WebDAV → KOReader Cloud Storage** | EPUB | 无限制 | 中 |
| **USB 拷贝** | EPUB 或 KFX | 无限制 | 零 |
| **Calibre Content Server → KOReader** | EPUB | 无限制 | 低 |
| **File Browser (Kindle 浏览器拖拽)** | EPUB | 无限制 | 零 |
| **SSH/SFTP (KOReader 内建)** | EPUB | 无限制 | 高 |

---

## 五、EPUBCheck 常见错误速查

| 错误类型 | 典型信息 | 修复方式 |
|---|---|---|
| 缺失 OPF 条目 | `item not in manifest` | ebooklib: `book.add_item()` |
| 断链 | `referenced resource missing` | 修复 href 或补全文件 |
| 无效日期 | `date not valid per OPF spec` | 改为 `YYYY-MM-DD` 格式 |
| CSS 语法错误 | `CSS parsing error` | AI 审查 CSS → 修复 |
| 图片无 alt | `alt text missing for image` | 补充 alt 属性 |
| 字体未声明 | `font not in OPF manifest` | 在 OPF 中声明或移除引用 |

---

## 六、云服务器 vs Windows 分工总结

| 处理任务 | ☁️ 云服务器 (2C2G) | 💻 Windows |
|---|---|---|
| EPUB 下载/获取 | ✅ | ✅ |
| ebook-convert 标准化 | ✅ | ✅ |
| EPUBCheck 验证 | ✅ | ✅ |
| ebooklib 程序化修复 | ✅ | ✅ |
| Agent AI 审查 + 脚本生成 | ✅ | ✅ |
| Calibre calibredb 元数据管理 | ✅ (连远程 server) | ✅ |
| Sigil Automate List GUI 修复 | ❌ | ✅ |
| **KFX 生成 (Kindle Previewer 3)** | **❌ (Wine 不推荐)** | **✅** |
| WebDAV 服务 | ✅ | ✅ |

> **推荐策略**：云服务器承担所有可自动化的 EPUB 处理（标准化、验证、元数据补全），Windows 只做 KFX 生成和 Sigil GUI 操作这两个必须本地的任务。

---

## 参考

- [EPUBCheck (W3C)](https://github.com/w3c/epubcheck) — 权威 EPUB 验证器
- [ebooklib](https://github.com/aerkalov/ebooklib) — Python EPUB 读写库
- [Calibre KFX Output 插件](https://www.mobileread.com/forums/showthread.php?t=272407) — 官方插件索引，46K+ 下载
- [Sigil 官方用户指南](https://sigil-ebook.com/sigil-user-guide) — Automate Lists 使用方法
- [KOReader 格式支持](https://koreader.rocks/user_guide/)
