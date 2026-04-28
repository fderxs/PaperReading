#!/usr/bin/env python3
"""Render a paper selection HTML page from a Codex-prepared shortlist."""

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


USER_AGENT = "paperreading-selector/1.0 (+https://arxiv.org/list/cs.RO/recent)"
ARXIV_API = "https://export.arxiv.org/api/query"

VLA_RE = re.compile(r"\b(VLA|vision[-\s]?language[-\s]?action)\b", re.I)
PLANNING_RE = re.compile(
    r"\b(planning|planner|motion planning|world model|model[-\s]?predictive|"
    r"trajectory|long[-\s]?horizon|action synthesis|temporal logic)\b",
    re.I,
)
BENCHMARK_RE = re.compile(r"\b(dataset|benchmark|bench|evaluation|test)\b", re.I)
SAFETY_RE = re.compile(r"\b(calibration|uncertainty|failure|safe|safety|robust)\b", re.I)
EMBODIED_RE = re.compile(
    r"\b(embodied|manipulation|robotic autonomy|foundation model|cross[-\s]?embodiment)\b",
    re.I,
)
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
SUMMARY_ZH_CACHE = DATA_DIR / "summary_zh_cache.json"
INSTITUTIONS_CACHE = DATA_DIR / "institutions_cache.json"


def arxiv_id_from_pdf_url(pdf_url: str) -> str:
    match = re.search(r"/pdf/([^/?#]+)", pdf_url)
    if not match:
        return ""
    return match.group(1).removesuffix(".pdf")


def chunked(values: List[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def fetch_arxiv_metadata(arxiv_ids: List[str], timeout: int) -> Dict[str, Dict[str, object]]:
    metadata: Dict[str, Dict[str, object]] = {}
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for batch in chunked(arxiv_ids, 50):
        url = f"{ARXIV_API}?{urlencode({'id_list': ','.join(batch), 'max_results': len(batch)})}"
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=timeout) as response:
            root = ET.fromstring(response.read())

        for entry in root.findall("atom:entry", ns):
            raw_id = entry.findtext("atom:id", default="", namespaces=ns).rsplit("/", 1)[-1]
            arxiv_id = re.sub(r"v\d+$", "", raw_id)
            title = " ".join(entry.findtext("atom:title", default="", namespaces=ns).split())
            summary = " ".join(entry.findtext("atom:summary", default="", namespaces=ns).split())
            authors = [
                author.findtext("atom:name", default="", namespaces=ns)
                for author in entry.findall("atom:author", ns)
            ]
            metadata[arxiv_id] = {
                "title": title,
                "summary": summary,
                "authors": authors,
            }

    return metadata


def load_summary_zh_cache() -> Dict[str, str]:
    if not SUMMARY_ZH_CACHE.exists():
        return {}
    return json.loads(SUMMARY_ZH_CACHE.read_text(encoding="utf-8"))


def load_institutions_cache() -> Dict[str, str]:
    if not INSTITUTIONS_CACHE.exists():
        return {}
    return json.loads(INSTITUTIONS_CACHE.read_text(encoding="utf-8"))


def classify_paper(title: str, summary: str) -> Dict[str, object]:
    text = f"{title}\n{summary}"
    score = 0
    tags: List[str] = []

    if VLA_RE.search(text):
        score += 10
        tags.append("VLA")
    if PLANNING_RE.search(text):
        score += 8
        tags.append("Planning")
    if "world model" in text.lower():
        score += 4
        tags.append("World Model")
    if EMBODIED_RE.search(text):
        score += 4
        tags.append("具身/机器人")
    if SAFETY_RE.search(text):
        score += 3
        tags.append("可靠性/安全")
    if BENCHMARK_RE.search(text):
        score += 2
        tags.append("数据集/基准")

    tags = list(dict.fromkeys(tags))
    return {"score": score, "tags": tags}


def reason_from_tags(tags: List[str]) -> str:
    if "VLA" in tags and "Planning" in tags:
        return "同时涉及 VLA 与规划/长时程决策，是高优先级候选。"
    if "VLA" in tags:
        return "直接涉及 VLA 或视觉-语言-动作模型，符合当前筛选主线。"
    if "Planning" in tags or "World Model" in tags:
        return "直接涉及具身规划、运动规划或 world model，符合当前筛选主线。"
    if "数据集/基准" in tags:
        return "包含数据集、基准或评测信息，可作为 VLA/规划方向参考。"
    return "关键词相关，建议快速浏览后决定是否深入。"


def build_shortlist(scraped_path: Path, timeout: int, use_api: bool) -> Dict[str, object]:
    scraped = json.loads(scraped_path.read_text(encoding="utf-8"))
    raw_papers = scraped.get("papers", [])
    arxiv_ids = [arxiv_id_from_pdf_url(paper.get("pdf_url", "")) for paper in raw_papers]
    arxiv_ids = [arxiv_id for arxiv_id in arxiv_ids if arxiv_id]

    metadata: Dict[str, Dict[str, object]] = {}
    if use_api and arxiv_ids:
        metadata = fetch_arxiv_metadata(arxiv_ids, timeout=timeout)
    summary_zh_cache = load_summary_zh_cache()
    institutions_cache = load_institutions_cache()

    candidates = []
    for raw in raw_papers:
        arxiv_id = arxiv_id_from_pdf_url(raw.get("pdf_url", ""))
        meta = metadata.get(arxiv_id, {})
        title = str(meta.get("title") or raw.get("title") or "").strip()
        summary = str(meta.get("summary") or "").strip()
        authors = list(meta.get("authors") or [])
        classification = classify_paper(title, summary)
        score = int(classification["score"])

        if score < 6:
            continue

        tags = list(classification["tags"])
        candidates.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "pdf_url": raw.get("pdf_url", ""),
                "authors": authors,
                "institutions": institutions_cache.get(arxiv_id, "机构待补充；如需精读，可从 PDF 首页确认。"),
                "summary": summary,
                "summary_zh": summary_zh_cache.get(arxiv_id, ""),
                "tags": tags,
                "score": score,
                "reason": reason_from_tags(tags),
            }
        )

    candidates.sort(key=lambda item: (-int(item["score"]), item["title"].lower()))
    for index, paper in enumerate(candidates, 1):
        paper["paper_id"] = f"P{index:02d}"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_json": str(scraped_path),
        "run_date": scraped_path.parent.name,
        "arxiv_date": scraped.get("target_date", ""),
        "source_url": scraped.get("source_url", ""),
        "total_paper_count": len(raw_papers),
        "shortlist_count": len(candidates),
        "papers": candidates,
    }


def render_html(shortlist: Dict[str, object], output_json_name: str) -> str:
    papers_json = json.dumps(shortlist["papers"], ensure_ascii=False, indent=2)
    date_label = str(shortlist.get("target_date_label") or shortlist["arxiv_date"])
    title = f"{date_label} VLA / 具身规划论文选择器"
    escaped_title = html.escape(title)
    output_name_json = json.dumps(output_json_name, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      --ink: #1d2520;
      --muted: #607064;
      --paper: #fffaf0;
      --line: #d9cfb9;
      --accent: #b5532b;
      --accent-strong: #82341e;
      --sage: #d9e5d2;
      --sage-dark: #496950;
      --selected: #fff2de;
      --shadow: 0 18px 45px rgba(58, 48, 32, 0.12);
      --ok: #2f6f4e;
      --warn: #9b5b17;
      --error: #a83232;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 10%, rgba(181, 83, 43, 0.14), transparent 34rem),
        radial-gradient(circle at 88% 3%, rgba(73, 105, 80, 0.16), transparent 30rem),
        linear-gradient(135deg, #f5ecd7 0%, #fbf8ee 48%, #eef4e8 100%);
      font-family: "Iowan Old Style", "Songti SC", "Hiragino Mincho ProN", Georgia, serif;
      line-height: 1.6;
      min-height: 100vh;
    }}
    header, main {{ max-width: 1120px; margin: 0 auto; padding-left: 22px; padding-right: 22px; }}
    header {{ padding-top: 48px; padding-bottom: 24px; }}
    h1 {{ font-size: clamp(2rem, 4vw, 4.1rem); line-height: 1.05; margin: 0 0 14px; letter-spacing: -0.05em; }}
    .lede {{ color: var(--muted); font-size: 1.05rem; max-width: 850px; margin: 0; }}
    .toolbar {{
      position: sticky;
      top: 12px;
      z-index: 10;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
      padding: 16px;
      margin: 20px 0 22px;
      border: 1px solid rgba(217, 207, 185, 0.85);
      border-radius: 22px;
      background: rgba(255, 250, 240, 0.92);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}
    .count {{ color: var(--sage-dark); font-weight: 800; }}
    .hint {{ color: var(--muted); font-size: 0.92rem; margin: 8px 0 0; }}
    .notice {{
      display: none;
      margin: 16px 0 0;
      padding: 12px 14px;
      border-radius: 16px;
      font: 700 0.95rem/1.45 "Avenir Next", "PingFang SC", sans-serif;
    }}
    .notice.ok {{ display: block; color: #fff; background: var(--ok); }}
    .notice.warn {{ display: block; color: #fff; background: var(--warn); }}
    .notice.error {{ display: block; color: #fff; background: var(--error); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }}
    button {{
      appearance: none;
      border: 1px solid transparent;
      border-radius: 999px;
      color: #fff;
      background: var(--accent);
      cursor: pointer;
      font: 700 0.94rem/1 "Avenir Next", "PingFang SC", sans-serif;
      padding: 12px 16px;
    }}
    button.secondary {{ color: var(--accent-strong); background: transparent; border-color: rgba(181, 83, 43, 0.35); }}
    .grid {{ display: grid; gap: 16px; padding-bottom: 64px; }}
    article {{
      display: grid;
      grid-template-columns: 78px 1fr;
      gap: 16px;
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: 26px;
      background: rgba(255, 255, 250, 0.94);
      box-shadow: 0 10px 28px rgba(58, 48, 32, 0.08);
    }}
    article.selected {{ border-color: rgba(181, 83, 43, 0.65); background: var(--selected); box-shadow: 0 18px 42px rgba(181, 83, 43, 0.15); }}
    .status {{
      align-self: start;
      text-align: center;
      border-radius: 18px;
      padding: 10px 8px;
      background: #eee6d3;
      color: var(--muted);
      font: 800 0.78rem/1.3 "Avenir Next", "PingFang SC", sans-serif;
    }}
    article.selected .status {{ background: var(--accent); color: #fff; }}
    h2 {{ font-size: clamp(1.18rem, 2vw, 1.7rem); line-height: 1.22; margin: 0 0 10px; letter-spacing: -0.02em; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px; }}
    .tag, .id {{ border-radius: 999px; padding: 4px 10px; font: 700 0.82rem/1.2 "Avenir Next", "PingFang SC", sans-serif; }}
    .id {{ color: var(--accent-strong); background: #f4dbc8; }}
    .tag {{ color: var(--sage-dark); background: var(--sage); }}
    a {{ color: var(--accent-strong); font-weight: 700; text-decoration-thickness: 0.08em; text-underline-offset: 0.18em; }}
    .reason {{ color: var(--muted); margin: 0 0 12px; }}
    .institution-preview {{
      margin: 0 0 12px;
      color: var(--sage-dark);
      font-size: 0.95rem;
    }}
    .controls {{ display: grid; grid-template-columns: minmax(160px, 220px) 1fr; gap: 10px; margin: 14px 0; }}
    select, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--paper);
      color: var(--ink);
      font: 0.94rem/1.5 "Avenir Next", "PingFang SC", sans-serif;
      padding: 10px 12px;
    }}
    textarea {{ min-height: 46px; resize: vertical; }}
    details {{ border-top: 1px dashed var(--line); margin-top: 14px; padding-top: 12px; }}
    summary {{ cursor: pointer; color: var(--accent-strong); font-weight: 700; }}
    .detail-block {{ color: var(--muted); margin: 10px 0 0; }}
    .detail-block strong {{ color: var(--ink); }}
    @media (max-width: 760px) {{
      .toolbar {{ grid-template-columns: 1fr; position: static; }}
      .actions {{ justify-content: flex-start; }}
      article {{ grid-template-columns: 1fr; padding: 18px; }}
      .status {{ justify-self: start; }}
      .controls {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escaped_title}</h1>
    <p class="lede">不需要手动打勾。只要给某篇论文选择了优先级，或在备注里写了任何内容，它就会自动进入“已选择”。清空优先级和备注后会自动取消选择。点击保存后，会直接覆盖写入当天日期文件夹里的选择 JSON。</p>
  </header>
  <main>
    <section class="toolbar" aria-label="操作栏">
      <div>
        <div class="count" id="count">已选择 0 / 0 篇</div>
        <p class="hint">请通过 <code>start_daily_review.sh</code> 启动后打开本地 URL；保存会写入当天日期文件夹。</p>
      </div>
      <div class="actions">
        <button type="button" id="save">保存/覆盖 JSON</button>
        <button type="button" id="copy" class="secondary">复制结果</button>
        <button type="button" id="clear" class="secondary">清空所有选择</button>
      </div>
    </section>
    <div id="notice" class="notice" role="status" aria-live="polite"></div>
    <section class="grid" id="paper-list"></section>
  </main>
  <script>
    const storageKey = "vla-planning-selection-{shortlist['run_date']}-{shortlist['arxiv_date']}";
    const outputFileName = {output_name_json};
    const papers = {papers_json};
    let state = loadState();
    const list = document.querySelector("#paper-list");
    const count = document.querySelector("#count");
    const notice = document.querySelector("#notice");

    function loadState() {{
      try {{ return JSON.parse(localStorage.getItem(storageKey)) || {{}}; }}
      catch (_) {{ return {{}}; }}
    }}
    function stateKey(paper) {{
      return paper.arxiv_id || paper.paper_id;
    }}
    function paperState(key) {{
      state[key] = state[key] || {{ priority: "", notes: "" }};
      return state[key];
    }}
    function isSelected(key) {{
      const item = paperState(key);
      return Boolean(item.priority || item.notes.trim());
    }}
    function saveState() {{
      localStorage.setItem(storageKey, JSON.stringify(state));
      renderCount();
    }}
    function selectedPapers() {{
      return papers.filter((paper) => isSelected(stateKey(paper))).map((paper) => ({{
        paper_id: paper.paper_id,
        arxiv_id: paper.arxiv_id,
        title: paper.title,
        pdf_url: paper.pdf_url,
        priority: paperState(stateKey(paper)).priority,
        notes: paperState(stateKey(paper)).notes.trim()
      }}));
    }}
    function exportPayload() {{
      return {{
        source: "{Path(str(shortlist['source_json'])).name}",
        run_date: "{shortlist['run_date']}",
        arxiv_date: "{shortlist['arxiv_date']}",
        selected_at: new Date().toISOString(),
        selected_count: selectedPapers().length,
        selected_papers: selectedPapers()
      }};
    }}
    function renderCount() {{
      const selected = selectedPapers().length;
      count.textContent = `已选择 ${{selected}} / ${{papers.length}} 篇`;
      document.querySelectorAll("article").forEach((card) => {{
        const selectedNow = isSelected(card.dataset.id);
        card.classList.toggle("selected", selectedNow);
        card.querySelector(".status").textContent = selectedNow ? "已选择" : "未选择";
      }});
    }}
    function renderPapers() {{
      papers.forEach((paper) => {{
        const card = document.createElement("article");
        const key = stateKey(paper);
        card.dataset.id = key;

        const status = document.createElement("div");
        status.className = "status";
        status.textContent = "未选择";

        const body = document.createElement("div");
        const title = document.createElement("h2");
        title.textContent = paper.title;

        const meta = document.createElement("div");
        meta.className = "meta";
        const id = document.createElement("span");
        id.className = "id";
        id.textContent = `${{paper.paper_id}} · arXiv:${{paper.arxiv_id}}`;
        meta.append(id, ...paper.tags.map((tag) => {{
          const span = document.createElement("span");
          span.className = "tag";
          span.textContent = tag;
          return span;
        }}));

        const reason = document.createElement("p");
        reason.className = "reason";
        reason.textContent = paper.reason;

        const institutions = document.createElement("p");
        institutions.className = "institution-preview";
        institutions.innerHTML = `<strong>机构：</strong>${{escapeHtml(paper.institutions || "机构待补充；可从 arXiv HTML 或 TeX source 确认。")}}`;

        const link = document.createElement("a");
        link.href = paper.pdf_url;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "打开 PDF";

        const controls = document.createElement("div");
        controls.className = "controls";
        const priority = document.createElement("select");
        priority.innerHTML = `
          <option value="">不选择/清空优先级</option>
          <option value="A">A：最想精读</option>
          <option value="B">B：有时间再看</option>
          <option value="C">C：暂时保留</option>
        `;
        priority.value = paperState(key).priority;
        priority.addEventListener("change", () => {{
          paperState(key).priority = priority.value;
          saveState();
        }});

        const notes = document.createElement("textarea");
        notes.placeholder = "备注：写了备注会自动选中；清空备注且清空优先级会自动取消";
        notes.value = paperState(key).notes;
        notes.addEventListener("input", () => {{
          paperState(key).notes = notes.value;
          saveState();
        }});
        controls.append(priority, notes);

        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = "展开作者与中文摘要";
        const detail = document.createElement("div");
        detail.className = "detail-block";
        const summaryZh = paper.summary_zh || "中文摘要待补充；可先参考英文摘要。";
        detail.innerHTML = `
          <p><strong>作者：</strong>${{escapeHtml((paper.authors || []).join(", ") || "未从 arXiv API 获取到")}}</p>
          <p><strong>机构：</strong>${{escapeHtml(paper.institutions || "机构待补充；如需精读，可从 PDF 首页确认。")}}</p>
          <p><strong>中文摘要：</strong>${{escapeHtml(summaryZh)}}</p>
          <details>
            <summary>查看英文原始摘要</summary>
            <p>${{escapeHtml(paper.summary || "未从 arXiv API 获取到摘要")}}</p>
          </details>
        `;
        details.append(summary, detail);

        body.append(title, meta, reason, institutions, link, controls, details);
        card.append(status, body);
        list.append(card);
      }});
      renderCount();
    }}
    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }}
    function payloadText() {{ return JSON.stringify(exportPayload(), null, 2) + "\\n"; }}
    function setNotice(kind, message) {{
      notice.className = `notice ${{kind}}`;
      notice.textContent = message;
    }}
    async function getSelectionStatus() {{
      const response = await fetch(`/selection-status?arxiv_date=${{encodeURIComponent("{shortlist['arxiv_date']}")}}`);
      const result = await response.json();
      if (!response.ok || !result.ok) {{
        throw new Error(result.error || "无法检查现有选择文件");
      }}
      return result;
    }}
    async function saveJson() {{
      if (window.location.protocol === "file:") {{
        setNotice("error", "保存失败：请不要直接双击 HTML 文件保存。请运行 start_daily_review.sh，并从终端显示的 http://127.0.0.1 地址打开页面。");
        return;
      }}
      const status = await getSelectionStatus();
      if (status.exists) {{
        const confirmed = confirm(`选择结果文件已存在：\\n${{status.path}}\\n\\n是否覆盖？`);
        if (!confirmed) {{
          setNotice("warn", "已取消保存，没有覆盖现有 JSON。");
          return;
        }}
      }}
      const response = await fetch("/save-selection", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json;charset=utf-8" }},
        body: payloadText()
      }});
      const result = await response.json();
      if (!response.ok || !result.ok) {{
        throw new Error(result.error || "保存失败");
      }}
      setNotice("ok", `保存成功：已写入 ${{result.path}}`);
    }}
    document.querySelector("#save").addEventListener("click", () => saveJson().catch((error) => {{
      console.warn(error);
      setNotice("error", `保存失败：${{error.message}}`);
    }}));
    document.querySelector("#copy").addEventListener("click", async () => {{
      try {{
        await navigator.clipboard.writeText(payloadText());
        setNotice("ok", "已复制选择结果。");
      }} catch (_) {{
        setNotice("error", "复制失败：浏览器拒绝访问剪贴板。请优先使用保存按钮。");
      }}
    }});
    document.querySelector("#clear").addEventListener("click", () => {{
      if (!confirm("确定清空所有优先级和备注吗？")) return;
      state = {{}};
      localStorage.removeItem(storageKey);
      list.innerHTML = "";
      renderPapers();
      setNotice("warn", "已清空页面上的优先级和备注；如需覆盖 JSON，请再次点击保存。");
    }});
    renderPapers();
  </script>
</body>
</html>
"""


def normalize_shortlist(shortlist: Dict[str, object], source_path: Path) -> Dict[str, object]:
    papers = list(shortlist.get("papers", []))
    for index, paper in enumerate(papers, 1):
        paper.setdefault("paper_id", f"P{index:02d}")
        paper.setdefault("tags", [])
        paper.setdefault("score", 0)
        paper.setdefault("reason", reason_from_tags(list(paper.get("tags", []))))
        paper.setdefault("authors", [])
        paper.setdefault("institutions", "机构待补充；如需精读，可从 PDF 首页确认。")
        paper.setdefault("summary", "")
        paper.setdefault("summary_zh", "")

    shortlist["papers"] = papers
    shortlist["shortlist_count"] = len(papers)
    shortlist.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
    shortlist.setdefault("source_json", str(source_path))
    shortlist.setdefault("run_date", source_path.parent.name)
    shortlist.setdefault("arxiv_date", "")
    shortlist.setdefault("target_date_label", shortlist["arxiv_date"])
    shortlist.setdefault("source_url", "")
    shortlist.setdefault("total_paper_count", len(papers))
    return shortlist


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a VLA/planning paper selector HTML.")
    parser.add_argument("shortlist_json", type=Path, help="Path to shortlist_vla_planning_<date>.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    shortlist_path = args.shortlist_json.resolve()
    shortlist = normalize_shortlist(json.loads(shortlist_path.read_text(encoding="utf-8")), shortlist_path)

    arxiv_date = shortlist["arxiv_date"]

    selector_path = shortlist_path.parent / f"vla_planning_selector_{arxiv_date}.html"
    selected_name = f"selected_vla_planning_papers_{arxiv_date}.json"

    shortlist_path.write_text(
        json.dumps(shortlist, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    selector_path.write_text(render_html(shortlist, selected_name), encoding="utf-8")

    print(f"Wrote shortlist: {shortlist_path}")
    print(f"Wrote selector: {selector_path}")
    print(f"Shortlisted {shortlist['shortlist_count']} / {shortlist['total_paper_count']} papers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
