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
请读取 runs/YYYY-MM-DD/llm_filter_task_<arxiv-scope>.md，按任务单完成筛选并生成 reading dashboard。
```

Codex 会生成或更新 `shortlist_vla_planning_<arxiv-scope>.json`，并渲染全局唯一入口 `dashboard/reading_dashboard.html`。

初筛时 `institutions` 字段必须尽量补全。处理顺序是：先用 `data/institutions_cache.json`，再看 arXiv HTML/ar5iv 页面作者区，必要时查 Semantic Scholar/OpenAlex/Google Scholar 等学术元数据页；无法确认就写 `待补充`。不要为了机构下载 PDF、arXiv e-print 源码，或创建 `tmp/institution_src_probe` 这类源码探测目录。

3. 打开 reading dashboard 并保存选择：

```bash
./start_dashboard.sh --run-dir runs/YYYY-MM-DD
```

4. 处理已选论文：

```bash
./process_selected_papers.sh --run-dir runs/YYYY-MM-DD
```

脚本会记录偏好、下载 PDF、创建分析文件，并生成 `llm_analysis_task_<arxiv-scope>.md`。同时会生成 `reading_manifest_<arxiv-scope>.json` 和 `reading_status_<arxiv-scope>.json`，并刷新全局 `dashboard/reading_dashboard.html`，用于后续交互式阅读。

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

7. 打开阅读台：

```bash
./start_dashboard.sh --run-dir runs/YYYY-MM-DD
```

脚本会自动选择可用端口并打开浏览器。阅读台是唯一入口：左侧归档目录按 `runs/YYYY-MM-DD/` 自动整理成日期、月份和年份；点击任意日期、月份或年份会显示对应范围内的论文。列表页显示已选论文、统一主题标签、阅读 ID、已读/未读和精读状态，并支持按优先级、主题标签和关键词筛选。

阅读台顶部可以在“阅读列表”和“论文挑选”之间切换。论文挑选视图直接读取对应日期的 `shortlist_vla_planning_<arxiv-scope>.json`，可设置 A/B/C 级别和备注，并保存回 `selected_vla_planning_papers_<arxiv-scope>.json`。

阅读页右侧是英文 PDF，左侧可在分析 Markdown 与中文 PDF 之间切换。“已读”和“精读”按钮会保存到 `reading_status_<arxiv-scope>.json`。主题标签会从 shortlist 的 `tags` 与分析文档 `论文定位` 中的方向字段汇总归一，每篇最多展示 3 个。标签池固定在 dashboard 渲染脚本中；新主题不要直接进入页面，需要先确认后再加入标签池。目前继续使用 JSON 文件记录状态，这些文件规模小、可直接人工查看，暂不引入数据库。

8. 处理精读翻译：

```bash
./process_intensive_papers.sh --run-dir runs/YYYY-MM-DD
```

脚本会读取阅读台中标记为“精读”的论文，将这些选择写入偏好记录，并在 `runs/YYYY-MM-DD/paper_cn/` 下准备 arXiv 源码、中文翻译源码目录、编译脚本和 `llm_intensive_translation_task_<arxiv-scope>.md`。完成翻译并编译出 `paper_cn.pdf` 后，重新运行第 4 步或刷新阅读台，中文 PDF 会出现在阅读页左侧切换视图中。

中文 PDF 面板支持网页内文字便签和高亮框标注。“保存到PDF”会通过本地 `serve_selector.sh` server 覆盖写回 `runs/YYYY-MM-DD/paper_cn/<RID>_<arxiv_id>/paper_cn.pdf`，并在同目录生成 `paper_cn.before_notes_<timestamp>.pdf` 备份。中文 PDF 页面由服务端使用 `PyMuPDF` 渲染为 PNG，以避免浏览器 PDF.js 对中文字体/编码渲染不稳定；保存写回由前端 `pdf-lib` 完成。

如果首次使用中文 PDF 标注时缺少依赖，安装：

```bash
python3 -m pip install PyMuPDF
```

## 本机 LaTeX 环境

精读翻译会基于 arXiv 源码生成中文 LaTeX，并通过 `compile_cn.sh` 编译 `paper_cn.pdf`。本机当前使用轻量 TinyTeX，而不是完整 MacTeX：

- 安装目录：`~/Library/TinyTeX`
- 常用命令入口：`~/.local/bin/latexmk`、`~/.local/bin/xelatex`、`~/.local/bin/tlmgr`
- Shell 配置：`~/.zshrc` 和 `~/.zprofile` 已加入 `~/.local/bin` 与 `~/Library/TinyTeX/bin/universal-darwin`
- 已验证工具：`latexmk`、`xelatex`、`xdvipdfmx`
- 已补充常用包：`ctex`、`xeCJK`、`fandol`、`zhnumber`、`algorithmicx`、`algorithms`、`caption`、`cleveref`、`multirow`、`makecell`、`siunitx`、`pgf`、`mathtools`、`bbm`、`stmaryrd`、`physics`、`enumitem`、`subfig`、`wrapfig`、`sttools`、`threeparttable`

如果中文源码需要加入 `ctex`，优先使用 TinyTeX 自带 Fandol 字体，避免依赖本机系统字体：

```tex
\documentclass[UTF8,fontset=fandol]{ctexart}
```

或：

```tex
\usepackage[fontset=fandol]{ctex}
```

单篇精读翻译完成后，在对应目录运行：

```bash
cd runs/YYYY-MM-DD/paper_cn/<RID>_<arxiv_id>
./compile_cn.sh
```

若提示缺少 LaTeX 包，优先用 `tlmgr install <package>` 小范围补装，不要安装 `collection-latexextra` 这类大集合。

## 清理临时文件

项目中 `runs/`、`papers/`、`data/` 都承载阅读结果或长期状态，不应随意清空。定期清理请先 dry-run：

```bash
./cleanup_run_artifacts.sh
```

确认列表无误后再执行删除：

```bash
./cleanup_run_artifacts.sh --apply
```

默认会清理 `tmp/` 下可重新生成的 arXiv HTML/source 探测结果、PDF 文本缓存、溢出版面检查截图、LaTeX 测试目录和 `pycache`，并清理 `runs/` 中 LaTeX 编译辅助文件。对于超过 30 天的 run，还会删除未被 `analyses/*.md` 引用的 `figures/` 和 `tables/` 文件。不会删除分析 Markdown、阅读台 HTML、原始 PDF、中文 PDF 正本或 `tmp/docling_models/`。若确实要删除 Docling 模型缓存，可额外加 `--include-model-cache`，之后下次抽图表会重新下载模型。

## 目录约定

- `scripts/`：确定性 Python 脚本。
- `runs/YYYY-MM-DD/`：每日抓取、筛选、选择和分析文件。
- `data/`：长期偏好记录、中文摘要缓存和机构缓存。
- `papers/`：统一存放已下载 PDF。
- `runs/YYYY-MM-DD/paper_cn/`：精读论文中文翻译源码与编译后的中文 PDF。
- `tmp/`：临时文件。
- `templates/`：分析模板。
