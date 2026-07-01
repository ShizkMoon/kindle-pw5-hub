# EPUB 处理流水线

**唯一的格式就是 EPUB。任何输入 -> EPUB -> KOReader。**

所有处理目标均为已越狱 KPW5 上的 KOReader。亚马逊格式（KFX/AZW3/MOBI）、云服务（Whispersync/发送至 Kindle）、Kindle 原生阅读均不在本流水线范围内。

这是一条 AI 驱动的质量流水线。从文本编码检测到最终 KOReader 适配，每个阶段都有 AI 介入的决策点，自动选择模型路由、修复策略和质检标准。

---

## 输入格式矩阵

| 输入格式 | 工具 | 命令 | 备注 |
|---|---|---|---|
| TXT（UTF-8） | `charset-normalizer` + pipeline | `python scripts/txt2epub/pipeline.py novel.txt` | 完整的 7 步网文流水线 |
| TXT（GBK/GB18030/Big5） | `charset-normalizer` | 自动检测 -> UTF-8，然后进入流水线 | 中文网文最常见场景 |
| MOBI | `ebook-convert` | `ebook-convert input.mobi output.epub` | 一条命令完成，元数据保留 |
| AZW3 | `ebook-convert` | `ebook-convert input.azw3 output.epub` | 一条命令完成，元数据保留 |
| PDF（文字型） | `ebook-convert` | `ebook-convert input.pdf output.epub --enable-heuristics` | 质量取决于源文件排版 |
| PDF（扫描型） | 不适用 | 使用 KOReader 原生 PDF 重排 | OCR 为人工操作，不在此流水线中 |
| HTML | `ebook-convert` | `ebook-convert input.html output.epub --level1-toc //h1` | --level1-toc 提取标题结构 |
| DOCX | `ebook-convert` | `ebook-convert input.docx output.epub` | Calibre 原生支持 DOCX |
| EPUB（原始） | ebooklib | 程序化修复 + CSS 审计 | 跳过格式转换，直接进入 L3+ |

---

## TXT 网文流水线

TXT 输入走专用的 7 步流水线。其他格式从 L5（组装）开始。

```
L1: 编码检测    L2: 垃圾过滤    L3: 章节检测     L4: 繁简转换
 (charset    ->   (正则+AI   ->   (正则+AI   ->   (OpenCC)
  normalizer)      规则过滤)       路由决策)         
    |                 |               |               |
    v                 v               v               v
L5: 排版修复    L6: 元数据补全   L7: 组装 + 校验 + KOReader 适配 -> 最终 EPUB
```

### 流水线设计哲学

这条流水线的核心设计思路：**AI 不是流水线的替代，而是流水线的决策层**。每一步都有确定性规则作为基础，AI 只在规则无法覆盖的边界和模糊地带介入——做"判断"而不是做"搬运"。

---

## 模型路由决策

我的 API 网关背后有四款模型可用，不同任务调用不同模型，不是"越贵越好"，而是"谁适合谁上"。

### 路由总表

| 任务 | 首选模型 | 替代模型 | 单次成本 | 选择依据 |
|---|---|---|---|---|
| 章节模式检测 | GLM-4.7 | DeepSeek V3 | ~0.005 元 | 纯模式匹配与结构识别，GLM-4.7 绰绰有余，没有必要用大模型。响应快、成本低。 |
| 元数据补全 | GLM-5.2 | Kimi K2.7 | ~0.02 元 | 需要理解文本语义来提取书名、作者、摘要，GLM-5.2 在中文语境下的理解能力明显优于 4.7。 |
| CSS 审计 | GLM-5.2 | DeepSeek V3 | ~0.03 元 | 最复杂的任务。需要理解 EPUB 规范的 CSS 约束、KOReader 的渲染特性、以及中英文混排的边界条件。GLM-5.2 可以一次性返回结构化的审计报告和修复建议。 |
| 内容质量评估 | DeepSeek V3 | GLM-5.2 | ~0.01 元 | 大段文本的连贯性、重复段落检测、错别字识别——DeepSeek V3 在长文本分析上性价比最高。 |
| 超长文档分析 | Kimi K2.7 | — | ~0.05 元 | 全书结构分析、跨章节引用检测、超过 100K token 的场景，Kimi 的上下文窗口无人能敌。 |
| 摘要生成 | GLM-5.2 | MiniMax M3 | ~0.02 元 | GLM-5.2 的中文摘要质量稳定，冗余信息过滤干净。 |

### 为什么这样分

这个路由方案是在几十次实际跑书后沉淀下来的。核心原则就两条：

1. **GLM-4.7 负责"找"（检测、匹配、分类），GLM-5.2 负责"判断"（分析、评估、生成）。** 前者是阅读理解的选择题，后者是主观题。
2. **DeepSeek V3 和 Kimi K2.7 是 GLM 系列的补充，不是替代。** DeepSeek 在长文本性价比上胜出，Kimi 在超长上下文上无人能及。MiniMax M3 目前只在内容摘要的候选池里，日常负载不高。

---

## L1：编码检测

```python
import charset_normalizer

with open('novel.txt', 'rb') as f:
    raw = f.read()
result = charset_normalizer.from_bytes(raw).best()
text = str(result)  # 自动转换为 UTF-8 字符串
```

`charset-normalizer` 在中文网文场景下的表现远超 `chardet`。GBK/GB18030/UTF-8/Big5 的自动识别准确率在实战中接近 100%。如果置信度低于 0.8，Agent 会用 GLM-4.7 采样文本内容做二次确认（极少数情况，一个月遇到不了一次）。

---

## L2：垃圾过滤

移除爬取网文中的常见噪声：

- 含 URL 的行（`https?://\S+`）
- 网站固定模板：`记住本站`、`手机阅读`、`本章未完.*请点击下一页`、`一秒记住.*`
- 连续重复的章节标题（正则匹配后比对相邻标题）
- 连续纯符号行（>= 3 行 `~~~~~~~`、`=======` 等）
- 纯数字/空白且不足 10 字符的行

垃圾规则库维护在一个独立的 YAML 文件里，Agent 每次跑流水线时会自动检测是否有新出现的噪声模式，发现可疑行时交给 GLM-4.7 判断是否为垃圾（成本约 0.003 元/次，一个月触发不超过 20 次）。

---

## L3：章节检测（AI 第一优先级）

章节检测是整个流水线最关键的阶段。如果章节分错了，后续的排版、目录、导航全部错位。所以这里不是"正则主力 + AI 辅助"，而是 **正则初筛 -> AI 决策 -> 正则执行** 的三段式架构。

### 第一层：正则初筛

```
中文模式：  第[0-9零一二三四五六七八九十百千万]+[章回卷节部集篇]
英文模式：  ^Chapter\s+\d+[:\s]+  |  ^Part\s+[IVX]+[:\s]+  |  ^Book\s+\d+[:\s]+
兜底策略：  未发现章节 -> 按空行分组，约每 50 段 = 1 章
```

正则跑完后，输出三个指标：
- `detected_count`：匹配到的章节数
- `coverage_ratio`：匹配行覆盖的总行数占比
- `pattern_variance`：匹配到的模式种类数（正常应该 <= 3 种）

### 第二层：AI 决策

| 触发条件 | 动作 | 使用模型 | 说明 |
|---|---|---|---|
| `coverage_ratio >= 0.95` 且 `pattern_variance <= 2` | 直接使用正则结果，AI 跳过 | 无需调用 | 标准格式，正则完全能搞定，不浪费 AI 调用 |
| `0.7 <= coverage_ratio < 0.95` | AI 确认 + 补充 | GLM-4.7 | Agent 将前 500 行的采样发给 GLM-4.7，要求返回：检测到的章节模式、匹配示例、卷/序/跋标记。成本 ~0.005 元 |
| `coverage_ratio < 0.7` | 全书结构分析 | Kimi K2.7 | 正则基本失效，说明是非标准格式（可能是分段符、特殊标记或无章节结构）。将全书文本发给 Kimi，利用超长上下文做全局结构分析，返回完整的章节边界列表。成本 ~0.05 元，但这种情况本身就罕见 |
| `pattern_variance > 3` | AI 判定主模式 | GLM-4.7 | 同一文档中出现多种章节标记方式（如"第X章"混着"Chapter X"），Agent 请 AI 判定哪个是主要模式，其他的归为子标题或卷名 |

AI 的返回格式统一为 JSON：

```json
{
  "pattern": "第[零一二三四五六七八九十百千]+章",
  "pattern_type": "regex_cn_number",
  "confidence": 0.97,
  "samples": ["第一章 楔子", "第二章 少年", "第三章 长安"],
  "structure_hints": {
    "has_prologue": true,
    "prologue_line": 42,
    "has_volume_headers": true,
    "volume_pattern": "第[一二三四五]卷"
  }
}
```

### 第三层：正则执行

AI 返回确认过的模式后，Agent 用该模式重跑一次全文档匹配，生成最终的章节边界列表。这一步全是确定性操作，不会再调用 AI。

---

## L4：繁简转换（OpenCC）

| 配置 | 方向 | 使用场景 |
|---|---|---|
| `s2t.json` | 简体 -> 繁体 | 默认首选输出；繁体字在 E Ink 屏幕上笔画更饱满，阅读体验更好 |
| `s2tw.json` | 简体 -> 台湾繁体 | 台湾特有词汇场景 |
| `t2s.json` | 繁体 -> 简体 | 源文本为繁体 |

自动检测逻辑：分析 CJK 字符比例。若 >70% 为繁体字符，应用 `s2t.json`。否则保留原文。

```bash
opencc -c s2t.json -i input.txt -o output.txt
```

```python
import opencc
cc = opencc.OpenCC('s2t.json')
text = cc.convert(text)
```

---

## L5：排版修复

| 操作 | 规则 |
|---|---|
| 硬换行合并 | 中文行尾 + 中文行首 -> 合并为同一段落 |
| 空行归一化 | 连续空行 -> 单个空行 |
| 缩进去除 | 前导空格 -> 由 CSS `text-indent: 2em` 统一处理 |
| 引号归一化 | 可选：`""` -> `「」` |
| 全角转换 | 可选：英文标点 -> 中文标点 |

排版修复之后，Agent 会用正则抽样检查 20 个位置，验证合并和归一化是否按预期执行。这一步零 AI 成本，纯确定性自动化。

---

## L6：AI 元数据补全

元数据补全是 AI 介入最深的环节之一。目标不是"填几个字段"，而是让 EPUB 的元数据达到 Standard Ebooks 级别的完备度。

### 补全字段

| 字段 | 来源 | 兜底策略 | 使用的模型 |
|---|---|---|---|
| 书名 | 文件名（去除站点前缀） | 正文第一非空行 | GLM-4.7 |
| 作者 | 前 100 行中搜索 `作者：XXX` | Agent 联网搜索 + GLM-5.2 确认 | GLM-5.2 |
| 语言 | 自动检测 | `zh` | 无需 AI |
| 简介 | GLM-5.2 摘要生成 | 无 | GLM-5.2 |
| 标签/分类 | GLM-5.2 内容分类 | 文件名关键词提取 | GLM-5.2 |
| 封面 | Agent 生成（SVG -> 内嵌） | 纯文字封面 | GLM-5.2 |
| ISBN | 联网搜索 + Agent 确认 | 空 | GLM-5.2 |
| 出版日期 | 联网搜索 + Agent 确认 | 当前日期 | GLM-5.2 |

### 元数据补全的处理流程

```
书名/作者提取（本地正则 + GLM-4.7 确认）
  -> 简介生成（GLM-5.2，将前 2000 字总结为 100 字内的简介）
    -> 标签分类（GLM-5.2，从预定义的 50 个标签池中最多选 5 个）
      -> 封面生成（GLM-5.2 生成 SVG，矢量格式，内嵌于 EPUB，不依赖外部资源）
        -> ISBN/日期（联网搜索，仅当作者信息确定后才触发）
          -> 写入 OPF metadata + 校验
```

---

## L7：组装 -> 校验 -> KOReader 适配

### 组装

标准 EPUB 结构组装。将经 L1-L6 处理后的文本按章节拆分为 XHTML 文件，生成 `content.opf`（目录和元数据）、`toc.ncx`（向后兼容的目录）、`nav.xhtml`（EPUB 3 导航文档）以及 `style.css`（全局样式表）。

### CSS 审计（AI 驱动）

经过 L1-L6 处理后生成的 CSS 必须再过一遍 AI 审计。不是"信任自己生成的"，而是"每个属性都需要被重新审视"。

**审计检查清单（GLM-5.2 执行）：**

| 检查项 | 违规示例 | 正确做法 | 严重性 |
|---|---|---|---|
| `font-size` 使用相对单位 | `font-size: 16px` | `font-size: 1em` | 致命 |
| `body` 未被锁定 | `body { font-family: "SimSun"; font-size: 14pt; }` | `body { font-family: serif; }` | 致命 |
| 垂直 `margin` 使用 `em` | `margin-top: 5%` | `margin-top: 1em` | 严重 |
| 水平 `margin` 使用 `%` | `margin-left: 2em` | `margin-left: 5%` | 严重 |
| `line-height` 仅设置在 `body` 上 | `p { line-height: 1.8; }` | `body { line-height: 1.5; }` | 严重 |
| 无 `px`/`pt` 作为任何排版单位 | `text-indent: 32px` | `text-indent: 2em` | 致命 |
| `page-break-after` 一致性 | 混用 before/after | 统一用 after | 建议 |
| `small-caps` 真假 | `font-variant: small-caps` | `font-variant-caps: small-caps` | 建议 |

GLM-5.2 返回结构化的审计报告：

```json
{
  "pass": false,
  "critical_violations": [
    {
      "selector": "p.chapter-intro",
      "property": "font-size",
      "current": "14px",
      "suggested": "0.95em",
      "reason": "px 无法随 KOReader 字号缩放，用户调大字体会导致该段文字不变"
    }
  ],
  "warnings": [
    {
      "selector": "h2",
      "property": "margin-top",
      "current": "3%",
      "suggested": "2em",
      "reason": "垂直间距应跟随文字大小缩放，使用百分比会导致大字号时间距不足"
    }
  ],
  "suggestions": [
    {
      "description": "h1 和 h2 之间缺少 page-break，建议在 h1 之前添加 page-break-before: always 以确保卷标题独占一页"
    }
  ]
}
```

Agent 收到审计报告后，如果 `pass == false`，自动修复 `critical_violations`，然后递交给用户确认 `warnings` 是否也修。`suggestions` 不强修，留给用户阅读后决定。

### EPUBCheck 校验

```bash
java -jar epubcheck.jar book.epub
```

目标输出：`未发现错误或警告。`

### 常见错误与修复

| 错误 | EPUBCheck 消息 | 修复方式 |
|---|---|---|
| 缺少 OPF 条目 | `item not in OPF manifest` | `book.add_item()` 在 ebooklib 中注册 |
| 引用断裂 | `referenced resource missing` | 修复 `href` 或补充缺失文件 |
| 日期格式无效 | `date not valid per OPF spec` | 使用 `YYYY-MM-DD` 格式 |
| CSS 解析错误 | `CSS parsing error` | Agent 审计 -> 重新生成 CSS |
| 缺少 alt 文本 | `alt text missing for image` | 为 `<img>` 添加 `alt` 属性 |
| 字体未注册 | `font not in OPF manifest` | 在 OPF 中声明 `@font-face` 或移除 |

```python
# 程序化修复入口
from ebooklib import epub
book = epub.read_epub('input.epub')
# 检查和修复 items、metadata、CSS
epub.write_epub('output.epub', book)
```

### KOReader 适配

适配清单（Agent 自动执行）：

1. **样式微调兼容性检查**——确保 CSS 不冲突于 KOReader 的"忽略出版商的字体"和"强制稳定行高"两项微调
2. **字体策略验证**——确认未嵌入 CJK 字体和正文字体；symbol 字体和装饰性标题字体（如有）文件大小 < 50KB
3. **单位强制检查**——遍历全部 CSS 属性，确认文本相关单位全部使用 `em` 或 `%`
4. **封面生成**——Agent 生成 SVG 封面，内嵌于 EPUB，不依赖外部资源
5. **导航层级验证**——确认目录层级不超过 3 级（KOReader 目录面板的实际可用深度）

---

## EPUB 质量标准

### CSS 规则

| 规则 | 正确做法 | 错误做法 | 原因 |
|---|---|---|---|
| 字号单位 | `em` / `%` / `rem` | `px` / `pt` / `cm` | KOReader 无法缩放绝对单位 |
| 水平边距单位 | `%` | `em` | `em` 边距随字号一起放大，挤压正文空间 |
| 垂直边距单位 | `em` | `%` / `px` | 垂直间距应跟随文字缩放 |
| 正文对齐 | `text-align: justify` | `left` / `right` / `center` | 一致的阅读节奏 |
| 行高 | >= 1.2 | < 1.2 | 低于 1.2 在某些渲染器中会裁切文字 |
| 行高放置位置 | 仅在 `body` | 各元素单独设置 | 逐元素行高会覆盖 KOReader 的"强制稳定行高"微调 |
| 分页符 | 优先 `page-break-after` | 混用 before/after | 一致性原则；优先在章节结尾添加 |
| 小型大写字母 | `font-variant-caps: small-caps` | `font-variant: small-caps` | 后者是假小型大写，为等比例缩小 |
| 正文字体 | 留空（不设置） | 显式 `font-family` / `font-size` | 让 KOReader 引擎控制正文 |

### 硬性规则

1. **绝不在 `font-size` 中使用 `px` 或 `pt`。** KOReader 的字号控件只能缩放相对单位。用绝对单位等于锁死字号，用户无法调整。
2. **不锁定 `body`。** `body` 上不设 `font-family`、`font-size` 或强制 `line-height`。KOReader 用户通过样式微调控制这些。
3. **`em` 管垂直，`%` 管水平。** 防止用户在调字号时发生排版错乱。
4. **`line-height` 只放在 `body` 上。** 逐元素设置行高会与 KOReader 的"强制稳定行高"微调冲突。

### 标准 CSS 模板

```css
/* 基础 */
body {
  font-family: serif;
  line-height: 1.5;
  text-align: justify;
  margin: 0;
  padding: 0;
  widows: 1;
  orphans: 1;
  hyphens: auto;
  -webkit-hyphens: auto;
  -epub-hyphens: auto;
  font-variant-numeric: oldstyle-nums proportional-nums;
  font-kerning: normal;
}

/* 段落 */
p {
  margin-top: 0;
  margin-bottom: 0;
  text-indent: 2em;
}

h1 + p, h2 + p, h3 + p, .section-break + p {
  text-indent: 0;           /* 标题后首段不缩进 */
}

p + p {
  margin-top: 0.3em;        /* 相邻段落之间微间距 */
}

/* 标题 */
h1 { text-align: center; font-size: 2em;   margin: 3em 0 1em 0; }   /* 书名 */
h2 { text-align: center; font-size: 1.5em; margin: 2em 0 0.5em 0; } /* 卷名 */
h3 { text-align: left;   font-size: 1.3em; margin: 1.5em 0 0.5em 0; } /* 章节名 */

/* 引用块 */
blockquote {
  margin: 1em 5%;           /* 垂直 em，水平 % */
  font-size: 0.95em;
}

/* 图片与表格 */
img  { max-width: 100%; height: auto; }
table { max-width: 100%; border-collapse: collapse; }

/* 真小型大写字母（非等比缩小） */
.small-caps {
  font-variant-caps: small-caps;
  letter-spacing: 0.05em;
}
```

---

## KOReader 适配

### 应启用的样式微调

| 微调项 | 效果 |
|---|---|
| `忽略出版商的字体族` | 使用 KOReader 字体替代嵌入字体 |
| `忽略出版商的字号` | 使用 KOReader 字号（仅当源 EPUB 排版混乱时启用） |
| `强制稳定行高` | 防止上下标导致行间距抖动 |
| `缩小上下标` | 将上下标缩至 50%，提升可读性 |

### 字体策略

| 类别 | 策略 | 原因 |
|---|---|---|
| 正文字体（衬线/无衬线） | 不嵌入 | KOReader 自动以用户字体替换 |
| 中文字体 | 不嵌入 | 文件过大；通过 `koreader/fonts/` 目录管理 |
| 符号/音标字体 | 按需嵌入 | 数学、IPA、特殊字符（文件极小） |
| 装饰性标题字体 | 按需嵌入 | 仅用于 h1/h2（文件极小） |

### 单位强制规范

所有影响文本尺寸的 CSS 属性必须使用相对单位：

| 属性 | 单位 | 说明 |
|---|---|---|
| `font-size` | `em` | KOReader 可缩放 |
| `margin`（垂直） | `em` | 跟随文字缩放 |
| `margin`（水平） | `%` | 相对视口，不会被挤压 |
| `padding` | `em` 或 `%` | 视场景而定 |
| `text-indent` | `em` | 自然缩放 |
| `line-height` | 无单位或 `em` | 推荐无单位（1.5 而非 1.5em） |

---

## 工具参考

| 工具 | 安装方式 | 主要 CLI 用法 | 角色 |
|---|---|---|---|
| **ebook-convert**（Calibre） | `scoop install calibre` | `ebook-convert input.fmt output.epub` | 格式转换、EPUB 归一化 |
| **EPUBCheck** | 从 [github.com/w3c/epubcheck](https://github.com/w3c/epubcheck) 下载 JAR | `java -jar epubcheck.jar book.epub` | W3C EPUB 标准校验 |
| **ebooklib** | `pip install ebooklib` | `epub.read_epub()` / `epub.write_epub()`（Python） | 程序化 EPUB 读写与修复 |
| **Sigil** | [sigil-ebook.com](https://sigil-ebook.com) | GUI 编辑器 + Automate List 插件 | 人工精细修复（GUI 专用工具） |
| **OpenCC** | `pip install opencc` | `opencc -c s2t.json -i in.txt -o out.txt` | 中文繁简转换 |
| **charset-normalizer** | `pip install charset-normalizer` | `charset_normalizer.from_bytes(raw).best()`（Python） | 编码检测 |

### 常用 ebook-convert 参数

```
--enable-heuristics           PDF：尝试检测文档结构
--level1-toc //h1             将 H1 映射为一级目录
--level2-toc //h2             将 H2 映射为二级目录
--base-font-size 12           相对字号的基准值设为 12pt
--output-profile generic_eink_hd   E Ink 优化输出
--remove-paragraph-spacing    去除段间距
--change-justification justify  强制两端对齐
```

---

## 云端 vs Windows 分工

| 任务 | 云端（2C2G） | Windows 笔记本 |
|---|---|---|
| TXT/MOBI/AZW3/HTML -> EPUB 转换 | 是 | 是 |
| EPUB 归一化（`ebook-convert`） | 是 | 是 |
| EPUBCheck 校验 | 是 | 是 |
| ebooklib 程序化修复 | 是 | 是 |
| 正则章节检测 | 是 | 是 |
| AI 章节检测（GLM-4.7 / Kimi K2.7） | 是 | 是 |
| AI 元数据补全（GLM-5.2） | 是 | 是 |
| AI CSS 审计（GLM-5.2） | 是 | 是 |
| 封面 SVG 生成（GLM-5.2） | 是 | 是 |
| WebDAV 上传到 KOReader | 是 | 是 |
| Sigil GUI 修复 | 否 | 是 |
| Calibre GUI 书库管理 | 否 | 是 |
| KOSyncthing+ 对等守护进程 | 否 | 是 |
| KOReader 标注采集 cron | 是（每日 22:00） | 否 |
| 模型路由决策 | 是 | 否 |

---

## AI 调用成本估算

按一本典型 50 万字的网文计算：

| 阶段 | 调用模型 | 次数 | 单次成本 | 阶段成本 |
|---|---|---|---|---|
| 章节检测（标准） | GLM-4.7 | 1 | 0.005 元 | 0.005 元 |
| 章节检测（异常） | Kimi K2.7 | 0-1 | 0.05 元 | ~0.005 元（概率加权） |
| 垃圾模式发现 | GLM-4.7 | 0-1 | 0.003 元 | ~0.001 元（概率加权） |
| 元数据补全 | GLM-5.2 | 3-5 | 0.02 元 | 0.06-0.10 元 |
| CSS 审计 | GLM-5.2 | 1 | 0.03 元 | 0.03 元 |
| **单书合计** | | | | **~0.10-0.15 元** |

以每月处理 50 本书计，AI 调用总成本不超过 8 元/月。这就是为什么我敢把 AI 塞进流水线每个环节——成本低到不需要考虑"省着用"。

---

## 参考资料

- [EPUB 3.4 W3C 规范](https://www.w3.org/TR/epub-34/)
- [Amazon KDP 出版指南](https://kdp.amazon.com/en_US/help/topic/GH4DRT75GWWAGBTU)
- [Friends of EPUB / BlitzTricks](https://friendsofepub.github.io/eBookTricks/)
- [KOReader 用户指南](https://koreader.rocks/user_guide/)
- [Calibre ebook-convert 文档](https://manual.calibre-ebook.com/generated/en/ebook-convert.html)
- [EPUBCheck（W3C）](https://github.com/w3c/epubcheck)
- [ebooklib](https://github.com/aerkalov/ebooklib)
- [OpenCC](https://github.com/BYVoid/OpenCC)
