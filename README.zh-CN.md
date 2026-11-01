<p align="center">
  <img src="public/assets/app-icon.svg" width="88" height="88" alt="ExpObserver 图标" />
</p>
<h1 align="center">ExpObserver</h1>
<p align="center"><strong>看见 Agent 的研究如何展开。</strong></p>
<p align="center">把问题、实验、证据与发现，连接在一个本地工作空间里。</p>
<p align="center">
  <a href="https://github.com/EuanTop/exp-observer/actions/workflows/ci.yml"><img src="https://github.com/EuanTop/exp-observer/actions/workflows/ci.yml/badge.svg" alt="构建与测试" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT 许可" /></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10 及以上" /></a>
</p>
<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="docs/usage.zh-CN.md">使用指南</a> ·
  <a href="skills/exp-observer/SKILL.md">Agent Skill</a> ·
  <a href="README.md">English</a>
</p>

![ExpObserver 真实研究案例：收起容器后查看主脉络和暂停的后续问题](docs/screenshots/research-workspace.png)

<p align="center"><sub>真实探索案例：先看研究主脉络，再进入容器查看具体实验与证据。</sub></p>

## 让研究过程看得见

| 跟上研究思路 | 查看实际依据 |
| :--- | :--- |
| **逐层展开。** 追溯问题的提出依据，最外层呈现主脉络，子问题、备选思路和深入实验放进可嵌套的容器。 | **保留原始结果。** 在研究图旁阅读 Markdown 分析、原始文件、命令输出与对比结果。 |
| **跨对话接续。** 多个 Agent 对话通过可移植 Skill 共同维护实验；一键定位各自的当前节点，或复制引用继续讨论。 | **看清状态与成本。** 区分完成、暂停、排除和错误，查看已采集的耗时与可用的 Token 用量。 |

Agent 自主选择研究方法，ExpObserver 留下过程中的发现、负结果和未解决问题。记录、版本历史与证据保存在你的电脑上。

## 快速开始

界面默认英文，可在顶部语言选项中切换为**简体中文**，选择会自动保存。窄窗口下，语言选项位于**更多工具**菜单中。

### 交给 Agent 安装

把这句话发给 Agent：

> 请按照 https://github.com/EuanTop/exp-observer/blob/main/INSTALL.md 安装并启动 ExpObserver，同时安装它的 Skill。

### 或者自己启动

1. [下载 **exp-observer.zip**](https://github.com/EuanTop/exp-observer/releases/latest/download/exp-observer.zip) 并解压。
2. Windows 打开 **start.bat**，macOS 打开 **start.command**；Linux 运行 `python3 start.py`。
3. 在界面中打开**连接 Agent**，接入研究目录，把指令复制到 Agent 对话。

需要 **Python 3.10+**。运行发行包无需 Node.js、pip 依赖、账号或模型 API Key。[安装与升级详情 →](INSTALL.md)

接着给 Agent 你的研究任务：

> 使用 ExpObserver Skill 接入实验 `my-study`，研究我的问题，保留实际证据，并随研究进展维护实验记录。

平台关闭时，Skill 可以自动唤起已安装的平台；服务暂时不可用时，记录会先在本地暂存。

<details>
<summary><strong>进一步查看：展开研究步骤，在下一段对话中引用它</strong></summary>

![选中研究节点后查看详情，通过复制引用在 Agent 对话中继续讨论](docs/screenshots/node-details.png)

选中节点，点击**复制引用**，粘贴到任意 Agent 对话，再补充你的问题。引用保留实验和节点身份，Agent 可以按需读取最新上下文。

</details>

## 继续了解

[使用指南](docs/usage.zh-CN.md) · [Skill](skills/exp-observer/SKILL.md) · [API 与数据契约](docs/contract.md) · [实测案例](examples/real-study/report.md) · [参与开发](CONTRIBUTING.md)

使用 React、TypeScript、Tailwind CSS、React Flow、ELK 和 Python 构建。采用 [MIT 许可](LICENSE)。
