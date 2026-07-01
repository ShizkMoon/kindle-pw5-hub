# KPW5 × AI 自主管线架构方案

> **前提**：Kindle 已越狱（✅ 已确认），**不使用任何亚马逊云服务**（Whispersync、Send to Kindle、云端标注同步全部不可用）。
> **原则**：以 dorm-workstation 的 New API + 5 模型路由 + MCP 生态为骨干，Kindle 作为知识摄入硬件终端接入。
> **阅读器**：KOReader 主力 + Kindle 原生系统保留备用。
> 这是架构方案，不是实施计划。

---

## 一、总览：去亚马逊化的自主体系

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          User's AI Infrastructure                             │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                      New API (API Gateway)                             │    │
│  │     ZhiPu GLM │ DeepSeek │ MiniMax │ Kimi │ Anthropic (via OpenRouter) │    │
│  └───────────────────────────┬──────────────────────────────────────────┘    │
│                              │                                                │
│         ┌────────────────────┼────────────────────┐                          │
│         ▼                    ▼                    ▼                          │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐                 │
│  │  calibremcp  │   │  Custom MCP  │   │  KOReader Bridge │                 │
│  │  (21 tools)  │   │  Servers     │   │  (KOReader sync  │                 │
│  │  Calibre     │   │  (metadata,  │   │   plugins)       │                 │
│  │  Library Mgt │   │   Sigil, DL) │   │                  │                 │
│  └──────┬───────┘   └──────┬───────┘   └────────┬─────────┘                 │
│         │                  │                     │                            │
│         ▼                  ▼                     ▼                            │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐                 │
│  │   Calibre    │   │    Sigil     │   │  Kindle PW5       │                │
│  │  (本地书库)   │   │  (EPUB 编辑) │   │  (已越狱+KOReader) │                │
│  └──────┬───────┘   └──────────────┘   └────────┬─────────┘                 │
│         │                                       │                            │
│         │                    ┌──────────────────┘                            │
│         │                    │                                               │
│         ▼                    ▼                                               │
│  ┌──────────────────────────────────────────────────────────────┐           │
│  │                     WebDAV Server (Docker)                     │           │
│  │  用途：KOReader ↔ PC 双向传书、同步标注、中转笔记                 │           │
│  │  地址：已在 dorm-workstation deploy 中有 Radicale，可复用同一 Nginx  │           │
│  └──────────────────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、三层架构设计

### 第 1 层：Kindle 终端（KOReader）

越狱后的 Kindle 以 KOReader 为主力阅读器。**不依赖任何亚马逊云服务**。

**传书方式（去亚马逊化）：**

| 方式 | 技术 | 适用场景 |
|---|---|---|
| **Wi-Fi WebDAV 下载** | KOReader Cloud Storage → WebDAV | 日常传书主力 |
| **USB 拷贝** | 直接写入 `documents/` 或 KOReader 目录 | 批量导入、大文件 |
| **Calibre Wi-Fi 推送** | Calibre Content Server → KOReader Calibre 插件 | 从 PC 书库直传 |
| **File Browser** | Kindle 浏览器 → 拖拽上传 | 临时快速传书 |
| **SSH/SFTP** | KOReader 内建 SSH Server | 高级用户远程管理 |
| **Syncthing 自动同步** | KOSyncthing+ 插件 | 多设备自动同步 |

**标注与进度同步（去亚马逊化）：**

| 插件 | 功能 | 传输 |
|---|---|---|
| **Syncery** | 阅读进度 + 标注 + 书签跨设备同步 | Syncthing 或 WebDAV |
| **AnnotationSync** | 标注自动同步 + JSON 存储 | WebDAV / Dropbox / FTP |
| **HighlightSync** | 标注合并 + Markdown 导出 | WebDAV / Dropbox + Tailscale |
| **KOReader 内置导出** | 按书导出为 JSON / Markdown / MyClippings 格式 | 文件系统 → WebDAV 上传 |

**推荐方案**：**Syncery (Syncthing) + HighlightSync (WebDAV) + 手动导出 Markdown**

```
Kindle KOReader
    │
    ├── Syncery → Syncthing → PC (实时同步进度/标注)
    │
    ├── HighlightSync → WebDAV (localhost:8181, Nginx 反代)
    │     └── Agent 定期拉取 JSON → 处理 → local knowledge store
    │
    └── 手动导出 Markdown → WebDAV 上传
          └── Agent 监控目录 → 自动导入 local note directory
```

### 第 2 层：PC 中枢（Calibre + MCP + Sigil）

#### 2.1 Calibre + calibremcp

Calibre 作为本地书库管理中心，通过 calibremcp (FastMCP 3.2) 暴露 21 个 MCP 工具给 Agent：

```
Agent (Claude Code / CherryStudio / OpenCode)
    │
    ▼ MCP Protocol
calibremcp
    │
    ├── 语义搜索 (LanceDB)
    ├── 全文搜索 (Calibre FTS)
    ├── 元数据管理 (批量 AI 补全)
    ├── 格式转换 (ebook-convert 包装)
    ├── 书库浏览 & 导出
    └── 阅读进度追踪
```

#### 2.2 EPUB 格式自动化处理

**KOReader 只读 EPUB**——KFX 无用。全链路统一为 EPUB：**任何输入格式 → EPUB → KOReader**。

##### 输入格式覆盖

| 输入格式 | 转换工具 | 典型场景 |
|---|---|---|
| **EPUB** (已有) | EPUBCheck → ebooklib 修复 | 下载/购买的成品电子书 |
| **TXT** (质量差) | ebook-convert 启发式处理 + Agent 后处理 | 网文、自整理文本 |
| **MOBI / AZW3** | ebook-convert → EPUB | 旧 Kindle 格式迁移 |
| **PDF** (文字型) | ebook-convert / KOReader 原生重排 | 论文、教材 |
| **PDF** (扫描版) | OCR → EPUB | 扫描书（低频，人工处理为主） |
| **HTML / DOCX** | ebook-convert → EPUB | 网页文章、Word 文档 |

##### 工具矩阵

| 工具 | 类型 | 运行位置 | 可信度 |
|---|---|---|---|
| **Calibre `ebook-convert`** | CLI | ☁️ 云服务器 / 💻 Windows | ⭐⭐⭐⭐⭐ |
| **EPUBCheck** | Java CLI (W3C 官方) | ☁️ 云服务器 / 💻 Windows | ⭐⭐⭐⭐⭐ |
| **ebooklib** | Python 库 | ☁️ 云服务器 / 💻 Windows | ⭐⭐⭐⭐⭐ |
| **Sigil Automate Lists** | GUI 批量操作链 | 💻 Windows only | ⭐⭐⭐⭐⭐ (官方) |

##### 各工具职责

```
[1] ebook-convert → EPUB 标准化
    任何输入 → EPUB。统一编码 UTF-8、移除垃圾样式、基础排版
    运行: ☁️ 云服务器 或 💻 Windows
    命令: ebook-convert input.xxx output.epub [参数]

[2] EPUBCheck → 验证
    W3C 标准 EPUB 验证，检测格式错误
    运行: ☁️ 云服务器 或 💻 Windows

[3] ebooklib → 程序化修复
    移除冗余 CSS、补全 OPF manifest、修复断链、统一字体引用
    运行: ☁️ 云服务器 或 💻 Windows

[4] Sigil Automate Lists → 深度修复 (GUI)
    CSS 深度清理、ToC 重建、结构重组等需要 GUI 预览的操作
    运行: 💻 Windows GUI only
```

##### TXT（低质量网文）→ EPUB 专项处理

网文 TXT 的典型问题：无章节结构、编码混乱、多余换行、无元数据、无封面。

```
[1] 编码检测与标准化
    Agent 检测文件编码 → 统一转换为 UTF-8

[2] 章节结构识别 (Agent + 规则引擎)
    ├── 正则匹配: 第X章、Chapter X、Volume X 等模式
    ├── AI 辅助: 规则失败时，Agent 分析文本结构推断章节边界
    └── 生成 ToC → 写入 EPUB spine

[3] 排版清理
    ├── 移除多余空行/换行
    ├── 统一段落缩进
    ├── 修复半角全角混排
    └── 可选: 繁简转换 (OpenCC)

[4] 元数据生成
    ├── 书名: 从文件名或正文首行提取
    ├── 作者: 从文件名或正文提取
    └── Agent 调元数据管线 → 自动补全

[5] EPUB 组装
    ebook-convert cleaned.txt output.epub
    --formatting-type heuristic
    --chapter-mark pagebreak
    --level1-toc //h:h1
    --base-font-size 12
```

> **云服务器 vs Windows**：TXT→EPUB 全流程可在 ☁️ 云服务器上完成（CLI + Python 脚本），无需 Windows GUI。完成后通过 WebDAV 直接推送到 KOReader。

### 第 3 层：AI 增强（Agent 自动处理）

#### 3.1 元数据自动化补全与验证

**数据流：**

```
新书导入 Calibre
    │
    ▼
Agent 检测到缺少元数据
    │
    ├── ISBN 存在？
    │   ├── 是 → 多源交叉验证
    │   │   ├── Google Books API (免费)
    │   │   ├── Open Library API (免费)
    │   │   ├── Goodreads 爬取 (评分+标签)
    │   │   ├── Library of Congress (权威日期/页数)
    │   │   ├── Amazon 爬取 (封面+描述)
    │   │   └── WikiData (规范化出版商/系列)
    │   │
    │   └── 否 → 标题+作者搜索
    │       ├── Google Books / Open Library 模糊搜索
    │       └── ISBN 回收 → 走上面 ISBN 流程
    │
    ▼
AI 冲突解决（多源数据不一致时）
    │
    ├── 元数据字段逐一对比各源
    ├── AI 判断最可信值（考虑源权威性 + 一致性）
    ├── 低置信度标记 → 人工审核
    └── 高置信度自动写入
    │
    ▼
calibremcp batch_enrich → 写入 Calibre 数据库
```

**作为 MCP 工具链：**

```python
# 伪代码：Agent 调用的元数据补全 MCP 工具
calibre_enrich_book_metadata(book_id=42)
    → 自动检测 ISBN/ASIN
    → 并行查询 Google Books + Open Library + Goodreads
    → AI 合并冲突字段
    → 写入 Calibre
    → 返回变更摘要
```

#### 3.2 知识管线（KOReader → Agent → local store）

AGENT 处理的替代方案：

```
Kindle KOReader
    │
    │  阅读中标注
    ▼
KOReader 内置: 标注 → <book>.sdr/metadata.epub.lua
    │
    │  HighlightSync 插件: 自动 merge + sync → WebDAV
    ▼
PC WebDAV Server (Docker, localhost:8181)
    │  /koreader/highlights/<book_hash>.json
    │
    │  Agent Cron 或 FileSystemWatcher: 检测新标注文件
    ▼
Agent (Claude Code via MCP)
    │
    ├── Step 1: 解析 JSON → 提取标注文本 + 元数据
    ├── Step 2: 两阶段 AI 处理
    │   ├── Phase 1 (GLM-4.7): 去重、筛选高质量标注、格式整理
    │   └── Phase 2 (GLM-5.2): 深度综合、跨书连接、生成原子笔记
    ├── Step 3: 写入 local knowledge store
    │   ├── 原始标注文件 → raw_highlights/ (Markdown)
    │   ├── 原子笔记 → atomic_notes/ ([[wikilinks]])
    │   └── MOC 更新 → maps_of_content/ (地图更新)
    └── Step 4: 清理 WebDAV 已处理文件
```

#### 3.3 多模型路由（读书场景细化）

| 任务 | 模型 | 原因 | 月成本估算 |
|---|---|---|---|
| EPUB 格式检测与修复建议 | GLM-4.7 | 结构化任务，轻量即可 | ~¥0.1 |
| 元数据多源交叉验证 | GLM-4.7 + 规则引擎 | 规则为主 AI 为辅 | ~¥0.1 |
| 标注质量筛选/聚类 | DeepSeek V3 | 文本分类任务，成本低 | ~¥0.05/周 |
| 深度标注综合 → 原子笔记 | GLM-5.2 | 需要推理+创意 | ~¥0.3/本 |
| 跨书概念综合 (L3+) | GLM-5.2 (非高峰) | 最重推理任务 | ~¥0.5/次 |
| 书籍推荐/相似书 | MiniMax M3 | 对话型任务 | ~¥0.01/次 |
| 封面 OCR / 视觉元数据 | Kimi K2.7 / GLM-4.7 | 多模态视觉 | ~¥0.02/张 |

---

## 三、完整工作流设计

### 工作流 A：新书入库全自动处理

```
1. 获取 EPUB (下载/购买/自制)
       │
2. Agent 检测到新文件 (FileSystemWatcher on D:\Downloads\Books\)
       │
3. ebook-convert EPUB → EPUB 标准化
   ├── 统一编码为 UTF-8
   ├── 移除内嵌垃圾样式
   └── 标准化基础排版参数
       │ (可运行于 ☁️ 云服务器)
       │
4. EPUBCheck 验证 → 检测格式问题
       │ (可运行于 ☁️ 云服务器)
       │
5. Agent 元数据补全
   ├── ISBN 查找 → 多源交叉验证 → AI 冲突解决
   ├── 封面下载 (最高分辨率)
   └── 写入 Calibre (calibremcp batch_enrich)
       │ (可运行于 ☁️ 云服务器)
       │
6. EPUB 修复 (根据 EPUBCheck 结果)
   ├── 轻度问题 → ebooklib Python 脚本自动修复 (☁️/💻)
   └── 复杂问题 → Sigil Automate List 手工触发 (💻 GUI only)
       │
7. Calibre 入库 (EPUB 唯一格式)
       │
8. 推送到 Kindle
   ├── EPUB → WebDAV 上传 → KOReader Cloud Storage 下载 (Wi-Fi)
   └── 或 USB 拷贝到 documents/
       │
9. Agent 通知: "《XXX》已入库并推送至 Kindle ✓"
    (Hermes 可通过 WeChat 通知)
```

### 工作流 B：阅读后知识提取

```
1. 在 Kindle KOReader 上阅读 + 标注
       │
2. HighlightSync 自动同步标注到 WebDAV (Wi-Fi 环境下)
       │
3. Agent 定时 (每日 22:00) 检查 WebDAV 新标注
       │
4. Phase 1 (GLM-4.7): 解析 → 去重 → 筛选
       │
5. Phase 2 (GLM-5.2): 综合 → 原子笔记生成
   ├── 标注按主题聚类
   ├── 提取核心概念 → 创建 Zettelkasten 笔记
   ├── 与已有笔记做 [[双向链接]]
   └── 识别与已读书籍的联系 (Convergence/Divergence)
       │
6. 写入 local knowledge store
   ├── raw_highlights/ 原始标注 (保留溯源)
   ├── atomic_notes/ 原子笔记
   └── 更新 MOC
       │
7. Hermes 晨间简报: "昨日阅读《XXX》3章，新增标注12条，生成4条新笔记"
```

### 工作流 C：书籍格式修复（按需触发）

```
Agent 收到: "修复 D:\Books\messy.epub 的排版"

1. EPUBCheck → 列出所有格式问题
2. Agent 分析问题清单 → 生成修复策略
3. 执行修复:
   ├── CSS 清理: AI 审查 CSS → 识别冗余/冲突规则 → 生成清理版本
   ├── HTML 修复: 检测断链、乱码、缺失属性 → 自动修复
   ├── 字体处理: 检测嵌入字体问题 → 子集化或移除
   ├── 结构修复: 重建 ToC、补全 OPF manifest
   └── 统一排版: 标准化段落样式、移除行内样式
4. EPUBCheck 复验 ✓
5. 输出修复报告: "修复了 15 个 CSS 冲突，3 个断链，重新生成了目录"
```

---

## 四、MCP 服务矩阵

### 4.1 已有（可直接部署）

| MCP Server | 工具数 | 职责 | 部署位置 |
|---|---|---|---|
| **calibremcp** (sandraschi) | 21 | Calibre 书库全管理 + AI RAG | Windows 本机 |
| **access-calibre** | 8 | Calibre 书库浏览 + 章节读取 | Windows 本机 |

### 4.2 需开发（dorm-workstation 体系内）

| MCP Server | 工具数 | 职责 | 优先级 |
|---|---|---|---|
| **koreader-bridge** | ~6 | KOReader 标注拉取、进度查询、书籍推送 | P1 |
| **sigil-automation** | ~4 | EPUB 格式检测、修复脚本生成、EPUBCheck 封装 | P1 |
| **metadata-enricher** | ~5 | 多源元数据查询、交叉验证、AI 合并 | P1 |
| **reading-notes** | ~4 | 标注→原子笔记转换、跨书综合、MOC 更新 | P2 |

### 4.3 koreader-bridge MCP 工具设计（草案）

```python
# KOReader → Agent 桥接
tools = [
    "koreader_list_devices",           # 扫描网络中 KOReader 设备
    "koreader_get_highlights",         # 拉取指定书的标注 (JSON)
    "koreader_get_reading_progress",   # 获取阅读进度
    "koreader_sync_highlights_to_pc",  # 触发 WebDAV 同步
    "koreader_push_book",              # 推送书籍到 KOReader (WebDAV/SFTP)
    "koreader_get_stats",             # 获取阅读统计 (时长/速度)
]
```

### 4.4 metadata-enricher MCP 工具设计（草案）

```python
tools = [
    "isbn_lookup",                     # ISBN → 多源元数据 (Google/OL/Goodreads)
    "search_book_metadata",            # 标题+作者 → 模糊搜索
    "cross_validate_metadata",         # 多源数据交叉验证 + AI 冲突解决
    "enrich_calibre_book",             # 单书元数据补全并写入 Calibre
    "batch_enrich_missing",            # 批量补全书库中缺少元数据的书
]
```

---

## 五、WebDAV 服务设计

复用 dorm-workstation 已有的 Docker + Nginx 基础设施，新增 WebDAV 容器：

```yaml
# 追加到 deploy/docker-compose.yml
webdav:
  image: bytemark/webdav:latest
  ports: "127.0.0.1:8181:80"
  environment:
    AUTH_TYPE: Digest
    USERNAME: koreader
    PASSWORD: ${WEBDAV_PASSWORD}
  volumes:
    - ./webdav/data:/var/lib/dav/data
    - ./webdav/config:/etc/nginx
  security_opt:
    - no-new-privileges:true
  read_only: false
```

Nginx 追加 location：

```nginx
# 追加到 deploy/nginx/new-api.conf
location /webdav/ {
    proxy_pass http://127.0.0.1:8181/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    client_max_body_size 100m;  # 电子书可能很大
}
```

KOReader 端配置 Cloud Storage → WebDAV：
- URL: `https://<your-domain>/webdav/`
- Username: `koreader`
- Password: `<WEBDAV_PASSWORD>`
- Start folder: `/koreader/`

---

## 六、成本概算

### 一次性

| 项目 | 费用 |
|---|---|
| WebDAV 容器 | ¥0（复用已有 2C2G 服务器） |
| Sigil | ¥0（开源） |
| Calibre + calibremcp | ¥0（开源） |
| KOReader + 插件 | ¥0（开源） |

### 月费（AI API 用量）

| 操作 | 频率 | 模型 | 月成本 |
|---|---|---|---|
| 新书元数据补全 | ~10 本/月 | GLM-4.7 | ~¥0.5 |
| EPUB 格式修复 (AI 审查) | ~5 本/月 | GLM-4.7 | ~¥0.25 |
| 标注 → 原子笔记 | ~3 本/月 | GLM-5.2 | ~¥1 |
| 跨书综合 (L3+) | ~2 次/月 | GLM-5.2 | ~¥1 |
| 封面 OCR | ~10 张/月 | Kimi K2.7 | ~¥0.2 |
| 日常推荐/搜索 | ~30 次/月 | MiniMax M3 | ~¥0.3 |
| **合计** | | | **~¥3-4/月** |

对比 external cloud sync services：**省掉了 ~$8/月 (≈¥58) 的外部订阅费用**，以 Agent 处理替代——成本更低，且完全自主可控。

---

## 七、与之前方案的关键差异

| 维度 | 之前方案（有亚马逊云） | 现在方案（去亚马逊化） |
|---|---|---|
| **Kindle 标注同步** | Amazon cloud → third-party sync → cloud vault | KOReader → WebDAV → Agent → local store |
| **传书** | Send to Kindle 推送 | WebDAV / Calibre Wi-Fi / USB |
| **多设备进度同步** | Whispersync | Syncery + Syncthing |
| **标注处理** | 外部服务聚合 + AI | Agent 直接解析 JSON + AI 处理 |
| **月费** | ~¥61 (external sync $8 + AI ¥3-5) | ~¥3-4 (纯 AI) |
| **隐私** | 标注经外部云端 | 标注经自家 WebDAV，全链路本机/自建 |
| **依赖** | Amazon + external sync 两项外部服务 | 零外部服务依赖 |

---

## 八、实施优先级

| 优先级 | 项目 | 投入 | 说明 |
|---|---|---|---|
| **P0** | KPW5 越狱 + KOReader 安装 | 30 分钟 | ✅ 已确认，WinterBreak 方案 |
| **P0** | Calibre + calibremcp 部署 | 30 分钟 | Agent 操作书库的基础 |
| **P1** | WebDAV 容器部署 | 15 分钟 | KOReader ↔ PC 桥梁 |
| **P1** | KOReader Cloud Storage → WebDAV 配置 | 10 分钟 | 打通传书管道 |
| **P1** | metadata-enricher MCP 开发 | 1-2 小时 | 元数据自动化 |
| **P1** | EPUB 自动化修复管线 (ebooklib + EPUBCheck) | 1-2 小时 | 格式自动修复 (☁️/💻) |
| **P1** | Sigil Automate List 配置 (复杂修复) | 30 分钟 | GUI 批量修复链 (💻 only) |
| **P1** | KOReader 标注 → Markdown 导出管线 | 15 分钟 | 替代外部云同步服务 |
| **P2** | koreader-bridge MCP 开发 | 2-3 小时 | Agent 直连 KOReader |
| **P2** | 标注 → 原子笔记 Agent 工作流 | 1-2 小时 | 知识提取自动化 |
| **P2** | HighlightSync / Syncery 配置 | 20 分钟 | 多设备同步 |
| **P3** | Hermes Kindle 命令集成 | 1 小时 | IM 控制阅读 |
| **P3** | 跨书综合(L3+)工作流 | 2-3 小时 | 知识体系化 |

---

## 参考

- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [Sigil 官方用户指南](https://github.com/Sigil-Ebook/sigil-user-guide) — [在线版](https://sigil-ebook.com/sigil-user-guide)
- [Sigil Plugin Framework (官方)](https://github.com/Sigil-Ebook/Sigil/blob/master/docs/Sigil_Plugin_Framework_rev15.epub)
- [EPUBCheck (W3C 官方 EPUB 验证器)](https://github.com/w3c/epubcheck)
- [ebooklib (Python EPUB 库)](https://github.com/aerkalov/ebooklib)
- [calibremcp (sandraschi)](https://github.com/sandraschi/calibremcp)
- [Syncery.koplugin](https://github.com/d0nizam/syncery.koplugin)
- [HighlightSync.koplugin](https://github.com/KarimMoustamid/highlightsync.koplugin)
- [KOSyncthing+](https://github.com/d0nizam/kosyncthing_plus.koplugin)
- [Calibre-Web-Automated Metadata System](https://github.com/crocodilestick/Calibre-Web-Automated)
- [Colibri Metadata Enrichment](https://colibri-hq.org/user-guide/metadata-enrichment)
