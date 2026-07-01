# 我的 Kindle 工作流

> KPW5 (第 11 代) 越狱后 × AI 智能管线，打造个人最舒适的阅读书务体系。
> 任意格式进，精排 EPUB 出，KOReader 阅读，AI 自动处理标注。

## 核心理念

这不是一个"Kindle 使用指南"——这是一套 **AI 驱动的一人书务自动化工程**。我把一切可以交给机器的环节都交给了机器：格式转换、章节识别、元数据补全、CSS 排版、标注合成。我只负责阅读和思考。

## 决策

| 决策 | 状态 |
|---|---|
| 越狱 | ✅ WinterBreak，KOReader 主力阅读器，原生系统保留备份 |
| 格式 | **EPUB 唯一**，任何输入格式 → EPUB 标准化 → KOReader |
| 亚马逊云 | ❌ 不用（无 Whispersync / Send to Kindle） |
| AI 骨干 | New API 网关 + 5 模型智能路由 (GLM-5.2/4.7, DeepSeek V4, MiniMax M3, Kimi K2.7) |
| MCP 生态 | calibremcp (21 工具) 已部署；epub-processor / metadata-enricher / koreader-bridge 规划中 |
| 运行平台 | ☁️ 云服务器 (2C2G Docker) + 💻 Windows 笔记本 |
| 月费 | ~¥3-4（纯 AI API 调用费，其余全开源） |

## 文档

| 文档 | 内容 |
|---|---|
| [系统架构](docs/architecture.md) | 完整工程规格：拓扑、数据流、AI 管线、模型路由、MCP 矩阵、部署清单 |
| [EPUB 处理管线](docs/pipeline.md) | 处理标准：输入矩阵、TXT 网文专项、CSS 规范、验证流程 |
| [Kindle 部署](docs/kindle-setup.md) | 越狱 → KOReader → 插件安装 → 样式配置 |
| [MCP 规格](docs/mcp-specs.md) | 3 组 MCP Server 完整工具定义与接口说明 |
| [阅读在日常节律中的位置](docs/daily-reading-rhythm.md) | Kindle × AI 管线在一天 24 小时里的实际体验 |

## AI 管线工作流

```
📥 源文件 (TXT/网文/其他格式)
      │
      ▼
🤖 AI 格式判定 → ebook-convert 标准化 → EPUB 初稿
      │
      ▼
🤖 AI 章节检测 (GLM-4.7) → 网文自动分章 → 目录生成
      │
      ▼
🤖 AI CSS 审查 (GLM-4.7) → KOReader 优化样式注入
      │
      ▼
🔧 结构修复 → EPUBCheck 验证 → ebooklib 自动修补
      │
      ▼
🤖 AI 元数据补全 → 多源查询 → 交叉验证 → 写入 EPUB
      │
      ▼
📚 Calibre 书库 (EPUB 母本) → WebDAV 推送 → KOReader 下载
      │
      ▼
📖 阅读中: 标注自动回流 → 🤖 AI 合成笔记 → 本地知识库
```

**你只需要两件事**：把文件放进来源目录，在 KOReader 中打开书。剩下的都是自动的。

## 脚本

这 5 个脚本是管线的主力执行者，每个都集成了 AI 调用能力：

```
scripts/
├── txt2epub/
│   └── pipeline.py              网文 TXT → 精排 EPUB
│       · charset-normalizer 编码检测
│       · 正则 + AI (GLM-4.7) 双通道章节识别
│       · OpenCC 简繁转换
│       · KOReader CSS 样式注入
├── epub_fix/
│   ├── validate.py              EPUBCheck 包装，输出结构化报告
│   └── fix_common.py            自动修复 spine/NCX/引用/元数据
├── metadata/
│   └── enrich.py                 ISBN → 豆瓣/Google/OL 查询 → AI 融合写入
└── koreader_sync/
    └── sync_highlights.py       WebDAV 拉取 → AI 去重格式化 → Markdown 输出
```

## 快速开始

### 我的日常使用流程

```powershell
# 1. 把 TXT 网文扔进工作目录，一句命令出 EPUB
python scripts/txt2epub/pipeline.py "D:\Books\新下载的小说.txt" -t "书名" -a "作者"

# 2. 检查生成的 EPUB 是否合规
python scripts/epub_fix/validate.py "D:\Books\书名.epub"

# 3. 如果验证有问题，自动修复（先预演确认再执行）
python scripts/epub_fix/fix_common.py "D:\Books\书名.epub" --fix all --dry-run
python scripts/epub_fix/fix_common.py "D:\Books\书名.epub" --fix all

# 4. 补全元数据（有 ISBN 最好，没有也能搜）
python scripts/metadata/enrich.py --isbn 9787544270878
python scripts/metadata/enrich.py --title "书名" --author "作者"

# 5. 扔进 Calibre，WebDAV 自动同步到 KOReader
# （Calibre 导入 → 书架选中 → WebDAV 上传，本步骤通过 MCP 全自动）

# 6. 在 KOReader 上阅读，标注自动回流
# 每日 22:00 Agent 自动处理，也可手动触发:
python scripts/koreader_sync/sync_highlights.py --pull --export-to "D:\Notes\阅读笔记"
```

### 环境依赖

```powershell
# Python 包
pip install ebooklib charset-normalizer opencc pillow lxml

# Calibre (提供 ebook-convert / calibredb CLI，以及 GUI 管理)
scoop install calibre

# EPUBCheck (W3C EPUB 验证器)
# 从 https://github.com/w3c/epubcheck/releases 下载，解压到 PATH 目录

# MCP 客户端 (二选一)
# - CherryStudio: 图形化 MCP 管理，适合日常使用
# - Claude Code: 终端 MCP 集成，适合开发调试
```

### 环境变量

```powershell
# 在 $env:USERPROFILE\.claude\.env 或系统环境变量中设置:
$env:NEW_API_KEY = "sk-your-key"       # New API 网关密钥
$env:NEW_API_BASE = "https://你的网关地址/v1"
$env:WEBDAV_PASSWORD = "your-password"  # WebDAV 鉴权密码
$env:CALIBRE_LIBRARY = "D:\Calibre 书库"  # Calibre 书库路径
```

## 设备状态

| 设备 | 系统 | 角色 |
|---|---|---|
| Kindle PW5 (第 11 代) | KOReader (越狱) | 主力阅读终端 |
| 云服务器 (2C2G) | Debian + Docker | WebDAV / Calibre CLI / Agent 运行时 |
| Windows 笔记本 | Windows 11 | Calibre GUI / Sigil / 本地开发 |

## 参考

- [书伴 bookfere.com](https://bookfere.com/novice) — Kindle 折腾百科全书
- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [calibremcp](https://github.com/sandraschi/calibremcp) — Calibre MCP Server
- [EPUBCheck (W3C)](https://github.com/w3c/epubcheck)
- [Sigil Plugin Framework](https://github.com/Sigil-Ebook/Sigil/blob/master/docs/Sigil_Plugin_Framework_rev15.epub)
- [OpenCC](https://github.com/BYVoid/OpenCC) — 中文简繁转换
- [WinterBreak](https://kindlemodding.org/) — KPW5 越狱方案
- [iFixit KPW5](https://www.ifixit.com/Device/Kindle_Paperwhite_11th_Generation)
