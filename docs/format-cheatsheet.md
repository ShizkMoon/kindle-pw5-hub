# Kindle 格式速查表

> 传书格式选择、转换参数、推送对比 —— 快速决策参考。

---

## 一、格式选型

| 格式 | 自定义字体 | 排版质量 | Send to Kindle 推送 | USB 拷贝 | 推荐场景 |
|---|---|---|---|---|---|
| **AZW3 (KF8)** | ✅ | 好 | ❌ | ✅ | **USB 传书首选** |
| KFX | ✅ | 最好 | ❌ | ✅ | 极致排版追求 |
| EPUB | ✅（推送后转） | 好 | ✅ | ✅ | **云端推送首选** |
| MOBI (旧) | ❌ | 差 | ✅ | ✅ | 已淘汰 |
| MOBI (both) | ✅ | 一般 | ✅ | ✅ | 过渡兼容 |
| PDF | — | — | ✅ | ✅ | 漫画/扫描书（需重排） |
| TXT | — | — | ✅ | ✅ | 纯文本（建议先转 EPUB） |

### 决策树

```
你要怎么传？
├─ USB 数据线 → AZW3
│   └─ 想要增强排版？ → KFX（需 Calibre + KFX Output 插件）
├─ 云端推送 → EPUB（亚马逊会自动转 KFX）
│   └─ 文件 > 50MB → 只能 USB
└─ 无线（Calibre Content Server） → AZW3
```

---

## 二、ebook-convert 常用参数

### EPUB → AZW3（KPW5 优化）

```powershell
ebook-convert input.epub output.azw3 `
  --output-profile generic_eink_hd `
  --base-font-size 12 `
  --change-justification justify `
  --remove-paragraph-spacing `
  --margin-top 5 `
  --margin-bottom 5 `
  --margin-left 5 `
  --margin-right 5
```

### TXT → EPUB

```powershell
ebook-convert input.txt output.epub `
  --formatting-type heuristic `
  --base-font-size 12 `
  --chapter-mark pagebreak
```

### PDF → AZW3（不推荐，效果差）

```powershell
# PDF 固定版式转换效果不好，建议使用 KOReader 的重排功能
ebook-convert input.pdf output.azw3 `
  --enable-heuristics `
  --pdf-monochrome
```

### 查参数

```powershell
# 每个格式组合的可用参数不同
ebook-convert input.epub output.azw3 -h
```

---

## 三、传书方式对比

| 方式 | 最大文件 | 封面保留 | 云端同步 | 字体保留 | 配置难度 |
|---|---|---|---|---|---|
| USB 拷贝 AZW3 | 无限制 | ✅ | ❌ | ✅ | 零 |
| Send to Kindle 邮箱 | 50MB | ❌ (丢失) | ✅ | ✅ | 中 |
| 网页版 Send to Kindle | 50MB | ❌ | ✅ | ✅ | 零 |
| Calibre 邮件推送 | 50MB | ✅ (插件) | ✅ | ✅ | 高 |
| Calibre Content Server | 无限制 | ✅ | ❌ | ✅ | 低 |
| KOReader WebDAV | 无限制 | ✅ | ❌ | ✅ | 中 |

---

## 四、封面问题速解

Kindle 不显示封面的常见原因和解决方案：

| 原因 | 解决 |
|---|---|
| AZW3 缺少 ASIN 元数据 | Calibre 转换时确保勾选"使用封面作为书籍封面" |
| 推送的 EPUB 转 KFX 后丢失 | 推送时用 Calibre Send to Kindle 插件（保留封面） |
| 缩略图未生成 | 断开 USB 后让 Kindle 休眠 30 秒自动生成 |
| MOBI 格式太旧 | 改用 AZW3 |

---

## 五、Kindle 原生支持格式

| 格式 | 直接读取 | 需转换 |
|---|---|---|
| AZW3, KFX, AZW | ✅ | — |
| MOBI, PRC | ✅ | — |
| PDF | ✅ | —（但体验差） |
| EPUB | ❌ | → AZW3 或推送 |
| TXT | ✅ | —（排版差，建议转 EPUB） |
| HTML, DOCX | ❌ | → AZW3 或 EPUB |
| CBR, CBZ | ❌ | → PDF 或 MOBI（用 Kindle Comic Converter） |
| RTF | ✅ | — |
| JPEG, PNG, GIF | ✅ | —（图片查看器） |

---

## 六、关键数字

| 指标 | 值 |
|---|---|
| KPW5 屏幕分辨率 | 1072 × 1448 (300 PPI) |
| Send to Kindle 单文件上限 | **50 MB** |
| Kindle 邮箱推送附件数上限 | 25 个 |
| 可信任发件人邮箱数 | 20 个 |
| USB 模式充电规格 | 5V/1A，充满约 2.5h |
| KPW5 电池容量 | 1700 mAh |
| 官方标称续航 | 10 周（每天 30 分钟，Wi-Fi 关，亮度 13） |
| 存储可用空间 | 8GB 版 ≈6.2GB，16GB 版 ≈13GB |
