# 归档：KPW5 × AI 自主管线架构方案

归档时间：2026-07-06

这是早期“去亚马逊化阅读系统”的总体蓝图。方向仍然对：EPUB、KOReader、WebDAV、本地可控、AI 辅助。但很多组件当时只是设想，现在已经被更小、更稳的 Hermes intake 取代。当前架构见 [docs/architecture.md](../docs/architecture.md)。

## 当时的核心想法

```text
Kindle / KOReader
  <-> WebDAV / Syncthing
  <-> PC / Cloud Agent
  <-> Calibre / MCP / AI
```

目标是减少对亚马逊云的依赖，把书籍处理、传输、阅读状态和标注处理都放回自己能控制的基础设施里。

## 已经落地为 Hermes 的部分

- EPUB-only 输出。
- WebDAV `/books` 发布。
- KOReader 作为主阅读端。
- 本地 TXT/EPUB intake。
- 每本书的 manifest 和 reports。
- 旧书 append-safe / metadata-safe 检查。
- 风险更新进入 `.pending/`。
- 元数据增强框架。

## 被重写的部分

| 旧设想 | 当前做法 |
|---|---|
| Calibre 是中心母库 | WebDAV 远端 EPUB + `.hermes.json` 是当前发布母本 |
| MCP-first | 先实现 Python 管线，再考虑 MCP 封装 |
| 多模型路由已接入 | 当前只提供 provider/reasoner 接口，真实 LLM 尚未接入 CLI |
| KOReader bridge 直接管理设备 | 当前不直接改 Kindle 本地状态 |
| 标注每日自动合成 | 仍是后续独立管线 |

## 仍值得保留的原则

### 本地可审计

每次运行都应该有本地报告。即使远端挂了，用户也能知道发生了什么。

### 工具边界清楚

EPUB 处理、元数据搜索、LLM 裁决、WebDAV 发布、KOReader 状态迁移应该是独立模块。不要让一个大模型调用同时做所有事情。

### 旧书优先保护

已经读过的书比新生成的候选文件更重要。不能确定安全，就 pending。

## 后续迁移路线

1. 把当前 Python API 封装为 `hermes-books` MCP。
2. 增加真实 metadata provider。
3. 增加 LLM reasoner，并强制 JSON schema。
4. 增加正文清洗报告层。
5. 单独设计 KOReader sidecar migration。

这份归档不再作为实施计划，只保留作为设计脉络。
