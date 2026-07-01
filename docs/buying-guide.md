# 阅读器选购建议

> 已持有 KPW5 的前提下，是否值得升级或换门？

---

## 三款候选

| 规格 | KPW5 (11th, 2021) | KPW6 (12th, 2024) | Kobo Clara BW (2024) |
|---|---|---|---|
| 屏幕 | 6.8" Carta 1200 | **7.0" Carta 1300** | 6.0" Carta 1300 |
| PPI | 300 | 300 | 300 |
| 前光 | 暖光可调 (17 LED) | 暖光可调 | 暖光可调 (ComfortLight PRO) |
| 防水 | IPX8 | IPX8 | IPX8 |
| 接口 | USB-C | USB-C | USB-C |
| 存储 | 8/16/32GB | 16/32GB | 16GB |
| 电池 | 1700 mAh / 10 周 | 1900 mAh / **12 周** | 1500 mAh / ~6 周 |
| 重量 | 205g | 211g | **174g** |
| 屏幕类型 | 纯平 | 纯平 | 凹陷式 |
| 处理器 | — | 快 25% | 与 KPW6 相当 |
| 价格 | 已持有 | $160-200 | $130-140 |
| 越狱 | WinterBreak | 需确认固件 | **不需要——KOReader 直接安装** |

---

## 逐台分析

### KPW6 (12th Gen)：不值得升级

KPW5 到 KPW6 的代际提升极其有限：

- 屏幕从 6.8" → 7.0"，差异 0.2 英寸。多显示两行字。
- 处理器快 25%，但 KPW5 升级到最新固件（5.17.1）后翻页速度与 KPW6 持平——软件优化的功劳，不是硬件的。
- 电池从 10 周 → 12 周。在开飞行模式读 EPUB 的场景下，两者都能轻松撑一个多月，差异无感知。
- 充电从 5 小时 → 2.5 小时。但 Kindle 的充电频率是"月"级别——这个提升对实际体验影响极小。

**更关键的问题**：KPW6 首发批次存在屏幕品控问题。约 10% 的用户报告屏幕底部有黄色条带（yellow banding），与 Kindle Colorsoft 的黄屏问题是同一时期的品控事故。Android Police 评测直接给了 6.5/10，原因是"能不能抽到好屏幕全看运气"。

> 如果你在用 KPW5，KPW6 没有任何值得花 $160 的理由。省下这笔钱。

### Kobo Clara BW：如果今天从零买，它会赢

Clara BW 有几个对这套工作流至关重要的优势：

**1. KOReader 不需要越狱。** Kobo 固件本质是 Linux，对第三方软件的态度是"不拦着你"。装 KOReader 的步骤就是解压几个文件、运行安装脚本——五分钟，不需要任何漏洞利用。这意味着永远不用担心固件升级堵死越狱路径。

**2. EPUB 是原生格式。** Kobo 原生支持 15 种格式，EPUB 是核心——不需要 Calibre 转换、不需要担心兼容性。这和"越狱后的 KPW5 + KOReader"效果相同，但少了一步越狱。

**3. 和 Calibre 的整合好得多。** Kobo 的数据库结构对 Calibre 友好，元数据同步、丛书管理、标签整理都比 Kindle 顺畅。MobileRead 论坛上的共识是"Kobo + Calibre 是电子书管理的最佳组合"。

**4. 图书馆借阅内置。** OverDrive/Libby 直接集成在系统里——在设备上搜书、借阅、归还。Kindle 也能用 Libby，但需要先在手机 App 上借、再选"Send to Kindle"——每次多几步。

**5. 无广告。** Kobo 不卖广告版。首页可能有书籍推荐，但可以通过 Sideloaded Mode（编辑一个文本文件，不是破解）完全关掉。Kindle 要花 $20 去广告。

**6. 排版控制更强。** 出厂就支持侧载字体、独立调节行高/字重/对齐/连字符。Kindle 原生系统这方面限制更多——当然，如果你在两者上都用 KOReader，这条差异消失。

**Clara BW 的缺点：**
- 屏幕只有 6 英寸——比 KPW5 的 6.8 英寸小了一圈。这是一个真正的取舍：更便携但每页显示更少。
- 凹陷式屏幕（非纯平）。纯平屏幕视觉上更高级，但凹陷式反光更少、指纹更不明显。
- 没有蓝牙/Audible。如果你听有声书，这是硬伤。
- 电池 6 周 vs KPW5 的 10 周。日常感知不明显，但长途旅行有差距。
- Kobo 书城比 Kindle Store 小。但你不打算从任何书城买书——EPUB 来源是自建的——所以这条不构成影响。

---

## 对当前工作流的适配分析

你的实际场景：

```
EPUB 唯一格式
→ Calibre 本地管理
→ WebDAV / USB 传书
→ KOReader 阅读
→ HighlightSync → WebDAV → Agent 标注处理
→ 不使用任何云同步服务
```

| 适配维度 | KPW5（越狱后） | KPW6（越狱后） | Kobo Clara BW（装 KOReader） |
|---|---|---|---|
| EPUB 原生支持 | ❌ → KOReader 解决 | ❌ → KOReader 解决 | ✅ 原生支持 |
| KOReader 安装 | 需要越狱 | 需要越狱（固件待确认） | 直接安装，5 分钟 |
| 固件升级风险 | 可能堵死越狱 | 可能堵死越狱 | 不堵——官方不拦 |
| WebDAV 传书 | KOReader Cloud Storage | 同左 | KOReader Cloud Storage |
| 标注导出 | KOReader 内置 JSON | 同左 | 同左 |
| Calibre 整合 | calibremcp | 同左 | 原生更好 |

---

## 结论：双机策略

### 主力机：KPW5（已有）

不换。6.8 英寸、暖光、USB-C、防水——越狱后 KOReader 接管一切。放在床头，每天晚上读。这是沉浸式阅读的设备——大屏幕、双手持握、连续读两小时不累。

### 副机：Kobo Clara BW（推荐购入）

> 彩色墨水屏当前技术不成熟——Kaleido 3 的底色偏灰、对比度不如 Carta、色彩饱和度低。在 6-7 英寸级别上，彩色墨水屏带来的体验提升远不如牺牲的对比度。等这代技术成熟再说。

Clara BW 作为"外出机"的参数恰好成立：

| Clara BW 特性 | 为什么适合外出 |
|---|---|
| 174g | 比 KPW5 轻 31g，比大多数手机还轻 |
| 6 英寸 | 牛仔裤后袋、外套内袋、背包侧袋——真正能随身 |
| 凹陷式屏幕 | 反光比纯平少、指纹不明显、裸奔不心疼 |
| KOReader 直接装 | 不需要越狱，5 分钟配好，固件升级不堵路 |
| Kobo + Calibre 整合 | 原生 EPUB 支持，元数据同步比 Kindle 顺畅 |
| $130-140 | 外出丢/摔的心理负担远低于 KPW5 |

两台设备用 Syncthing（KOSyncthing+ 插件）自动同步阅读进度和标注。床上放下 KPW5，第二天出门拿起 Clara BW，翻开就是昨晚停下的那一页。标注也在——HighlightSync 的 WebDAV 目标可以配置为同一台服务器，两台设备的标注汇入同一个 JSON 文件，Agent 处理管线不需要知道设备切换了。

### 具体场景

```
在家 / 睡前：
  KPW5（床头，6.8"，暖光 14，连续读两小时）
      │
      │ Syncthing 自动同步
      ▼
外出 / 通勤 / 课间 / 食堂排队：
  Clara BW（背包/口袋，6"，174g，单手可握）
      │
      │ Syncthing 自动同步
      ▼
回家：
  KPW5 翻开 → 进度已同步 → 继续读
```

两台设备上都是 KOReader，体验一致。字体、排版、CSS Tweaks 配置可以通过 Syncery 的 render settings 同步——你在 KPW5 上调好的 Bookerly 字号 5、暖光 14、行距中，Clara BW 上完全一致。

### 关于彩色墨水屏

暂时不碰。Kaleido 3 的底色偏灰——135 PPI 的彩色滤光层叠在 300 PPI 的黑白层上，导致黑白文字对比度下降。彩色饱和度低，画面像褪色印刷品。在 6-7 英寸这个尺寸级别上，漫画和 PDF 图表是唯一能从彩色中获益的场景，但屏幕太小了——看漫画不如 iPad mini，看 PDF 不如 iPad 或电脑。

等技术成熟再考虑。可能是 Kobo 的下一代彩色面板，可能是 E Ink Gallery 3 的量产版，但不是现在。

### 远期：KPW5 退役后的升级路径

如果将来 KPW5 出问题或电池衰退到不可接受，主力机的接替选项：

1. **Kobo Libra 系列**（7 英寸 + 物理翻页键）——最自然的升级。屏幕尺寸不变，多了翻页键，KOReader 直接装。目前是 Libra Colour（彩色版），等它出黑白版或下一代。
2. **等 Kobo 出 7 英寸黑白旗舰**——Clara BW 证明了 Kobo 做黑白机的功力。如果他们把 Carta 1300 放到 7 英寸、加上翻页键、去掉彩色滤光层，这就是完美的主力机。
3. **Boox Page / Leaf**（7 英寸 + Android）——可以装任何阅读 App，但 Android 的功耗管理和 E Ink 刷新策略不如 Kobo/Kindle 的原生系统精细。不优先考虑。

但现在不急。KPW5 的电池才用了不到一年，E Ink 屏幕的寿命以十年计。让它服役。

---

## 参考

- [Ars Technica: KPW6 Review](https://arstechnica.com/gadgets/2024/11/review-amazons-2024-kindle-paperwhite-makes-the-best-e-reader-a-little-better/)
- [The Verge: KPW6 Review](https://www.theverge.com/24326185/amazon-kindle-paperwhite-signature-edition-2024-e-reader-review)
- [Android Police: KPW6 Review (6.5/10)](https://www.androidpolice.com/kindle-paperwhite-2024-review/)
- [How-To Geek: Kobo + KOReader](https://www.howtogeek.com/my-ancient-kobo-ereader-is-now-better-than-a-new-kindle/)
- [Trusted Reviews: Kobo Clara BW](https://www.trustedreviews.com/reviews/kobo-clara-bw)
- [Boredom at Work: KPW vs Kobo Clara](https://boredom-at-work.com/kindle-paperwhite-vs-kobo-clara/)
- [MobileRead: Kobo vs Kindle discussion](https://www.mobileread.com/forums/showthread.php?p=4493179)
