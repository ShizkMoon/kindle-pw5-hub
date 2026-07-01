# Kindle 格式速查表

> **KOReader 只读 EPUB。全链路：任何输入格式 → EPUB → KOReader。**

---

## 一、格式策略

| 格式 | 角色 | 流向 |
|---|---|---|
| **EPUB** | 唯一格式、唯一源 | → KOReader 直接阅读 |
| ~~KFX, AZW3, MOBI~~ | 不保留 | → 统一转 EPUB |
| **TXT, HTML, DOCX** | 输入源 | → EPUB |
| **PDF** | 输入源 | → EPUB 或 KOReader 原生重排 |

---

## 二、各输入格式 → EPUB

### TXT（网文 / 低质量文本）

```
原始 TXT
    │
[1] 编码检测 → 统一转为 UTF-8
[2] 章节识别
    ├── 规则: 正则匹配 "第X章" / "Chapter X" / "Volume X"
    └── AI: 规则失败时 Agent 分析文本结构推断章节边界
[3] 排版清理
    ├── 移除多余空行/换行
    ├── 统一段落缩进
    ├── 修复半角全角混排
    └── 可选: OpenCC 繁简转换
[4] 元数据提取
    ├── 书名: 文件名/正文首行
    ├── 作者: 文件名/正文提取
    └── Agent 元数据管线 → 自动补全
[5] EPUB 组装
    ebook-convert cleaned.txt output.epub `
      --formatting-type heuristic `
      --chapter-mark pagebreak `
      --level1-toc //h:h1 `
      --base-font-size 12
```

### MOBI / AZW3 → EPUB

```powershell
# 直接转换，保留所有元数据
ebook-convert input.azw3 output.epub
```

### HTML / DOCX → EPUB

```powershell
# DOCX 需要先装 pandoc 或用 Calibre 直接转换
ebook-convert input.docx output.epub

# HTML 直接转
ebook-convert input.html output.epub `
  --level1-toc //h1 `
  --level2-toc //h2
```

### PDF → EPUB

```powershell
# 文字型 PDF: 直接转换（效果取决于原排版）
ebook-convert input.pdf output.epub --enable-heuristics

# 扫描版 PDF: 需要 OCR → 人工处理为主
# 或直接用 KOReader 原生 PDF 重排（推荐）
```

---

## 三、EPUB 标准化与验证

### 标准化

```powershell
ebook-convert input.epub normalized.epub `
  --output-profile generic_eink_hd `
  --base-font-size 12 `
  --remove-paragraph-spacing `
  --change-justification justify
```

### 验证

```bash
java -jar epubcheck.jar book.epub
```

### 程序化修复

```python
import ebooklib
from ebooklib import epub

book = epub.read_epub('input.epub')
# 操作 items, metadata, CSS
epub.write_epub('output.epub', book)
```

---

## 四、EPUBCheck 常见错误速查

| 错误类型 | 典型信息 | 修复方式 |
|---|---|---|
| 缺失 OPF 条目 | `item not in manifest` | ebooklib: `book.add_item()` |
| 断链 | `referenced resource missing` | 修复 href 或补全文件 |
| 无效日期 | `date not valid per OPF spec` | 改为 `YYYY-MM-DD` 格式 |
| CSS 语法错误 | `CSS parsing error` | AI 审查 CSS → 修复 |
| 图片无 alt | `alt text missing for image` | 补充 alt 属性 |
| 字体未声明 | `font not in OPF manifest` | 在 OPF 中声明或移除引用 |

---

## 五、KOReader 格式支持

| 格式 | 支持程度 | 推荐处理 |
|---|---|---|
| **EPUB** | ✅ 完美原生 | 直接阅读 |
| PDF | ✅ 含智能重排 | 直接阅读或用 KOReader 裁边+重排 |
| MOBI / AZW3 | ✅ 可读 | 建议先转 EPUB（保留元数据更好） |
| TXT, HTML, DOCX, RTF, MD | ✅ 全部支持 | 转 EPUB 体验更好 |
| DJVU, CBZ, CBT, FB2, PDB, CHM | ✅ 全部支持 | 直接阅读 |
| ~~KFX~~ | ❌ 不支持 | 不要在 KOReader 用 |

---

## 六、传书方式

越狱后 KOReader 不依赖亚马逊云：

| 方式 | 配置难度 | 场景 |
|---|---|---|
| **WebDAV → KOReader Cloud Storage** | 中 | 日常传书主力 |
| **USB 拷贝** | 零 | 批量导入 |
| **Calibre Content Server → KOReader** | 低 | 从 PC 书库直传 |
| **File Browser (浏览器拖拽)** | 零 | 临时快速 |
| **SSH/SFTP (KOReader 内建)** | 高 | 高级管理 |
| **Syncthing (KOSyncthing+)** | 中 | 多设备自动同步 |

---

## 七、运行位置总结

| 任务 | ☁️ 云服务器 | 💻 Windows |
|---|---|---|
| TXT/MOBI/AZW3/HTML → EPUB 转换 | ✅ | ✅ |
| EPUB 标准化 (ebook-convert) | ✅ | ✅ |
| EPUBCheck 验证 | ✅ | ✅ |
| ebooklib 程序化修复 | ✅ | ✅ |
| Agent AI 章节识别 + 元数据 | ✅ | ✅ |
| Sigil Automate List GUI 修复 | ❌ | ✅ |
| WebDAV 服务 → KOReader | ✅ | ✅ |

---

## 参考

- [EPUBCheck (W3C)](https://github.com/w3c/epubcheck)
- [ebooklib](https://github.com/aerkalov/ebooklib)
- [Calibre ebook-convert 文档](https://manual.calibre-ebook.com/generated/en/ebook-convert.html)
- [Sigil 官方用户指南](https://sigil-ebook.com/sigil-user-guide)
- [KOReader 格式支持](https://koreader.rocks/user_guide/)
