# Kindle Paperwhite 5 Hub

KPW5（第 11 代）× dorm-workstation AI 体系集成工程。

## 决策

| 决策 | 状态 |
|---|---|
| 越狱 | ✅ WinterBreak，KOReader 主力，原生系统备份 |
| 格式 | **EPUB 唯一**，任何输入 → EPUB → KOReader |
| 亚马逊云 | ❌ 不使用（无 Whispersync / Send to Kindle） |
| AI 骨干 | New API + 5 模型路由 + MCP |
| 运行平台 | ☁️ 云服务器 (2C2G) + 💻 Windows 本机 |
| 月费 | ~¥3-4（纯 AI API） |

## 文档

| 文档 | 用途 |
|---|---|
| [System Architecture](docs/architecture.md) | 系统拓扑、数据流、MCP 矩阵、部署清单 |
| [EPUB Pipeline](docs/pipeline.md) | 处理管线标准：输入矩阵、TXT 专项、CSS 规范、验证 |
| [Kindle Setup](docs/kindle-setup.md) | 越狱 → KOReader → 插件 → 配置 |
| [MCP Specifications](docs/mcp-specs.md) | 3 组 MCP Server 工具定义 |

## 脚本

```
scripts/
├── txt2epub/
│   └── pipeline.py          TXT → EPUB 全自动管线
├── epub_fix/
│   ├── validate.py          EPUBCheck 包装器
│   └── fix_common.py        常见 EPUB 结构修复
├── metadata/
│   └── enrich.py            ISBN 元数据多源查询
└── koreader_sync/
    └── sync_highlights.py   KOReader 标注同步 + 导出
```

## 快速开始

```powershell
# TXT → EPUB
python scripts/txt2epub/pipeline.py novel.txt -t "书名" -a "作者"

# EPUB 验证
python scripts/epub_fix/validate.py book.epub

# 修复常见问题
python scripts/epub_fix/fix_common.py book.epub --fix all --dry-run

# 元数据查询
python scripts/metadata/enrich.py --isbn 9787544270878
```

## 依赖

```
pip install ebooklib charset-normalizer opencc
```

Calibre CLI (`ebook-convert`, `calibredb`) 需单独安装：`scoop install calibre`

## 参考

- [书伴 bookfere.com](https://bookfere.com/novice)
- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [calibremcp](https://github.com/sandraschi/calibremcp)
- [EPUBCheck (W3C)](https://github.com/w3c/epubcheck)
- [Sigil Plugin Framework](https://github.com/Sigil-Ebook/Sigil/blob/master/docs/Sigil_Plugin_Framework_rev15.epub)
- [iFixit KPW5](https://www.ifixit.com/Device/Kindle_Paperwhite_11th_Generation)
