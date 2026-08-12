# GKD-Merged

<div align="center">

# GKD-Merged

**把多个 GKD 订阅整合到一起，让你只需要维护一个订阅。**

[![GKD](https://img.shields.io/badge/GKD-订阅支持-blue)](https://github.com/gkd-kit/gkd)
[![自动更新](https://img.shields.io/badge/自动更新-每6小时-success)](https://github.com/2186748980/GKD-Merged/actions)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/2186748980/GKD-Merged/update-gkd.yml?label=Build)](https://github.com/2186748980/GKD-Merged/actions)

**推荐用户：** 已经在使用 GKD，希望把多个社区订阅合并，又不想在 GKD 里维护一长串订阅地址的人。

</div>

---

## 这是什么？

[GKD](https://github.com/gkd-kit/gkd) 是一个基于 Android 无障碍服务的自动点击工具，可以按照规则自动处理开屏广告、弹窗、按钮等界面元素。

而 **GKD-Merged** 并不是一个新的 GKD 客户端，也不是 GKD 官方订阅。

它更像一个“订阅聚合器”：定期获取多个公开的 GKD 订阅，将其中的规则整理、去重、合并，最后生成一个可以直接添加到 GKD 的综合订阅。

简单理解就是：

```text
                 ┌─ Lin-arm
                 ├─ ganlinte
多个订阅 ────────┼─ AIsouler（历史）
                 └─ Adpro（历史）
                        │
                        ▼
                 自动下载 / 解析
                        │
                        ▼
                    去重 / 合并
                        │
                        ▼
                 GKD-Merged 综合订阅
                        │
                        ▼
                  你的 GKD App
```

---

## 一句话使用方法

如果你已经安装了 GKD：

1. 打开 GKD 的 **订阅** 页面。
2. 添加下面的综合订阅地址。
3. 拉取更新。
4. 根据自己的需要启用规则。

### 综合订阅

```text
https://raw.githubusercontent.com/2186748980/GKD-Merged/main/gkd/gkd.json5
```

如果你所在网络访问 GitHub Raw 较慢，可以使用 jsDelivr 镜像：

```text
https://fastly.jsdelivr.net/gh/2186748980/GKD-Merged@main/gkd/gkd.json5
```

> 如果其中一个地址访问失败，可以尝试另一个。GKD 官方订阅模板也提供了 GitHub Raw 与 jsDelivr 镜像思路。  
> 参考：[GKD subscription-template](https://github.com/gkd-kit/subscription-template)

---

## 为什么要做这个？

GKD 社区里有很多优秀的规则订阅，但不同订阅的覆盖范围、维护节奏和规则风格并不完全相同。

如果全部单独添加，就可能变成：

```text
订阅 A
订阅 B
订阅 C
订阅 D
订阅 E
……
```

而 GKD-Merged 的目标就是把它们集中起来：

> **你只需要添加一个订阅地址，剩下的事情交给 GitHub Actions 自动完成。**

---

## 当前整合来源

| 来源 | 定位 | 优先级 |
| --- | --- | ---: |
| [Lin-arm/GKD_subscription](https://github.com/Lin-arm/GKD_subscription) | 当前主要来源 | 100 |
| [ganlinte/GKD-subscription](https://github.com/ganlinte/GKD-subscription) | 补充来源 | 90 |
| [AIsouler/GKD_subscription](https://github.com/AIsouler/GKD_subscription) | 历史规则补充 | 50 |
| [Adpro-Team/GKD_subscription](https://github.com/Adpro-Team/GKD_subscription) | 历史规则补充 | 40 |

### 关于已经停止维护的来源

AIsouler 和 Adpro 在这里主要承担“历史规则库”的角色。它们可能包含目前活跃订阅没有覆盖的规则，因此不会因为停止维护就直接全部丢弃。

同时，**本项目不代表这些上游项目的官方立场，也不意味着上游作者认可本项目。**

---

## 合并策略

项目不是简单地把几个 JSON 文件拼在一起，而是进行了一定程度的整理。

### 1. 高优先级来源优先

目前优先级为：

```text
Lin-arm      100
ganlinte      90
AIsouler      50
Adpro         40
```

### 2. 尽量保留互补规则

如果高优先级来源没有某个 APP 或规则组，低优先级来源仍然可以补充进去。

### 3. 重复规则去重

相同规则不会因为来自不同订阅就无限重复。

### 4. 自动处理 key / preKeys

不同订阅中的规则可能使用相同的 key。合并时会重新分配冲突 key，并同步处理 `preKeys` 依赖关系。

### 5. 上游临时不可用时使用缓存

如果某个上游暂时无法访问，但之前已经成功获取过，则使用缓存继续构建，避免一次网络故障导致整个综合订阅不可用。

如果所有来源都无法获取，构建会失败，而不是生成一个看似正常的空订阅。

---

## 自动更新

本项目使用 GitHub Actions 定期检查上游，目前默认每 **6 小时**运行一次。

```text
上游订阅
   ↓
定时检查
   ↓
下载 / 缓存
   ↓
解析
   ↓
合并 / 去重
   ↓
生成 gkd.json5
   ↓
GKD 获取更新
```

### 版本号

本项目不会单纯使用 Unix 时间戳作为版本号。

采用：

```text
YYYYMMDDNN
```

例如：

```text
2026081101
```

表示：

> 2026 年 8 月 11 日，第 1 次实际内容更新。

如果 GitHub Actions 运行了很多次，但订阅内容没有发生变化，**版本号不会变化**。

这样可以避免 GKD 每隔几个小时都收到一次“实际上没有任何变化”的更新。

---

## 项目文件结构

```text
GKD-Merged/
├── .github/
│   └── workflows/
│       └── update-gkd.yml      # 自动构建工作流
│
├── cache/
│   └── sources/                # 上游订阅缓存
│
├── gkd/
│   ├── gkd.json5               # 最终综合订阅
│   ├── gkd.version.json5       # GKD 版本检查文件
│   ├── merge-status.json       # 最近一次构建状态
│   └── version-state.json      # 版本与内容哈希状态
│
├── scripts/
│   └── merge_gkd.py            # 核心合并脚本
│
└── README.md
```

---

## 我想自己维护 / 修改怎么办？

这个项目本质上是一个普通的 GitHub 仓库。

如果你有 Python 基础，可以从：

```text
scripts/merge_gkd.py
```

开始看。

如果你只是普通 GKD 用户，**不需要修改任何代码**，直接添加综合订阅即可。

如果以后想增加一个新的上游，主要需要修改合并脚本中的 `SOURCES` 配置，然后运行一次 GitHub Actions。

---

## 自定义规则

后续计划增加独立的 `custom/` 层，用来存放本项目自己的规则。

这样可以把：

```text
上游社区规则
```

与：

```text
本项目自己的修复 / 自定义规则
```

分开管理。

例如以后针对某个 APP 新版本进行了适配，不需要修改上游规则，也不会因为上游更新而丢失。

---

## GKD 官方项目

如果你还不了解 GKD，建议先看官方项目：

- **GKD 主项目**：https://github.com/gkd-kit/gkd
- **GKD 官方网站**：https://gkd.li/
- **GKD 使用教程**：https://gkd.li/guide/
- **GKD API / 规则文档**：https://gkd.li/api/
- **GKD 订阅模板**：https://github.com/gkd-kit/subscription-template

官方订阅模板说明了 GKD 订阅的基本结构、构建方式以及 GitHub Actions 自动构建流程。citeturn0search0

---

## 常见问题

### 添加后显示“解析订阅失败”怎么办？

先检查订阅地址是否完整，并尝试切换 GitHub Raw 与 jsDelivr 地址。

也可以打开本仓库的 **Actions** 页面查看最近一次构建是否成功。

---

### 为什么我看到某个规则在这里和其他订阅不一样？

因为本项目会对不同来源进行合并和去重，并按照来源优先级处理冲突。

它不是简单复制某一个上游订阅。

---

### 为什么还保留已经停止维护的订阅？

因为停止维护不等于所有历史规则都没有价值。

对于活跃订阅没有覆盖的 APP，历史规则有时仍然可以工作，因此这里把它们作为低优先级补充来源。

---

### 这个项目是 GKD 官方项目吗？

不是。

**GKD-Merged 是个人维护的第三方订阅聚合项目。**

GKD 本身请以官方项目和官方文档为准。

---

## 注意事项

- GKD 规则具有自动点击能力，请只启用自己理解并信任的规则。
- 不建议无脑开启大量规则。规则越多，可能增加匹配开销，并可能产生误触或规则冲突。
- 上游规则的许可证、版权声明和维护政策仍然由各自上游项目决定；本项目只是进行订阅聚合。
- 如果某个上游明确要求不要转载、镜像或再分发，应尊重其项目声明，并及时调整本项目的来源策略。

---

## 反馈与贡献

发现问题可以：

1. 先确认最近一次 GitHub Actions 构建是否成功；
2. 确认问题是否来自某个上游规则；
3. 再提交 Issue，并尽量提供 APP 名称、版本、规则组名称以及必要的快照信息。

如果你想贡献代码或规则，欢迎提交 Pull Request。

---

## 致谢

感谢 GKD 项目及各个公开订阅项目的维护者和贡献者。

本项目建立在这些社区工作之上，**GKD-Merged 并不拥有上游规则的原始版权。**

---

<div align="center">

**如果这个项目对你有帮助，欢迎点一个 Star。**

Made with ❤️ for GKD users

</div>
