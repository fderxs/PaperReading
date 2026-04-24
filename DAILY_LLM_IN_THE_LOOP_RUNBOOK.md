# Daily LLM-in-the-loop Runbook

这个文档是每天运行 PaperReading 流程时给 Codex 使用的操作手册。用户只需要说：

```text
请按照 DAILY_LLM_IN_THE_LOOP_RUNBOOK.md 跑一遍今天的论文流程。
```

Codex 应按本文档自动执行该执行的脚本，并只在需要用户打开 HTML 交互选择论文时暂停提醒用户。

## 首次运行前置说明

- 如果这是该项目第一次完整运行，或者 `tmp/docling_models/` 还不存在，Codex 必须记得在第 6 步显式初始化 `Docling`。
- 换句话说，首次完整跑流程时，第 6 步应优先使用：

```bash
./extract_pdf_artifacts.sh --run-dir runs/YYYY-MM-DD --backend docling --docling-download-models --write-tmp-text
```

- 只有在 `tmp/docling_models/` 已经准备好之后，后续每日运行才默认使用：

```bash
./extract_pdf_artifacts.sh --run-dir runs/YYYY-MM-DD --write-tmp-text
```

- Codex 在首次运行时，应主动说明“将先配置 Docling，再继续抽取 PDF 图表与表格”。

## 原则

- 不调用任何大模型 API。所有筛选和精读分析都由当前 Codex/Cursor 对话里的模型完成。
- 脚本只负责爬取、整理、渲染、记录、下载 PDF 和创建文件壳子。
- 需要判断的任务由 Codex 在对话中读取本地文件后完成，包括初筛、中文摘要润色、机构补全和论文精读。
- 每日运行产物都放在 `runs/YYYY-MM-DD/`。
- PDF 统一放在项目根目录 `papers/`。
- 长期偏好和缓存保存在 `data/`，不要为了重跑当天流程而删除。

## 每日执行流程

### 1. 准备当天材料

Codex 在项目根目录运行：

```bash
./start_daily_review.sh
```

预期产物：

```text
runs/YYYY-MM-DD/cs_ro_papers_<arxiv-scope>.json
runs/YYYY-MM-DD/all_papers_metadata_<arxiv-scope>.json
runs/YYYY-MM-DD/llm_filter_task_<arxiv-scope>.md
```

说明：

- `<arxiv-scope>` 可能是单天，如 `2026-04-24`。
- 如果中间漏跑了多天，它也可能是一个范围，如 `2026-04-21_to_2026-04-24`。
- 这些遗漏日期的论文会统一写入本次运行的 `runs/YYYY-MM-DD/` 文件夹。

如果脚本因为网络失败而停止，Codex 应说明失败位置，并在合适时请求重新运行。

### 2. Codex 完成初筛

Codex 读取最新的：

```text
runs/YYYY-MM-DD/llm_filter_task_<arxiv-scope>.md
runs/YYYY-MM-DD/all_papers_metadata_<arxiv-scope>.json
data/paper_preference_records.jsonl
data/summary_zh_cache.json
data/institutions_cache.json
```

筛选目标：

- VLA / Vision-Language-Action。
- 具身规划 / Planning / long-horizon decision making。
- World Model、机器人基础模型、具身智能相关文章。
- 与上述方向相关的综述、数据集、benchmark、评测、安全性、可靠性文章。
- 结合历史偏好，优先保留用户过去选择过的方向和相似问题。

Codex 需要生成或覆盖：

```text
runs/YYYY-MM-DD/shortlist_vla_planning_<arxiv-scope>.json
```

`shortlist` 每篇论文至少包含：

```json
{
  "paper_id": "P01",
  "arxiv_id": "2604.xxxxx",
  "title": "论文标题",
  "pdf_url": "https://arxiv.org/pdf/...",
  "authors": ["作者"],
  "institutions": "机构，无法确认时写待补充",
  "summary": "英文摘要",
  "summary_zh": "中文摘要",
  "tags": ["VLA", "Planning"],
  "score": 18,
  "reason": "为什么推荐/保留"
}
```

如 Codex 补充了中文摘要或机构信息，应同步更新：

```text
data/summary_zh_cache.json
data/institutions_cache.json
```

### 3. 渲染选择器 HTML

Codex 运行：

```bash
python3 scripts/render_selector.py runs/YYYY-MM-DD/shortlist_vla_planning_<arxiv-scope>.json
```

预期产物：

```text
runs/YYYY-MM-DD/vla_planning_selector_<arxiv-scope>.html
```

### 4. 启动本地选择器并暂停等待用户

Codex 运行：

```bash
./serve_selector.sh --run-dir runs/YYYY-MM-DD
```

脚本会输出本地 URL，例如：

```text
http://127.0.0.1:8765/vla_planning_selector_<arxiv-scope>.html
```

Codex 此时应暂停，并明确告诉用户：

```text
请打开上面的 URL，给想深入了解的论文设置优先级或备注，然后点击“保存/覆盖 JSON”。保存成功后告诉我“继续”。
```

用户保存后，预期产物：

```text
runs/YYYY-MM-DD/selected_vla_planning_papers_<arxiv-scope>.json
```

### 5. 处理用户选择

用户说“继续”后，Codex 先确认选择 JSON 是否存在。若不存在，应提醒用户回到 HTML 点击保存。

若存在，Codex 运行：

```bash
./process_selected_papers.sh --run-dir runs/YYYY-MM-DD
```

预期产物：

```text
data/paper_preference_records.jsonl
papers/*.pdf
runs/YYYY-MM-DD/selection_record_<arxiv-scope>.json
runs/YYYY-MM-DD/analyses/*.md
runs/YYYY-MM-DD/llm_analysis_task_<arxiv-scope>.md
```

如果 PDF 下载因为网络失败而停止，Codex 应说明失败论文，并请求重新运行或跳过。

### 6. 抽取 PDF 图表与表格

Codex 运行：

```bash
./extract_pdf_artifacts.sh --run-dir runs/YYYY-MM-DD --write-tmp-text
```

预期产物：

```text
runs/YYYY-MM-DD/figures/*.png
runs/YYYY-MM-DD/tables/*.md
runs/YYYY-MM-DD/artifacts/*.json
tmp/pdf_text/*.txt
```

这个步骤只允许使用 `Docling`。

如果是项目首次完整运行，或 `tmp/docling_models/` 尚不存在，Codex 应显式运行：

```bash
./extract_pdf_artifacts.sh --run-dir runs/YYYY-MM-DD --backend docling --docling-download-models --write-tmp-text
```

`Docling` 模型会缓存到 `tmp/docling_models/`。首次运行完成后，后续每日流程直接使用默认命令即可。若某些论文图表是复杂跨页、跨栏或附录长表，自动抽取虽然通常优于通用 PDF 裁剪，但仍可能需要人工复核，Codex 应在分析中说明。这个步骤只负责生成 `artifacts/`、`figures/` 和 `tables/` 支撑材料，不应把所有图表统一追加到分析文件末尾。

### 7. Codex 完成精读分析

Codex 读取：

```text
runs/YYYY-MM-DD/llm_analysis_task_<arxiv-scope>.md
runs/YYYY-MM-DD/selected_vla_planning_papers_<arxiv-scope>.json
runs/YYYY-MM-DD/selection_record_<arxiv-scope>.json
data/paper_preference_records.jsonl
templates/analysis_template.md
papers/*.pdf
runs/YYYY-MM-DD/figures/*.png
runs/YYYY-MM-DD/tables/*.md
runs/YYYY-MM-DD/artifacts/*.json
```

Codex 应按优先级处理：

```text
A -> B -> C
```

每篇分析写入对应文件：

```text
runs/YYYY-MM-DD/analyses/*.md
```

分析必须覆盖：

- 一句话结论。
- 论文定位。
- 背景与动机。
- 核心贡献。
- 方法详解。
- 实验与结果。
- 对用户有用的启发。
- 局限与疑问。
- 是否值得继续读。
- 用户备注中的具体问题。

如果 PDF 中有关键图表，Codex 应只挑真正有帮助的 1 到 3 张插入正文相关段落，例如：

- 方法总览/架构图插入 `5. 方法详解`
- 主结果表/benchmark 对比表插入 `6. 实验与结果`
- 消融表只在确实支撑正文判断时插入

不要把所有图表在文末再列一遍。完整抽取结果已经保留在：

```text
runs/YYYY-MM-DD/figures/
```

## 完成时汇报

流程完成后，Codex 应简要汇报：

- 本次爬取日期。
- 初筛保留论文数量。
- 用户最终选择数量。
- 已下载 PDF 数量。
- 已生成或更新的分析文件位置。
- 是否存在未完成项或需要用户确认的问题。

## 常用触发语

从头开始当天流程：

```text
请按照 DAILY_LLM_IN_THE_LOOP_RUNBOOK.md 跑一遍今天的论文流程。
```

用户完成 HTML 选择后继续：

```text
继续，已经保存 JSON。
```

只做精读阶段：

```text
请读取最新的 llm_analysis_task，继续精读分析。
```
