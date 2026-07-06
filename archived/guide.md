# 归档：Kindle Paperwhite 5 优化指南

归档时间：2026-07-06

这是一份偏通用的 Kindle PW5 使用指南，包含原生 Kindle、AZW3、Send to Kindle、Calibre 等内容。当前项目已经转向 KOReader + EPUB + WebDAV + Hermes，因此本文不再作为主手册。当前设备配置见 [docs/kindle-setup.md](../docs/kindle-setup.md)。

## 仍然可参考

- KPW5 的硬件特性。
- 亮度、暖光、刷新频率等阅读设置。
- 字体选择。
- 电池和维护建议。
- KOReader 基础操作。

## 已不作为当前主线

- AZW3 作为首选输出。
- Send to Kindle。
- Whispersync。
- Kindle 原生标注作为主知识来源。
- Calibre 邮件推送。

Hermes 当前只把 EPUB 放到 WebDAV，让 KOReader 读取。

## 当前推荐简版

### 设备

KPW5 仍然适合作为主力长读设备。屏幕、重量、续航和暖光都足够稳定。只要 KOReader 可用，就没有必要为了 Hermes 工作流换设备。

### 阅读器

推荐 KOReader。Kindle 原生系统可以保留作备用，但它的阅读状态和 KOReader 不互通。

### 格式

只把 EPUB 作为主格式。其他格式先转换成 EPUB，再进入 Hermes。

### 传书

使用 KOReader Cloud Storage 访问 WebDAV `/books`。不要把 Send to Kindle 当主路径。

### 旧书更新

旧书更新交给 Hermes 判断。`published` 才代表已经安全发布；`.pending` 代表需要人工看原因。

## 基础设置备忘

| 项 | 建议 |
|---|---|
| 夜间暖光 | 开启，按个人习惯 |
| 飞行模式 | 阅读时可开启，减少干扰和耗电 |
| 页面刷新 | 残影明显时每页刷新 |
| 字体 | 中文长读优先宋体/楷体类 |
| KOReader 字体目录 | `koreader/fonts/` |

## 历史价值

这份文档可以留作“没有 Hermes 时如何配置 Kindle”的参考。进入当前项目语境后，应优先阅读：

- [docs/kindle-setup.md](../docs/kindle-setup.md)
- [docs/pipeline.md](../docs/pipeline.md)
- [README.md](../README.md)
