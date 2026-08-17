"""补充协议变更写事务的固定锁序与持久化访问。"""

from __future__ import annotations

from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.auth import Organization
from app.models.document_processing import DocumentBlock, DocumentPage, DocumentParseVersion
from app.models.documents import FileRecord
from app.models.financial import (
    Contract,
    ContractField,
    SupplementaryAgreement,
    SupplementaryAgreementChange,
)
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository


class SupplementaryAgreementWriteRepository:
    """组织锁 → 幂等锁 → 协议行 → 变更/证据行的固定顺序。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._idempotency = UserWriteRepository(session)

    def database_now(self) -> datetime:
        return cast(datetime, self._session.scalar(select(func.clock_timestamp())))

    def acquire_locks(
        self,
        organization_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> None:
        self._idempotency.acquire_organization_lock(organization_id)
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
            resource_type="supplementary_agreement",
        )

    def lock_agreement(
        self,
        organization_id: UUID,
        contract_id: UUID,
        agreement_id: UUID,
    ) -> SupplementaryAgreement | None:
        return self._session.execute(
            select(SupplementaryAgreement)
            .join(Contract, SupplementaryAgreement.contract_id == Contract.id)
            .where(
                SupplementaryAgreement.id == agreement_id,
                SupplementaryAgreement.organization_id == organization_id,
                SupplementaryAgreement.contract_id == contract_id,
                SupplementaryAgreement.deleted_at.is_(None),
                Contract.id == contract_id,
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
            .with_for_update(of=SupplementaryAgreement)
        ).scalar_one_or_none()

    def lock_contract(
        self,
        organization_id: UUID,
        contract_id: UUID,
    ) -> Contract | None:
        return self._session.execute(
            select(Contract)
            .where(
                Contract.id == contract_id,
                Contract.organization_id == organization_id,
                Contract.deleted_at.is_(None),
            )
            .with_for_update(of=Contract)
        ).scalar_one_or_none()

    def lock_changes(self, agreement_id: UUID) -> tuple[SupplementaryAgreementChange, ...]:
        return tuple(
            self._session.scalars(
                select(SupplementaryAgreementChange)
                .where(SupplementaryAgreementChange.supplementary_agreement_id == agreement_id)
                .order_by(SupplementaryAgreementChange.field_code)
                .with_for_update(of=SupplementaryAgreementChange)
            ).all()
        )

    def lock_contract_fields(self, contract_id: UUID) -> tuple[ContractField, ...]:
        return tuple(
            self._session.scalars(
                select(ContractField)
                .where(ContractField.contract_id == contract_id)
                .order_by(ContractField.field_code)
                .with_for_update(of=ContractField)
            ).all()
        )

    def lock_prior_changes(
        self,
        contract_id: UUID,
        excluded_agreement_id: UUID,
        before_date: date,
    ) -> tuple[tuple[SupplementaryAgreementChange, SupplementaryAgreement], ...]:
        rows = self._session.execute(
            select(SupplementaryAgreementChange, SupplementaryAgreement)
            .join(
                SupplementaryAgreement,
                SupplementaryAgreementChange.supplementary_agreement_id
                == SupplementaryAgreement.id,
            )
            .where(
                SupplementaryAgreement.contract_id == contract_id,
                SupplementaryAgreement.id != excluded_agreement_id,
                SupplementaryAgreement.deleted_at.is_(None),
                SupplementaryAgreement.effective_date <= before_date,
            )
            .order_by(
                SupplementaryAgreement.effective_date,
                SupplementaryAgreement.id,
                SupplementaryAgreementChange.field_code,
            )
            .with_for_update(of=(SupplementaryAgreement, SupplementaryAgreementChange))
        ).all()
        return tuple(
            (cast(SupplementaryAgreementChange, row[0]), cast(SupplementaryAgreement, row[1]))
            for row in rows
        )

    def validate_evidence_blocks(
        self,
        organization_id: UUID,
        evidence: tuple[tuple[UUID, int], ...],
    ) -> bool:
        if not evidence:
            return True
        block_ids = tuple(block_id for block_id, _ in evidence)
        rows = self._session.execute(
            select(DocumentBlock.id, DocumentPage.page_no)
            .join(DocumentPage, DocumentBlock.page_id == DocumentPage.id)
            .join(
                DocumentParseVersion,
                DocumentBlock.parse_version_id == DocumentParseVersion.id,
            )
            .join(FileRecord, DocumentParseVersion.file_id == FileRecord.id)
            .where(
                DocumentBlock.id.in_(block_ids),
                FileRecord.organization_id == organization_id,
                FileRecord.deleted_at.is_(None),
            )
            .with_for_update(of=DocumentBlock)
        ).all()
        observed = {(row.id, row.page_no) for row in rows}
        return observed == set(evidence)

    def replace_changes(
        self,
        agreement_id: UUID,
        changes: tuple[SupplementaryAgreementChange, ...],
    ) -> None:
        self._session.execute(
            delete(SupplementaryAgreementChange).where(
                SupplementaryAgreementChange.supplementary_agreement_id == agreement_id
            )
        )
        self._session.add_all(changes)

    def add(self, value: object) -> None:
        self._session.add(value)

    def flush(self) -> None:
        self._session.flush()


__all__ = ["SupplementaryAgreementWriteRepository"]
