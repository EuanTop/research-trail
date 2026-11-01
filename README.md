<p align="center">
  <img src="public/assets/app-icon.svg" width="88" height="88" alt="ExpObserver icon" />
</p>
<h1 align="center">ExpObserver</h1>
<p align="center"><strong>See how your agent's research unfolds.</strong></p>
<p align="center">Questions, experiments, evidence, and findings — connected in one local workspace.</p>
<p align="center">
  <a href="https://github.com/EuanTop/exp-observer/actions/workflows/ci.yml"><img src="https://github.com/EuanTop/exp-observer/actions/workflows/ci.yml/badge.svg" alt="Build and tests" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license" /></a>
  <a href="INSTALL.md"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10 or newer" /></a>
</p>
<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="docs/usage.md">User guide</a> ·
  <a href="skills/exp-observer/SKILL.md">Agent Skill</a> ·
  <a href="README.zh-CN.md">简体中文</a>
</p>

![ExpObserver's English interface showing a real agent research session, with nested questions, execution timing and measured usage](docs/screenshots/platform-workspace.en.png)

<p align="center"><sub>Follow a real agent research session. Open a question to inspect its experiments, evidence, and next steps.</sub></p>

## Research you can follow

| Follow the reasoning | Inspect the evidence |
| :--- | :--- |
| **Nested research spaces.** Trace the source of a question and keep the main story readable; open containers for subquestions, alternatives, and deeper experiments. | **Original results.** Read native Markdown analysis, retained files, command output, and comparisons beside the graph. |
| **Work across conversations.** A portable Skill lets multiple agent chats contribute to the same experiment. Jump to each conversation’s current nodes, or copy a reference to discuss a specific step. | **Visible progress and cost.** See completed, paused, excluded, and failed work, with captured timing and available Token usage. |

Your agent chooses the research approach. ExpObserver preserves how it develops, including negative results and unfinished questions. Records, revision history, and evidence stay on your computer.

The workspace above comes from a real research session. [Open the same example →](examples/har-study/README.md)

## Quick start

### Ask your agent

Send this instruction to your agent:

> Install and start ExpObserver and its Skill by following https://github.com/EuanTop/exp-observer/blob/main/INSTALL.md.

### Or start it yourself

1. [Download **exp-observer.zip**](https://github.com/EuanTop/exp-observer/releases/latest/download/exp-observer.zip) and extract it.
2. Launch **start.bat** on Windows or **start.command** on macOS. On Linux, run `python3 start.py`.
3. Open **Connect Agent**, connect your research directory, and copy the instruction into your agent chat.

Requires **Python 3.10+**. The ready-to-run package needs no Node.js, pip packages, account, or model API key. [Installation & upgrades →](INSTALL.md)

Then give your agent a research task:

> Use the ExpObserver Skill for experiment `my-study`. Investigate my question, retain the evidence, and keep the experiment up to date as you work.

The Skill can wake the installed platform when it is closed. Records queue locally if the service is unavailable; delivery failures stay visible and retry without rerunning experiments.

The interface defaults to **English**. Choose **简体中文** in the language selector; your choice is remembered. In compact windows, open **More tools** to find it.

<details>
<summary><strong>A closer look: explore a research step and reference it in your next conversation</strong></summary>

![ExpObserver showing the original analysis of a selected node, with its evidence and copy-reference action](docs/screenshots/platform-details.en.png)

Select a node and choose **Copy reference**. Paste it into any agent chat and add your question. The reference carries the experiment and node identity, so the agent can read the latest context.

</details>

## Explore further

[User guide](docs/usage.md) · [Skill](skills/exp-observer/SKILL.md) · [API & data contract](docs/contract.md) · [HAR case](examples/har-study/README.md) · [Exact-search case](examples/real-study/report.md) · [Contributing](CONTRIBUTING.md)

Built with React, TypeScript, Tailwind CSS, React Flow, ELK, and Python. [MIT licensed](LICENSE).
