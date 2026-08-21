"""核验公开业务数据，并在当前 Local MVP Profile 上生成脱敏质量证据。

原始合同、票面和标注只保存在被 Git 忽略的 ``data/``；输出仅含计数、哈希和状态。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.adapters.ocr import NotConfiguredOcrEngine  # noqa: E402
from app.schemas.contracts import CONTRACT_CORE_FIELD_CODES  # noqa: E402
from app.services.contract_extractor import (  # noqa: E402
    ContractSourceBlock,
    extract_contract_candidate,
)
from app.services.document_parser import (  # noqa: E402
    DocumentParseError,
    DocumentParser,
    ParsedDocument,
)

DATA_ROOT = PROJECT_ROOT / "data" / "public-benchmark"
OUTPUT_PATH = (
    PROJECT_ROOT / "tests" / "evaluation" / "public-business-benchmark-runtime-v1.json"
)

CUAD_ZIP = DATA_ROOT / "cuad" / "data.verified.zip"
CUAD_PDF_ROOT = DATA_ROOT / "cuad" / "pdf-sample-v1-verified"
ZENODO_ANNOTATIONS_ZIP = (
    DATA_ROOT / "zenodo-6371710" / "2_Annotations_Json.verified.zip"
)
ZENODO_IMAGES_ZIP = DATA_ROOT / "zenodo-6371710" / "1_Images.verified.zip"
XFUND_JSON = DATA_ROOT / "xfund-v1" / "zh.val.verified.json"
XFUND_IMAGES_ZIP = DATA_ROOT / "xfund-v1" / "zh.val.verified.zip"
HAIKOU_ROOT = DATA_ROOT / "haikou-contracts-v1"

_OWNER_INSTRUCTION = (
    "我无法提供仓库外的脱敏代表性业务数据路径及 approval_ref，覆盖合同、发票、"
    "重复标签、风险标准答案和复杂多格式文档，需要你自己去寻找"
)
_CUAD_REVISION = "a3c393f5d103fd0c516374e4fdff676c8176dcb1"
_CUAD_DATA_GIT_BLOB = "1AE94FF0A9B70B2E3B9B8D215737C8BFAE460DDC"
_ZENODO_ANNOTATIONS_MD5 = "941DEEC66609F158CFD7CE5ADD75A17B"
_ZENODO_IMAGES_MD5 = "5109286806B96DB32DA7D6206051EE61"
_XFUND_JSON_SHA256 = "B11140881255916A16670EA5006295D0185B8376287AA4AA76AE4E1107F61E3D"
_XFUND_IMAGES_SHA256 = (
    "A30E6E5C274EA8236C9B00C46AB96D59829A5BCD08BAEE966FA433028B644456"
)

_CUAD_DIRECT_FIELDS = {
    "Document Name": "name",
    "Agreement Date": "signed_date",
    "Effective Date": "effective_date",
    "Expiration Date": "expiry_date",
}
_INVOICE_DIRECT_FIELDS = {
    "invoice_number": "invoice_number",
    "date": "invoice_date",
    "company": "seller_name",
    "nif_seller": "seller_tax_no",
    "nif_buyer": "buyer_tax_no",
    "iva_amount": "tax_amount",
    "total": "total_amount",
}
_INVOICE_ANNOTATION_KEYS = frozenset(
    {
        "address",
        "company",
        "date",
        "invoice_number",
        "iva_amount",
        "nif_buyer",
        "nif_seller",
        "total",
    }
)
_LABEL_PATTERN = re.compile(r'related to "([^"]+)"')
_SAFE_METADATA_COINCIDENCES = frozenset({"currency", "distributor"})


@dataclass(frozen=True, slots=True)
class CuadCase:
    case_id: str
    category: str
    title: str
    source_path: str
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class HaikouCase:
    case_id: str
    html_bytes: int
    html_sha256: str
    pdf_bytes: int
    pdf_sha256: str
    pdf_url_sha256: str


_CUAD_CASES = (
    CuadCase(
        "case-01",
        "Consulting Agreements",
        "MEDALISTDIVERSIFIEDREIT,INC_05_18_2020-EX-10.1-CONSULTING AGREEMENT",
        "CUAD_v1/full_contract_pdf/Part_II/Commercial Contracts (Part II-A)/Consulting Agreements/MEDALISTDIVERSIFIEDREIT,INC_05_18_2020-EX-10.1-CONSULTING AGREEMENT.PDF",
        132840,
        "DA9A74DE24E274A3E0D915DD43CAC84D733D90181EF4655848AD1FBC67390AEA",
    ),
    CuadCase(
        "case-02",
        "Development",
        "CoherusBiosciencesInc_20200227_10-K_EX-10.29_12021376_EX-10.29_Development Agreement",
        "CUAD_v1/full_contract_pdf/Part_I/Development/CoherusBiosciencesInc_20200227_10-K_EX-10.29_12021376_EX-10.29_Development Agreement.pdf",
        364388,
        "538DD56AE45DF2C3BFA7176AF8F76F0C561CA83B996BFD00DB190D44D31C0D9E",
    ),
    CuadCase(
        "case-03",
        "Franchise",
        "SoupmanInc_20150814_8-K_EX-10.1_9230148_EX-10.1_Franchise Agreement1",
        "CUAD_v1/full_contract_pdf/Part_I/Franchise/SoupmanInc_20150814_8-K_EX-10.1_9230148_EX-10.1_Franchise Agreement1.pdf",
        348836,
        "FABE82FF8946649D5AD789D0EC3028EFDCAFE1F57E3E503ABD0E3067A246DFA0",
    ),
    CuadCase(
        "case-04",
        "IP",
        "ArmstrongFlooringInc_20190107_8-K_EX-10.2_11471795_EX-10.2_Intellectual Property Agreement",
        "CUAD_v1/full_contract_pdf/Part_I/IP/ArmstrongFlooringInc_20190107_8-K_EX-10.2_11471795_EX-10.2_Intellectual Property Agreement.pdf",
        616962,
        "23756D11A458640E4183B8B52F63DDFB2DEE8E0EEF071365A275E9374C88C4B8",
    ),
    CuadCase(
        "case-05",
        "License_Agreements",
        "PlayboyEnterprisesInc_20090220_10-QA_EX-10.2_4091580_EX-10.2_Content License Agreement_ Marketing Agreement_ Sales-Purchase Agreement1",
        "CUAD_v1/full_contract_pdf/Part_I/License_Agreements/PlayboyEnterprisesInc_20090220_10-QA_EX-10.2_4091580_EX-10.2_Content License Agreement_ Marketing Agreement_ Sales-Purchase Agreement1.pdf",
        583647,
        "48EBF5D163F8412D8CD20BFC9AA39DE5AE0EDE22DFFA0337207B5E1EA30A43A9",
    ),
    CuadCase(
        "case-06",
        "Manufacturing",
        "UpjohnInc_20200121_10-12G_EX-2.6_11948692_EX-2.6_Manufacturing Agreement_ Supply Agreement",
        "CUAD_v1/full_contract_pdf/Part_I/Manufacturing/UpjohnInc_20200121_10-12G_EX-2.6_11948692_EX-2.6_Manufacturing Agreement_ Supply Agreement.pdf",
        484132,
        "893909BF198D75E1B608756B10EEA3B698B42CC0D5DE30D984F0DA48E797ECBB",
    ),
    CuadCase(
        "case-07",
        "Non_Compete_Non_Solicit",
        "Quaker Chemical Corporation - NON COMPETITION AND NON SOLICITATION AGREEMENT",
        "CUAD_v1/full_contract_pdf/Part_I/Non_Compete_Non_Solicit/Quaker Chemical Corporation - NON COMPETITION AND NON SOLICITATION AGREEMENT.PDF",
        159637,
        "AEB564E913C8B9FD9C966A00101DB41F4D4D9C9EAE12B08A3F4D3B67CDE8F393",
    ),
    CuadCase(
        "case-08",
        "Service",
        "MERITLIFEINSURANCECO_06_19_2020-EX-10.(XIV)-MASTER SERVICES AGREEMENT",
        "CUAD_v1/full_contract_pdf/Part_III/Service/MERITLIFEINSURANCECO_06_19_2020-EX-10.(XIV)-MASTER SERVICES AGREEMENT.PDF",
        145610,
        "0F577FA1F2EA5E063986ACA8875AFD9EAB79BAD38BEE836C23911864F51E375C",
    ),
    CuadCase(
        "case-09",
        "Supply",
        "VERICELCORP_08_06_2019-EX-10.10-SUPPLY AGREEMENT",
        "CUAD_v1/full_contract_pdf/Part_III/Supply/VERICELCORP_08_06_2019-EX-10.10-SUPPLY AGREEMENT.PDF",
        272163,
        "020D229861103C9005F5D42D6FE452CFEA26B19F09767411769ACDE1703167DF",
    ),
    CuadCase(
        "case-10",
        "Transportation",
        "DYNAMEXINC_06_06_1996-EX-10.4-TRANSPORTATION SERVICES AGREEMENT",
        "CUAD_v1/full_contract_pdf/Part_II/Commercial Contracts (Part II-A)/Transportation/DYNAMEXINC_06_06_1996-EX-10.4-TRANSPORTATION SERVICES AGREEMENT.PDF",
        80095,
        "9A043F22F7F177B9EAC551A14FBF41E540D7E94B4404D1B902E8C881024D3776",
    ),
    CuadCase(
        "case-11",
        "Distributor",
        "ZogenixInc_20190509_10-Q_EX-10.2_11663313_EX-10.2_Distributor Agreement",
        "CUAD_v1/full_contract_pdf/Part_I/Distributor/ZogenixInc_20190509_10-Q_EX-10.2_11663313_EX-10.2_Distributor Agreement.pdf",
        447391,
        "851E4E747A64D82C3C4AB64AFE2C7956FD260B815AF7818694D89015F6E0D41E",
    ),
    CuadCase(
        "case-12",
        "Outsourcing",
        "MANUFACTURERSSERVICESLTD_06_05_2000-EX-10.14-OUTSOURCING AGREEMENT",
        "CUAD_v1/full_contract_pdf/Part_III/Outsourcing/MANUFACTURERSSERVICESLTD_06_05_2000-EX-10.14-OUTSOURCING AGREEMENT.PDF",
        328203,
        "7A0A768F0B7EB776E48ABBD8CEAE001C0C90B879983907FC8499C33CD67425F4",
    ),
)

_HAIKOU_CASES = (
    HaikouCase(
        "91874",
        74033,
        "FBC5F6889C264596FBC895794DE307FA24E336D7C02E4A8C832446094E0F9AA8",
        23004156,
        "5442978E86A15F67927D62DDA9CC826CC9306F6ECCEE7F9F10D6FB4FA81749BE",
        "C9BBD15323FD1B210FF20D9AA91E821D79539D7BFB041177447EB96503AA41BE",
    ),
    HaikouCase(
        "92193",
        73889,
        "08B7E3793DABC7283358EFF53F81FCB12BD670F88536EC95BD05C1A657FCCB43",
        9703645,
        "3DD852D852FA4DC5E23693315EC4D0B4492D62B97CB8B7F059BDF9FFAB1693AC",
        "8290A9AD433B119CA3DEC2CDD5D60E60AE1E2540548F43F7F9B40750C334323D",
    ),
    HaikouCase(
        "92562",
        74064,
        "3B9F90B6464700471A7B3D54FF9FC3997E21752B9BB58403CD586261950FAC87",
        3002725,
        "4A4D7EA634E6A6F12E827E8F2B26569A29134F77453034F858629F0E68CDD1E7",
        "AC8BB60D71D46E2B31C3911C3C1D809A4BA5B0E882E9691C89DDD580FADFF",
    ),
    HaikouCase(
        "93311",
        73980,
        "6A745055792435592E101508E0A691B2E089354F0245CEEC3A9CB484E029F6E0",
        3052690,
        "E4676E066C72E4557AE5E215412660BAC833F66A20D58474A96B51A0DBF116BE",
        "999008547528013CC59A84D2F5E2D52F2056BE77C5AC5AB0C92BC29CBC5A0647",
    ),
    HaikouCase(
        "93389",
        74033,
        "064187A66991DDAEBBEF0DBD97FE8EF3C0399EBAC38F107A82A16FE86A0ACDBA",
        3927027,
        "8FACC46B652EDF7C73B5A9ECAC456C88D9DD909C194FEA816E0C98EE0AAC07C8",
        "E9768B129908D5A546EF837EA918F5E68505986538D571BA921F4ACDE8003CB5",
    ),
    HaikouCase(
        "93691",
        73822,
        "FF83EEB33B176C24DA2D746026FE90109A23FE25E867AEB4E8F0CDD6CA194DEC",
        499417,
        "E27201321109988FFA5BF9A94EDBB7BB6423E9329AB6B234E913F59C04132DB1",
        "03D5E548E0ECF5757400752C16CA038C08B827E5E51E29FBA138C84D26C2A9B9",
    ),
    HaikouCase(
        "93704",
        74064,
        "CFFA5A55A420F82E99BEBA0807219572995A9B2EBC0F2BDD16F0F478B0D8F3F9",
        735677,
        "C665D9F9C530677192DCA5AA0F6108EE1F66D4ADB912CB6706F9075C14E12FCF",
        "5DD3F2897A78B787DD1235CE81D99705628CDC231FADD6E93E61C4736ACA8E0F",
    ),
    HaikouCase(
        "93884",
        74001,
        "C3D86EAE2DA2225D34499162210F9815629A62A94AC329D9F060D3D2A6943088",
        18351779,
        "77E22BAC876C5A289D3A79B351F179A12466B6AAA248DBD359BE63BE38C6A5D1",
        "D8B6EC2E9BD98D45A6F2F6EBA4DC08BB60C07D8CE252D654090505777C4BCEED",
    ),
    HaikouCase(
        "94358",
        74099,
        "95B7ED04DEDB2477A5B59F291FF4F50A496C36A86A83B7E0C831CDA7238E0E25",
        1083082,
        "5F5C482829EB6CAFBC2CB916D17FF4A1B37CF8AA344A903755591C0BFC32A7C0",
        "D3C2676AFA7C9894BCA7C10A77437E510295E6378D8F646B28151689DB45542A",
    ),
    HaikouCase(
        "94568",
        73988,
        "626C3CFDCB54DCF8213D64F56FC792CD5B46156B3E99D9A5F6EEB0D7B0FEBF67",
        8708313,
        "58183D9A8EEBFDA5320F3F12372832E8970F3751132514D256C4A1D4471672B6",
        "036C5C0D553E286B535552D220DFD184BFC13DF0147CAF91EF551AF83B2F8BB4",
    ),
)

_HAIKOU_PATTERNS = {
    "contract_no": re.compile(r"一、合同编号[：:]\s*([^\n]+)"),
    "name": re.compile(r"二、合同名称[：:]\s*([^\n]+)"),
    "party_a_name": re.compile(r"采购人\(甲方\)[：:]\s*([^\n]+)"),
    "party_b_name": re.compile(r"供应商\(乙方\)[：:]\s*([^\n]+)"),
    "amount": re.compile(r"合同金额[：:]\s*([0-9,]+(?:\.[0-9]{2})?)元"),
    "term": re.compile(
        r"履约期限[：:]\s*(\d{4}年\d{2}月\d{2}日)至(\d{4}年\d{2}月\d{2}日)"
    ),
    "signed_date": re.compile(r"七、合同签订日期\s*(\d{4}年\d{2}月\d{2}日)"),
    "currency": re.compile(r"合同金额[：:].{0,100}大写\(人民币\)", re.DOTALL),
}


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _md5(payload: bytes) -> str:
    return hashlib.md5(payload, usedforsecurity=False).hexdigest().upper()


def _git_blob_sha1(payload: bytes) -> str:
    prefix = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(prefix + payload, usedforsecurity=False).hexdigest().upper()


def _mapping(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError("expected object")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError("expected array")
    return cast(list[object], value)


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("expected string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("expected integer")
    return value


class _TextOnlyHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = unescape(data).strip()
        if value:
            self.parts.append(value)


def _normalized(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", _text(value)).split()).casefold()


def _require_file(
    path: Path, *, byte_count: int, checksum: str, algorithm: str
) -> bytes:
    payload = path.read_bytes()
    if len(payload) != byte_count:
        raise ValueError(f"{path.name} byte count drift")
    actual = {
        "sha256": _sha256,
        "md5": _md5,
        "git_blob_sha1": _git_blob_sha1,
    }[algorithm](payload)
    if actual != checksum:
        raise ValueError(f"{path.name} checksum drift")
    return payload


def _source_binding(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "bytes": len(payload),
        "sha256": _sha256(payload),
    }


def _document_parser() -> DocumentParser:
    return DocumentParser(ocr_engine=NotConfiguredOcrEngine(), pdf_renderer=None)


def _contract_actual(
    parsed: ParsedDocument,
    *,
    namespace: str,
) -> tuple[dict[str, object], int]:
    parse_version_id = uuid5(NAMESPACE_URL, f"{namespace}/parse")
    blocks = tuple(
        ContractSourceBlock(
            id=uuid5(NAMESPACE_URL, f"{namespace}/block/{block.block_index}"),
            parse_version_id=parse_version_id,
            page_no=block.page_no,
            block_index=block.block_index,
            text=block.text,
            bbox=cast(dict[str, object] | None, block.bbox),
            confidence=block.confidence,
        )
        for page in parsed.pages
        for block in page.blocks
    )
    return extract_contract_candidate(blocks).facts.model_dump(mode="json"), len(blocks)


def _chinese_date(value: str) -> str:
    match = re.fullmatch(r"(\d{4})年(\d{2})月(\d{2})日", value)
    if match is None:
        raise ValueError("invalid Chinese date")
    return date(*(int(part) for part in match.groups())).isoformat()


def _haikou_expected(payload: bytes) -> dict[str, str]:
    parser = _TextOnlyHtmlParser()
    parser.feed(payload.decode("utf-8", errors="strict"))
    page_text = "\n".join(parser.parts)
    matches = {
        key: pattern.search(page_text) for key, pattern in _HAIKOU_PATTERNS.items()
    }
    if any(match is None for match in matches.values()):
        raise ValueError("Haikou contract page field coverage drift")
    present = cast(dict[str, re.Match[str]], matches)
    term = present["term"]
    return {
        "contract_no": " ".join(
            term for term in present["contract_no"].group(1).split()
        ),
        "name": " ".join(term for term in present["name"].group(1).split()),
        "party_a_name": " ".join(
            term for term in present["party_a_name"].group(1).split()
        ),
        "party_b_name": " ".join(
            term for term in present["party_b_name"].group(1).split()
        ),
        "amount": present["amount"].group(1).replace(",", ""),
        "currency": "CNY",
        "signed_date": _chinese_date(present["signed_date"].group(1)),
        "effective_date": _chinese_date(term.group(1)),
        "expiry_date": _chinese_date(term.group(2)),
    }


def _cuad_artifact() -> dict[str, object]:
    archive_payload = _require_file(
        CUAD_ZIP,
        byte_count=18_309_308,
        checksum=_CUAD_DATA_GIT_BLOB,
        algorithm="git_blob_sha1",
    )
    with zipfile.ZipFile(CUAD_ZIP) as archive:
        dataset = _mapping(json.loads(archive.read("CUADv1.json")))
    documents = [_mapping(item) for item in _list(dataset["data"])]
    if len(documents) != 510:
        raise ValueError("CUAD document count drift")
    by_title = {_text(document["title"]): document for document in documents}

    qa_count = 0
    answerable_count = 0
    for document in documents:
        for paragraph in [_mapping(item) for item in _list(document["paragraphs"])]:
            for qa in [_mapping(item) for item in _list(paragraph["qas"])]:
                qa_count += 1
                answerable_count += bool(_list(qa["answers"]))
    if (qa_count, answerable_count) != (20_910, 6_702):
        raise ValueError("CUAD annotation count drift")

    parser = _document_parser()
    case_results: list[dict[str, object]] = []
    page_counts: list[int] = []
    parser_outcomes: Counter[str] = Counter()
    total_expected = total_matched = total_actual_non_null = 0
    for case in _CUAD_CASES:
        pdf_path = CUAD_PDF_ROOT / f"{case.case_id}.pdf"
        pdf_payload = _require_file(
            pdf_path,
            byte_count=case.byte_count,
            checksum=case.sha256,
            algorithm="sha256",
        )
        page_count = len(PdfReader(io.BytesIO(pdf_payload), strict=True).pages)
        page_counts.append(page_count)
        actual: dict[str, object]
        try:
            parsed = parser.parse(pdf_payload, mime_type="application/pdf")
        except DocumentParseError as error:
            parser_outcomes[error.code] += 1
            parser_status = "failed"
            parser_failure_code: str | None = error.code
            source_type: str | None = None
            block_count = 0
            actual = {field_code: None for field_code in CONTRACT_CORE_FIELD_CODES}
        else:
            parser_outcomes["PASSED"] += 1
            parser_status = "passed"
            parser_failure_code = None
            source_type = parsed.source_type
            actual, block_count = _contract_actual(
                parsed,
                namespace=f"finaudit-public/{case.case_id}",
            )
        actual_non_null = sum(value is not None for value in actual.values())

        expected: dict[str, set[str]] = {}
        selected_document = by_title.get(case.title)
        if selected_document is None:
            raise ValueError(f"CUAD title missing for {case.case_id}")
        for paragraph in [
            _mapping(item) for item in _list(selected_document["paragraphs"])
        ]:
            for qa in [_mapping(item) for item in _list(paragraph["qas"])]:
                match = _LABEL_PATTERN.search(_text(qa["question"]))
                if match is None or match.group(1) not in _CUAD_DIRECT_FIELDS:
                    continue
                answers = [_mapping(item) for item in _list(qa["answers"])]
                if not answers:
                    continue
                field_code = _CUAD_DIRECT_FIELDS[match.group(1)]
                expected[field_code] = {
                    _normalized(answer["text"])
                    for answer in answers
                    if _normalized(answer["text"])
                }
        matched = sum(
            actual[field_code] is not None
            and _normalized(str(actual[field_code])) in expected_values
            for field_code, expected_values in expected.items()
        )
        total_expected += len(expected)
        total_matched += matched
        total_actual_non_null += actual_non_null
        case_results.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "source_path_sha256": _sha256(case.source_path.encode("utf-8")),
                "source_pdf_sha256": case.sha256,
                "page_count": page_count,
                "product_parser_status": parser_status,
                "product_parser_failure_code": parser_failure_code,
                "source_type": source_type,
                "block_count": block_count,
                "expected_direct_field_count": len(expected),
                "expected_values_sha256": _sha256(
                    _canonical_bytes(
                        {
                            field_code: sorted(values)
                            for field_code, values in expected.items()
                        }
                    )
                ),
                "actual_non_null_frozen_field_count": actual_non_null,
                "matched_direct_field_count": matched,
            }
        )
    if (
        len(page_counts) != 12
        or sum(page_counts) != 490
        or min(page_counts) != 8
        or max(page_counts) != 82
    ):
        raise ValueError("CUAD selected PDF page profile drift")
    if total_actual_non_null != 0 or total_matched != 0:
        raise ValueError("current deterministic contract extraction result drift")

    return {
        "source": {
            "dataset_id": "cuad-v1",
            "publisher": "The Atticus Project",
            "primary_url": "https://www.atticusprojectai.org/cuad/",
            "source_revision": _CUAD_REVISION,
            "license": "CC-BY-4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "package_bytes": len(archive_payload),
            "package_git_blob_sha1": _CUAD_DATA_GIT_BLOB,
            "document_count": len(documents),
            "qa_annotation_count": qa_count,
            "answerable_annotation_count": answerable_count,
        },
        "selection": {
            "method": "one_high-core-coverage_document_per_12_contract_categories",
            "case_count": len(case_results),
            "category_count": len({case.category for case in _CUAD_CASES}),
            "case_ids_sha256": _sha256(
                "\n".join(case.case_id for case in _CUAD_CASES).encode("ascii")
            ),
        },
        "current_profile_runtime": {
            "parser": "DocumentParser+NotConfiguredOcrEngine",
            "parser_pass_count": parser_outcomes["PASSED"],
            "parser_fail_count": len(case_results) - parser_outcomes["PASSED"],
            "parser_outcome_counts": dict(sorted(parser_outcomes.items())),
            "total_page_count": sum(page_counts),
            "min_page_count": min(page_counts),
            "max_page_count": max(page_counts),
            "frozen_field_count": len(CONTRACT_CORE_FIELD_CODES),
            "directly_annotated_field_codes": sorted(_CUAD_DIRECT_FIELDS.values()),
            "direct_schema_coverage_count": len(_CUAD_DIRECT_FIELDS),
            "expected_direct_field_count": total_expected,
            "actual_non_null_frozen_field_count": total_actual_non_null,
            "matched_direct_field_count": total_matched,
            "direct_field_accuracy": "0.000000",
            "threshold": "0.850000",
            "threshold_status": "FAILED",
            "formal_13_field_gate_status": "NOT_COMPUTABLE_INSUFFICIENT_SOURCE_FIELD_COVERAGE",
        },
        "cases": case_results,
    }


def _haikou_artifact() -> dict[str, object]:
    parser = _document_parser()
    parser_outcomes: Counter[str] = Counter()
    page_counts: list[int] = []
    case_results: list[dict[str, object]] = []
    total_expected = total_matched = total_actual_non_null = 0
    direct_fields: set[str] = set()

    for case in _HAIKOU_CASES:
        html_payload = _require_file(
            HAIKOU_ROOT / f"{case.case_id}.html",
            byte_count=case.html_bytes,
            checksum=case.html_sha256,
            algorithm="sha256",
        )
        pdf_payload = _require_file(
            HAIKOU_ROOT / f"{case.case_id}.pdf",
            byte_count=case.pdf_bytes,
            checksum=case.pdf_sha256,
            algorithm="sha256",
        )
        expected = _haikou_expected(html_payload)
        if len(expected) != 9:
            raise ValueError("Haikou expected contract field count drift")
        direct_fields.update(expected)
        page_count = len(PdfReader(io.BytesIO(pdf_payload), strict=True).pages)
        page_counts.append(page_count)

        actual: dict[str, object]
        try:
            parsed = parser.parse(pdf_payload, mime_type="application/pdf")
        except DocumentParseError as error:
            parser_outcomes[error.code] += 1
            parser_status = "failed"
            parser_failure_code: str | None = error.code
            source_type: str | None = None
            block_count = 0
            actual = {field_code: None for field_code in CONTRACT_CORE_FIELD_CODES}
        else:
            parser_outcomes["PASSED"] += 1
            parser_status = "passed"
            parser_failure_code = None
            source_type = parsed.source_type
            actual, block_count = _contract_actual(
                parsed,
                namespace=f"haikou-public/{case.case_id}",
            )

        matched_fields = [
            field_code
            for field_code, expected_value in expected.items()
            if actual[field_code] is not None
            and _normalized(str(actual[field_code])) == _normalized(expected_value)
        ]
        actual_non_null = sum(value is not None for value in actual.values())
        total_expected += len(expected)
        total_matched += len(matched_fields)
        total_actual_non_null += actual_non_null
        case_results.append(
            {
                "case_id": case.case_id,
                "page_url": f"https://ggzy.haikou.gov.cn/gonggao/{case.case_id}",
                "html_sha256": case.html_sha256,
                "pdf_sha256": case.pdf_sha256,
                "pdf_url_sha256": case.pdf_url_sha256,
                "page_count": page_count,
                "expected_direct_field_count": len(expected),
                "expected_values_sha256": _sha256(_canonical_bytes(expected)),
                "product_parser_status": parser_status,
                "product_parser_failure_code": parser_failure_code,
                "source_type": source_type,
                "block_count": block_count,
                "actual_non_null_frozen_field_count": actual_non_null,
                "matched_direct_field_count": len(matched_fields),
                "matched_field_codes": sorted(matched_fields),
            }
        )

    if len(page_counts) != 10 or min(page_counts) < 1:
        raise ValueError("Haikou selected PDF page profile drift")
    if parser_outcomes != {"PDF_OCR_RENDERER_NOT_CONFIGURED": 10}:
        raise ValueError("current scanned Chinese contract OCR boundary drift")
    if total_expected != 90 or total_matched != 0 or total_actual_non_null != 0:
        raise ValueError("current Chinese contract extraction result drift")

    return {
        "source": {
            "dataset_id": "haikou-government-procurement-contracts-v1",
            "publisher": "海口市公共资源交易中心",
            "primary_url": "https://ggzy.haikou.gov.cn/",
            "document_language": "Chinese",
            "public_disclosure": True,
            "explicit_open_data_license": False,
            "raw_redistribution_authorized": False,
            "local_evaluation_only": True,
            "case_count": len(case_results),
            "html_total_bytes": sum(case.html_bytes for case in _HAIKOU_CASES),
            "pdf_total_bytes": sum(case.pdf_bytes for case in _HAIKOU_CASES),
        },
        "selection": {
            "method": "ten_official_structured_announcements_with_original_pdf_attachments",
            "case_count": len(case_results),
            "case_ids_sha256": _sha256(
                "\n".join(case.case_id for case in _HAIKOU_CASES).encode("ascii")
            ),
        },
        "annotation_quality": {
            "official_structured_page_count": len(case_results),
            "expected_direct_field_count": total_expected,
            "frozen_field_count": len(CONTRACT_CORE_FIELD_CODES),
            "directly_annotated_field_codes": sorted(direct_fields),
            "direct_schema_coverage_count": len(direct_fields),
            "gold_values_persisted": False,
        },
        "current_profile_runtime": {
            "parser": "DocumentParser+NotConfiguredOcrEngine",
            "parser_pass_count": parser_outcomes["PASSED"],
            "parser_fail_count": len(case_results) - parser_outcomes["PASSED"],
            "parser_outcome_counts": dict(sorted(parser_outcomes.items())),
            "total_page_count": sum(page_counts),
            "min_page_count": min(page_counts),
            "max_page_count": max(page_counts),
            "expected_direct_field_count": total_expected,
            "actual_non_null_frozen_field_count": total_actual_non_null,
            "matched_direct_field_count": total_matched,
            "direct_field_accuracy": "0.000000",
            "threshold": "0.850000",
            "threshold_status": "FAILED",
            "formal_13_field_gate_status": "NOT_COMPUTABLE_INSUFFICIENT_SOURCE_FIELD_COVERAGE",
        },
        "cases": case_results,
    }


def _zip_json_records(path: Path) -> dict[str, dict[str, object]]:
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if not name.endswith("/") and name.lower().endswith(".txt")
        )
        records: dict[str, dict[str, object]] = {}
        for name in names:
            stem = Path(name).stem
            if stem in records:
                raise ValueError("duplicate annotation stem")
            records[stem] = _mapping(json.loads(archive.read(name)))
        return records


def _zip_images(path: Path) -> tuple[zipfile.ZipFile, dict[str, str], Counter[str]]:
    archive = zipfile.ZipFile(path)
    image_names: dict[str, str] = {}
    extensions: Counter[str] = Counter()
    for name in archive.namelist():
        extension = Path(name).suffix.lower()
        if name.endswith("/") or extension not in {".jpg", ".jpeg", ".png"}:
            continue
        stem = Path(name).stem
        if stem in image_names:
            archive.close()
            raise ValueError("duplicate image stem")
        image_names[stem] = name
        extensions[extension] += 1
    return archive, image_names, extensions


def _image_mime(name: str) -> str:
    return "image/png" if Path(name).suffix.lower() == ".png" else "image/jpeg"


def _ocr_disabled_probe(
    archive: zipfile.ZipFile,
    image_names: dict[str, str],
    stems: list[str],
) -> Counter[str]:
    parser = _document_parser()
    outcomes: Counter[str] = Counter()
    for stem in stems:
        name = image_names[stem]
        try:
            parser.parse(archive.read(name), mime_type=_image_mime(name))
        except DocumentParseError as error:
            outcomes[error.code] += 1
        else:
            outcomes["UNEXPECTED_SUCCESS"] += 1
    return outcomes


def _zenodo_artifact() -> dict[str, object]:
    annotations_payload = _require_file(
        ZENODO_ANNOTATIONS_ZIP,
        byte_count=290_214,
        checksum=_ZENODO_ANNOTATIONS_MD5,
        algorithm="md5",
    )
    images_payload = _require_file(
        ZENODO_IMAGES_ZIP,
        byte_count=410_222_137,
        checksum=_ZENODO_IMAGES_MD5,
        algorithm="md5",
    )
    records = _zip_json_records(ZENODO_ANNOTATIONS_ZIP)
    if len(records) != 813 or any(
        set(record) != _INVOICE_ANNOTATION_KEYS for record in records.values()
    ):
        raise ValueError("Zenodo invoice annotation shape drift")

    field_nonblank = {
        key: sum(bool(_normalized(record[key])) for record in records.values())
        for key in sorted(_INVOICE_ANNOTATION_KEYS)
    }
    source_identities = Counter(
        (_normalized(record["nif_seller"]), _normalized(record["invoice_number"]))
        for record in records.values()
        if _normalized(record["nif_seller"]) and _normalized(record["invoice_number"])
    )
    duplicate_groups = [count for count in source_identities.values() if count > 1]
    if (len(duplicate_groups), sum(duplicate_groups), max(duplicate_groups)) != (
        55,
        117,
        4,
    ):
        raise ValueError("Zenodo duplicate identity profile drift")

    archive, image_names, extensions = _zip_images(ZENODO_IMAGES_ZIP)
    try:
        matched_stems = sorted(set(records) & set(image_names))
        if len(image_names) != 813 or len(matched_stems) != 813:
            raise ValueError("Zenodo invoice image/annotation binding drift")
        eligible = [
            stem
            for stem in matched_stems
            if all(
                _normalized(records[stem][source]) for source in _INVOICE_DIRECT_FIELDS
            )
        ]
        sample = sorted(eligible, key=lambda stem: _sha256(stem.encode("utf-8")))[:50]
        if len(sample) != 50:
            raise ValueError("Zenodo eligible invoice sample is too small")
        outcomes = _ocr_disabled_probe(archive, image_names, sample)
    finally:
        archive.close()
    if outcomes != {"OCR_NOT_CONFIGURED": 50}:
        raise ValueError("current invoice image OCR boundary drift")

    return {
        "source": {
            "dataset_id": "zenodo-6371710",
            "publisher": "NOVA Information Management School authors",
            "primary_url": "https://zenodo.org/records/6371710",
            "license": "CC-BY-4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "document_language": "Portuguese",
            "document_count": len(records),
            "annotation_package_bytes": len(annotations_payload),
            "annotation_package_md5": _ZENODO_ANNOTATIONS_MD5,
            "image_package_bytes": len(images_payload),
            "image_package_md5": _ZENODO_IMAGES_MD5,
            "image_extension_counts": dict(sorted(extensions.items())),
        },
        "annotation_quality": {
            "invalid_json_count": 0,
            "field_nonblank_counts": field_nonblank,
            "direct_field_mapping": _INVOICE_DIRECT_FIELDS,
            "frozen_field_count": 13,
            "direct_schema_coverage_count": len(_INVOICE_DIRECT_FIELDS),
            "image_annotation_binding_count": len(records),
        },
        "duplicate_ground_truth": {
            "source_identity_fields": ["nif_seller", "invoice_number"],
            "source_complete_distinct_identity_count": len(source_identities),
            "duplicate_identity_group_count": len(duplicate_groups),
            "duplicate_identity_document_count": sum(duplicate_groups),
            "max_duplicate_group_size": max(duplicate_groups),
            "product_identity_fields": [
                "invoice_code",
                "invoice_number",
                "seller_tax_no",
            ],
            "product_complete_identity_count": 0,
            "metric_status": "NOT_COMPUTABLE_SOURCE_LACKS_INVOICE_CODE",
        },
        "current_profile_runtime": {
            "sample_count": len(sample),
            "sample_ids_sha256": _sha256("\n".join(sample).encode("utf-8")),
            "expected_nonblank_direct_field_count": len(sample)
            * len(_INVOICE_DIRECT_FIELDS),
            "valid_output_count": 0,
            "matched_direct_field_count": 0,
            "failure_code_counts": dict(outcomes),
            "direct_field_accuracy": "0.000000",
            "threshold": "0.950000",
            "threshold_status": "FAILED",
            "formal_13_field_gate_status": "NOT_COMPUTABLE_INSUFFICIENT_SOURCE_FIELD_COVERAGE",
        },
    }


def _xfund_artifact() -> dict[str, object]:
    payload = _require_file(
        XFUND_JSON,
        byte_count=1_711_142,
        checksum=_XFUND_JSON_SHA256,
        algorithm="sha256",
    )
    dataset = _mapping(json.loads(payload))
    documents = [_mapping(item) for item in _list(dataset["documents"])]
    if len(documents) != 50:
        raise ValueError("XFUND zh validation document count drift")
    labels = Counter(
        _text(entity["label"])
        for document in documents
        for entity in [_mapping(item) for item in _list(document["document"])]
    )
    if labels != {"answer": 1732, "question": 1253, "other": 586, "header": 58}:
        raise ValueError("XFUND zh validation label profile drift")

    image_payload = _require_file(
        XFUND_IMAGES_ZIP,
        byte_count=69_217_820,
        checksum=_XFUND_IMAGES_SHA256,
        algorithm="sha256",
    )
    archive, image_names, extensions = _zip_images(XFUND_IMAGES_ZIP)
    try:
        expected_names = [
            _text(_mapping(document["img"])["fname"]) for document in documents
        ]
        expected_stems = [Path(name).stem for name in expected_names]
        if len(set(expected_stems)) != 50 or not set(expected_stems) <= set(
            image_names
        ):
            raise ValueError("XFUND zh validation image binding drift")
        outcomes = _ocr_disabled_probe(archive, image_names, sorted(expected_stems))
    finally:
        archive.close()
    if outcomes != {"OCR_NOT_CONFIGURED": 50}:
        raise ValueError("current XFUND image OCR boundary drift")

    widths = [_integer(_mapping(document["img"])["width"]) for document in documents]
    heights = [_integer(_mapping(document["img"])["height"]) for document in documents]
    return {
        "source": {
            "dataset_id": "xfund-v1-zh-validation",
            "publisher": "Microsoft Research / doc-analysis",
            "primary_url": "https://github.com/doc-analysis/XFUND/releases/tag/v1.0",
            "license": "CC-BY-NC-SA-4.0",
            "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
            "document_language": "Chinese",
            "document_count": len(documents),
            "annotation_bytes": len(payload),
            "annotation_sha256": _XFUND_JSON_SHA256,
            "image_package_bytes": len(image_payload),
            "image_package_sha256": _sha256(image_payload),
            "image_extension_counts": dict(sorted(extensions.items())),
        },
        "annotation_quality": {
            "entity_count": sum(labels.values()),
            "label_counts": dict(sorted(labels.items())),
            "documents_with_key_value_links": 50,
            "image_width_range": [min(widths), max(widths)],
            "image_height_range": [min(heights), max(heights)],
        },
        "current_profile_runtime": {
            "sample_count": 50,
            "valid_output_count": 0,
            "failure_code_counts": dict(outcomes),
            "quality_status": "FAILED_OCR_NOT_CONFIGURED",
        },
    }


def _raw_value_candidates() -> set[str]:
    records = _zip_json_records(ZENODO_ANNOTATIONS_ZIP)
    values = {
        _normalized(value)
        for record in records.values()
        for value in record.values()
        if type(value) is str and len(value.strip()) >= 6
    }
    for case in _HAIKOU_CASES:
        expected = _haikou_expected((HAIKOU_ROOT / f"{case.case_id}.html").read_bytes())
        values.update(
            _normalized(value) for value in expected.values() if len(value.strip()) >= 6
        )
    with zipfile.ZipFile(CUAD_ZIP) as archive:
        cuad = _mapping(json.loads(archive.read("CUADv1.json")))
    selected_titles = {case.title for case in _CUAD_CASES}
    for document in [_mapping(item) for item in _list(cuad["data"])]:
        if _text(document["title"]) not in selected_titles:
            continue
        for paragraph in [_mapping(item) for item in _list(document["paragraphs"])]:
            for qa in [_mapping(item) for item in _list(paragraph["qas"])]:
                for answer in [_mapping(item) for item in _list(qa["answers"])]:
                    answer_text = _text(answer["text"])
                    if len(answer_text.strip()) >= 6:
                        values.add(_normalized(answer_text))
    xfund = _mapping(json.loads(XFUND_JSON.read_bytes()))
    for document in [_mapping(item) for item in _list(xfund["documents"])]:
        for entity in [_mapping(item) for item in _list(document["document"])]:
            entity_text = _text(entity["text"])
            if len(entity_text.strip()) >= 6:
                values.add(_normalized(entity_text))
    return values


def _artifact_string_values(value: object) -> set[str]:
    if type(value) is str:
        return {_normalized(value)}
    if type(value) is list:
        return {item for child in value for item in _artifact_string_values(child)}
    if type(value) is dict:
        return {
            item for child in value.values() for item in _artifact_string_values(child)
        }
    return set()


def build_artifact() -> dict[str, object]:
    contract = _cuad_artifact()
    chinese_contract = _haikou_artifact()
    invoice = _zenodo_artifact()
    xfund = _xfund_artifact()
    artifact: dict[str, object] = {
        "schema_version": "public-business-benchmark-runtime-v1",
        "classification": "public_open_data_with_untracked_raw_documents",
        "environment_scope": ["local", "test"],
        "source_binding": [
            _source_binding(
                PROJECT_ROOT / "scripts" / "verify_public_business_benchmark.py"
            ),
            _source_binding(BACKEND_ROOT / "app" / "services" / "document_parser.py"),
            _source_binding(
                BACKEND_ROOT / "app" / "services" / "contract_extractor.py"
            ),
        ],
        "selection_authority": {
            "approval_ref": None,
            "approval_ref_provided": False,
            "owner_instruction_sha256": _sha256(_OWNER_INSTRUCTION.encode("utf-8")),
            "owner_instruction_scope": "agent_selects_public_sources_for_local_technical_measurement",
            "human_review_claimed": False,
        },
        "source_qualification_status": "PASSED",
        "contract": contract,
        "chinese_government_contracts": chinese_contract,
        "contract_source_coverage": {
            "combined_direct_field_codes": _mapping(
                chinese_contract["annotation_quality"]
            )["directly_annotated_field_codes"],
            "combined_direct_schema_coverage_count": 9,
            "frozen_field_count": 13,
            "formal_gate_status": "NOT_COMPUTABLE_INSUFFICIENT_SOURCE_FIELD_COVERAGE",
        },
        "invoice": invoice,
        "chinese_complex_forms": xfund,
        "risk_rule_ground_truth": {
            "builtin_rule_count": 15,
            "independent_matching_label_count": 0,
            "cuad_legal_clause_labels_are_not_builtin_financial_rule_labels": True,
            "invoice_source_has_fields_but_no_independent_rule_dispositions": True,
            "metric_status": "NOT_COMPUTABLE_NO_INDEPENDENT_MATCHING_GROUND_TRUTH",
        },
        "complex_multi_format": {
            "document_formats_present": ["PDF", "JPEG"],
            "annotation_formats_present": ["JSON"],
            "contract_pdf_parser_status": "PARTIAL",
            "digital_english_contract_pdf_status": "PASSED",
            "scanned_chinese_contract_pdf_status": "FAILED_OCR_NOT_CONFIGURED",
            "contract_pdf_page_range": [
                min(
                    _integer(
                        _mapping(contract["current_profile_runtime"])["min_page_count"]
                    ),
                    _integer(
                        _mapping(chinese_contract["current_profile_runtime"])[
                            "min_page_count"
                        ]
                    ),
                ),
                max(
                    _integer(
                        _mapping(contract["current_profile_runtime"])["max_page_count"]
                    ),
                    _integer(
                        _mapping(chinese_contract["current_profile_runtime"])[
                            "max_page_count"
                        ]
                    ),
                ),
            ],
            "invoice_image_status": "FAILED_OCR_NOT_CONFIGURED",
            "chinese_form_image_status": "FAILED_OCR_NOT_CONFIGURED",
            "native_docx_public_case_count": 0,
            "quality_status": "PARTIAL_PDF_PASS_IMAGE_OCR_DISABLED_DOCX_NOT_COVERED",
        },
        "quality_gate_summary": {
            "contract_85": "FAILED_CURRENT_PROFILE_AND_INSUFFICIENT_13_FIELD_COVERAGE",
            "invoice_95": "FAILED_CURRENT_PROFILE_AND_INSUFFICIENT_13_FIELD_COVERAGE",
            "duplicate_invoice": "NOT_COMPUTABLE_SOURCE_LACKS_PRODUCT_IDENTITY_TRIPLE",
            "risk_rules": "NOT_COMPUTABLE_NO_MATCHING_INDEPENDENT_LABELS",
            "complex_multi_format": "PARTIAL",
            "overall_status": "MEASURED_FAILED",
        },
        "privacy_and_storage": {
            "raw_data_path": "data/public-benchmark/",
            "raw_data_git_ignored": True,
            "raw_documents_tracked": False,
            "raw_annotation_values_persisted_in_evidence": False,
            "business_identifiers_persisted_in_evidence": False,
            "tracked_output_contains_only_counts_hashes_and_status": True,
        },
        "acceptance_boundary": {
            "is_public_cross_domain_technical_measurement": True,
            "is_customer_business_representative_dataset": False,
            "is_human_uat": False,
            "is_formal_ac_acceptance": False,
            "may_mark_ac_accepted": False,
            "may_claim_contract_85_passed": False,
            "may_claim_invoice_95_passed": False,
        },
    }
    candidates = _raw_value_candidates()
    persisted_matches = candidates & _artifact_string_values(artifact)
    unexpected_matches = persisted_matches - _SAFE_METADATA_COINCIDENCES
    if unexpected_matches:
        raise ValueError("raw business value persisted in tracked evidence")
    privacy = _mapping(artifact["privacy_and_storage"])
    privacy["raw_value_cross_check_candidate_count"] = len(candidates)
    privacy["raw_value_cross_check_generic_metadata_coincidence_count"] = len(
        persisted_matches & _SAFE_METADATA_COINCIDENCES
    )
    privacy["raw_value_cross_check_persisted_match_count"] = 0
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = _canonical_bytes(build_artifact())
    if args.check:
        if not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_bytes() != payload:
            print("PUBLIC_BUSINESS_BENCHMARK_RUNTIME=DRIFT")
            return 1
        print("PUBLIC_BUSINESS_BENCHMARK_RUNTIME=MEASURED_FAILED_EVIDENCE_PASS")
        return 0
    OUTPUT_PATH.write_bytes(payload)
    print(
        "PUBLIC_BUSINESS_BENCHMARK_RUNTIME=MEASURED_FAILED "
        f"sha256={_sha256(payload)} raw_values_persisted=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
