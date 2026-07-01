# EPUB 高质量处理管线

> 基于 EPUB 3.4 / W3C 规范、Amazon KDP 排版指南、Friends of EPUB 最佳实践、KOReader 渲染特性。
> 目标：任何输入 → 符合专业出版质量标准的 EPUB → KOReader。

---

## 一、管线总览

```
输入 (TXT/MOBI/AZW3/PDF/HTML/DOCX/EPUB)
    │
    ▼
[L1] 编码标准化 + 格式提取
    │
    ▼
[L2] 结构识别 + 语义标记
    │
    ▼
[L3] 内容清理 + 排版规范化
    │
    ▼
[L4] 元数据补全
    │
    ▼
[L5] EPUB 组装 + CSS 注入
    │
    ▼
[L6] 验证 (EPUBCheck)
    │
    ▼
[L7] KOReader 适配优化
    │
    ▼
输出: 高质量 EPUB → WebDAV → KOReader
```

---

## 二、各层详细规范

### L1：编码标准化 + 格式提取

| 输入格式 | 工具 | 命令/方法 |
|---|---|---|
| TXT (GBK/GB18030/Big5) | `chardet` / `charset-normalizer` | Python 自动检测 → UTF-8 |
| TXT (UTF-8) | 直接处理 | 跳过编码转换 |
| MOBI/AZW3 | `ebook-convert` | `ebook-convert input.azw3 temp.epub` |
| HTML/DOCX | `ebook-convert` | `ebook-convert input.html temp.epub` |
| PDF (文字型) | `ebook-convert` | `ebook-convert input.pdf temp.epub --enable-heuristics` |
| EPUB (已有) | 直接进入 L3 | 跳过 L1-L2 |

```python
# 编码检测
import charset_normalizer

with open('novel.txt', 'rb') as f:
    raw = f.read()
result = charset_normalizer.from_bytes(raw).best()
text = str(result)  # 已自动转为 UTF-8 str
```

### L2：结构识别 + 语义标记

#### 章节模式匹配

```
中文:
  第[0-9零一二三四五六七八九十百千万]+[章回卷节部集篇]
  Chapter\s+\d+[:\s]+
  Volume\s+\d+[:\s]+

英文:
  ^Chapter\s+\d+[:\s]+
  ^Part\s+[IVX]+[:\s]+
  ^Book\s+\d+[:\s]+

兜底: 全文无章节 → 以空行分节 → 每 N 段为一章 (默认 50 段)
```

#### AI 辅助策略

当正则匹配失败或置信度低时，调用 LLM 辅助：

```
[Agent Prompt]
分析以下 TXT 文本的前 500 行，识别章节结构。
输出 JSON:
{
  "format": "chinese_chapter" | "english_chapter" | "no_structure",
  "chapter_pattern": "正则表达式",
  "sample_matches": ["匹配示例1", "匹配示例2"],
  "has_volume": true/false,
  "has_prologue": true/false,
  "has_epilogue": true/false
}
```

**模型选择**：GLM-4.7（~¥0.005/次），只在规则失败时触发。

#### OpenCC 繁简转换

```powershell
# CLI
opencc -c s2t.json -i input.txt -o output.txt

# Python API
import opencc
cc = opencc.OpenCC('s2t.json')
text = cc.convert(text)
```

常用配置：
| 配置 | 说明 |
|---|---|
| `s2t.json` | 简体→繁体 |
| `s2tw.json` | 简体→台湾繁体 |
| `t2s.json` | 繁体→简体 |
| `s2twp.json` | 简体→台湾繁体（含词汇转换） |

> **建议**：保留用户原始编码的繁简状态，仅在检测到混合繁简或明确需求时才转换。默认 `s2t.json`。

### L3：内容清理 + 排版规范化

#### 3.1 网文垃圾清理

```python
# 自动过滤模式（可配置）
FILTER_PATTERNS = [
    r'本章未完.*请点击下一页',
    r'记住本站.*',
    r'https?://\S+',
    r'最新章节.*',
    r'手机阅读.*',
    r'ps[：:].*',       # 英文附注
    r'PS[：:].*',
    r'[\(（][^)）]*[求更求票求收藏求推荐][^)）]*[\)）]',
]

# 段落级：连续 3 个以上纯符号行 → 删除
# 行级：纯数字/纯空白/纯标点且 < 10 字符 → 删除
```

#### 3.2 排版标准化（CSS 注入策略）

基于 Amazon KDP 指南 + Friends of EPUB + KOReader 特性，注入标准 CSS：

```css
/* ===== 基础设置 ===== */
body {
  font-family: serif;          /* KOReader 会替换为用户字体 */
  line-height: 1.5;            /* 加到 body 避免覆盖用户设置 */
  text-align: justify;
  margin: 0;
  padding: 0;
  widows: 1;
  orphans: 1;
}

/* ===== 段落 ===== */
p {
  margin-top: 0;
  margin-bottom: 0;
  text-indent: 2em;            /* Amazon 建议 ≤4em */
}

/* 章节标题后的第一段不缩进 */
h1 + p, h2 + p, h3 + p,
.section-break + p {
  text-indent: 0;
}

/* 段落间距：相邻段落微间距（避免双倍行距） */
p + p {
  margin-top: 0.3em;
}

/* ===== 标题 ===== */
h1 {  /* 书名 */
  text-align: center;
  font-size: 2em;
  margin-top: 3em;
  margin-bottom: 1em;
}

h2 {  /* 卷 */
  text-align: center;
  font-size: 1.5em;
  margin-top: 2em;
  margin-bottom: 0.5em;
}

h3 {  /* 章 */
  text-align: left;            /* KDP: 标题不要 justify */
  font-size: 1.3em;
  margin-top: 1.5em;
  margin-bottom: 0.5em;
}

/* ===== 排版增强 ===== */
/* 连字符 */body {
  hyphens: auto;
  -webkit-hyphens: auto;
  -epub-hyphens: auto;
  hyphenate-limit-chars: 6 3 2;
  hyphenate-limit-lines: 2;
}

/* OpenType 可读性增强 */
body {
  font-variant-numeric: oldstyle-nums proportional-nums;
  font-kerning: normal;
}

/* 真实小型大写字母（比 fake small-caps 好得多） */
.small-caps {
  font-variant-caps: small-caps;
  letter-spacing: 0.05em;
}

/* ===== 引用块 ===== */
blockquote {
  margin: 1em 5%;              /* 水平用 %，垂直用 em */
  font-size: 0.95em;
}

/* ===== 图片 ===== */
img {
  max-width: 100%;
  height: auto;
}

/* ===== 表格 ===== */
table {
  max-width: 100%;
  border-collapse: collapse;
}

/* ===== 脚注 ===== */
/* EPUB 3: 使用 epub:type="footnote" 语义标记 */
```

#### 3.3 排版关键原则

| 原则 | 正确 | 错误 |
|---|---|---|
| 字体大小单位 | `em` / `%` / `rem` | `px` / `pt` / `cm` (KOReader 无法缩放) |
| 水平边距单位 | `%` | `em` (随字号变大而挤压内容) |
| 垂直边距单位 | `em` | `%` / `px` |
| 正文对齐 | `text-align: justify` | 强制 `left` / `right` / `center` |
| 行高 | ≥ 1.2 | < 1.2 (部分阅读器截断) |
| line-height 位置 | `body` | 单独元素（会覆盖阅读器用户设置） |
| 页面断 | `page-break-after` 优于 `page-break-before` | 混用 |
| 小型大写字母 | `font-variant-caps: small-caps` | `font-variant: small-caps` (fake) |
| 正文字体样式 | 全默认（让阅读器控制） | 强制指定 body 字体/字号 |

#### 3.4 Agent 辅助 CSS 审查

```
[Agent Prompt]
分析这个 EPUB 的 CSS 文件。找出以下问题：
1. 使用了 px/pt 等绝对单位的属性
2. 对 body 文本指定了 font-family 或 font-size
3. line-height 小于 1.2 的元素
4. 使用 em 做水平边距的元素（bug：字号越大边距越大）
5. 冲突的选择器规则
6. 冗余/未使用的 CSS 规则

输出 JSON，包含每个问题的文件位置和建议修复方案。
```

### L4：元数据补全

见 `local-first-architecture.md` 第 3.1 节。核心流程：

```
ISBN 查找 → 多源交叉验证 → AI 冲突解决 → calibremcp 写入
```

EPUB 元数据字段（Dubulin Core）：

```xml
<dc:title>书名</dc:title>
<dc:creator>作者</dc:creator>
<dc:language>zh</dc:language>
<dc:date>2024-01-01</dc:date>
<dc:publisher>出版社</dc:publisher>
<dc:description>简介</dc:description>
<dc:subject>标签1</dc:subject>
<dc:identifier id="isbn">urn:isbn:978XXXXXXXXXX</dc:identifier>
```

### L5：EPUB 组装 + CSS 注入

```python
from ebooklib import epub

book = epub.EpubBook()

# 元数据
book.set_identifier('urn:uuid:' + str(uuid4()))
book.set_title('书名')
book.set_language('zh')
book.add_author('作者')

# 注入标准 CSS
css = epub.EpubItem(
    uid="style",
    file_name="style/standard.css",
    media_type="text/css",
    content=STANDARD_CSS.encode('utf-8')
)
book.add_item(css)

# 章节（按 L2 识别的结构）
for idx, chapter_data in enumerate(chapters):
    c = epub.EpubHtml(
        title=chapter_data['title'],
        file_name=f'chapter_{idx:03d}.xhtml',
        lang='zh'
    )
    c.content = wrap_chapter_html(chapter_data['content'], chapter_data['title'])
    c.add_item(css)
    book.add_item(c)
    book.spine.append(c)

# ToC
book.toc = [(epub.Section('目录'), [epub.Link(f'chapter_{i:03d}.xhtml', ch['title'], f'ch{i}')) for i, ch in enumerate(chapters)])]
book.add_item(epub.EpubNcx())
book.add_item(epub.EpubNav())

# 写入
epub.write_epub('output.epub', book)
```

#### 章节 HTML 模板

```html
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh">
<head>
  <title>{chapter_title}</title>
  <link rel="stylesheet" type="text/css" href="style/standard.css"/>
</head>
<body>
  <h3>{chapter_title}</h3>
  {chapter_body_as_p_tags}
</body>
</html>
```

### L6：验证 (EPUBCheck)

```bash
java -jar epubcheck.jar output.epub
```

期望输出：`No errors or warnings detected.`

常见错误自动修复策略：

| 错误 | 自动修复 |
|---|---|
| `item not in OPF manifest` | `book.add_item()` 补全 |
| `referenced resource missing` | 检查 href → 补全或移除引用 |
| `date not valid` | 标准化为 `YYYY-MM-DD` |
| `CSS parsing error` | Agent 分析 → 生成修复 CSS |
| `missing alt text for image` | AI 生成 alt 文本 |
| `font not in OPF manifest` | 声明或移除 `@font-face` |

### L7：KOReader 适配优化

KOReader 的渲染特性决定了以下优化：

#### L7.1 使用相对单位

KOReader 的字体大小 widget 只缩放 `em` / `%` / `rem` 单位的文本。`px` / `pt` 单位的内容不会随用户的字号设置变化。

> **硬规则**：EPUB CSS 中禁止 `px` 和 `pt` 作为字体大小单位。

#### L7.2 不锁定 body 样式

KOReader 允许用户通过 Style Tweaks 覆盖以下属性：
- `font-family` — 用户可强制忽略出版方字体
- `font-size` — 用户可重置主文字大小
- `line-height` — 用户可忽略出版方行高

> **原则**：body 不要指定 `font-family`、`font-size`、强制 `line-height`。让 KOReader 的排版引擎和用户设置主导。

#### L7.3 字体嵌入策略

```
不需要嵌入的:
  - serif / sans-serif 族（KOReader 自动替换为用户字体）
  - CJK 字体（体积太大，KOReader 的 fonts/ 文件夹统一管理）

可以嵌入的:
  - 特殊符号字体（数学公式、音标）
  - 装饰性标题字体（仅用于 h1/h2，体积极小）
```

#### L7.4 KOReader Style Tweaks 预配置

KOReader 内建了以下 Style Tweaks，应该在 Kindle 上启用：

| Tweak | 效果 |
|---|---|
| `Ignore publisher font families` | 统一用 KOReader 字体 |
| `Ignore publisher font sizes` | 统一用 KOReader 字号（仅在 EPUB 字体大小混乱时） |
| `Enforce steady line heights` | 防止上下标影响行高 |
| `Smaller sub- and superscript` | 上下标缩小到 50% |

---

## 三、TXT 网文专项管线

网文 TXT 有独特的问题模式，需要专项处理：

```
原始网文 TXT
    │
[W1] 编码检测 → UTF-8
    │
[W2] 垃圾过滤
    ├── 网站广告行 (包含 URL 或特定关键词)
    ├── "记住本站"/"手机阅读"等提示行
    ├── 重复章节标题 (第X章 第X章)
    ├── 连续纯符号行 (~~~~~~~, =======)
    └── 纯数字/空白行
    │
[W3] 章节识别
    ├── 正则: 第[0-9零一二三四五六七八九十百千万]+[章回卷]
    ├── AI 辅助: 正则失败时 Agent 分析
    └── 去重: 连续相同章节标题合并
    │
[W4] 繁简处理
    ├── 检测: 统计 CJK 字符中繁体比例
    ├── >70% 繁体 → OpenCC s2t.json 转繁体
    └── 保持原样
    │
[W5] 排版修复
    ├── 硬换行合并: 中文段落内单个换行 → 合并为一段
    ├── 段落空行: 连续空行 → 单空行 (段落分隔)
    ├── 半角全角: 英文标点 → 中文标点（可选）
    ├── 引号标准化: "" → 「」或保持原样（可选）
    └── 缩进统一: 段首空格 → 2em CSS text-indent
    │
[W6] 元数据提取
    ├── 书名: 文件名 (去后缀和网站前缀)
    ├── 作者: 正文前 100 行搜索 "作者：XXX"
    └── Agent 补全
    │
[W7] EPUB 组装 (L5) → 验证 (L6) → 适配 (L7)
    │
    输出 → WebDAV → KOReader
```

### 硬换行合并算法

```
中文段落内换行判定:
  - 上一行以中文/标点结尾 + 下一行以中文开头 → 合并
  - 上一行以英文/数字结尾 + 下一行以英文开头 → 保留换行（可能是代码/表格）
  - 连续两个空行 → 段落分隔标记

实现: Python 逐行扫描 + CJK Unicode 范围判断
```

---

## 四、推荐工具栈

| 层级 | 工具 | 安装 | 用途 |
|---|---|---|---|
| 编码 | `charset-normalizer` | `pip install charset-normalizer` | 自动编码检测 |
| 繁简 | `opencc` | `pip install opencc` | 简繁转换 |
| 转换 | `calibre` | `scoop install calibre` | 格式转换 + 标准化 |
| 构建 | `ebooklib` | `pip install ebooklib` | EPUB 程序化读写 |
| 验证 | `epubcheck` | 下载 JAR | W3C 标准 EPUB 验证 |
| AI | New API (已有) | — | 章节识别 + 元数据 + CSS 审查 |
| 编辑 | Sigil | 官网安装 | GUI 深度修复（可选） |

---

## 五、参考

- [EPUB 3.4 W3C 规范](https://www.w3.org/TR/epub-34/)
- [Amazon KDP 排版指南](https://kdp.amazon.com/en_US/help/topic/GH4DRT75GWWAGBTU)
- [Friends of EPUB / BlitzTricks](https://friendsofepub.github.io/eBookTricks/)
- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [Calibre ebook-convert 文档](https://manual.calibre-ebook.com/generated/en/ebook-convert.html)
- [OpenCC](https://github.com/BYVoid/OpenCC)
- [cn-epub-maker](https://github.com/muyen/cn-epub-maker) — 中文 TXT→EPUB 参考实现
- [txt-to-epub-converter (oomol-lab)](https://github.com/oomol-lab/txt-to-epub-converter) — AI 辅助章节识别
- [EPUBCheck](https://github.com/w3c/epubcheck)
