# Daily LLM-in-the-loop Runbook

这个文档是每天运行 PaperReading 流程时给 Codex 使用的操作手册。用户只需要说：

```text
请按照 DAILY_LLM_IN_THE_LOOP_RUNBOOK.md 跑一遍今天的论文流程。
```

Codex 应按本文档自动执行该执行的脚本，并只在需要用户打开 HTML 交互选择论文时暂停提醒用户。

## 首次运行前置说明

- 如果这是该项目第一次完整运行，或者 `tmp/docling_models/` 还不存在，Codex 必须记得在第 6 步显式初始化 `Docling`。
- 如果要处理精读全文翻译，Codex 应先确认本机 LaTeX 工具可用。本机推荐使用轻量 TinyTeX，安装目录为 `~/Library/TinyTeX`，命令入口通过 `~/.local/bin` 和 `~/Library/TinyTeX/bin/universal-darwin` 加入 `~/.zshrc`、`~/.zprofile`。
- 换句话说，首次完整跑流程时，第 6 步应优先使用：

```bash
./extract_pdf_artifacts.sh --run-dir runs/YYYY-MM-DD --backend docling --docling-download-models --write-tmp-text
```

- 只有在 `tmp/docling_models/` 已经准备好之后，后续每日运行才默认使用：

```bash
./extract_pdf_artifacts.sh --run-dir runs/YYYY-MM-DD --write-tmp-text
```

- Codex 在首次运行时，应主动说明“将先配置 Docling，再继续抽取 PDF 图表与表格”。
- 精读翻译前可用以下命令检查 LaTeX 环境：

```bash
zsh -l -c 'command -v latexmk && command -v xelatex && command -v xdvipdfmx'
```

预期能找到 `latexmk`、`xelatex` 和 `xdvipdfmx`。如果缺包，优先执行 `tlmgr install <package>` 小范围补装；不要安装 `collection-latexextra`、`scheme-full` 这类大集合。

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

机构信息对用户筛选很重要。Codex 必须对进入 `shortlist` 的论文补全 `institutions` 字段，处理顺序如下：

1. 先查 `data/institutions_cache.json`，已有缓存直接使用。
2. 缓存没有时，优先查看 arXiv abstract 页面右侧的 `HTML` / `HTML (experimental)`，或直接访问 `https://ar5iv.labs.arxiv.org/html/<arxiv_id>` / `https://ar5iv.org/html/<arxiv_id>`，只读取页面开头作者区的 affiliation。
3. 若 arXiv HTML/ar5iv 不可用，可用论文标题或 arXiv ID 查询 Semantic Scholar、OpenAlex、Google Scholar 等学术元数据页面，只记录能明确确认的机构。
4. 如果无法快速、可靠确认，`institutions` 写 `"待补充"`，不要编造，不要从作者当前主页推断。
5. 成功确认后，把 `data/institutions_cache.json` 更新为 `{"<arxiv_id>": "机构1; 机构2"}` 这类简单映射。

禁止事项：

- 不要为了机构信息下载 PDF。
- 不要为了机构信息下载 `https://arxiv.org/e-print/<arxiv_id>` 源码。
- 不要为了机构信息创建或保存 `tmp/institution_src_probe`、`tmp/arxiv_src_*` 等源码探测目录。
- arXiv 源码下载只允许出现在后续“精读全文翻译”流程中，不属于初筛机构补全。

### 3. 渲染 reading dashboard

Codex 运行：

```bash
python3 scripts/render_reading_dashboard.py --shortlist runs/YYYY-MM-DD/shortlist_vla_planning_<arxiv-scope>.json
```

预期产物：

```text
dashboard/reading_dashboard.html
```

### 4. 启动本地 dashboard 并暂停等待用户

Codex 运行：

```bash
./start_dashboard.sh --run-dir runs/YYYY-MM-DD
```

脚本会输出本地 URL，例如：

```text
http://127.0.0.1:8765/dashboard/reading_dashboard.html
```

Codex 此时应暂停，并明确告诉用户：

```text
请打开上面的 URL，在“论文挑选”视图里给想深入了解的论文设置优先级或备注，然后点击“保存选择”。保存成功后告诉我“继续”。
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
dashboard/reading_dashboard.html
runs/YYYY-MM-DD/reading_manifest_<arxiv-scope>.json
runs/YYYY-MM-DD/reading_status_<arxiv-scope>.json
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

### 8. 打开交互式阅读台

精读分析完成后，Codex 可继续使用同一个本地 server：

```bash
./start_dashboard.sh --run-dir runs/YYYY-MM-DD
```

脚本会自动选择可用端口并打开，URL 形如：

```text
http://127.0.0.1:8765/dashboard/reading_dashboard.html
```

阅读台是唯一交互入口。标题页左侧有历史归档目录，按 `runs/YYYY-MM-DD/` 自动整理为日期、月份和年份；点击日期、月份或年份会显示对应范围内的论文。列表页显示用户选中的论文列表，包括统一阅读 ID、arXiv ID、优先级、主题标签、已读/未读和精读状态，并支持按关键词、优先级和主题标签筛选。

阅读台顶部可以切换“阅读列表”和“论文挑选”。论文挑选视图直接读取对应日期的 `shortlist_vla_planning_<arxiv-scope>.json`，可设置 A/B/C 级别和备注，并保存回：

```text
runs/YYYY-MM-DD/selected_vla_planning_papers_<arxiv-scope>.json
```

因此，历史选择和当天选择都在同一个全局 `dashboard/reading_dashboard.html` 完成。`runs/YYYY-MM-DD/` 只保留数据、manifest、status、分析和论文相关产物，不再保存 dashboard HTML。

用户点击论文后进入阅读页，右侧显示英文 PDF 原文，左侧可在 `analyses/*.md` 分析文档和中文 PDF 之间切换。已读和精读状态会保存在：

```text
runs/YYYY-MM-DD/reading_status_<arxiv-scope>.json
```

用户后续提问时可直接引用阅读 ID，例如 `R03`。

主题标签来源：

- `shortlist_vla_planning_<arxiv-scope>.json` 中每篇论文的 `tags`。
- 分析文档中 `论文定位` 表格的 `方向` 字段。

渲染阅读台时会使用固定标签池做归一，例如 VLA、规划/长时程、世界模型、数据集/基准、可靠性/安全、机器人操作等，每篇最多展示 3 个主题标签。源数据里未进入固定池的新标签不会自动出现在页面；如果确实需要新增主题标签，先向用户说明拟新增标签和理由，确认后再修改标签池。当前状态文件仍使用 JSON：`reading_status_*.json`、`selected_vla_planning_papers_*.json` 和 dashboard 内嵌索引已经足够小、可人工审查，暂不引入数据库。

### 9. 继续处理精读翻译

用户看完当天论文并在阅读台中标记“精读”后，如果输入“继续指令”，Codex 应先运行：

```bash
./process_intensive_papers.sh --run-dir runs/YYYY-MM-DD
```

该脚本会：

- 自动读取 `reading_status_<arxiv-scope>.json` 中 `intensive=true` 的论文。
- 将精读选择写入 `data/paper_preference_records.jsonl`，`preference_stage` 为 `intensive_translation`。
- 下载 `https://arxiv.org/e-print/<arxiv_id>` 源码并解包到 `runs/YYYY-MM-DD/paper_cn/<RID>_<arxiv_id>/source_original/`。
- 复制一份待翻译源码到 `source_cn/`。
- 写入每篇论文的 `TRANSLATION_TASK.md`、`compile_cn.sh`，以及总任务 `llm_intensive_translation_task_<arxiv-scope>.md`。

随后 Codex 按任务要求翻译 `source_cn/` 中的 LaTeX 源码，保持公式、引用、label 和文件结构可编译；英文正文翻译成中文，caption 和必要注释翻译，姓名不翻译。完成后运行对应 `compile_cn.sh`，目标 PDF 为：

```text
runs/YYYY-MM-DD/paper_cn/<RID>_<arxiv_id>/paper_cn.pdf
```

LaTeX 编译约定：

- `process_intensive_papers.sh` 生成的 `compile_cn.sh` 会主动加入 TinyTeX 路径，通常直接运行即可。
- 中文支持优先使用 `xelatex` + `ctex`/`xeCJK`。
- 如果需要新增 `ctex` 支持，优先使用 TinyTeX 自带 Fandol 字体，例如 `\documentclass[UTF8,fontset=fandol]{ctexart}` 或 `\usepackage[fontset=fandol]{ctex}`。
- 不要依赖 `STHeiti` 等 macOS 系统字体；这会让源码在本机或其他环境中更容易编译失败。
- 已常备的包包括 `ctex`、`xeCJK`、`fandol`、`zhnumber`、`algorithmicx`、`algorithms`、`caption`、`cleveref`、`multirow`、`makecell`、`siunitx`、`pgf`、`mathtools`、`bbm`、`stmaryrd`、`physics`、`enumitem`、`subfig`、`wrapfig`、`sttools`、`threeparttable`。遇到新的缺包再用 `tlmgr install <package>` 补装。

中文 PDF 面板支持网页内文字便签和高亮框标注。“保存到PDF”会通过本地 `serve_selector.sh` server 覆盖写回 `runs/YYYY-MM-DD/paper_cn/<RID>_<arxiv_id>/paper_cn.pdf`，并在同目录生成 `paper_cn.before_notes_<timestamp>.pdf` 备份。中文 PDF 页面由服务端使用 `PyMuPDF` 渲染为 PNG，以避免浏览器 PDF.js 对中文字体/编码渲染不稳定；保存写回由前端 `pdf-lib` 完成。

如果本地缺少 `PyMuPDF`，先安装：

```bash
python3 -m pip install PyMuPDF
```

## 完成时汇报

流程完成后，Codex 应简要汇报：

- 本次爬取日期。
- 初筛保留论文数量。
- 用户最终选择数量。
- 已下载 PDF 数量。
- 已生成或更新的分析文件位置。
- 阅读台 HTML 和阅读状态 JSON 位置。
- 如处理了精读翻译，汇报 `paper_cn/` 工作目录和中文 PDF 编译结果。
- 是否存在未完成项或需要用户确认的问题。

## 定期清理

当 `tmp/` 或 LaTeX 编译辅助文件变多时，Codex 应先 dry-run：

```bash
./cleanup_run_artifacts.sh
```

确认只包含可重新生成的临时产物后，再执行：

```bash
./cleanup_run_artifacts.sh --apply
```

默认清理范围包括 `tmp/arxiv_html_*`、`tmp/arxiv_src_*`、`tmp/pdf_text`、`tmp/pdf-overflow-check`、`tmp/latex-test`、`tmp/docling_probe`、`tmp/pycache`，以及 `runs/` 下的 LaTeX 辅助文件如 `.aux`、`.log`、`.out`、`.fls`、`.fdb_latexmk`、`.xdv`。对于超过 30 天且已有 `analyses/*.md` 的 run，还会删除未被分析文档引用的 `figures/` 和 `tables/` 文件；可用 `--unused-artifact-days N` 调整阈值。不要删除分析 Markdown、阅读台 HTML、原始 PDF、中文 PDF 正本、`data/` 长期状态或 `tmp/docling_models/`，除非用户明确要求。

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
