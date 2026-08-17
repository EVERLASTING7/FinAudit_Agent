"""合同发票关系写事务的固定锁序与持久化访问。"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auth import Organization
from app.models.financial import Contract, ContractInvoice, Invoice
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository


class ContractInvoiceWriteRepository:
    """按组织/幂等、发票、关系列表和合同的顺序取得写锁。"""

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
            resource_type="contract_invoice",
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

    def lock_relations(self, invoice_id: UUID) -> tuple[ContractInvoice, ...]:
        return tuple(
            self._session.scalars(
                select(ContractInvoice)
                .where(
                    ContractInvoice.invoice_id == invoice_id,
                    ContractInvoice.deleted_at.is_(None),
                )
                .order_by(ContractInvoice.created_at, ContractInvoice.id)
                .with_for_update(of=ContractInvoice)
            ).all()
        )

    def lock_linkable_contract(
        self,
        organization_id: UUID,
        contract_id: UUID,
    ) -> Contract | None:
        return self._session.execute(
            select(Contract)
            .where(
                Contract.id == contract_id,
                Contract.organization_id == organization_id,
                Contract.confirmation_status == "confirmed",
                Contract.status != "draft",
                Contract.deleted_at.is_(None),
            )
            .with_for_update(of=Contract)
        ).scalar_one_or_none()

    def add(self, value: object) -> None:
        self._session.add(value)

    def flush(self) -> None:
        self._session.flush()


__all__ = ["ContractInvoiceWriteRepository"]
