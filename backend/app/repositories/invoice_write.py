"""发票提取、修正、确认与重复处置的固定锁序和持久化访问。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.auth import Organization
from app.models.corrections import UserCorrection
from app.models.document_processing import DocumentBlock, DocumentPage, DocumentParseVersion
from app.models.documents import FilePrimaryBusinessObject, FileRecord
from app.models.financial import Invoice, InvoiceItem
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository
from app.schemas.invoices import InvoiceEvidenceData
from app.services.invoice_extractor import InvoiceSourceBlock


@dataclass(frozen=True, slots=True)
class InvoiceExtractionSource:
    file: FileRecord
    parse_version: DocumentParseVersion
    blocks: tuple[InvoiceSourceBlock, ...]
    existing_invoice_id: UUID | None


class InvoiceWriteRepository:
    """组织域锁 → 幂等锁 → 文件/发票 → 明细/证据的固定顺序。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._idempotency = UserWriteRepository(session)

    def database_now(self) -> datetime:
        return cast(datetime, self._session.scalar(select(func.clock_timestamp())))

    def acquire_domain_lock(self, organization_id: UUID) -> None:
        identity = f"finaudit:invoice-write:{organization_id}"
        self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(identity, 0)))
        ).one()

    def acquire_api_locks(
        self,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> None:
        self.acquire_domain_lock(organization_id)
        self._idempotency.acquire_idempotency_lock(
            organization_id,
            actor_id,
            idempotency_key,
        )

    def lock_active_organization(self, organization_id: UUID) -> Organization | None:
        return self._idempotency.lock_active_organization(organization_id)

    def claim_idempotency(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
        request_method: str,
        request_path: str,
        request_hash: str,
        now: datetime,
        expires_at: datetime,
    ) -> IdempotencyClaim:
        return self._idempotency.claim_idempotency(
            organization_id=organization_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request_method=request_method,
            request_path=request_path,
            request_hash=request_hash,
            now=now,
            expires_at=expires_at,
        )

    def complete_idempotency(
        self,
        claim: IdempotencyClaim,
        *,
        response_body: dict[str, object],
        resource_id: UUID,
    ) -> None:
        self._idempotency.complete_idempotency(
            claim,
            response_status=200,
            response_body=response_body,
            resource_id=resource_id,
            resource_type="invoice",
        )

    def load_extraction_source(
        self,
        organization_id: UUID,
        file_id: UUID,
        parse_version_id: UUID,
    ) -> InvoiceExtractionSource | None:
        file = self._session.execute(
            select(FileRecord)
            .where(
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
            .with_for_update(of=FileRecord)
        ).scalar_one_or_none()
        if (
            file is None
            or file.status != "stored"
            or file.security_scan_status != "clean"
            or file.intended_business_type != "invoice"
            or not file.auto_process_requested
        ):
            return None
        binding = self._session.execute(
            select(FilePrimaryBusinessObject)
            .where(FilePrimaryBusinessObject.file_id == file.id)
            .with_for_update(of=FilePrimaryBusinessObject)
        ).scalar_one_or_none()
        if binding is not None and (
            binding.business_type != "invoice" or binding.invoice_id is None
        ):
            return None
        parse_version = self._session.execute(
            select(DocumentParseVersion).where(
                DocumentParseVersion.id == parse_version_id,
                DocumentParseVersion.file_id == file.id,
                DocumentParseVersion.status.in_(("succeeded", "manual_review_required", "active")),
                DocumentParseVersion.archived_at.is_(None),
            )
        ).scalar_one_or_none()
        if parse_version is None:
            return None
        rows = self._session.execute(
            select(DocumentBlock, DocumentPage.page_no)
            .join(DocumentPage, DocumentBlock.page_id == DocumentPage.id)
            .where(
                DocumentBlock.parse_version_id == parse_version.id,
                DocumentBlock.is_effective_content.is_(True),
                DocumentBlock.text_content.is_not(None),
            )
            .order_by(DocumentPage.page_no, DocumentBlock.block_index, DocumentBlock.id)
        ).all()
        blocks = tuple(
            InvoiceSourceBlock(
                id=block.id,
                parse_version_id=block.parse_version_id,
                page_no=page_no,
                block_index=block.block_index,
                text=cast(str, block.text_content),
                bbox=None if block.bbox_json is None else dict(block.bbox_json),
                confidence=block.confidence,
            )
            for block, page_no in rows
        )
        if not blocks:
            return None
        return InvoiceExtractionSource(
            file=file,
            parse_version=parse_version,
            blocks=blocks,
            existing_invoice_id=None if binding is None else binding.invoice_id,
        )

    def lock_invoice(self, organization_id: UUID, invoice_id: UUID) -> Invoice | None:
        return self._session.execute(
            select(Invoice)
            .where(
                Invoice.id == invoice_id,
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
            .with_for_update(of=Invoice)
        ).scalar_one_or_none()

    def lock_items(self, invoice_id: UUID) -> tuple[InvoiceItem, ...]:
        return tuple(
            self._session.scalars(
                select(InvoiceItem)
                .where(InvoiceItem.invoice_id == invoice_id)
                .order_by(InvoiceItem.line_no, InvoiceItem.id)
                .with_for_update(of=InvoiceItem)
            ).all()
        )

    def lock_binding(self, invoice_id: UUID) -> FilePrimaryBusinessObject | None:
        return self._session.execute(
            select(FilePrimaryBusinessObject)
            .where(
                FilePrimaryBusinessObject.invoice_id == invoice_id,
                FilePrimaryBusinessObject.business_type == "invoice",
            )
            .with_for_update(of=FilePrimaryBusinessObject)
        ).scalar_one_or_none()

    def validate_evidence(
        self,
        organization_id: UUID,
        file_id: UUID,
        evidence: tuple[InvoiceEvidenceData, ...],
        *,
        lock: bool = True,
    ) -> bool:
        if not evidence:
            return True
        block_ids = tuple(sorted({item.block_id for item in evidence}, key=lambda item: item.int))
        statement = (
            select(DocumentBlock, DocumentPage.page_no, DocumentParseVersion.file_id)
            .join(DocumentPage, DocumentBlock.page_id == DocumentPage.id)
            .join(
                DocumentParseVersion,
                DocumentBlock.parse_version_id == DocumentParseVersion.id,
            )
            .join(FileRecord, DocumentParseVersion.file_id == FileRecord.id)
            .where(
                DocumentBlock.id.in_(block_ids),
                DocumentBlock.is_effective_content.is_(True),
                DocumentParseVersion.archived_at.is_(None),
                FileRecord.id == file_id,
                FileRecord.organization_id == organization_id,
            )
        )
        if lock:
            statement = statement.with_for_update(of=DocumentBlock)
        rows = self._session.execute(statement).all()
        observed = {
            block.id: (block, page_no, observed_file_id)
            for block, page_no, observed_file_id in rows
        }
        if set(observed) != set(block_ids):
            return False
        for item in evidence:
            block, page_no, observed_file_id = observed[item.block_id]
            observed_confidence = block.confidence
            expected_confidence = None if item.confidence is None else Decimal(item.confidence)
            if (
                observed_file_id != file_id
                or block.parse_version_id != item.parse_version_id
                or page_no != item.page_no
                or block.text_content != item.quote_text
                or block.bbox_json != item.bbox
                or observed_confidence != expected_confidence
            ):
                return False
        return True

    def exact_duplicate_ids(
        self,
        invoice: Invoice,
        *,
        lock: bool,
    ) -> tuple[UUID, ...]:
        if not invoice.invoice_code or not invoice.invoice_number or not invoice.seller_tax_no:
            return ()
        statement = (
            select(Invoice.id)
            .where(
                Invoice.organization_id == invoice.organization_id,
                Invoice.id != invoice.id,
                Invoice.invoice_code == invoice.invoice_code,
                Invoice.invoice_number == invoice.invoice_number,
                Invoice.seller_tax_no == invoice.seller_tax_no,
                Invoice.deleted_at.is_(None),
                Invoice.status != "voided",
            )
            .order_by(Invoice.id)
        )
        if lock:
            statement = statement.with_for_update(of=Invoice)
        return tuple(self._session.scalars(statement).all())

    def lock_exact_duplicate(
        self,
        invoice: Invoice,
        candidate_id: UUID,
    ) -> Invoice | None:
        if not invoice.invoice_code or not invoice.invoice_number or not invoice.seller_tax_no:
            return None
        return self._session.execute(
            select(Invoice)
            .where(
                Invoice.id == candidate_id,
                Invoice.id != invoice.id,
                Invoice.organization_id == invoice.organization_id,
                Invoice.invoice_code == invoice.invoice_code,
                Invoice.invoice_number == invoice.invoice_number,
                Invoice.seller_tax_no == invoice.seller_tax_no,
                Invoice.deleted_at.is_(None),
                Invoice.status != "voided",
            )
            .with_for_update(of=Invoice)
        ).scalar_one_or_none()

    def correction_history(
        self,
        organization_id: UUID,
        invoice_id: UUID,
    ) -> tuple[UserCorrection, ...] | None:
        visible = self._session.scalar(
            select(Invoice.id).where(
                Invoice.id == invoice_id,
                Invoice.organization_id == organization_id,
                Invoice.deleted_at.is_(None),
            )
        )
        if visible is None:
            return None
        return tuple(
            self._session.scalars(
                select(UserCorrection)
                .where(
                    UserCorrection.organization_id == organization_id,
                    UserCorrection.correction_type == "invoice_field",
                    UserCorrection.object_type == "invoice",
                    UserCorrection.object_id == invoice_id,
                )
                .order_by(UserCorrection.created_at, UserCorrection.id)
            ).all()
        )

    def replace_items(self, invoice_id: UUID, items: tuple[InvoiceItem, ...]) -> None:
        self._session.execute(delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id))
        self._session.add_all(items)

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: tuple[object, ...]) -> None:
        self._session.add_all(values)

    def flush(self) -> None:
        self._session.flush()


__all__ = ["InvoiceExtractionSource", "InvoiceWriteRepository"]
