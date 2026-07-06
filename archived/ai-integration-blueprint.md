# 归档：AI 集成蓝图

归档时间：2026-07-06

这是早期把 AI 全面接入 Kindle 工作流的蓝图。它包含元数据补全、RAG、标注合成、IM 控制、Calibre 自动化等愿景。当前已落地的是更小的 Hermes intake 和元数据增强框架；其余部分仍需分阶段实现。

## 当前已经落地

- 本地 TXT/EPUB intake。
- 质量报告。
- WebDAV 发布。
- 旧书安全更新判断。
- `.pending/` 风险候选。
- provider/reasoner 形式的元数据增强接口。
- OPF metadata 和封面写入。
- KOReader `hashdocsettings` 保护。

## 尚未落地

- 真实联网 metadata provider。
- LLM reasoner。
- 章节级正文清洗。
- 广告自动删除。
- 缺章检测和正文补全。
- 插图搜索与插入。
- KOReader 标注自动合成知识库。
- IM 命令入口。
- MCP server 完整封装。

## 新的 AI 接入原则

### 元数据

AI 可以参与搜索结果融合，但必须返回结构化 decision：

```json
{
  "field": "series",
  "old_value": "",
  "new_value": "系列名",
  "action": "apply",
  "confidence": 0.94,
  "evidence_ids": ["bookwalker-1"],
  "reason": "出版社页面与书店页面一致"
}
```

没有 evidence URL、置信度不足或身份冲突时，不自动写入。

### 正文清洗

AI 先写报告，不直接改正文：

- 疑似广告。
- 疑似缺章。
- 疑似章节错位。
- 异常重复段落。
- 疑似 OCR 或编码错误。

Hermes 再把可解释的修复转成 patch，应用后重新 inspect。

### 标注处理

标注合成应独立于 book intake。读取 KOReader 导出文件后，可以做：

- 去重。
- 按书和章节归档。
- 生成摘要。
- 提取主题。
- 写入本地笔记。

但这不应影响 EPUB 发布链路。

## 为什么归档

旧蓝图的问题不是方向错，而是把太多层放在同一阶段：Calibre、MCP、IM、大模型、标注、传书、元数据、正文修复都混在一起。Hermes 现在的路线是先把一条窄路径做稳：

```text
TXT/EPUB -> inspect -> metadata -> diff -> WebDAV -> KOReader
```

之后每个 AI 能力都以 provider、reasoner 或 report 阶段接入。

## 仍可参考

- 多模型路由的思想。
- 标注进入知识库的目标。
- 元数据多源交叉验证。
- 用 IM 或 MCP 触发工作流。

这些会作为后续设计来源，而不是当前事实。
