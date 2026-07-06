# 归档：EPUB 高质量处理管线

归档时间：2026-07-06

这份文档是 Hermes intake 成形前的“理想 EPUB 管线”草案。它仍然有参考价值，尤其是 CSS、KOReader 适配和 TXT 清洗思路；但它不是当前实现说明。当前可靠手册见 [docs/pipeline.md](../docs/pipeline.md)。

## 已被当前流程取代的部分

- “任意格式进”被收窄为本地 TXT/EPUB intake。
- Calibre-first 入库被 WebDAV remote-master 发布取代。
- AI 章节检测、AI CSS 审计、AI 正文清洗尚未接入主流程。
- 元数据补全不再直接写 Calibre 数据库，而是通过 `MetadataProvider` / `MetadataReasoner` 生成 evidence 和 decision，再写 EPUB OPF。
- 发布前新增 `.hermes.json` manifest、append-safe diff、WebDAV 条件写、`.pending/` 和 KOReader guard。

## 仍然保留的原则

### EPUB 是唯一输出格式

Hermes 的阅读端目标仍然是 EPUB。MOBI/AZW3/PDF/DOCX 等格式可以在进入 Hermes 前另行转换，但主流程不围绕 Kindle 私有格式设计。

### AI 做判断，代码做写入

旧草案把 AI 放在很多步骤里，这个方向仍然正确，但边界要更硬：

- AI 判断章节模式、广告行、元数据冲突。
- Python 代码生成 patch、写 OPF、重建 EPUB。
- 每次写入后重新 inspect。
- 旧书更新必须通过 diff 和 KOReader guard。

### KOReader 优先

CSS 不应锁死正文字体、字号和行高。书内样式负责基本结构，KOReader 端保留阅读控制。

## 未来可恢复的阶段

### TXT 清洗

建议恢复为三层：

1. 规则层：编码检测、空白归一、明显广告模板。
2. 模型报告层：疑似章节错位、缺章、正文广告、异常短段。
3. patch 层：只应用可解释、可回滚的修改。

轻小说和网文常有短句独立成段，不能用“短行就是断段错误”的简单规则。

### CSS 审计

未来可以加入 LLM CSS 审计，但输出应是结构化问题清单：

```json
{
  "selector": "p.note",
  "property": "font-size",
  "current": "12px",
  "suggested": "0.9em",
  "severity": "warning",
  "reason": "绝对字号不随 KOReader 调整"
}
```

Hermes 再决定是否自动修复。

### 插图定位

旧文档设想自动补插图。当前只支持封面采用；插图仍应先进入候选报告，不直接插入正文。插图会影响章节资源 fingerprint，对旧书更新风险更高。

## 历史价值

这份归档可以继续作为“高质量 EPUB 最终形态”的参考，但实现顺序应以后来的 Hermes 架构为准：

```text
先保守可追溯
再自动补元数据
再接大模型清洗
最后处理 sidecar 迁移
```
