# Kindle Paperwhite 5 配置指南

KPW5（第 11 代）实用配置手册。已越狱，KOReader 为主力阅读器，Kindle 原生系统作为应急备份。

---

## 设备参数

| 规格 | KPW5（第 11 代，2021） |
|---|---|
| 屏幕 | 6.8 英寸 E Ink Carta 1200，300 PPI |
| 前光 | 17 颗 LED（白光 + 琥珀色暖光） |
| 存储 | 8 GB / 16 GB / 32 GB（签名版） |
| 接口 | USB-C、Wi-Fi 5（802.11ac）、蓝牙 5.0 |
| 防水 | IPX8（2 米淡水，60 分钟） |
| 电池 | 1700 mAh |
| 尺寸 | 174 x 125 x 8.1 mm，205 g |
| 固件要求 | 必须 **< 5.18.1** 才能使用 WinterBreak |

---

## 越狱

### 前置条件

- 固件版本 **低于 5.18.1**
- USB-C 数据线和电脑
- 耗时约 30 分钟
- 可逆操作：不会变砖，不影响硬件保修

### 方法：WinterBreak

WinterBreak 是 KPW5 推荐越狱方案。完整步骤参见 [WinterBreak Wiki](https://github.com/KindleModding/WinterBreak)。

**关键步骤清单：**

1. 确认固件版本：`设置 -> 设备选项 -> 设备信息`
2. 若固件 >= 5.18.1，需先降级（按 WinterBreak 降级流程操作）
3. 下载对应固件版本的 WinterBreak 包
4. 在 Kindle 上进入演示模式
5. 通过 USB 将 WinterBreak 文件复制到 Kindle 根目录
6. 通过演示模式菜单触发漏洞利用
7. 验证越狱成功：在搜索栏输入 `;log mrpi`，应有响应
8. 退出演示模式，回到正常模式

### 越狱后必做事项

越狱成功后，立即完成以下操作：

| 步骤 | 命令 / 操作 | 目的 |
|---|---|---|
| 安装热修复 | 将 `Update_hotfix_*.bin` 复制到根目录，然后 `设置 -> 更新您的 Kindle` | 防止固件升级后越狱失效 |
| 关闭 OTA 更新 | 在 Kindle 根目录创建空文件夹 `/update.bin.tmp.partial/`（或使用 renameotabin 插件） | 阻止亚马逊远程修补越狱漏洞 |
| hosts 屏蔽 OTA | 向 hosts 文件添加 `0.0.0.0 softwareupdates.amazon.com`（配合 KUAL+ 助手） | 网络层面阻断升级 |
| 安装 KUAL | 将 KUAL booklet 复制到 `documents/` | KOReader 启动所必需的应用启动器 |
| 安装 MRPI | 复制 MRPI 扩展文件夹 | 用于安装各类插件的包管理器 |

---

## KOReader 安装

### 通过 KUAL + MRPI 安装

1. 从 [koreader.rocks](https://koreader.rocks) 下载最新 KOReader 发行版
2. 解压到 Kindle 根目录——文件将合并到 `extensions/` 和 `koreader/` 文件夹
3. 弹出 Kindle，打开 KUAL，选择 KOReader 即可启动

---

## 为什么选这些插件——连接 AI 流水线

这部分解释每个 KOReader 插件在我的自动化书务系统中扮演什么角色。不是"好用才装"，而是流水线的一环。

| 插件 | 在 AI 流水线中的角色 | 为什么必须装 |
|---|---|---|
| **Syncery** | 多设备阅读进度同步，底层依赖 Syncthing | 只要进度在 Windows 和 Kindle 之间自动同步，我就可以在任何一端开始阅读、暂停、继续。云端 AI Agent 通过 WebDAV 推送书籍后，新书直接出现在 KOReader 的同步目录里，不需要手动拷贝。 |
| **HighlightSync** | 将标注和笔记导出到 WebDAV | 这是"读后处理"的起点。我在 KOReader 上做的所有划线、批注，每晚 22:00 由云端 cron 任务拉取到 WebDAV，然后 Agent 解析、分类、写入知识库（Obsidian + 记忆图谱）。没有它，标注就死在了 Kindle 上。 |
| **Cloud Storage** | 从 WebDAV 直接下载书籍 | AI 流水线处理完的书（格式转换 -> 章节检测 -> CSS 审计 -> 元数据补全 -> EPUBCheck 校验）自动上传到 WebDAV 的 `books/` 目录。我在 KOReader 里打开 Cloud Storage 就能看到新书，点一下即下载到本地阅读。完全绕开了 USB 线。 |
| **KOSyncthing+** | 后台 Syncthing 守护进程 | Syncery 插件的底层引擎。与 Windows 端的 Syncthing 配对后，`settings/`（阅读进度、书签、配置）、`highlights/`（标注导出）、`news/`（RSS 推送）三个目录自动双向/单向同步。Windows 端的 Syncthing 作为中转，云端 Agent 通过 WebDAV 读写同样的目录。 |
| **ReadTimer** | 阅读时长统计 | 数据不在于"多"而在于"可用"。Agent 读取阅读统计后可以分析阅读习惯，为后续书籍推荐、阅读节奏调整提供量化依据。虽然目前用得不多，但统计数据的采集是自动化的前提。 |
| **Terminal** | 内置 SSH/Telnet 客户端 | 应急通道。当 WebDAV/Syncthing 出问题时，可以通过终端直接登录云服务器排查。日常不打开，但不能没有。 |

### 数据流示意图

```
阅读端（KPW5 + KOReader）
  ├── KOSyncthing+ ———双向———— Windows Syncthing ─── 单向 ─── 云端 Agent cron
  │                                                              │
  │   ├── settings/        进度/书签/配置              ←→  解析阅读状态
  │   ├── highlights/      标注/批注                     →   写入 Obsidian + 知识图谱
  │   └── news/            RSS/订阅                      ←   每日推送
  │
  ├── Cloud Storage ——— HTTP/WebDAV ─── 云端 Agent
  │      新书下载 ←── books/ <—— EPUB 流水线输出
  │
  └── HighlightSync ——— WebDAV ─── 云端 Agent cron（22:00）
       标注导出      →     highlights/ →     解析、分类、入库
```

---

## KOReader 配置

### 样式微调

启用路径：`底部菜单 -> 齿轮（第二个标签页）-> 样式微调`

| 微调项 | 是否开启 | 效果 |
|---|---|---|
| `忽略出版商的字体族` | **是** | 全文使用 KOReader 所选字体，无视书内嵌字体 |
| `忽略出版商的字号` | 可选 | 仅当 EPUB 源排版字号混乱时启用 |
| `强制稳定行高` | **是** | 防止上下标导致行间距抖动，对含大量注释的中文书尤其重要 |
| `缩小上下标` | **是** | 将上下标缩至 50%，提升可读性 |
| `连字符` | 可选 | 正文启用西文断词连字符 |

### 字体配置

```
路径：   Kindle:/koreader/fonts/
文件：   *.ttf, *.otf
```

KOReader 自动共享 Kindle 原生 `fonts/` 目录，同时拥有独立的 `koreader/fonts/` 目录存放 KOReader 专属字体。`koreader/fonts/noto/` 是系统字体目录——不要删除。

**推荐中文字体：**

| 字体 | 风格 | 最适合 |
|---|---|---|
| Source Han Serif（思源宋体） | 宋体 | 长篇阅读 |
| Source Han Sans（思源黑体） | 无衬线 | 界面与菜单 |
| LXGW WenKai（霞鹜文楷） | 楷体风 | 文学/古籍类文本 |

**推荐拉丁字体：**

| 字体 | 风格 | 最适合 |
|---|---|---|
| Bookerly | 衬线 | Kindle 原生正文字体，E Ink 优化 |
| Literata | 衬线 | Google 电子阅读器字体，高 x 高度 |
| Atkinson Hyperlegible | 无衬线 | Braille Institute 出品，最高可读性 |

### Cloud Storage（WebDAV）配置

```
KOReader: 工具 -> Cloud Storage -> 添加 WebDAV
  URL:      https://<服务器地址>:<端口>/<路径>
  Username: koreader
  Password: <webdav_password>
```

放入 WebDAV 目录的书籍会自动出现在 KOReader 的 Cloud Storage 浏览器中，点选即下载。

### Syncthing 配对（Syncery）

1. 在 KOReader 上安装 KOSyncthing+ 插件
2. 启动 KOSyncthing+，界面会显示设备 ID
3. 在 Windows 端（Syncthing 管理界面 `http://127.0.0.1:8384`）：
   - `添加远程设备` -> 输入 KOReader 的设备 ID
   - 选择要共享的文件夹（如 KOReader 的 `settings/` 和 `highlights/`）
4. 在 KOReader 上确认配对
5. 启用 Syncery 插件，此后将通过 KOSyncthing+ 守护进程自动同步

**需要同步的文件夹：**

| 文件夹 | 用途 | 同步方向 |
|---|---|---|
| `koreader/settings/` | 阅读进度、书签、配置 | 双向 |
| `koreader/highlights/` | 标注导出 | KOReader -> PC |
| `koreader/news/` | RSS/新闻推送 | PC -> KOReader |

---

## 推荐阅读设置

### 亮度和暖光（KPW5 硬件）

| 场景 | 亮度 | 暖光 | 说明 |
|---|---|---|---|
| 日间室内 | 8-10 | 0 | E Ink 屏幕本身反射环境光，前光只是补充 |
| 夜间床头 | 6-8 | 15-18 | 搭配深色模式（白字黑底），零环境光阅读 |
| 户外阳光下 | 0 | 0 | E Ink 在直射光下无需前光 |
| 最大化续航 | <= 10 | 0 | 亮度 20+ 续航约减半 |

- **关闭自动亮度**：环境光传感器持续耗电
- **暖光定时**：设定 19:00-07:00 自动切换，或按日落日出手动调整
- **预估续航**：亮度 10 + 飞行模式 = 约 30 小时阅读；亮度 24 + 暖光 = 约 18 小时

### KOReader 显示设置

| 设置项 | 推荐值 | 原因 |
|---|---|---|
| E Ink 刷新频率 | 每页刷新 | 消除残影；KPW5 翻页速度使其几乎无感 |
| 对比度 | 默认（1.0） | 如文字发灰则按书调整 |
| 字体粗细 | 默认（0） | 细笔画中文字体可上调至 +1 或 +2 |
| 伽马 | 默认（1.0） | 在不改变对比度的情况下加深文字 |
| 屏幕 DPI | 300 | 与 KPW5 硬件匹配 |

---

## 速查手册

### KOReader 手势

| 手势 | 区域 | 操作 |
|---|---|---|
| 单击 | 左边缘 | 上一页 |
| 单击 | 右侧/中央 | 下一页 |
| 单击 | 顶部边缘 | 切换菜单 |
| 单击 | 底部边缘 | 切换底部菜单 |
| 上滑 | 左边缘 | 前光亮度 + |
| 下滑 | 左边缘 | 前光亮度 - |
| 上滑 | 右边缘 | 暖光 + |
| 下滑 | 右边缘 | 暖光 - |
| 长按 | 单词 | 查字典 + 标注 |
| 长按 | 页码（底部） | 跳转页面 |
| 双指捏合 | 任意位置 | 缩放（PDF/图片） |
| 双指滑动 | 任意位置 | 平移（缩放后） |

### Kindle 原生快捷键

| 操作 | 方法 |
|---|---|
| 截图 | 同时点击左上角 + 右下角 |
| 强制重启 | 按住电源键 40 秒 |
| 快速调亮度 | 从顶部边缘下滑 |
| 横屏模式 | `Aa -> 布局 -> 方向 -> 横屏` |
| 显示时钟 | `Aa -> 更多 -> 显示时钟` |

### 常用 KOReader 操作

| 操作 | 路径 |
|---|---|
| 打开文件浏览器 | 顶部菜单 -> 文件浏览器 |
| 切换书籍 | 顶部下滑 -> 文件浏览器，或点击顶部菜单书名 |
| 添加书签 | 顶部菜单 -> 书签图标，或点击右上角 |
| 查看书签 | 顶部菜单 -> 目录 -> 书签标签页 |
| 查字典 | 长按单词 |
| 书内搜索 | 顶部菜单 -> 搜索图标（放大镜） |
| 阅读统计 | 顶部菜单 -> 汉堡菜单 -> 阅读统计 |
| Cloud Storage | 顶部菜单 -> 汉堡菜单 -> Cloud Storage |
| 插件管理 | 顶部菜单 -> 汉堡菜单 -> 更多工具 -> 插件管理 |
| 退出 KOReader | 顶部菜单 -> 汉堡菜单 -> 退出 -> 退出 KOReader |

### 故障排查

| 问题 | 解决方法 |
|---|---|
| KOReader 无法启动 | 通过 MRPI 重装；检查 `extensions/koreader/` 目录是否存在 |
| 书籍不显示 | 确认格式为 EPUB；检查文件是否在 `documents/` 下或等待 KOReader 扫描库 |
| WebDAV 连接失败 | 检查服务器 URL、用户名和密码；先用手机测试服务器可达性 |
| Syncthing 不同步 | 确认两端在线；检查共享文件夹 ID 匹配；确保无文件冲突 |
| 电量异常消耗 | 大批量导入后等待 24 小时（索引进度）；不用时关闭 Wi-Fi；亮度 <= 10 |
| 残影（原页痕迹） | 在 KOReader 中启用"每页刷新"；Kindle 原生：`设置 -> 阅读选项 -> 页面刷新 -> 开启` |
| 插件列表不显示 | 刷新插件列表：`插件管理 -> 重新加载`；确认文件在 `koreader/plugins/` 目录下 |
| KOReader 卡死 | 尝试通过菜单退出；无效则强制重启 Kindle |

### 重要注意事项

- **KOReader 运行时不要连接 USB。** 先退出 KOReader，再插 USB。KOReader 持有文件系统，USB 大容量存储模式可能导致数据损坏。
- **不要删除 `koreader/fonts/noto/`。** 这些是 KOReader 依赖的系统级字体。
- **KOReader 与 Kindle 原生共享 `documents/` 文件夹，但各自维护独立的阅读状态。** 在 KOReader 阅读的书籍不会在 Kindle 原生中显示进度，反之亦然。

---

## 参考资料

- [WinterBreak 越狱 Wiki](https://github.com/KindleModding/WinterBreak)
- [KOReader 用户指南](https://koreader.rocks/user_guide/)
- [KOReader 插件列表](https://github.com/koreader/koreader/wiki/Plugins)
- [Syncthing 文档](https://docs.syncthing.net/)
- [Bookfere Kindle 新手入门](https://bookfere.com/novice)
- [Bookfere Kindle 字典下载](https://bookfere.com/dict)
- [iFixit KPW5 维修指南](https://www.ifixit.com/Device/Kindle_Paperwhite_11th_Generation)
- [Standard Ebooks](https://standardebooks.org/)
