# Kindle Paperwhite 5 Hub

KPW5（第 11 代）优化与自动化管理知识库。

## 设备

| 项目 | 规格 |
|---|---|
| 屏幕 | 6.8" E Ink Carta 1200, 300 PPI (1072×1448) |
| 前光 | 17 颗 LED，支持暖光色温 |
| 接口 | USB-C |
| 存储 | 8GB / 16GB（Signature 版 32GB） |
| 电池 | 1700 mAh |
| 防水 | IPX8 |
| 型号 | M2L3EK / M2L4EK |

## 架构原则（已确认）

- **Kindle 已越狱**，不使用任何亚马逊云服务（无 Whispersync、无 Send to Kindle、无外部云标注同步）
- **以 dorm-workstation 的 AI 管线为主**（New API + 5 模型路由 + MCP 生态），Kindle 作为知识摄入终端接入
- **全链路本地/自建**：WebDAV server → KOReader 同步，Calibre + calibremcp → Agent 书库管理，Sigil → EPUB 自动化
- **月费 ~¥3-4**（纯 AI API 用量，无限外部服务订阅）

## 文档

- [完整最佳实践指南](docs/guide.md) —— 从开箱设置到越狱 KOReader
- [Calibre 自动化方案](docs/calibre-automation.md) —— Agent 操控 Calibre 的接口与工作流
- [格式速查表](docs/format-cheatsheet.md) —— 格式选型、转换参数、推送对比
- [AI 集成方案蓝图](docs/ai-integration-blueprint.md) —— KPW5 × dorm-workstation 全景设计（Calibre AI / MCP / 翻译管线）
- [自主管线架构方案](docs/local-first-architecture.md) —— **当前采纳方案**：去亚马逊化，本地优先，AI 管线为骨干

## 目录结构

```
kindle-pw5-hub/
├── README.md
├── docs/
│   ├── guide.md                        # 完整优化指南
│   ├── calibre-automation.md           # Calibre + Agent 集成方案
│   ├── format-cheatsheet.md            # 格式与转换速查
│   ├── ai-integration-blueprint.md     # AI 集成蓝图（Calibre AI / MCP / 翻译管线）
│   └── local-first-architecture.md     # ★ 自主管线架构（当前采纳方案）
└── scripts/                            # 自动化脚本（待实现）
```

## 快速决策

- **传书**：WebDAV / Calibre Wi-Fi / USB。不推送到 Kindle 邮箱
- **工具**：Calibre + calibremcp (21 MCP 工具) 是 Agent 操作书库的基础
- **同步**：KOReader Syncery (Syncthing) + HighlightSync (WebDAV)
- **越狱**：固件 < 5.18.1 用 WinterBreak → 装 KOReader + 全套插件
- **元数据**：多源 API 查询 + AI 交叉验证 → calibremcp 自动写入
- **排版修复**：Sigil Automate List + Python 插件 → Agent 驱动批量处理
- **续航**：飞行模式 + 亮度 8-10

## 参考来源

- [书伴 bookfere.com](https://bookfere.com/novice)
- [KOReader 用户指南](https://koreader.rocks/user_guide/zh_Hans.html)
- [calibremcp (21-tool MCP Server)](https://github.com/sandraschi/calibremcp)
- [Sigil Plugin Framework](https://fossies.org/linux/Sigil/docs/Sigil_Plugin_Framework_rev14.epub)
- [iFixit KPW5 拆解](https://www.ifixit.com/Device/Kindle_Paperwhite_11th_Generation)
