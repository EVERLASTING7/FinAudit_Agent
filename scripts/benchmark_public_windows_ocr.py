"""在公开数据子集上复算 Windows Media OCR 的 local/test 技术质量。"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import cast

from PIL import Image
from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.verify_public_business_benchmark as benchmark  # noqa: E402

OUTPUT_PATH = PROJECT_ROOT / "tests" / "evaluation" / "public-windows-ocr-pilot-v1.json"
HELPER_PATH = PROJECT_ROOT / "scripts" / "windows-media-ocr-batch.ps1"
QWEN_PILOT_PATH = PROJECT_ROOT / "scripts" / "run_local_qwen_contract_pilot.py"
PUBLIC_EVIDENCE_PATH = (
    PROJECT_ROOT / "tests" / "evaluation" / "public-business-benchmark-runtime-v1.json"
)

_INVOICE_COUNT = 20
_XFUND_COUNT = 20
_CONTRACT_IDS = ("93691", "93704", "94358")
_MAX_IMAGE_DIMENSION = 2400


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _binding(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "bytes": len(payload),
        "sha256": _sha256(payload),
    }


def _mapping(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError("expected object")
    return cast(dict[str, object], value)


def _compact(value: object) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", str(value)).casefold()
        if character.isalnum()
    )


def _numeric(value: object) -> str:
    raw = unicodedata.normalize("NFKC", str(value)).replace("€", "").replace(" ", "")
    if "," in raw and "." in raw:
        raw = (
            raw.replace(".", "").replace(",", ".")
            if raw.rfind(",") > raw.rfind(".")
            else raw.replace(",", "")
        )
    elif "," in raw:
        tail = raw.rsplit(",", maxsplit=1)[1]
        raw = raw.replace(",", ".") if len(tail) <= 2 else raw.replace(",", "")
    return re.sub(r"[^0-9.-]", "", raw)


def _resized_png(source: bytes, target: Path) -> None:
    with Image.open(io.BytesIO(source)) as image:
        converted = image.convert("RGB")
        if max(converted.size) > _MAX_IMAGE_DIMENSION:
            scale = _MAX_IMAGE_DIMENSION / max(converted.size)
            converted = converted.resize(
                (round(converted.width * scale), round(converted.height * scale)),
                Image.Resampling.LANCZOS,
            )
        converted.save(target)


def _run_ocr(cases: list[dict[str, str]], workdir: Path) -> dict[str, object]:
    manifest = workdir / "manifest.json"
    result_path = workdir / "result.json"
    manifest.write_bytes(
        json.dumps(
            {"schema_version": "windows-media-ocr-batch-v1", "cases": cases},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(HELPER_PATH),
            "-ManifestPath",
            str(manifest),
            "-OutputPath",
            str(result_path),
        ],
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if (
        completed.returncode != 0
        or completed.stderr
        or completed.stdout.strip()
        != f"WINDOWS_MEDIA_OCR_BATCH=PASS cases={len(cases)}"
    ):
        raise RuntimeError("WINDOWS_MEDIA_OCR_BATCH_FAILED")
    result = json.loads(result_path.read_bytes())
    if type(result) is not dict or result.get("schema_version") != (
        "windows-media-ocr-batch-result-v1"
    ):
        raise RuntimeError("WINDOWS_MEDIA_OCR_RESULT_INVALID")
    raw_cases = result.get("cases")
    if type(raw_cases) is not list or len(raw_cases) != len(cases):
        raise RuntimeError("WINDOWS_MEDIA_OCR_RESULT_INVALID")
    return cast(dict[str, object], result)


def _invoice_cases(workdir: Path) -> tuple[list[dict[str, str]], list[str]]:
    records = benchmark._zip_json_records(benchmark.ZENODO_ANNOTATIONS_ZIP)
    eligible = [
        stem
        for stem, record in records.items()
        if all(
            benchmark._normalized(record[source])
            for source in benchmark._INVOICE_DIRECT_FIELDS
        )
    ]
    stems = sorted(eligible, key=lambda value: benchmark._sha256(value.encode()))[
        :_INVOICE_COUNT
    ]
    with zipfile.ZipFile(benchmark.ZENODO_IMAGES_ZIP) as archive:
        by_stem = {
            Path(name).stem: name
            for name in archive.namelist()
            if Path(name).suffix.lower() == ".jpg"
        }
        cases = []
        for index, stem in enumerate(stems, start=1):
            target = workdir / f"invoice-{index:03d}.png"
            _resized_png(archive.read(by_stem[stem]), target)
            cases.append(
                {
                    "case_id": f"invoice-{index:03d}",
                    "input_path": str(target),
                    "language": "en-US",
                }
            )
    return cases, stems


def _xfund_cases(workdir: Path) -> tuple[list[dict[str, str]], list[str]]:
    dataset = _mapping(json.loads(benchmark.XFUND_JSON.read_bytes()))
    documents = sorted(
        (_mapping(item) for item in cast(list[object], dataset["documents"])),
        key=lambda item: str(item["id"]),
    )[:_XFUND_COUNT]
    names = [str(_mapping(document["img"])["fname"]) for document in documents]
    with zipfile.ZipFile(benchmark.XFUND_IMAGES_ZIP) as archive:
        by_name = {
            Path(name).name: name
            for name in archive.namelist()
            if name.endswith(".jpg")
        }
        cases = []
        for index, name in enumerate(names, start=1):
            target = workdir / f"xfund-{index:03d}.png"
            _resized_png(archive.read(by_name[name]), target)
            cases.append(
                {
                    "case_id": f"xfund-{index:03d}",
                    "input_path": str(target),
                    "language": "zh-Hans-CN",
                }
            )
    return cases, names


def _contract_cases(workdir: Path) -> tuple[list[dict[str, str]], dict[str, int]]:
    renderer = shutil.which("pdftoppm")
    if renderer is None:
        raise RuntimeError("PDFTOPPM_UNAVAILABLE")
    cases: list[dict[str, str]] = []
    page_counts: dict[str, int] = {}
    for contract_id in _CONTRACT_IDS:
        pdf_path = benchmark.HAIKOU_ROOT / f"{contract_id}.pdf"
        render_prefix = workdir / f"render-{contract_id}"
        completed = subprocess.run(
            [renderer, "-png", "-r", "120", str(pdf_path), str(render_prefix)],
            cwd=workdir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("PDF_RENDER_FAILED")
        pages = sorted(workdir.glob(f"render-{contract_id}-*.png"))
        if len(pages) != len(PdfReader(pdf_path).pages):
            raise RuntimeError("PDF_RENDER_PAGE_COUNT_DRIFT")
        page_counts[contract_id] = len(pages)
        for page_no, source in enumerate(pages, start=1):
            target = workdir / f"contract-{contract_id}-p{page_no:03d}.png"
            _resized_png(source.read_bytes(), target)
            cases.append(
                {
                    "case_id": f"contract-{contract_id}-p{page_no:03d}",
                    "input_path": str(target),
                    "language": "zh-Hans-CN",
                }
            )
    return cases, page_counts


def _score(
    result: dict[str, object],
    invoice_stems: list[str],
    xfund_names: list[str],
    contract_pages: dict[str, int],
) -> dict[str, object]:
    raw_cases = cast(list[object], result["cases"])
    cases = {_mapping(case)["case_id"]: _mapping(case) for case in raw_cases}
    failure_count = sum(case["status"] != "succeeded" for case in cases.values())

    records = benchmark._zip_json_records(benchmark.ZENODO_ANNOTATIONS_ZIP)
    invoice_field_counts = {
        source: {"matched": 0, "total": 0}
        for source in benchmark._INVOICE_DIRECT_FIELDS
    }
    invoice_match = invoice_total = 0
    invoice_chars: list[int] = []
    for index, stem in enumerate(invoice_stems, start=1):
        text = str(cases[f"invoice-{index:03d}"]["text"] or "")
        invoice_chars.append(len(text))
        for source in benchmark._INVOICE_DIRECT_FIELDS:
            expected = records[stem][source]
            invoice_total += 1
            invoice_field_counts[source]["total"] += 1
            matched = (
                bool(_numeric(expected)) and _numeric(expected) in _numeric(text)
                if source in {"iva_amount", "total"}
                else bool(_compact(expected)) and _compact(expected) in _compact(text)
            )
            if matched:
                invoice_match += 1
                invoice_field_counts[source]["matched"] += 1

    xfund = _mapping(json.loads(benchmark.XFUND_JSON.read_bytes()))
    documents = {
        str(_mapping(document["img"])["fname"]): document
        for document in (
            _mapping(item) for item in cast(list[object], xfund["documents"])
        )
    }
    entity_match = entity_total = 0
    xfund_chars: list[int] = []
    for index, name in enumerate(xfund_names, start=1):
        text = str(cases[f"xfund-{index:03d}"]["text"] or "")
        xfund_chars.append(len(text))
        for raw_entity in cast(list[object], documents[name]["document"]):
            entity = _mapping(raw_entity)
            expected = _compact(entity["text"])
            if expected:
                entity_total += 1
                entity_match += expected in _compact(text)

    contract_rows: list[dict[str, object]] = []
    contract_match = contract_total = 0
    for contract_id in _CONTRACT_IDS:
        texts = [
            str(cases[f"contract-{contract_id}-p{page_no:03d}"]["text"] or "")
            for page_no in range(1, contract_pages[contract_id] + 1)
        ]
        combined = "\n".join(texts)
        expected = benchmark._haikou_expected(
            (benchmark.HAIKOU_ROOT / f"{contract_id}.html").read_bytes()
        )
        matched_fields = [
            field_code
            for field_code, expected_value in expected.items()
            if (
                _numeric(expected_value) in _numeric(combined)
                if field_code == "amount"
                else _compact(expected_value) in _compact(combined)
            )
        ]
        contract_match += len(matched_fields)
        contract_total += len(expected)
        contract_rows.append(
            {
                "case_id": contract_id,
                "page_count": contract_pages[contract_id],
                "matched_field_count": len(matched_fields),
                "expected_field_count": len(expected),
                "matched_field_codes": sorted(matched_fields),
                "ocr_text_char_count": len(combined),
            }
        )

    return {
        "failure_count": failure_count,
        "invoice": {
            "case_count": len(invoice_stems),
            "matched_direct_field_count": invoice_match,
            "total_direct_field_count": invoice_total,
            "direct_field_accuracy": f"{invoice_match / invoice_total:.6f}",
            "threshold": "0.950000",
            "threshold_status": "FAILED",
            "field_counts": invoice_field_counts,
            "ocr_text_char_range": [min(invoice_chars), max(invoice_chars)],
        },
        "xfund": {
            "case_count": len(xfund_names),
            "matched_entity_count": entity_match,
            "total_entity_count": entity_total,
            "entity_recall": f"{entity_match / entity_total:.6f}",
            "ocr_text_char_range": [min(xfund_chars), max(xfund_chars)],
        },
        "contract": {
            "case_count": len(_CONTRACT_IDS),
            "matched_direct_field_count": contract_match,
            "total_direct_field_count": contract_total,
            "direct_field_visibility": f"{contract_match / contract_total:.6f}",
            "threshold": "0.850000",
            "threshold_status": "FAILED",
            "cases": contract_rows,
        },
    }


def build_artifact() -> dict[str, object]:
    (PROJECT_ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="finaudit-public-ocr-", dir=PROJECT_ROOT / "tmp"
    ) as raw:
        workdir = Path(raw)
        invoice_cases, invoice_stems = _invoice_cases(workdir)
        xfund_cases, xfund_names = _xfund_cases(workdir)
        contract_cases, contract_pages = _contract_cases(workdir)
        all_cases = invoice_cases + xfund_cases + contract_cases
        result = _run_ocr(all_cases, workdir)
        metrics = _score(result, invoice_stems, xfund_names, contract_pages)

    return {
        "schema_version": "public-windows-ocr-pilot-v1",
        "classification": "public_open_data_local_test_technical_measurement",
        "source_binding": [
            _binding(Path(__file__)),
            _binding(HELPER_PATH),
            _binding(QWEN_PILOT_PATH),
            _binding(PUBLIC_EVIDENCE_PATH),
        ],
        "runtime": {
            "engine": "windows-media-ocr",
            "languages": ["en-US", "zh-Hans-CN"],
            "case_count": _INVOICE_COUNT + _XFUND_COUNT + sum(contract_pages.values()),
            "provider_network_calls": 0,
            "paid_cost_cny": "0.000000",
            "temporary_raw_ocr_output_removed": True,
            "raw_ocr_text_persisted_in_evidence": False,
        },
        "metrics": metrics,
        "local_qwen_contract_pilot": {
            "model": "qwen3:8b",
            "model_storage": "preexisting_local_cache",
            "attempt_count": 3,
            "production_schema_attempt": "HTTP_400_GRAMMAR_REGEX_UNSUPPORTED",
            "full_json_mode_attempt": "TIMEOUT_300_SECONDS",
            "filtered_json_mode_attempt": {
                "status": "COMPLETED_INVALID_OUTPUT",
                "elapsed_ms": "107781.000",
                "block_selection": "field_term_plus_adjacent_lines_max_80",
                "ocr_block_count": 80,
                "prompt_eval_count": 4098,
                "eval_count": 806,
                "output_valid": False,
                "matched_field_count": 0,
                "expected_field_count": 9,
                "response_sha256": (
                    "A01C461CE3A02843ED06A4E29C9270D32612679341DD6ACA94DD2D6A445DA8A0"
                ),
            },
            "retry_count": 0,
            "output_adopted": False,
            "provider_network_calls": 0,
            "paid_cost_cny": "0.000000",
            "cleanup_remaining_process_count": 0,
            "cleanup_listener_11434": False,
            "cleanup_listener_8764": False,
        },
        "quality_gate_summary": {
            "invoice_95": "FAILED",
            "contract_85": "FAILED",
            "complex_chinese_form_quality": "BELOW_FORMAL_THRESHOLD_NOT_DEFINED",
            "overall_status": "MEASURED_FAILED",
        },
        "acceptance_boundary": {
            "default_local_profile_changed": False,
            "is_customer_business_representative_dataset": False,
            "is_human_uat": False,
            "is_formal_ac_acceptance": False,
            "may_mark_ac_accepted": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = _canonical_bytes(build_artifact())
    if args.check:
        if not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_bytes() != payload:
            print("PUBLIC_WINDOWS_OCR_PILOT=DRIFT")
            return 1
        print("PUBLIC_WINDOWS_OCR_PILOT=MEASURED_FAILED_EVIDENCE_PASS")
        return 0
    OUTPUT_PATH.write_bytes(payload)
    print(
        "PUBLIC_WINDOWS_OCR_PILOT=MEASURED_FAILED "
        f"sha256={_sha256(payload)} raw_ocr_text_persisted=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
