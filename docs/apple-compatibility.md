# Apple 设备兼容性分析

> 当前未持有任何 Apple 设备（iPhone / iPad / Mac / Apple Watch）。本文档评估现有基础设施对 Apple 生态的兼容性，为未来决策做准备。

## 总览

| 子系统 | 兼容性 | 需要额外做什么 |
|---|---|---|
| 米家灯光控制 (S1-S5) | ✅ 通过 HA HomeKit Bridge | 在 HA 中启用 HomeKit Bridge，扫码配对 |
| Hermes 日常交互 | ✅ 飞书/微信 iOS 客户端 | 无 |
| 日历同步 (Radicale) | ✅ iOS/macOS 原生 CalDAV | 在账户设置中添加 CalDAV 账户 |
| VPN 接入 (Tailscale) | ✅ Apple Silicon 原生 + iOS | 安装 App，登录同一账号 |
| KOReader 阅读进度同步 | ✅ 通过 Readest App | 部署 koreader-sync-server，两端配置 |
| Multica 编码 | ✅ Web 端，Safari 可用 | 无 |
| CherryStudio | ⚠️ 仅桌面端，无 iOS 版 | 用 Mac 版替代，或 iPad 上用 Web 版 |
| Kindle PW5 管线 | ✅ 脚本运行在 Windows/云服务器 | 无（管线不依赖客户端 OS） |
| 墨水屏面板 | ✅ ESPHome 驱动，独立于客户端 | 无 |
| 3D 打印 | ✅ Hermes MQTT + FTPS | 无 |

## 逐系统分析

### 一、HomeKit 桥接：让米家设备出现在 Apple Home

这是最有价值的集成。HA 的 HomeKit Bridge 集成可以将任何 HA 实体暴露为 HomeKit 配件。

```
米家设备 (S1-S5 灯带、传感器、无线开关)
    │
    ▼
Xiaomi Home 集成 (HA)
    │
    ▼
HomeKit Bridge (HA)
    │
    ▼
Apple Home App (iPhone / iPad / Mac / Apple Watch / Siri)
```

**效果**：
- S1-S5 灯带在 Apple Home 里显示为原生灯光配件
- "Hey Siri，切换到工作模式" → HA scene 触发
- Apple Watch 抬手点一下就能关所有灯
- 控制中心直接操作（iOS 18+ 支持自定义磁贴）
- iPhone Focus 模式联动：睡眠模式自动切到夜间灯光

**配置步骤**：HA 设置 → 集成 → 添加 HomeKit Bridge → 选择要暴露的实体 → 扫码配对到 Apple Home。5 分钟。

**限制**：HomeKit Bridge 最多 150 个配件/桥。对于你的设备数量完全够用。HA 和 iPhone 需要在同一个局域网才能首次配对（或通过 mDNS 反射器跨越 VLAN）。

### 二、HA Companion App：iPhone 变身传感器中枢

HA 官方 iOS App 不仅是控制面板，还会把手机数据喂给 HA 作为传感器：

| 传感器 | 用途 |
|---|---|
| 位置 (GPS) | "离开宿舍自动关灯"、"回到宿舍自动开灯" |
| 电池电量 | 低电量提醒 |
| 活动类型 | 步行/骑行/驾车/静止——触发不同场景 |
| Wi-Fi SSID | 比 GPS 更快更准的到家检测 |
| Focus 模式 | 睡眠模式 → 自动切夜间灯光 |
| 步数 | 日常记录 |

**Shortcuts 集成**："Hey Siri，我出门了" → 触发 HA 的"离开"自动化。不需要打开任何 App。

### 三、日历同步：Radicale 原生兼容

iOS/macOS 原生 CalDAV 客户端直接支持 Radicale。不需要第三方 App。

```
iPhone 设置 → 日历 → 账户 → 添加账户 → 其他 → 添加 CalDAV 账户
服务器: https://your-domain.com/caldav/
用户名/密码: 你的 Radicale 凭据
```

添加后，iPhone 日历 App 和 HA Calendar 实体共享同一份数据。Hermes 在日历上创建的提醒会出现在 iPhone 的通知中心。反过来——你在 iPhone 日历上加的事件，Hermes 也能读到。

### 四、KOReader 阅读进度同步

KOReader 的 sync server 协议已有现成的第三方实现。关键是 Readest——一个跨平台的开源阅读器，原生支持 KOReader Sync。

```
Kindle PW5 (KOReader)
    │
    │ KOReader Sync Protocol
    ▼
koreader-sync-server (云服务器 Docker)
    │
    │ 同一个 document hash
    ▼
iPhone / iPad / Mac (Readest App)
```

**部署**：`koreader-sync-server` 有很多实现（官方 Lua、Python、TypeScript、Go 各有一版），选一个 Docker 化跑在云服务器上即可。KOReader 端和 Readest 端各配置一次服务器 URL——之后自动同步。

**注意**：两边必须是完全相同的文件（同一个 MD5 hash）。Calibre 作为文件的 Single Source of Truth，通过 OPDS 或 WebDAV 分发给两个设备。

### 五、网络层：Tailscale

Tailscale 对 Apple 生态的支持是最成熟的：
- macOS：Apple Silicon 原生支持（Universal Binary，ARM + x86），macOS 12.0+
- iOS/iPadOS：App Store 直接安装，支持 WireGuard 协议
- 所有设备同一虚拟网络，IP 不变

### 六、有局限的地方

| 场景 | 状态 | 替代方案 |
|---|---|---|
| CherryStudio | 无 iOS 版 | Mac 版可用；iPad 上用 Safari 访问 CherryStudio Web（如果有） |
| KOReader | 无 iOS 版 | Readest 替代，体验接近 |
| Calibre GUI | 无 iOS 版 | Calibre Content Server 用 Safari 浏览；calibredb CLI 在 macOS 终端可用 |
| Sigil | 无 iOS/macOS 轻量版 | macOS 有完整桌面版 |
| pipeline.py 等脚本 | 脚本本身跨平台 | macOS 有 Python，依赖（ebooklib、charset-normalizer、opencc）都有 macOS 版本 |

### 七、Apple Silicon Mac 的 Docker 兼容性

如果将来买 MacBook 或 Mac mini 做开发机：

| 组件 | Apple Silicon 兼容 |
|---|---|
| Docker Desktop for Mac | ✅ Apple Silicon 原生（Rosetta 备选） |
| `linux/amd64` 镜像 | ✅ Docker 自动仿真，但有性能损耗 |
| Calibre | ✅ macOS 原生 ARM 版本 |
| Python 3.x | ✅ ARM 原生 |
| `ebook-convert` | ✅ macOS Calibre 自带 |
| Tailscale | ✅ Apple Silicon 原生 |

> 云服务器上的 Docker 容器（New API、Nginx、HA、Hermes）不受客户端 Mac 影响——它们跑在 x86 云服务器上。只有本地开发用的工具需要在 Mac 上重新安装 ARM 版本。

### 八、如果有 Apple Watch

Apple Watch 对这套体系的价值在于**无感交互**：
- 抬腕看 HA 通知（打印完成、Kindle 标注已处理）
- Siri 表盘显示日历下一个事件（Radicale → CalDAV → Apple Watch）
- Home 应用抬手控制灯光
- 不会在手表上跑 Agent——屏幕太小

### 九、iCloud+ 的策略

| 层级 | 价格 | 你会用到的 |
|---|---|---|
| 免费 5GB | ¥0 | 不够用——一张照片都不够 |
| 50GB | ¥6/月 | 纯照片勉强够，不含备份 |
| 200GB | ¥21/月 | 照片 + 整机备份，够用 |
| **2TB** | **¥68/月** | 全部无忧 |

¥68/月在你的 AI 订阅（¥944-994/月）面前可以忽略。推荐直接上 2TB——不是因为你真的需要 2TB，而是因为不用操心配额。照片自动同步、整机备份、文件跨设备同步——这些是自建方案很难达到相同体验的。

**iCloud 管什么、自建管什么**：

| 服务 | 用谁 | 原因 |
|---|---|---|
| 照片同步 + 备份 | iCloud+ | 自建照片同步维护成本高，体验差距大 |
| 整机备份 | iCloud+ | 换机时一键恢复，自建不可替代 |
| 日历 | Radicale（自建） | Hermes 需要 CalDAV 读写权限 |
| 文件同步 | WebDAV（自建） | KOReader 标注回流依赖 WebDAV |
| 笔记/备忘录 | 待定 | iCloud 自带可用，或自建 |

### 十、什么是你现在不需要的

| 苹果生态组件 | 理由 |
|---|---|
| HomePod / HomePod mini | 你已有足够的音频设备。HomePod 的唯一增量价值是作为 HomeKit Hub——但 HA 已在云服务器上，远程访问通过 Nginx 解决 |
| Apple TV | 宿舍没有电视 |
| HomeKit Secure Video | 你没有摄像头，也不打算装 |

## 结论

**现有基础设施已做好 Apple 就绪的准备。** 不需要任何架构变更。当第一部 iPhone 到手时：

1. 开通 iCloud+ 2TB（¥68/月）——照片、备份、文件全自动
2. 装 Tailscale（App Store）
3. 装 HA Companion App
4. 在 HA 里启用 HomeKit Bridge，扫码配对
5. 加 Radicale CalDAV 账户（日历继续自建——Hermes 需要）
6. 装 Readest 做阅读同步
7. Siri Shortcuts 配几句常用命令

30 分钟全部就绪。iCloud 管照片和备份，自建服务（HA、Radicale、Tailscale、koreader-sync-server）管智能家居和数据主权——各司其职。
