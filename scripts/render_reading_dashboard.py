#!/usr/bin/env python3
"""Render an interactive reading dashboard for selected papers."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def relpath(path: Path, start: Path) -> str:
    return os.path.relpath(path, start).replace(os.sep, "/")


def reading_id(index: int) -> str:
    return f"R{index:02d}"


def find_cn_pdf(run_dir: Path, read_id: str, arxiv_id: str) -> str:
    paper_cn_dir = run_dir / "paper_cn"
    candidates = [
        paper_cn_dir / f"{read_id}_{arxiv_id}" / "paper_cn.pdf",
        paper_cn_dir / f"{read_id}_{arxiv_id}" / "translated.pdf",
        paper_cn_dir / f"{read_id}_{arxiv_id}" / f"{arxiv_id}_cn.pdf",
        paper_cn_dir / arxiv_id / "paper_cn.pdf",
        paper_cn_dir / arxiv_id / f"{arxiv_id}_cn.pdf",
    ]
    for candidate in candidates:
        if candidate.exists():
            return relpath(candidate.resolve(), run_dir.resolve())
    return ""


def build_manifest(
    root: Path,
    run_dir: Path,
    arxiv_date: str,
    analysis_items: List[Dict[str, object]],
) -> Dict[str, object]:
    papers = []
    for index, item in enumerate(analysis_items, 1):
        record = item["record"]
        pdf_path = Path(str(item["pdf_path"])).resolve()
        analysis_path = Path(str(item["analysis_path"])).resolve()
        read_id = reading_id(index)
        arxiv_id = str(record.get("arxiv_id", ""))
        papers.append(
            {
                "reading_id": read_id,
                "selector_id": str(record.get("paper_id", "")),
                "arxiv_id": arxiv_id,
                "title": str(record.get("title", "")),
                "priority": str(record.get("priority", "")),
                "notes": str(record.get("notes", "")),
                "tags": list(record.get("tags", [])),
                "pdf_path": relpath(pdf_path, run_dir),
                "analysis_path": relpath(analysis_path, run_dir),
                "cn_pdf_path": find_cn_pdf(run_dir, read_id, arxiv_id),
                "pdf_file": pdf_path.name,
                "analysis_file": analysis_path.name,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_date": run_dir.name,
        "arxiv_date": arxiv_date,
        "root": relpath(root.resolve(), run_dir.resolve()),
        "paper_count": len(papers),
        "papers": papers,
    }


def render_html(manifest: Dict[str, object]) -> str:
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    title = f"{manifest['arxiv_date']} 论文阅读台"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --ink: #1f2528;
      --muted: #687277;
      --line: #d8dedb;
      --bg: #f6f7f3;
      --panel: #ffffff;
      --accent: #226b5f;
      --accent-soft: #e0f0ec;
      --warn: #8a5b12;
      --shadow: 0 14px 36px rgba(31, 37, 40, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    header {{
      height: 68px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 0 20px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.94);
      position: sticky;
      top: 0;
      z-index: 5;
    }}
    h1 {{ font-size: 1.12rem; margin: 0; }}
    .summary {{ color: var(--muted); font-size: 0.92rem; }}
    .hidden {{ display: none !important; }}
    .list-view {{
      min-height: calc(100vh - 68px);
      padding: 18px;
      max-width: 1180px;
      margin: 0 auto;
      width: 100%;
    }}
    .filters {{
      display: grid;
      grid-template-columns: 1fr 120px;
      gap: 8px;
      margin-bottom: 14px;
    }}
    input[type="search"], select {{
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 9px;
      background: white;
      color: var(--ink);
    }}
    #paperList {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      grid-auto-rows: 158px;
      gap: 12px;
    }}
    .paper-row {{
      display: grid;
      grid-template-columns: 1fr;
      height: 158px;
      padding: 13px;
      border: 1px solid #f0c4bd;
      border-radius: 8px;
      background: #fff2ef;
      cursor: pointer;
      box-shadow: 0 1px 0 rgba(31, 37, 40, 0.03);
      overflow: hidden;
    }}
    .paper-row:hover, .paper-row.active {{
      border-color: #d57f72;
      background: #ffe9e4;
    }}
    .paper-row.read {{
      border-color: #a8d4bf;
      background: #eef8f1;
    }}
    .paper-row.read:hover, .paper-row.read.active {{
      border-color: #72b28f;
      background: #e2f2e8;
    }}
    .paper-row.read .row-title {{ color: #4f675b; }}
    .paper-row.intensive {{
      border-color: #124c36;
      background: linear-gradient(135deg, #174c38, #0f3c2f);
      color: #f4fff8;
      box-shadow: 0 12px 28px rgba(15, 60, 47, 0.18);
    }}
    .paper-row.intensive:hover, .paper-row.intensive.active {{
      border-color: #72c49a;
      background: linear-gradient(135deg, #1d5c44, #124635);
    }}
    .paper-row.intensive .row-id,
    .paper-row.intensive .row-title,
    .paper-row.intensive .row-meta {{ color: #f4fff8; }}
    .paper-row.intensive .pill {{
      background: rgba(255, 255, 255, 0.14);
      color: #f4fff8;
      border: 1px solid rgba(255, 255, 255, 0.18);
    }}
    .row-body {{
      min-height: 0;
      display: flex;
      flex-direction: column;
      height: 100%;
    }}
    .row-id {{ font-weight: 800; color: var(--accent); font-size: 0.86rem; }}
    .row-title {{
      margin: 4px 0 10px;
      font-weight: 650;
      font-size: 0.94rem;
      line-height: 1.35;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .row-meta {{ display: flex; flex-wrap: wrap; gap: 6px; color: var(--muted); font-size: 0.78rem; }}
    .row-meta {{ margin-top: auto; align-items: flex-end; }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-height: 21px;
      padding: 1px 7px;
      border-radius: 999px;
      background: #eef2ef;
      color: #435049;
    }}
    .pill.priority-a {{ background: #ffe7cc; color: #7a420b; }}
    .pill.priority-b {{ background: #e4edf9; color: #285078; }}
    .pill.priority-c {{ background: #eeeeee; color: #555; }}
    .reader-view {{
      min-height: calc(100vh - 68px);
    }}
    .reader-top {{
      height: 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 0 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
    }}
    .toolbar-left, .toolbar-right {{
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }}
    .toolbar-left {{
      flex: 1 1 auto;
    }}
    .toolbar-right {{
      flex: 0 0 auto;
      margin-left: auto;
    }}
    .toolbar-button {{
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--ink);
      cursor: pointer;
      padding: 4px 10px;
      font: inherit;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      white-space: nowrap;
    }}
    .toolbar-button.primary {{
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }}
    .toolbar-button.read {{
      border-color: #8aa79e;
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .toolbar-button.intensive {{
      border-color: #124c36;
      background: #124c36;
      color: white;
    }}
    .view-toggle {{
      display: inline-flex;
      border: 1px solid var(--line);
      border-radius: 7px;
      overflow: hidden;
      background: white;
    }}
    .view-toggle button {{
      min-height: 32px;
      border: 0;
      border-right: 1px solid var(--line);
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      padding: 4px 10px;
      font: inherit;
    }}
    .view-toggle button:last-child {{ border-right: 0; }}
    .view-toggle button.active {{
      background: var(--accent);
      color: white;
    }}
    .reader-grid {{
      display: grid;
      grid-template-columns: minmax(360px, 48%) minmax(360px, 52%);
      min-width: 0;
    }}
    .reader-pane, .pdf-pane {{
      min-width: 0;
      height: calc(100vh - 116px);
      overflow: hidden;
      background: var(--panel);
    }}
    .current-id {{ color: var(--accent); font-weight: 800; }}
    .read-state {{ background: #f1f3f1; color: #56625d; }}
    .read-state.done {{ background: var(--accent-soft); color: var(--accent); }}
    .intensive-state {{ background: #124c36; color: white; }}
    #analysis {{
      height: 100%;
      overflow: auto;
      padding: 22px 28px 60px;
      font-size: 0.96rem;
    }}
    #analysis h1, #analysis h2, #analysis h3 {{ line-height: 1.25; }}
    #analysis h1 {{ font-size: 1.55rem; margin: 0 0 18px; }}
    #analysis h2 {{ font-size: 1.18rem; margin-top: 26px; }}
    #analysis h3 {{ font-size: 1rem; margin-top: 20px; }}
    #analysis pre {{
      overflow: auto;
      padding: 12px;
      background: #f0f2ef;
      border-radius: 6px;
    }}
    #analysis table {{ width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 0.88rem; }}
    #analysis th, #analysis td {{ border: 1px solid var(--line); padding: 7px; vertical-align: top; }}
    #analysis th {{ background: #f1f5f2; text-align: left; }}
    #analysis img {{ max-width: 100%; border: 1px solid var(--line); box-shadow: var(--shadow); }}
    iframe {{
      width: 100%;
      height: 100%;
      border: 0;
      background: #e8ece9;
    }}
    #cnPdfFrame {{ background: #f1f5f2; }}
    .cn-annotator {{
      height: 100%;
      display: flex;
      flex-direction: column;
      min-width: 0;
      background: #eef2ef;
    }}
    .note-toolbar {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
      flex-wrap: wrap;
    }}
    .note-toolbar button {{
      min-height: 30px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--ink);
      cursor: pointer;
      padding: 4px 9px;
      font: inherit;
      white-space: nowrap;
    }}
    .note-toolbar button.active {{
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }}
    .note-toolbar button.save {{
      border-color: #124c36;
      background: #124c36;
      color: white;
    }}
    .note-status {{
      color: var(--muted);
      font-size: 0.82rem;
      min-width: 120px;
    }}
    .cn-pages {{
      flex: 1 1 auto;
      overflow: auto;
      padding: 14px;
    }}
    .cn-page {{
      position: relative;
      margin: 0 auto 18px;
      background: white;
      box-shadow: 0 10px 28px rgba(31, 37, 40, 0.16);
      line-height: 0;
    }}
    .cn-page canvas {{
      display: block;
    }}
    .cn-page img {{
      display: block;
      width: 100%;
      height: 100%;
    }}
    .cn-annotation-layer {{
      position: absolute;
      inset: 0;
      cursor: crosshair;
    }}
    .empty {{
      padding: 30px;
      color: var(--muted);
    }}
    @media (max-width: 1040px) {{
      #paperList {{ grid-template-columns: 1fr; }}
      .reader-grid {{ grid-template-columns: 1fr; }}
      .reader-pane, .pdf-pane {{ height: 70vh; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>{title}</h1>
      <div class="summary"><span id="progress">0/0</span> 已读；点击列表项进入阅读界面，提问时可引用阅读 ID。</div>
    </div>
    <div class="summary">状态会保存到浏览器；通过本地 server 打开时也会写入 JSON。</div>
  </header>
  <div id="listView" class="list-view">
      <div class="filters">
        <input id="query" type="search" placeholder="搜索标题 / ID / arXiv">
        <select id="priority">
          <option value="">全部级别</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
        </select>
      </div>
      <div id="paperList"></div>
  </div>
  <main id="readerView" class="reader-view hidden">
    <div class="reader-top">
      <div class="toolbar-left">
        <button id="backToList" class="toolbar-button" type="button">返回列表</button>
        <span class="current-id" id="readerId">--</span>
        <div class="view-toggle" aria-label="左侧面板">
          <button id="analysisMode" class="active" type="button">分析</button>
          <button id="cnPdfMode" type="button">中文PDF</button>
        </div>
      </div>
      <div class="toolbar-right">
        <button id="readToggle" class="toolbar-button primary" type="button">标记已读</button>
        <button id="intensiveToggle" class="toolbar-button" type="button">精读</button>
        <a id="sourceLink" class="toolbar-button" href="#" target="_blank" rel="noopener">打开源文件</a>
      </div>
    </div>
    <div class="reader-grid">
      <section class="reader-pane">
        <article id="analysis"><div class="empty">从列表选择一篇论文开始阅读。</div></article>
        <iframe id="cnPdfFrame" class="hidden" title="中文 PDF"></iframe>
        <div id="cnAnnotator" class="cn-annotator hidden">
          <div class="note-toolbar">
            <button id="noteTool" class="active" type="button">文字便签</button>
            <button id="highlightTool" type="button">高亮框</button>
            <button id="saveCnPdf" class="save" type="button">保存到PDF</button>
            <button id="clearCnNotes" type="button">清空未保存</button>
            <span id="cnNoteStatus" class="note-status"></span>
          </div>
          <div id="cnPages" class="cn-pages"></div>
        </div>
        <div id="cnEmpty" class="empty hidden"></div>
      </section>
      <section class="pdf-pane">
        <iframe id="pdfFrame" title="PDF"></iframe>
      </section>
    </div>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.min.js"></script>
  <script>
    const manifest = {manifest_json};
    const storageKey = `paper-reading-status:${{manifest.run_date}}:${{manifest.arxiv_date}}`;
    let status = loadStatus();
    let current = null;
    let leftMode = "analysis";
    let cnState = {{
      paperKey: "",
      pdfBytes: null,
      pdfDocument: null,
      annotations: [],
      pages: [],
      tool: "note",
      drawing: null
    }};

    const listView = document.querySelector("#listView");
    const readerView = document.querySelector("#readerView");
    const list = document.querySelector("#paperList");
    const query = document.querySelector("#query");
    const priority = document.querySelector("#priority");
    query.addEventListener("input", renderList);
    priority.addEventListener("change", renderList);
    document.querySelector("#backToList").addEventListener("click", showList);
    document.querySelector("#readToggle").addEventListener("click", () => {{
      if (current) setRead(current, !isRead(current));
    }});
    document.querySelector("#intensiveToggle").addEventListener("click", () => {{
      if (current) setIntensive(current, !isIntensive(current));
    }});
    document.querySelector("#analysisMode").addEventListener("click", () => setLeftMode("analysis"));
    document.querySelector("#cnPdfMode").addEventListener("click", () => setLeftMode("cn"));
    document.querySelector("#noteTool").addEventListener("click", () => setNoteTool("note"));
    document.querySelector("#highlightTool").addEventListener("click", () => setNoteTool("highlight"));
    document.querySelector("#saveCnPdf").addEventListener("click", saveCnPdfNotes);
    document.querySelector("#clearCnNotes").addEventListener("click", clearCnNotes);

    function loadStatus() {{
      try {{ return JSON.parse(localStorage.getItem(storageKey) || "{{}}"); }}
      catch (_) {{ return {{}}; }}
    }}
    function saveLocalStatus() {{
      localStorage.setItem(storageKey, JSON.stringify(status));
      renderProgress();
    }}
    async function loadServerStatus() {{
      try {{
        const response = await fetch(`/reading-status?arxiv_date=${{encodeURIComponent(manifest.arxiv_date)}}`);
        const result = await response.json();
        if (response.ok && result.ok && result.status && Array.isArray(result.status.read_papers)) {{
          for (const item of result.status.read_papers) {{
            if (item.reading_id) status[item.reading_id] = {{
              read: Boolean(item.read),
              read_at: item.read_at || "",
              intensive: Boolean(item.intensive),
              intensive_at: item.intensive_at || ""
            }};
          }}
          saveLocalStatus();
          renderList();
        }}
      }} catch (_) {{}}
    }}
    async function saveServerStatus() {{
      const read_papers = manifest.papers.map((paper) => ({{
        reading_id: paper.reading_id,
        selector_id: paper.selector_id || "",
        arxiv_id: paper.arxiv_id,
        read: Boolean(status[paper.reading_id]?.read),
        read_at: status[paper.reading_id]?.read_at || "",
        intensive: Boolean(status[paper.reading_id]?.intensive),
        intensive_at: status[paper.reading_id]?.intensive_at || ""
      }}));
      try {{
        await fetch("/save-reading-status", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json;charset=utf-8" }},
          body: JSON.stringify({{
            run_date: manifest.run_date,
            arxiv_date: manifest.arxiv_date,
            updated_at: new Date().toISOString(),
            read_papers
          }})
        }});
      }} catch (_) {{}}
    }}
    function setRead(paper, read) {{
      const prior = status[paper.reading_id] || {{}};
      status[paper.reading_id] = {{ ...prior, read, read_at: read ? new Date().toISOString() : "" }};
      saveLocalStatus();
      saveServerStatus();
      renderList();
      if (current && current.reading_id === paper.reading_id) renderReadToggle();
    }}
    function isRead(paper) {{ return Boolean(status[paper.reading_id]?.read); }}
    function setIntensive(paper, intensive) {{
      const prior = status[paper.reading_id] || {{}};
      status[paper.reading_id] = {{
        ...prior,
        intensive,
        intensive_at: intensive ? new Date().toISOString() : ""
      }};
      saveLocalStatus();
      saveServerStatus();
      renderList();
      if (current && current.reading_id === paper.reading_id) renderIntensiveToggle();
    }}
    function isIntensive(paper) {{ return Boolean(status[paper.reading_id]?.intensive); }}
    function renderReadToggle() {{
      const button = document.querySelector("#readToggle");
      const read = current ? isRead(current) : false;
      button.textContent = read ? "已读" : "标记已读";
      button.classList.toggle("read", read);
      button.classList.toggle("primary", !read);
    }}
    function renderIntensiveToggle() {{
      const button = document.querySelector("#intensiveToggle");
      const intensive = current ? isIntensive(current) : false;
      button.textContent = intensive ? "精读中" : "精读";
      button.classList.toggle("intensive", intensive);
    }}
    function renderLeftMode() {{
      document.querySelector("#analysisMode").classList.toggle("active", leftMode === "analysis");
      document.querySelector("#cnPdfMode").classList.toggle("active", leftMode === "cn");
      const analysis = document.querySelector("#analysis");
      const cnPdf = document.querySelector("#cnPdfFrame");
      const cnAnnotator = document.querySelector("#cnAnnotator");
      const cnEmpty = document.querySelector("#cnEmpty");
      analysis.classList.toggle("hidden", leftMode !== "analysis");
      cnPdf.classList.add("hidden");
      cnAnnotator.classList.add("hidden");
      cnEmpty.classList.add("hidden");
      if (leftMode === "cn" && current) {{
        if (current.cn_pdf_path) {{
          cnPdf.removeAttribute("src");
          cnAnnotator.classList.remove("hidden");
          loadCnAnnotator(current);
        }} else {{
          cnPdf.removeAttribute("src");
          cnEmpty.classList.remove("hidden");
          cnEmpty.textContent = `${{current.reading_id}} 还没有生成中文 PDF。执行“继续指令”处理精读论文后会出现在这里。`;
        }}
      }}
    }}
    function setLeftMode(mode) {{
      leftMode = mode;
      renderLeftMode();
    }}
    function cnStorageKey() {{
      return current ? `paper-cn-notes:${{manifest.run_date}}:${{manifest.arxiv_date}}:${{current.reading_id}}` : "";
    }}
    function setNoteStatus(message) {{
      document.querySelector("#cnNoteStatus").textContent = message || "";
    }}
    function setNoteTool(tool) {{
      cnState.tool = tool;
      document.querySelector("#noteTool").classList.toggle("active", tool === "note");
      document.querySelector("#highlightTool").classList.toggle("active", tool === "highlight");
      setNoteStatus(tool === "note" ? "点击页面添加文字便签" : "拖拽页面添加高亮框");
    }}
    function loadStoredAnnotations() {{
      try {{ return JSON.parse(localStorage.getItem(cnStorageKey()) || "[]"); }}
      catch (_) {{ return []; }}
    }}
    function storeAnnotations() {{
      if (!current) return;
      localStorage.setItem(cnStorageKey(), JSON.stringify(cnState.annotations));
    }}
    async function loadCnAnnotator(paper) {{
      if (!window.PDFLib) {{
        setNoteStatus("PDF 保存组件加载失败，请检查网络或刷新页面。");
        return;
      }}
      const paperKey = `${{paper.reading_id}}:${{paper.cn_pdf_path}}`;
      if (cnState.paperKey === paperKey && cnState.pdfDocument) {{
        renderAllAnnotationLayers();
        return;
      }}
      cnState = {{
        ...cnState,
        paperKey,
        pdfBytes: null,
        pdfDocument: null,
        annotations: loadStoredAnnotations(),
        pages: [],
        drawing: null
      }};
      const pages = document.querySelector("#cnPages");
      pages.innerHTML = `<div class="empty">正在加载中文 PDF...</div>`;
      setNoteStatus("");
      try {{
        const response = await fetch(paper.cn_pdf_path, {{ cache: "no-store" }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const bytes = new Uint8Array(await response.arrayBuffer());
        cnState.pdfBytes = bytes;
        const infoResponse = await fetch(`/cn-pdf-info?path=${{encodeURIComponent(paper.cn_pdf_path)}}`, {{ cache: "no-store" }});
        const info = await infoResponse.json();
        if (!infoResponse.ok || !info.ok) throw new Error(info.error || `HTTP ${{infoResponse.status}}`);
        cnState.pdfDocument = info;
        await renderCnPages();
        setNoteTool(cnState.tool);
      }} catch (error) {{
        pages.innerHTML = `<div class="empty">无法加载中文 PDF：${{escapeHtml(error.message)}}<br>${{escapeHtml(paper.cn_pdf_path)}}</div>`;
      }}
    }}
    async function renderCnPages() {{
      const pages = document.querySelector("#cnPages");
      pages.innerHTML = "";
      cnState.pages = [];
      const maxWidth = Math.max(320, pages.clientWidth - 28);
      for (let pageIndex = 0; pageIndex < cnState.pdfDocument.page_count; pageIndex += 1) {{
        const pageMeta = cnState.pdfDocument.pages[pageIndex] || {{}};
        const pageWidth = Number(pageMeta.width || 612);
        const zoom = Math.min(1.55, Math.max(0.7, maxWidth / pageWidth));
        const wrapper = document.createElement("div");
        wrapper.className = "cn-page";
        const image = document.createElement("img");
        image.alt = `中文 PDF 第 ${{pageIndex + 1}} 页`;
        image.src = `/cn-pdf-page?path=${{encodeURIComponent(current.cn_pdf_path)}}&page=${{pageIndex}}&zoom=${{zoom.toFixed(3)}}&v=${{Date.now()}}`;
        const layer = document.createElement("canvas");
        layer.className = "cn-annotation-layer";
        layer.dataset.pageIndex = String(pageIndex);
        wrapper.append(image, layer);
        pages.append(wrapper);
        await new Promise((resolve, reject) => {{
          image.onload = resolve;
          image.onerror = () => reject(new Error(`无法渲染第 ${{pageIndex + 1}} 页`));
        }});
        wrapper.style.width = `${{image.naturalWidth}}px`;
        wrapper.style.height = `${{image.naturalHeight}}px`;
        layer.width = image.naturalWidth;
        layer.height = image.naturalHeight;
        cnState.pages.push({{ pageIndex, layer, width: layer.width, height: layer.height }});
        attachAnnotationEvents(layer);
      }}
      renderAllAnnotationLayers();
    }}
    function attachAnnotationEvents(layer) {{
      layer.addEventListener("pointerdown", (event) => {{
        if (cnState.tool === "note") {{
          const point = layerPoint(layer, event);
          const text = prompt("输入这条笔记：");
          if (!text || !text.trim()) return;
          cnState.annotations.push({{
            type: "note",
            pageIndex: Number(layer.dataset.pageIndex),
            x: point.x / layer.width,
            y: point.y / layer.height,
            text: text.trim()
          }});
          storeAnnotations();
          renderAllAnnotationLayers();
          setNoteStatus("已添加文字便签，点击“保存到PDF”写回文件");
          return;
        }}
        const point = layerPoint(layer, event);
        cnState.drawing = {{
          pageIndex: Number(layer.dataset.pageIndex),
          layer,
          startX: point.x,
          startY: point.y,
          endX: point.x,
          endY: point.y
        }};
        layer.setPointerCapture(event.pointerId);
      }});
      layer.addEventListener("pointermove", (event) => {{
        if (!cnState.drawing || cnState.drawing.layer !== layer) return;
        const point = layerPoint(layer, event);
        cnState.drawing.endX = point.x;
        cnState.drawing.endY = point.y;
        renderAllAnnotationLayers();
        drawHighlight(layer, cnState.drawing.startX, cnState.drawing.startY, cnState.drawing.endX, cnState.drawing.endY);
      }});
      layer.addEventListener("pointerup", (event) => {{
        if (!cnState.drawing || cnState.drawing.layer !== layer) return;
        const drawing = cnState.drawing;
        cnState.drawing = null;
        const x = Math.min(drawing.startX, drawing.endX);
        const y = Math.min(drawing.startY, drawing.endY);
        const w = Math.abs(drawing.endX - drawing.startX);
        const h = Math.abs(drawing.endY - drawing.startY);
        if (w < 8 || h < 8) {{
          renderAllAnnotationLayers();
          return;
        }}
        cnState.annotations.push({{
          type: "highlight",
          pageIndex: drawing.pageIndex,
          x: x / layer.width,
          y: y / layer.height,
          w: w / layer.width,
          h: h / layer.height
        }});
        storeAnnotations();
        renderAllAnnotationLayers();
        setNoteStatus("已添加高亮框，点击“保存到PDF”写回文件");
        try {{ layer.releasePointerCapture(event.pointerId); }} catch (_) {{}}
      }});
    }}
    function layerPoint(layer, event) {{
      const rect = layer.getBoundingClientRect();
      return {{
        x: Math.max(0, Math.min(layer.width, (event.clientX - rect.left) * layer.width / rect.width)),
        y: Math.max(0, Math.min(layer.height, (event.clientY - rect.top) * layer.height / rect.height))
      }};
    }}
    function renderAllAnnotationLayers() {{
      for (const page of cnState.pages) {{
        const ctx = page.layer.getContext("2d");
        ctx.clearRect(0, 0, page.width, page.height);
        for (const annotation of cnState.annotations.filter((item) => item.pageIndex === page.pageIndex)) {{
          drawAnnotation(ctx, page.width, page.height, annotation);
        }}
      }}
    }}
    function drawHighlight(layer, x1, y1, x2, y2) {{
      const ctx = layer.getContext("2d");
      ctx.save();
      ctx.fillStyle = "rgba(255, 221, 73, 0.32)";
      ctx.strokeStyle = "rgba(166, 118, 0, 0.75)";
      ctx.lineWidth = 2;
      ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
      ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
      ctx.restore();
    }}
    function drawAnnotation(ctx, width, height, annotation) {{
      if (annotation.type === "highlight") {{
        drawHighlight(ctx.canvas, annotation.x * width, annotation.y * height, (annotation.x + annotation.w) * width, (annotation.y + annotation.h) * height);
        return;
      }}
      const x = annotation.x * width;
      const y = annotation.y * height;
      const boxWidth = Math.min(260, Math.max(150, width - x - 12));
      const lines = wrapCanvasText(ctx, annotation.text || "", boxWidth - 16);
      const lineHeight = 18;
      const boxHeight = Math.max(34, lines.length * lineHeight + 14);
      ctx.save();
      ctx.fillStyle = "rgba(255, 246, 173, 0.92)";
      ctx.strokeStyle = "rgba(116, 88, 0, 0.85)";
      ctx.lineWidth = 1.5;
      ctx.fillRect(x, y, boxWidth, boxHeight);
      ctx.strokeRect(x, y, boxWidth, boxHeight);
      ctx.fillStyle = "#2f2b16";
      ctx.font = "14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      ctx.textBaseline = "top";
      lines.forEach((line, index) => ctx.fillText(line, x + 8, y + 7 + index * lineHeight));
      ctx.restore();
    }}
    function wrapCanvasText(ctx, text, maxWidth) {{
      ctx.font = "14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      const lines = [];
      let currentLine = "";
      for (const char of text) {{
        const nextLine = currentLine + char;
        if (currentLine && ctx.measureText(nextLine).width > maxWidth) {{
          lines.push(currentLine);
          currentLine = char;
        }} else {{
          currentLine = nextLine;
        }}
      }}
      if (currentLine) lines.push(currentLine);
      return lines.slice(0, 8);
    }}
    async function saveCnPdfNotes() {{
      if (!current || !current.cn_pdf_path || !cnState.pdfBytes) return;
      if (!cnState.annotations.length) {{
        setNoteStatus("没有未保存的标注");
        return;
      }}
      try {{
        setNoteStatus("正在写入 PDF...");
        const pdfDoc = await PDFLib.PDFDocument.load(cnState.pdfBytes);
        const pages = pdfDoc.getPages();
        for (const pageInfo of cnState.pages) {{
          const pageAnnotations = cnState.annotations.filter((item) => item.pageIndex === pageInfo.pageIndex);
          if (!pageAnnotations.length) continue;
          const overlay = document.createElement("canvas");
          overlay.width = pageInfo.width;
          overlay.height = pageInfo.height;
          const ctx = overlay.getContext("2d");
          pageAnnotations.forEach((annotation) => drawAnnotation(ctx, overlay.width, overlay.height, annotation));
          const pngBytes = await canvasToPngBytes(overlay);
          const png = await pdfDoc.embedPng(pngBytes);
          const page = pages[pageInfo.pageIndex];
          page.drawImage(png, {{ x: 0, y: 0, width: page.getWidth(), height: page.getHeight() }});
        }}
        const savedBytes = await pdfDoc.save();
        const response = await fetch("/save-cn-pdf", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json;charset=utf-8" }},
          body: JSON.stringify({{ path: current.cn_pdf_path, pdf_base64: bytesToBase64(savedBytes) }})
        }});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${{response.status}}`);
        cnState.pdfBytes = new Uint8Array(savedBytes);
        cnState.pdfDocument = null;
        cnState.paperKey = "";
        cnState.annotations = [];
        storeAnnotations();
        await loadCnAnnotator(current);
        setNoteStatus(`已保存到本地 PDF，备份：${{result.backup_path || ""}}`);
      }} catch (error) {{
        setNoteStatus(`保存失败：${{error.message}}`);
      }}
    }}
    async function canvasToPngBytes(canvas) {{
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      return new Uint8Array(await blob.arrayBuffer());
    }}
    function bytesToBase64(bytes) {{
      let binary = "";
      const chunkSize = 0x8000;
      for (let i = 0; i < bytes.length; i += chunkSize) {{
        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
      }}
      return btoa(binary);
    }}
    function clearCnNotes() {{
      if (!cnState.annotations.length) return;
      if (!confirm("清空当前未保存的 PDF 标注？已写入 PDF 的内容不会被删除。")) return;
      cnState.annotations = [];
      storeAnnotations();
      renderAllAnnotationLayers();
      setNoteStatus("未保存标注已清空");
    }}
    function renderProgress() {{
      const readCount = manifest.papers.filter(isRead).length;
      document.querySelector("#progress").textContent = `${{readCount}}/${{manifest.papers.length}}`;
    }}
    function renderList() {{
      const q = query.value.trim().toLowerCase();
      const p = priority.value;
      list.innerHTML = "";
      const rows = manifest.papers.filter((paper) => {{
        const haystack = `${{paper.reading_id}} ${{paper.arxiv_id}} ${{paper.title}}`.toLowerCase();
        return (!q || haystack.includes(q)) && (!p || paper.priority === p);
      }});
      for (const paper of rows) {{
        const row = document.createElement("div");
        row.className = `paper-row${{paper === current ? " active" : ""}}${{isRead(paper) ? " read" : ""}}${{isIntensive(paper) ? " intensive" : ""}}`;
        const body = document.createElement("div");
        body.className = "row-body";
        const read = isRead(paper);
        const intensive = isIntensive(paper);
        body.innerHTML = `
          <div class="row-id">${{escapeHtml(paper.reading_id)}} · arXiv:${{escapeHtml(paper.arxiv_id)}}</div>
          <div class="row-title">${{escapeHtml(paper.title)}}</div>
          <div class="row-meta">
            <span class="pill priority-${{escapeHtml((paper.priority || "").toLowerCase())}}">级别 ${{escapeHtml(paper.priority || "-")}}</span>
            <span class="pill">${{escapeHtml(paper.arxiv_id)}}</span>
            <span class="pill read-state${{read ? " done" : ""}}">${{read ? "已读" : "未读"}}</span>
            ${{intensive ? `<span class="pill intensive-state">精读</span>` : ""}}
          </div>
        `;
        row.append(body);
        row.addEventListener("click", () => selectPaper(paper));
        list.append(row);
      }}
      if (!rows.length) list.innerHTML = `<div class="empty">没有匹配的论文。</div>`;
      renderProgress();
    }}
    function showList() {{
      listView.classList.remove("hidden");
      readerView.classList.add("hidden");
      renderList();
    }}
    async function selectPaper(paper) {{
      current = paper;
      listView.classList.add("hidden");
      readerView.classList.remove("hidden");
      document.querySelector("#readerId").textContent = paper.reading_id;
      document.querySelector("#sourceLink").href = paper.pdf_path;
      document.querySelector("#pdfFrame").src = paper.pdf_path;
      renderReadToggle();
      renderIntensiveToggle();
      renderList();
      const analysis = document.querySelector("#analysis");
      analysis.innerHTML = `<div class="empty">正在加载 ${{escapeHtml(paper.reading_id)}} 的分析...</div>`;
      try {{
        const response = await fetch(paper.analysis_path);
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const markdown = await response.text();
        analysis.innerHTML = renderMarkdown(markdown, paper.analysis_path);
      }} catch (error) {{
        analysis.innerHTML = `<div class="empty">无法加载分析文件：${{escapeHtml(error.message)}}<br>${{escapeHtml(paper.analysis_path)}}</div>`;
      }}
      renderLeftMode();
    }}
    function renderMarkdown(markdown, basePath) {{
      const lines = markdown.replace(/\\r\\n/g, "\\n").split("\\n");
      const html = [];
      let inCode = false;
      let code = [];
      let table = [];
      function flushCode() {{
        if (code.length) html.push(`<pre><code>${{escapeHtml(code.join("\\n"))}}</code></pre>`);
        code = [];
      }}
      function flushTable() {{
        if (!table.length) return;
        const rows = table.filter((line) => !/^\\|?\\s*:?-{{3,}}/.test(line.replace(/\\|/g, "")));
        html.push("<table>");
        rows.forEach((line, index) => {{
          const cells = line.replace(/^\\||\\|$/g, "").split("|").map((cell) => cell.trim());
          html.push(index === 0 ? "<thead><tr>" : "<tbody><tr>");
          for (const cell of cells) html.push(index === 0 ? `<th>${{inlineMd(cell, basePath)}}</th>` : `<td>${{inlineMd(cell, basePath)}}</td>`);
          html.push(index === 0 ? "</tr></thead>" : "</tr></tbody>");
        }});
        html.push("</table>");
        table = [];
      }}
      for (const line of lines) {{
        if (line.startsWith("```")) {{
          if (inCode) {{ flushCode(); inCode = false; }} else {{ flushTable(); inCode = true; }}
          continue;
        }}
        if (inCode) {{ code.push(line); continue; }}
        if (/^\\|.*\\|$/.test(line.trim())) {{ table.push(line.trim()); continue; }}
        flushTable();
        const trimmed = line.trim();
        if (!trimmed) {{ html.push(""); continue; }}
        const heading = trimmed.match(/^(#{{1,4}})\\s+(.*)$/);
        if (heading) {{
          const level = heading[1].length;
          html.push(`<h${{level}}>${{inlineMd(heading[2], basePath)}}</h${{level}}>`);
        }} else if (/^[-*]\\s+/.test(trimmed)) {{
          html.push(`<p>• ${{inlineMd(trimmed.replace(/^[-*]\\s+/, ""), basePath)}}</p>`);
        }} else {{
          html.push(`<p>${{inlineMd(trimmed, basePath)}}</p>`);
        }}
      }}
      flushTable();
      flushCode();
      return html.join("\\n");
    }}
    function inlineMd(value, basePath) {{
      let out = escapeHtml(value);
      out = out.replace(/!\\[([^\\]]*)\\]\\(([^)]+)\\)/g, (_, alt, path) => `<img alt="${{escapeHtml(alt)}}" src="${{resolveRelative(path, basePath)}}">`);
      out = out.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, (_, text, path) => `<a href="${{resolveRelative(path, basePath)}}" target="_blank" rel="noopener">${{escapeHtml(text)}}</a>`);
      out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
      return out;
    }}
    function resolveRelative(path, basePath) {{
      if (/^(https?:|file:|\\/)/.test(path)) return path;
      return new URL(path, new URL(basePath, window.location.href)).href;
    }}
    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }}
    renderList();
    loadServerStatus();
  </script>
</body>
</html>
"""


def write_reading_dashboard(
    root: Path,
    run_dir: Path,
    arxiv_date: str,
    analysis_items: List[Dict[str, object]],
) -> Dict[str, Path]:
    manifest = build_manifest(root, run_dir, arxiv_date, analysis_items)
    manifest_path = run_dir / f"reading_manifest_{arxiv_date}.json"
    dashboard_path = run_dir / f"reading_dashboard_{arxiv_date}.html"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dashboard_path.write_text(render_html(manifest), encoding="utf-8")
    status_path = run_dir / f"reading_status_{arxiv_date}.json"
    status_payload = {
        "run_date": run_dir.name,
        "arxiv_date": arxiv_date,
        "updated_at": "",
        "read_papers": [],
    }
    if status_path.exists():
        try:
            status_payload.update(json.loads(status_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass

    selector_by_reading_id = {
        str(paper["reading_id"]): str(paper.get("selector_id", "")) for paper in manifest["papers"]
    }
    migrated_read_papers = []
    for item in status_payload.get("read_papers", []):
        if not isinstance(item, dict):
            continue
        item_reading_id = str(item.get("reading_id") or "").strip()
        migrated_read_papers.append(
            {
                "reading_id": item_reading_id,
                "selector_id": str(
                    item.get("selector_id") or item.get("paper_id") or selector_by_reading_id.get(item_reading_id, "")
                ).strip(),
                "arxiv_id": str(item.get("arxiv_id") or "").strip(),
                "read": bool(item.get("read")),
                "read_at": str(item.get("read_at") or "").strip(),
                "intensive": bool(item.get("intensive")),
                "intensive_at": str(item.get("intensive_at") or "").strip(),
            }
        )
    status_payload["run_date"] = run_dir.name
    status_payload["arxiv_date"] = arxiv_date
    status_payload["read_papers"] = migrated_read_papers
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"manifest": manifest_path, "dashboard": dashboard_path, "status": status_path}


def refresh_cn_pdf_paths(manifest_path: Path) -> Dict[str, Path]:
    run_dir = manifest_path.resolve().parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for paper in manifest.get("papers", []):
        if not isinstance(paper, dict):
            continue
        paper["cn_pdf_path"] = find_cn_pdf(
            run_dir,
            str(paper.get("reading_id", "")),
            str(paper.get("arxiv_id", "")),
        )
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    arxiv_date = str(manifest.get("arxiv_date") or manifest_path.name.removeprefix("reading_manifest_").removesuffix(".json"))
    dashboard_path = run_dir / f"reading_dashboard_{arxiv_date}.html"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dashboard_path.write_text(render_html(manifest), encoding="utf-8")
    return {"manifest": manifest_path, "dashboard": dashboard_path}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render reading dashboard from an analysis task.")
    parser.add_argument("analysis_task", type=Path, nargs="?", help="llm_analysis_task_<scope>.md")
    parser.add_argument("--refresh-manifest", type=Path, help="Refresh cn_pdf_path values in an existing reading manifest.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.refresh_manifest:
        paths = refresh_cn_pdf_paths(args.refresh_manifest)
        print(f"Reading manifest refreshed: {paths['manifest']}")
        print(f"Reading dashboard refreshed: {paths['dashboard']}")
        return 0
    raise SystemExit("Use write_reading_dashboard from process_selection.py, or pass --refresh-manifest.")


if __name__ == "__main__":
    raise SystemExit(main())
