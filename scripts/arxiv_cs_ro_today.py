#!/usr/bin/env python3
"""Scrape recent cs.RO papers from arXiv, optionally across a date range."""

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ARXIV_BASE_URL = "https://arxiv.org"
ARXIV_RECENT_URL = "https://arxiv.org/list/cs.RO/recent"
DEFAULT_SHOW = 2000
DEFAULT_TIMEOUT = 30
ROOT_DIR = Path(__file__).resolve().parent.parent
USER_AGENT = (
    "Mozilla/5.0 (compatible; cs-ro-paper-scraper/1.0; "
    "+https://arxiv.org/list/cs.RO/recent)"
)

MONTH_TO_NUMBER: Dict[str, int] = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
NUMBER_TO_MONTH = {value: key for key, value in MONTH_TO_NUMBER.items()}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DATE_HEADER_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})"
)
WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class Paper:
    title: str
    pdf_url: str
    arxiv_date: str


def normalize_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def parse_arxiv_header_date(text: str) -> Optional[date]:
    match = DATE_HEADER_RE.search(normalize_text(text))
    if not match:
        return None

    day_text, month_text, year_text = match.groups()
    month = MONTH_TO_NUMBER.get(month_text)
    if month is None:
        return None

    return date(int(year_text), month, int(day_text))


def format_arxiv_date(value: date) -> str:
    return f"{WEEKDAYS[value.weekday()]}, {value.day:02d} {NUMBER_TO_MONTH[value.month]} {value.year}"


def build_scope_id(start_date: date, end_date: date) -> str:
    if start_date == end_date:
        return start_date.isoformat()
    return f"{start_date.isoformat()}_to_{end_date.isoformat()}"


def build_scope_label(start_date: date, end_date: date) -> str:
    if start_date == end_date:
        return format_arxiv_date(start_date)
    return f"{format_arxiv_date(start_date)} to {format_arxiv_date(end_date)}"


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD, for example 2026-02-26") from exc


class ArxivRecentParser(HTMLParser):
    """Parser for arXiv category recent-list pages."""

    def __init__(
        self,
        *,
        target_date: Optional[date] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> None:
        super().__init__(convert_charrefs=True)
        if target_date is not None:
            start_date = target_date
            end_date = target_date

        self.requested_start_date = start_date
        self.requested_end_date = end_date
        self.range_start: Optional[date] = start_date
        self.range_end: Optional[date] = end_date
        self.latest_date: Optional[date] = None
        self.available_dates: List[date] = []
        self.papers: List[Paper] = []

        self.current_section_date: Optional[date] = None
        self.current_entry: Optional[Dict[str, Optional[str]]] = None

        self.in_h3 = False
        self.h3_parts: List[str] = []
        self.in_dt = False
        self.in_dd = False
        self.in_title_div = False
        self.title_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attrs_dict = dict(attrs)

        if tag == "h3":
            self.in_h3 = True
            self.h3_parts = []
            return

        if tag == "dt":
            self.in_dt = True
            self.current_entry = {"title": None, "pdf_url": None}
            return

        if tag == "dd":
            self.in_dd = True
            return

        if tag == "a" and self.in_dt and self.current_entry is not None:
            href = attrs_dict.get("href", "")
            if href.startswith("/pdf/") and self.current_entry["pdf_url"] is None:
                self.current_entry["pdf_url"] = urljoin(ARXIV_BASE_URL, href)
            return

        if tag == "div" and self.in_dd:
            class_names = attrs_dict.get("class", "").split()
            if "list-title" in class_names:
                self.in_title_div = True
                self.title_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_h3:
            self.h3_parts.append(data)
        if self.in_title_div:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self.in_h3:
            self._finish_h3()
            return

        if tag == "dt":
            self.in_dt = False
            return

        if tag == "div" and self.in_title_div:
            self._finish_title_div()
            return

        if tag == "dd" and self.in_dd:
            self._finish_dd()

    def _finish_h3(self) -> None:
        self.in_h3 = False
        section_date = parse_arxiv_header_date("".join(self.h3_parts))

        if section_date is None:
            self.current_section_date = None
            return

        self.current_section_date = section_date
        if section_date not in self.available_dates:
            self.available_dates.append(section_date)

        if self.latest_date is None:
            self.latest_date = section_date
            if self.range_end is None:
                self.range_end = section_date
            if self.range_start is None:
                self.range_start = self.range_end

    def _finish_title_div(self) -> None:
        self.in_title_div = False
        raw_title = normalize_text("".join(self.title_parts))
        title = raw_title.split(":", 1)[1].strip() if raw_title.lower().startswith("title:") else raw_title

        if self.current_entry is not None:
            self.current_entry["title"] = title

    def _is_in_requested_range(self) -> bool:
        if self.current_section_date is None:
            return False
        if self.range_start is None or self.range_end is None:
            return False
        return self.range_start <= self.current_section_date <= self.range_end

    def _finish_dd(self) -> None:
        self.in_dd = False
        if (
            self._is_in_requested_range()
            and self.current_entry is not None
            and self.current_entry.get("title")
            and self.current_entry.get("pdf_url")
        ):
            self.papers.append(
                Paper(
                    title=str(self.current_entry["title"]),
                    pdf_url=str(self.current_entry["pdf_url"]),
                    arxiv_date=self.current_section_date.isoformat(),
                )
            )

        self.current_entry = None


def build_recent_url(show: int) -> str:
    return f"{ARXIV_RECENT_URL}?show={show}"


def fetch_html(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def scrape_papers(
    html: str,
    target_date: Optional[date] = None,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> ArxivRecentParser:
    parser = ArxivRecentParser(target_date=target_date, start_date=start_date, end_date=end_date)
    parser.feed(html)
    parser.close()
    return parser


def validate_requested_range(parser: ArxivRecentParser) -> None:
    if parser.range_start is None or parser.range_end is None:
        raise RuntimeError("No arXiv date sections were found on the page.")

    if parser.range_start > parser.range_end:
        raise RuntimeError(
            f"Requested start date {parser.range_start.isoformat()} is later than end date {parser.range_end.isoformat()}."
        )

    if parser.available_dates and parser.requested_start_date is not None:
        earliest_available = min(parser.available_dates)
        if parser.requested_start_date < earliest_available:
            raise RuntimeError(
                "Requested start date "
                f"{parser.requested_start_date.isoformat()} is older than the earliest date "
                f"currently visible on arXiv recent page ({earliest_available.isoformat()})."
            )


def build_payload(parser: ArxivRecentParser, source_url: str) -> Dict[str, object]:
    validate_requested_range(parser)
    assert parser.range_start is not None
    assert parser.range_end is not None

    scope_id = build_scope_id(parser.range_start, parser.range_end)
    return {
        "source_url": source_url,
        "target_date": scope_id,
        "target_date_label": build_scope_label(parser.range_start, parser.range_end),
        "arxiv_start_date": parser.range_start.isoformat(),
        "arxiv_end_date": parser.range_end.isoformat(),
        "available_dates": [value.isoformat() for value in parser.available_dates],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "paper_count": len(parser.papers),
        "papers": [asdict(paper) for paper in parser.papers],
    }


def write_json(payload: Dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def build_default_output_path(run_date: date, target_date: str, output_dir: Optional[Path] = None) -> Path:
    daily_dir = output_dir.resolve() if output_dir else ROOT_DIR / "runs" / run_date.isoformat()
    return daily_dir / f"cs_ro_papers_{target_date}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape recent cs.RO papers from arXiv recent submissions."
    )
    parser.add_argument(
        "--date",
        type=parse_iso_date,
        default=None,
        help="Optional single arXiv date to scrape in YYYY-MM-DD.",
    )
    parser.add_argument(
        "--start-date",
        type=parse_iso_date,
        default=None,
        help="Optional inclusive start date in YYYY-MM-DD. Default: latest date section on the page.",
    )
    parser.add_argument(
        "--end-date",
        type=parse_iso_date,
        default=None,
        help="Optional inclusive end date in YYYY-MM-DD. Default: latest available date on the page.",
    )
    parser.add_argument(
        "--run-date",
        type=parse_iso_date,
        default=date.today(),
        help="Folder date in YYYY-MM-DD. Default: today's local date.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Explicit output JSON path.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory for the default output file name.",
    )
    parser.add_argument(
        "--show",
        type=int,
        default=DEFAULT_SHOW,
        help=f"Number of recent entries to request from arXiv. Default: {DEFAULT_SHOW}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds. Default: {DEFAULT_TIMEOUT}",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.date is not None and (args.start_date is not None or args.end_date is not None):
        print("--date cannot be combined with --start-date or --end-date.", flush=True)
        return 2

    source_url = build_recent_url(args.show)

    try:
        html = fetch_html(source_url, timeout=args.timeout)
        parser = scrape_papers(
            html,
            target_date=args.date,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        payload = build_payload(parser, source_url)
        output_path = args.output or build_default_output_path(
            args.run_date,
            str(payload["target_date"]),
            output_dir=args.output_dir,
        )
        write_json(payload, output_path)
    except URLError as exc:
        print(f"Failed to fetch {source_url}: {exc}", flush=True)
        return 1
    except RuntimeError as exc:
        print(str(exc), flush=True)
        return 1

    print(
        f"Wrote {payload['paper_count']} papers for {payload['target_date']} to {output_path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
