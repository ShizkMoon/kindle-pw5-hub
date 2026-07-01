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

## 文档

- [完整最佳实践指南](docs/guide.md) —— 从开箱设置到越狱 KOReader
- [Calibre 自动化方案](docs/calibre-automation.md) —— Agent 操控 Calibre 的接口与工作流
- [格式速查表](docs/format-cheatsheet.md) —— 格式选型、转换参数、推送对比
- [AI 集成方案蓝图](docs/ai-integration-blueprint.md) —— 将 KPW5 纳入 dorm-workstation 多模型多 Agent 体系的全景设计

## 目录结构

```
kindle-pw5-hub/
├── README.md
├── docs/
│   ├── guide.md                  # 完整优化指南
│   ├── calibre-automation.md     # Calibre + Agent 集成方案
│   ├── format-cheatsheet.md      # 格式与转换速查
│   └── ai-integration-blueprint.md  # AI 集成蓝图（× dorm-workstation）
└── scripts/                      # 自动化脚本（待实现）
```

## 快速决策

- **传书**：USB 用 AZW3，云端推送用 EPUB
- **工具**：Calibre 是必装桌面核心，CLI 对 Agent 友好
- **越狱**：固件 < 5.18.1 可用 WinterBreak，装 KOReader 获得 PDF 重排 + 阅读统计
- **续航**：开飞行模式是最大省电手段，亮度 8-10 足够白天用

## 参考来源

- [书伴 bookfere.com](https://bookfere.com/novice)
- [KOReader 用户指南](https://koreader.rocks/user_guide/zh_Hans.html)
- [iFixit KPW5 拆解](https://www.ifixit.com/Device/Kindle_Paperwhite_11th_Generation)
