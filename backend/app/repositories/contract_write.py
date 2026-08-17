"""合同提取、人工修正和确认的固定锁序与持久化访问。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auth import Organization
from app.models.corrections import UserCorrection
from app.models.document_processing import DocumentBlock, DocumentPage, DocumentParseVersion
from app.models.documents import FilePrimaryBusinessObject, FileRecord
from app.models.financial import Contract, ContractField
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository
from app.schemas.contracts import ContractEvidenceData
from app.services.contract_extractor import ContractSourceBlock


@dataclass(frozen=True, slots=True)
class ContractExtractionSource:
    file: FileRecord
    parse_version: DocumentParseVersion
    blocks: tuple[ContractSourceBlock, ...]
    existing_contract_id: UUID | None


class ContractWriteRepository:
    """组织域锁 → 幂等锁 → 文件/合同 → 字段/证据。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._idempotency = UserWriteRepository(session)

    def database_now(self) -> datetime:
        return cast(datetime, self._session.scalar(select(func.clock_timestamp())))

    def acquire_domain_lock(self, organization_id: UUID) -> None:
        identity = f"finaudit:contract-write:{organization_id}"
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
            resource_type="contract",
        )

    def load_extraction_source(
        self,
        organization_id: UUID,
        file_id: UUID,
        parse_version_id: UUID,
    ) -> ContractExtractionSource | None:
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
            or file.intended_business_type != "contract"
            or not file.auto_process_requested
        ):
            return None
        binding = self._session.execute(
            select(FilePrimaryBusinessObject)
            .where(FilePrimaryBusinessObject.file_id == file.id)
            .with_for_update(of=FilePrimaryBusinessObject)
        ).scalar_one_or_none()
        if binding is not None and (
            binding.business_type != "contract" or binding.contract_id is None
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
            ContractSourceBlock(
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
        return ContractExtractionSource(
            file=file,
            parse_version=parse_version,
            blocks=blocks,
            existing_contract_id=None if binding is None else binding.contract_id,
        )

    def lock_contract(self, organization_id: UUID, contract_id: UUID) -> Contract | None:
        return self._session.execute(
            select(Contract)
            .where(
                Contract.id == contract_id,
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
            .with_for_update(of=Contract)
        ).scalar_one_or_none()

    def lock_fields(self, contract_id: UUID) -> tuple[ContractField, ...]:
        return tuple(
            self._session.scalars(
                select(ContractField)
                .where(ContractField.contract_id == contract_id)
                .order_by(ContractField.field_code, ContractField.id)
                .with_for_update(of=ContractField)
            ).all()
        )

    def lock_binding(self, contract_id: UUID) -> FilePrimaryBusinessObject | None:
        return self._session.execute(
            select(FilePrimaryBusinessObject)
            .where(
                FilePrimaryBusinessObject.contract_id == contract_id,
                FilePrimaryBusinessObject.business_type == "contract",
            )
            .with_for_update(of=FilePrimaryBusinessObject)
        ).scalar_one_or_none()

    def validate_evidence(
        self,
        organization_id: UUID,
        file_id: UUID,
        evidence: tuple[ContractEvidenceData, ...],
        *,
        lock: bool = True,
    ) -> bool:
        if not evidence:
            return True
        block_ids = tuple(sorted({item.block_id for item in evidence}, key=lambda item: item.int))
        statement = (
            select(DocumentBlock, DocumentPage.page_no, DocumentParseVersion.file_id)
            .join(DocumentPage, DocumentBlock.page_id == DocumentPage.id)
            .join(DocumentParseVersion, DocumentBlock.parse_version_id == DocumentParseVersion.id)
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
            expected_confidence = None if item.confidence is None else Decimal(item.confidence)
            if (
                observed_file_id != file_id
                or block.parse_version_id != item.parse_version_id
                or page_no != item.page_no
                or block.text_content != item.quote_text
                or block.bbox_json != item.bbox
                or block.confidence != expected_confidence
            ):
                return False
        return True

    def contract_no_exists(
        self,
        organization_id: UUID,
        contract_id: UUID,
        contract_no: str | None,
    ) -> bool:
        if contract_no is None:
            return False
        return (
            self._session.scalar(
                select(Contract.id)
                .where(
                    Contract.organization_id == organization_id,
                    Contract.id != contract_id,
                    Contract.contract_no == contract_no,
                    Contract.deleted_at.is_(None),
                )
                .with_for_update(of=Contract)
            )
            is not None
        )

    def correction_history(
        self,
        organization_id: UUID,
        contract_id: UUID,
    ) -> tuple[UserCorrection, ...] | None:
        visible = self._session.scalar(
            select(Contract.id).where(
                Contract.id == contract_id,
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
        )
        if visible is None:
            return None
        return tuple(
            self._session.scalars(
                select(UserCorrection)
                .where(
                    UserCorrection.organization_id == organization_id,
                    UserCorrection.correction_type == "contract_field",
                    UserCorrection.object_type == "contract",
                    UserCorrection.object_id == contract_id,
                )
                .order_by(UserCorrection.created_at, UserCorrection.id)
            ).all()
        )

    def replace_fields(
        self,
        existing: tuple[ContractField, ...],
        replacements: tuple[ContractField, ...],
        *,
        actor_id: UUID,
        decided_at: datetime,
    ) -> tuple[ContractField, ...]:
        """逻辑整组替换；数据库禁止 DELETE，因此撤下的候选转为 rejected。"""

        by_code = {field.field_code: field for field in existing}
        replacement_codes = {field.field_code for field in replacements}
        current: list[ContractField] = []
        for replacement in replacements:
            stored = by_code.get(replacement.field_code)
            if stored is None:
                self._session.add(replacement)
                current.append(replacement)
                continue
            stored.value_type = replacement.value_type
            stored.extracted_value_json = replacement.extracted_value_json
            stored.confirmed_value_json = None
            stored.confidence = replacement.confidence
            stored.confirmation_status = "unconfirmed"
            stored.evidence_file_id = replacement.evidence_file_id
            stored.evidence_parse_version_id = replacement.evidence_parse_version_id
            stored.evidence_block_id = replacement.evidence_block_id
            stored.page_no = replacement.page_no
            stored.quote_text = replacement.quote_text
            stored.bbox_json = replacement.bbox_json
            stored.confirmed_by = None
            stored.confirmed_at = None
            stored.row_version += 1
            current.append(stored)
        for stored in existing:
            if stored.field_code in replacement_codes:
                continue
            stored.confirmed_value_json = None
            stored.confirmation_status = "rejected"
            stored.confirmed_by = actor_id
            stored.confirmed_at = decided_at
            stored.row_version += 1
            current.append(stored)
        return tuple(sorted(current, key=lambda item: item.field_code))

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: tuple[object, ...]) -> None:
        self._session.add_all(values)

    def flush(self) -> None:
        self._session.flush()


__all__ = ["ContractExtractionSource", "ContractWriteRepository"]
