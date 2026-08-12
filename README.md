<div align="center">

# GKD-Merged

### 一个更省心的 GKD 多源综合订阅

**把多个社区订阅整合成一个地址，让规则获取、去重和更新交给 GitHub Actions。**

[![GKD](https://img.shields.io/badge/GKD-订阅支持-4c9aff)](https://github.com/gkd-kit/gkd)
[![自动更新](https://img.shields.io/badge/自动更新-每6小时-2ea44f)](https://github.com/2186748980/GKD-Merged/actions)
[![Build](https://img.shields.io/github/actions/workflow/status/2186748980/GKD-Merged/update-gkd.yml?label=Build)](https://github.com/2186748980/GKD-Merged/actions)
[![License](https://img.shields.io/github/license/2186748980/GKD-Merged)](./LICENSE)

<br>

**第一次使用？** → [快速开始](./docs/getting-started.md)  
**想了解合并原理？** → [合并机制](./docs/merge.md)  
**遇到问题？** → [故障排查](./docs/troubleshooting.md)

</div>

---

## ⚡ 先用起来

如果你已经安装了 GKD，**只需要添加下面这一个订阅地址**：

```text
https://2186748980.github.io/GKD-Merged/gkd/gkd.json5
```

备用地址：

```text
https://raw.githubusercontent.com/2186748980/GKD-Merged/main/gkd/gkd.json5
```

> 推荐优先使用 GitHub Pages 地址；如果访问不稳定，再尝试 Raw 地址。

### 我是第一次使用 GKD

👉 [从零开始的使用教程](./docs/getting-started.md)

---

## 🌟 这是什么？

[GKD](https://github.com/gkd-kit/gkd) 是一个基于 Android 无障碍服务的自动点击工具，可以按照规则自动处理开屏广告、弹窗、按钮等界面元素。

**GKD-Merged 不是 GKD 客户端，也不是 GKD 官方项目。**

它是一个第三方社区订阅聚合器：定期获取多个公开 GKD 订阅，进行解析、整理、去重和合并，然后生成一个可以直接交给 GKD 使用的综合订阅。

简单来说：

```text
       Lin-arm ─────────┐
       ganlinte ────────┤
       AIsouler ────────┼──→ 下载 / 缓存
       Adpro ───────────┘          │
                                   ▼
                              解析 / 标准化
                                   │
                                   ▼
                              合并 / 去重
                                   │
                                   ▼
                         key / preKeys 处理
                                   │
                                   ▼
                           GKD-Merged 订阅
                                   │
                                   ▼
                                GKD App
```

> **核心目标只有一个：让你不用维护一长串订阅地址。**

---

## 📦 当前整合来源

| 来源 | 定位 | 优先级 |
| --- | --- | ---: |
| [Lin-arm/GKD_subscription](https://github.com/Lin-arm/GKD_subscription) | 当前主要来源 | **100** |
| [ganlinte/GKD-subscription](https://github.com/ganlinte/GKD-subscription) | 活跃补充来源 | **90** |
| [AIsouler/GKD_subscription](https://github.com/AIsouler/GKD_subscription) | 历史规则补充 | **50** |
| [Adpro-Team/GKD_subscription](https://github.com/Adpro-Team/GKD_subscription) | 历史规则补充 | **40** |

### 为什么还保留历史来源？

**停止维护 ≠ 所有旧规则都没有价值。**

某个历史订阅可能包含活跃订阅没有覆盖的 APP 或规则。因此这里把它们放在低优先级，用来补充缺失内容，而不是与活跃来源平起平坐。

本项目不代表任何上游项目的官方立场，也不意味着上游作者认可本项目。

更多说明： [上游来源](./docs/sources.md)

---

## 🧠 怎么合并？

这不是简单地把几个 JSON5 文件拼在一起。

### 合并逻辑

```text
高优先级来源
      │
      ├─ 有 → 优先采用
      │
      └─ 没有
           ↓
      低优先级来源补充
```

同时会：

- 合并同一 APP 的规则
- 合并互补规则组
- 对重复规则进行指纹去重
- 处理不同来源之间的 `key` 冲突
- 同步修正 `preKeys` 依赖
- 上游临时不可访问时使用缓存
- 所有来源都不可用时让构建失败，而不是生成空订阅

👉 [查看详细合并机制](./docs/merge.md)

---

## 🔄 自动更新

项目使用 GitHub Actions 自动构建，默认**每 6 小时**检查一次上游。

```text
上游更新
   ↓
定时检查
   ↓
下载 / 缓存
   ↓
JSON5 解析
   ↓
合并 / 去重
   ↓
内容发生变化？
   ├─ 否 → 保持原版本
   └─ 是 → 生成新版本
              ↓
        更新综合订阅
```

### 版本号很容易看懂

格式：

```text
YYYYMMDDNN
```

例如：

```text
2026081101
```

就是：

> **2026 年 8 月 11 日，第 1 次实际内容更新。**

如果 Actions 跑了 10 次，但规则内容完全没变化，版本号仍然不会变。

---

## 📊 构建状态

最近一次构建产生的状态会写入：

```text
 gkd/merge-status.json
```

其中包括：

- 上游下载状态
- 上游版本
- 最终 APP 数量
- 全局规则数量
- 综合订阅版本
- 内容哈希

你可以直接查看：[merge-status.json](./gkd/merge-status.json)

---

## 📁 项目结构

```text
GKD-Merged/
│
├── .github/
│   └── workflows/
│       └── update-gkd.yml       # 自动构建
│
├── cache/
│   └── sources/                 # 上游缓存
│
├── gkd/
│   ├── gkd.json5                # ⭐ 最终综合订阅
│   ├── gkd.version.json5        # GKD 更新检查
│   ├── merge-status.json        # 构建状态
│   └── version-state.json       # 版本状态
│
├── scripts/
│   └── merge_gkd.py             # 核心合并器
│
├── docs/
│   ├── getting-started.md       # 新手教程
│   ├── sources.md               # 上游来源
│   ├── merge.md                 # 合并机制
│   ├── custom-rules.md          # 自定义规则
│   └── troubleshooting.md       # 故障排查
│
├── CHANGELOG.md                 # 更新日志
├── CONTRIBUTING.md              # 贡献指南
├── LICENSE                      # 项目许可证
└── README.md                    # 项目主页
```

---

## 🛠️ 我想贡献规则 / 修复问题

欢迎！

如果只是发现某个 APP 的规则失效，最有价值的信息通常是：

- APP 名称 / 包名
- APP 版本
- GKD 版本
- 规则组名称
- GKD 快照
- 事件日志
- 清晰的复现步骤

👉 [贡献指南](./CONTRIBUTING.md)  
👉 [自定义规则说明](./docs/custom-rules.md)

---

## ❓ 常见问题

### 添加订阅后提示“解析订阅失败”

先检查：

1. 网络是否能访问 GitHub Pages；
2. 最近一次 Actions 是否构建成功；
3. 订阅地址是否完整。

👉 [详细排查方法](./docs/troubleshooting.md)

### 为什么一个订阅里有这么多规则？

因为这是多源聚合订阅。目标就是减少你在 GKD 里维护多个订阅的麻烦。

### 为什么旧订阅还在？

它们作为低优先级历史规则库，主要用于补充活跃来源没有覆盖的内容。

### 这是 GKD 官方项目吗？

**不是。**

GKD-Merged 是个人维护的第三方社区项目。GKD 本身请以官方项目和官方文档为准。

---

## 🔗 GKD 官方入口

如果你刚接触 GKD，建议先看看官方资料：

- [GKD 官方 GitHub](https://github.com/gkd-kit/gkd)
- [GKD 官方网站](https://gkd.li/)
- [GKD 使用教程](https://gkd.li/guide/)
- [GKD API / 规则文档](https://gkd.li/api/)
- [GKD 官方订阅模板](https://github.com/gkd-kit/subscription-template)

---

## ⚠️ 使用提醒

GKD 规则具有自动点击能力，请只启用你理解并信任的规则。

不建议无脑开启全部规则。规则数量越多，匹配开销和误触风险也可能增加。

上游规则的版权、许可证和归属仍以各自项目为准。本项目只负责聚合与构建，**不主张拥有上游规则的原始版权。**

---

## ❤️ 致谢

感谢：

- [GKD](https://github.com/gkd-kit/gkd) 项目及其贡献者
- Lin-arm
- ganlinte
- AIsouler
- Adpro-Team
- 所有提供规则、反馈问题和帮助测试的社区用户

没有这些社区项目，就不会有这个聚合器。

---

<div align="center">

### 如果这个项目帮到了你，欢迎给仓库点一个 ⭐ Star

**让多个订阅，变成一个更省心的选择。**

</div>
