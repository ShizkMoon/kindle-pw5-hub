# 阅读设备选择备忘

这份备忘只从 Hermes 工作流角度比较设备：EPUB 支持、KOReader、WebDAV、旧书更新和标注流。硬件价格、固件可越狱性和在售状态变化很快，购买前要重新确认。

## 当前结论

已有 Kindle PW5 的前提下，不急着换。Hermes 的核心输出是 EPUB + WebDAV，PW5 上的 KOReader 已经能承接这条链路。真正需要升级的理由不是“自动化跑不动”，而是屏幕尺寸、翻页键、防水、重量或设备生态偏好。

## 判断标准

| 标准 | 为什么重要 |
|---|---|
| KOReader 可用性 | Hermes 以 KOReader 为主要阅读端 |
| EPUB 体验 | Hermes 输出 EPUB，不走 Kindle 私有格式 |
| WebDAV 支持 | Cloud Storage 是最直接的取书方式 |
| 本地状态可控 | 旧书更新依赖路径、文件名和 metadata location |
| 标注导出 | 后续知识管线需要稳定导出 |
| 文件系统开放程度 | 影响 sidecar、同步和排障 |

## Kindle PW5

优势：

- 屏幕和续航足够长期阅读。
- 越狱后可用 KOReader。
- 现有设备无需迁移。
- Hermes 的 `/books` + Cloud Storage 流程已经适配。

限制：

- 越狱和固件状态需要维护。
- 文件系统和插件环境比 Kobo 更绕。
- Kindle 原生系统的进度与 KOReader 进度互不共享。

适合：

- 继续作为主力床头阅读器。
- 优先把 Hermes 管线做稳，而不是换设备。

## 新 Kindle

要重点确认：

- 当前固件是否可越狱。
- KOReader 是否能稳定安装。
- Cloud Storage、字体、插件是否正常。

如果不能稳定跑 KOReader，新 Kindle 对 Hermes 的价值会下降。Hermes 不依赖亚马逊云，也不把 Send to Kindle 当主链路。

## Kobo

优势：

- 一般更适合开放文件工作流。
- EPUB 原生体验更自然。
- KOReader 安装通常更直接。

需要确认：

- 具体型号的屏幕、重量和翻页体验。
- 与现有 Syncthing/WebDAV/标注导出方案的配合。
- 多设备阅读时 metadata location 和路径是否一致。

Kobo 更像“第二台开放阅读端”，不是 Hermes 的必要条件。

## iPad / iPhone / Mac

Apple 设备适合补充，不适合替代 E Ink 长读。

适合：

- 快速检查 EPUB。
- 浏览 pending reports。
- 阅读图文、PDF 或技术文档。
- 管理 WebDAV 文件。

不适合：

- 替代夜间长篇阅读。
- 无缝复用 KOReader 的本地 `.sdr` 状态。

详见 [Apple 兼容性](apple-compatibility.md)。

## 多设备同步风险

多设备不是只同步 EPUB 文件。真正麻烦的是状态：

- 阅读进度。
- 书签。
- 标注。
- 每本书的渲染设置。
- KOReader metadata location。

如果两台设备的本地路径、书名、文件 hash 或 docsettings 策略不同，同一本书可能被识别为两本书。Hermes 当前只保证 WebDAV 端发布安全，不保证所有设备本地状态自动迁移。

## 推荐路线

| 场景 | 建议 |
|---|---|
| 现在已有 PW5 | 继续用，先把 Hermes 管线做稳 |
| 想要开放系统 | 评估 Kobo |
| 想要大屏批注 | iPad 作为辅助 |
| 想要无折腾 | 暂时不要追新 Kindle 越狱 |
| 想要多设备同步 | 先设计状态同步，再买设备 |

## 购买前检查清单

- 能否稳定运行 KOReader。
- 是否支持 WebDAV 或至少能访问 WebDAV 文件。
- 字体和 CSS 控制是否足够。
- 标注能否导出。
- 设备文件系统是否方便排障。
- 是否会迫使 Hermes 改输出格式。

只要答案仍然是 EPUB + WebDAV + KOReader，Hermes 主线就不用变。
