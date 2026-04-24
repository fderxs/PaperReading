# PaperReading Workflow

这个项目采用半自动的 LLM-in-the-loop 流程：脚本只负责稳定、可重复的机械步骤；论文筛选和精读分析由当前 Codex/Cursor 对话中的模型完成，不在脚本里调用任何大模型 API。

## 每天怎么用

如果想让我从头执行当天流程，直接说：

```text
请按照 DAILY_LLM_IN_THE_LOOP_RUNBOOK.md 跑一遍今天的论文流程。
```

完整操作手册见 `DAILY_LLM_IN_THE_LOOP_RUNBOOK.md`。我会按文档自动运行脚本，并在需要你打开 HTML 选择论文时暂停提醒你。

首次完整运行这个项目时，我会先检查 `tmp/docling_models/` 是否存在。若还没有配置好 `Docling`，我会在图表抽取阶段显式初始化它。这个项目现在只允许使用 `Docling` 抽取 PDF 图表与表格。

## 每日流程

1. 准备当天材料：

```bash
./start_daily_review.sh
```

脚本会爬取 arXiv cs.RO、补充 arXiv 元数据，并生成 `runs/YYYY-MM-DD/llm_filter_task_<arxiv-scope>.md`。

如果中间漏跑了多天，脚本会自动从“上一次运行日期的下一天”补抓到当前 arXiv recent 页面可见的最新日期，并把这些论文统一放进本次运行的日期文件夹。此时相关文件名会使用一个范围标识，例如 `2026-04-21_to_2026-04-24`。

2. 把筛选任务交给 Codex：

```text
请读取 runs/YYYY-MM-DD/llm_filter_task_<arxiv-scope>.md，按任务单完成筛选并生成 HTML。
```

Codex 会生成或更新 `shortlist_vla_planning_<arxiv-scope>.json`，并渲染 `vla_planning_selector_<arxiv-scope>.html`。

3. 打开选择器并保存选择：

```bash
./serve_selector.sh --run-dir runs/YYYY-MM-DD
```

4. 处理已选论文：

```bash
./process_selected_papers.sh --run-dir runs/YYYY-MM-DD
```

脚本会记录偏好、下载 PDF、创建分析文件，并生成 `llm_analysis_task_<arxiv-scope>.md`。

5. 抽取 PDF 图表与表格：

```bash
./extract_pdf_artifacts.sh --run-dir runs/YYYY-MM-DD --write-tmp-text
```

脚本会把图表截图、表格文本和图表索引写入 `runs/YYYY-MM-DD/figures/`、`tables/` 和 `artifacts/`。分析正文里的插图由后续 LLM 精读时按需挑选，不再把所有图表统一挂到文末。这个步骤只支持 `Docling`。

项目首次完整运行时，先显式初始化 `Docling` 模型：

```bash
./extract_pdf_artifacts.sh --run-dir runs/YYYY-MM-DD --backend docling --docling-download-models --write-tmp-text
```

首次初始化完成后，后续每天再用默认命令即可：

```bash
./extract_pdf_artifacts.sh --run-dir runs/YYYY-MM-DD --write-tmp-text
```

6. 把精读任务交给 Codex：

```text
请读取 runs/YYYY-MM-DD/llm_analysis_task_<arxiv-scope>.md，按任务单精读我选择的论文。
```

Codex 会基于 PDF、你的备注和模板补全 `runs/YYYY-MM-DD/analyses/` 中的逐篇分析。

## 目录约定

- `scripts/`：确定性 Python 脚本。
- `runs/YYYY-MM-DD/`：每日抓取、筛选、选择和分析文件。
- `data/`：长期偏好记录、中文摘要缓存和机构缓存。
- `papers/`：统一存放已下载 PDF。
- `tmp/`：临时文件。
- `templates/`：分析模板。
