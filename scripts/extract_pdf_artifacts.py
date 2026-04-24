#!/usr/bin/env python3
"""Extract PDF figures/tables with Docling only and write artifact indexes."""

import argparse
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - user-facing dependency check.
    raise SystemExit(
        "Missing image dependencies. Run this script with the bundled workspace Python, "
        "or use ./extract_pdf_artifacts.sh."
    ) from exc

try:
    from docling.datamodel.base_models import ConversionStatus, InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.utils.model_downloader import download_models as docling_download_models
    from docling_core.types.doc import PictureItem, TableItem
except ImportError:  # pragma: no cover - user-facing dependency check.
    ConversionStatus = None
    InputFormat = None
    PdfPipelineOptions = None
    DocumentConverter = None
    PdfFormatOption = None
    docling_download_models = None
    PictureItem = None
    TableItem = None


ROOT_DIR = Path(__file__).resolve().parent.parent
CAPTION_RE = re.compile(
    r"^\s*(?P<kind>Fig(?:ure)?\.?|Table)\s*(?P<number>[IVXLCDM]+|[A-Z]|\d+[A-Za-z]?)\s*[:.\-]?\s*(?P<body>.*)",
    re.IGNORECASE,
)


@dataclass
class ExtractedImage:
    page: int
    index: int
    path: str
    width: int
    height: int


@dataclass
class Caption:
    kind: str
    number: str
    page: int
    text: str
    table_path: str = ""
    crop_path: str = ""


def find_latest_run_dir(root: Path) -> Path:
    runs_dir = root / "runs"
    dirs = [
        child
        for child in runs_dir.iterdir()
        if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name)
    ]
    if not dirs:
        raise FileNotFoundError("No YYYY-MM-DD run directory found.")
    return max(dirs, key=lambda path: path.name)


def arxiv_id_from_path(path: Path) -> str:
    return path.name.split("_", 1)[0]


def safe_slug(value: str, max_len: int = 50) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return slug[:max_len] or "artifact"


def save_image(image: Image.Image, output_path: Path) -> None:
    if image.mode not in {"RGB", "RGBA", "L"}:
        image = image.convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def require_docling_installed() -> None:
    if (
        DocumentConverter is None
        or PdfPipelineOptions is None
        or PdfFormatOption is None
        or InputFormat is None
        or ConversionStatus is None
        or PictureItem is None
        or TableItem is None
    ):
        raise RuntimeError(
            "Docling is not installed or not fully available. "
            "This project now uses Docling only for PDF artifact extraction."
        )


def docling_models_ready(models_dir: Path) -> bool:
    layout_model = models_dir / "docling-project--docling-layout-heron" / "model.safetensors"
    table_model = (
        models_dir
        / "docling-project--docling-models"
        / "model_artifacts"
        / "tableformer"
        / "accurate"
        / "tableformer_accurate.safetensors"
    )
    return layout_model.exists() and table_model.exists()


def download_docling_minimal_models(models_dir: Path) -> None:
    if docling_download_models is None:
        raise RuntimeError(
            "Docling is not installed. Install it first before downloading models."
        )

    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    models_dir.mkdir(parents=True, exist_ok=True)
    docling_download_models(
        output_dir=models_dir,
        progress=True,
        with_layout=True,
        with_tableformer=True,
        with_tableformer_v2=False,
        with_code_formula=False,
        with_picture_classifier=False,
        with_smolvlm=False,
        with_granitedocling=False,
        with_granitedocling_mlx=False,
        with_smoldocling=False,
        with_smoldocling_mlx=False,
        with_granite_vision=False,
        with_granite_chart_extraction=False,
        with_granite_chart_extraction_v4=False,
        with_rapidocr=False,
        with_easyocr=False,
    )


def build_docling_converter(models_dir: Path, image_scale: float) -> "DocumentConverter":
    require_docling_installed()

    options = PdfPipelineOptions()
    options.artifacts_path = models_dir
    options.do_ocr = False
    options.do_table_structure = True
    options.do_code_enrichment = False
    options.do_formula_enrichment = False
    options.do_picture_classification = False
    options.do_picture_description = False
    options.do_chart_extraction = False
    options.generate_page_images = True
    options.generate_picture_images = True
    options.images_scale = image_scale

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
        }
    )


def caption_number_from_text(kind: str, caption_text: str, fallback_index: int) -> str:
    match = CAPTION_RE.search(caption_text)
    if match:
        return match.group("number")
    prefix = "T" if kind == "Table" else "F"
    return f"{prefix}{fallback_index}"


def extract_with_docling(
    converter: "DocumentConverter",
    pdf_path: Path,
    arxiv_id: str,
    figures_dir: Path,
    tables_dir: Path,
    tmp_text_dir: Optional[Path],
    max_artifacts: int,
) -> tuple[List[ExtractedImage], List[Caption]]:
    require_docling_installed()

    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    if tmp_text_dir:
        tmp_text_dir.mkdir(parents=True, exist_ok=True)

    result = converter.convert(pdf_path)
    if result.status != ConversionStatus.SUCCESS:
        raise RuntimeError(f"Docling conversion failed for {pdf_path.name}: {result.status}")

    doc = result.document
    if tmp_text_dir:
        (tmp_text_dir / f"{arxiv_id}.txt").write_text(
            doc.export_to_text(traverse_pictures=True),
            encoding="utf-8",
        )

    images: List[ExtractedImage] = []
    captions: List[Caption] = []
    seen = set()
    figure_index = 0
    table_index = 0

    for item, _level in doc.iterate_items():
        if isinstance(item, PictureItem):
            kind = "Figure"
            figure_index += 1
            fallback_index = figure_index
        elif isinstance(item, TableItem):
            kind = "Table"
            table_index += 1
            fallback_index = table_index
        else:
            continue

        caption_text = " ".join(item.caption_text(doc).split())
        if kind == "Figure" and not caption_text:
            continue

        match = CAPTION_RE.search(caption_text)
        if match:
            raw_kind = match.group("kind")
            kind = "Table" if raw_kind.lower().startswith("table") else "Figure"

        page_number = item.prov[0].page_no if getattr(item, "prov", None) else 0
        number = caption_number_from_text(kind, caption_text, fallback_index=fallback_index)
        key = (kind, number, page_number, caption_text[:140])
        if key in seen:
            continue
        seen.add(key)

        crop_path = ""
        pil_image = item.get_image(doc)
        if pil_image is not None:
            filename = (
                f"{arxiv_id}_{kind.lower()}_{safe_slug(number)}_p{page_number:02d}_docling_{fallback_index:02d}.png"
            )
            output_path = figures_dir / filename
            save_image(pil_image, output_path)
            images.append(
                ExtractedImage(
                    page=page_number,
                    index=fallback_index,
                    path=str(output_path),
                    width=pil_image.width,
                    height=pil_image.height,
                )
            )
            crop_path = str(output_path)

        caption = Caption(
            kind=kind,
            number=number,
            page=page_number,
            text=caption_text or f"{kind} {number}",
            crop_path=crop_path,
        )

        if kind == "Table":
            table_path = tables_dir / f"{arxiv_id}_table_{safe_slug(number)}_p{page_number:02d}_docling.md"
            table_markdown = item.export_to_markdown(doc=doc).strip()
            table_path.write_text(
                f"# {arxiv_id} Table {number}\n\n"
                f"- Page: {page_number}\n"
                f"- Extracted with Docling table structure.\n"
                f"- Crop: {crop_path if crop_path else 'not available'}\n\n"
                f"{table_markdown}\n",
                encoding="utf-8",
            )
            caption.table_path = str(table_path)

        captions.append(caption)
        if len(images) >= max_artifacts:
            break

    return images, captions


def cleanup_generated_outputs(
    arxiv_id: str,
    figures_dir: Path,
    tables_dir: Path,
    artifacts_dir: Path,
    tmp_text_dir: Optional[Path],
) -> None:
    for directory in (figures_dir, tables_dir):
        if not directory.exists():
            continue
        for path in directory.glob(f"{arxiv_id}_*"):
            if path.is_file():
                path.unlink()
    artifact_path = artifacts_dir / f"{arxiv_id}_artifacts.json"
    if artifact_path.exists():
        artifact_path.unlink()
    if tmp_text_dir and tmp_text_dir.exists():
        for path in tmp_text_dir.glob(f"{arxiv_id}*"):
            if path.is_file():
                path.unlink()


def rehome_extracted_paths(
    images: List[ExtractedImage],
    captions: List[Caption],
    figures_dir: Path,
    tables_dir: Path,
) -> tuple[List[ExtractedImage], List[Caption]]:
    remapped_images: List[ExtractedImage] = []
    for image in images:
        filename = Path(image.path).name
        remapped_images.append(
            ExtractedImage(
                page=image.page,
                index=image.index,
                path=str(figures_dir / filename),
                width=image.width,
                height=image.height,
            )
        )

    remapped_captions: List[Caption] = []
    for caption in captions:
        crop_path = str(figures_dir / Path(caption.crop_path).name) if caption.crop_path else ""
        table_path = str(tables_dir / Path(caption.table_path).name) if caption.table_path else ""
        remapped_captions.append(
            Caption(
                kind=caption.kind,
                number=caption.number,
                page=caption.page,
                text=caption.text,
                table_path=table_path,
                crop_path=crop_path,
            )
        )
    return remapped_images, remapped_captions


def finalize_generated_outputs(
    *,
    arxiv_id: str,
    pdf_path: Path,
    images: List[ExtractedImage],
    captions: List[Caption],
    temp_figures_dir: Path,
    temp_tables_dir: Path,
    temp_text_dir: Optional[Path],
    figures_dir: Path,
    tables_dir: Path,
    artifacts_dir: Path,
    tmp_text_dir: Optional[Path],
) -> None:
    remapped_images, remapped_captions = rehome_extracted_paths(images, captions, figures_dir, tables_dir)

    cleanup_generated_outputs(arxiv_id, figures_dir, tables_dir, artifacts_dir, tmp_text_dir)
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for source in sorted(temp_figures_dir.glob(f"{arxiv_id}_*")):
        shutil.move(str(source), str(figures_dir / source.name))
    for source in sorted(temp_tables_dir.glob(f"{arxiv_id}_*")):
        shutil.move(str(source), str(tables_dir / source.name))

    if tmp_text_dir and temp_text_dir:
        tmp_text_dir.mkdir(parents=True, exist_ok=True)
        for source in sorted(temp_text_dir.glob(f"{arxiv_id}*")):
            shutil.move(str(source), str(tmp_text_dir / source.name))

    artifact_json_path = artifacts_dir / f"{arxiv_id}_artifacts.json"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=artifacts_dir,
        prefix=f".{artifact_json_path.stem}_",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_json_path = Path(handle.name)
        json.dump(
            {
                "arxiv_id": arxiv_id,
                "pdf_path": str(pdf_path),
                "backend": "docling",
                "images": [asdict(image) for image in remapped_images],
                "captions": [asdict(caption) for caption in remapped_captions],
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")

    os.replace(temp_json_path, artifact_json_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract PDF artifacts with Docling only.")
    parser.add_argument("--root", type=Path, default=ROOT_DIR, help="PaperReading root directory.")
    parser.add_argument("--run-dir", type=Path, default=None, help="Run directory. Default: latest under runs/.")
    parser.add_argument(
        "--backend",
        choices=["docling"],
        default="docling",
        help="Artifact extraction backend. Only Docling is supported.",
    )
    parser.add_argument("--max-images", type=int, default=30, help="Maximum artifacts to extract per paper.")
    parser.add_argument(
        "--docling-models-dir",
        type=Path,
        default=ROOT_DIR / "tmp" / "docling_models",
        help="Local Docling artifacts directory for offline conversion.",
    )
    parser.add_argument(
        "--docling-image-scale",
        type=float,
        default=2.0,
        help="Docling page image scale used for item cropping.",
    )
    parser.add_argument(
        "--docling-download-models",
        action="store_true",
        help="Download minimal Docling layout/table models into --docling-models-dir before extraction.",
    )
    parser.add_argument("--write-tmp-text", action="store_true", help="Write extracted PDF text to tmp/pdf_text.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    run_dir = args.run_dir.resolve() if args.run_dir else find_latest_run_dir(root)
    docling_models_dir = args.docling_models_dir.resolve()
    figures_dir = run_dir / "figures"
    tables_dir = run_dir / "tables"
    artifacts_dir = run_dir / "artifacts"
    tmp_text_dir = root / "tmp" / "pdf_text" if args.write_tmp_text else None
    (root / "tmp").mkdir(parents=True, exist_ok=True)

    require_docling_installed()

    if args.docling_download_models:
        download_docling_minimal_models(docling_models_dir)

    if not docling_models_ready(docling_models_dir):
        raise FileNotFoundError(
            f"Docling models are not ready in {docling_models_dir}. "
            "Run again with --docling-download-models."
        )

    analysis_paths = sorted((run_dir / "analyses").glob("*.md"))
    if not analysis_paths:
        raise FileNotFoundError(f"No analysis Markdown files found in {run_dir / 'analyses'}")

    docling_converter = build_docling_converter(
        docling_models_dir,
        image_scale=args.docling_image_scale,
    )

    total_images = 0
    total_captions = 0
    processed = 0
    for analysis_path in analysis_paths:
        arxiv_id = arxiv_id_from_path(analysis_path)
        pdf_matches = sorted((root / "papers").glob(f"{arxiv_id}_*.pdf"))
        if not pdf_matches:
            print(f"Skip {arxiv_id}: PDF not found")
            continue

        pdf_path = pdf_matches[0]
        with tempfile.TemporaryDirectory(prefix=f"docling_{arxiv_id}_", dir=root / "tmp") as temp_root_str:
            temp_root = Path(temp_root_str)
            temp_figures_dir = temp_root / "figures"
            temp_tables_dir = temp_root / "tables"
            temp_text_dir = temp_root / "pdf_text" if tmp_text_dir else None

            images, captions = extract_with_docling(
                docling_converter,
                pdf_path,
                arxiv_id,
                temp_figures_dir,
                temp_tables_dir,
                tmp_text_dir=temp_text_dir,
                max_artifacts=args.max_images,
            )
            finalize_generated_outputs(
                arxiv_id=arxiv_id,
                pdf_path=pdf_path,
                images=images,
                captions=captions,
                temp_figures_dir=temp_figures_dir,
                temp_tables_dir=temp_tables_dir,
                temp_text_dir=temp_text_dir,
                figures_dir=figures_dir,
                tables_dir=tables_dir,
                artifacts_dir=artifacts_dir,
                tmp_text_dir=tmp_text_dir,
            )

        total_images += len(images)
        total_captions += len(captions)
        processed += 1
        print(f"{arxiv_id}: {len(images)} images, {len(captions)} captions")

    print(f"Processed analyses: {processed}")
    print("Backend: docling")
    print(f"Extracted images: {total_images}")
    print(f"Extracted captions: {total_captions}")
    print(f"Figures dir: {figures_dir}")
    print(f"Tables dir: {tables_dir}")
    print(f"Artifacts dir: {artifacts_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
