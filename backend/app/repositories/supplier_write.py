"""供应商来源解析与候选处理的固定锁序、CAS 和持久化访问。"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.auth import Organization
from app.models.financial import Contract, Invoice, Supplier
from app.repositories.user_write import IdempotencyClaim, UserWriteRepository


class SupplierWriteRepository:
    """组织 → 来源 → supplier UUID 升序；写入始终附带 row-version CAS。"""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._idempotency = UserWriteRepository(session)

    def database_now(self) -> datetime:
        return cast(datetime, self._session.scalar(select(func.clock_timestamp())))

    def acquire_api_locks(
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
            resource_type="supplier",
        )

    def list_suppliers(
        self,
        organization_id: UUID,
        cursor_id: UUID | None,
        limit: int,
    ) -> tuple[Supplier, ...]:
        statement = select(Supplier).where(
            Supplier.organization_id == organization_id,
            Supplier.deleted_at.is_(None),
        )
        if cursor_id is not None:
            statement = statement.where(Supplier.id > cursor_id)
        return tuple(self._session.scalars(statement.order_by(Supplier.id).limit(limit)).all())

    def get_supplier(self, organization_id: UUID, supplier_id: UUID) -> Supplier | None:
        return self._session.scalar(
            select(Supplier).where(
                Supplier.id == supplier_id,
                Supplier.organization_id == organization_id,
                Supplier.deleted_at.is_(None),
            )
        )

    def locate_supplier(self, organization_id: UUID, supplier_id: UUID) -> Supplier | None:
        """在组织行已锁定后读取锁序所需的来源标识。"""

        return self.get_supplier(organization_id, supplier_id)

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

    def source_candidate_id(
        self,
        organization_id: UUID,
        source_type: str,
        source_id: UUID,
    ) -> UUID | None:
        source_column = (
            Supplier.source_contract_id if source_type == "contract" else Supplier.source_invoice_id
        )
        return self._session.scalar(
            select(Supplier.id).where(
                Supplier.organization_id == organization_id,
                source_column == source_id,
                Supplier.status == "candidate",
                Supplier.deleted_at.is_(None),
            )
        )

    def active_supplier_id_by_tax(
        self,
        organization_id: UUID,
        tax_number: str,
        *,
        excluded_id: UUID | None = None,
    ) -> UUID | None:
        statement = select(Supplier.id).where(
            Supplier.organization_id == organization_id,
            Supplier.status == "active",
            Supplier.confirmation_status == "confirmed",
            Supplier.deleted_at.is_(None),
            func.coalesce(Supplier.unified_social_credit_code, Supplier.tax_number) == tax_number,
        )
        if excluded_id is not None:
            statement = statement.where(Supplier.id != excluded_id)
        return self._session.scalar(statement.order_by(Supplier.id).limit(1))

    def lock_suppliers(
        self,
        organization_id: UUID,
        supplier_ids: set[UUID],
    ) -> dict[UUID, Supplier]:
        if not supplier_ids:
            return {}
        rows = self._session.scalars(
            select(Supplier)
            .where(
                Supplier.organization_id == organization_id,
                Supplier.id.in_(tuple(sorted(supplier_ids, key=lambda item: item.int))),
                Supplier.deleted_at.is_(None),
            )
            .order_by(Supplier.id)
            .with_for_update(of=Supplier)
        ).all()
        return {row.id: row for row in rows}

    def cas_contract_supplier(
        self,
        contract: Contract,
        supplier_id: UUID,
        actor_id: UUID,
        now: datetime,
    ) -> bool:
        expected = contract.row_version
        updated_id = self._session.scalar(
            update(Contract)
            .where(
                Contract.id == contract.id,
                Contract.organization_id == contract.organization_id,
                Contract.deleted_at.is_(None),
                Contract.row_version == expected,
            )
            .values(
                supplier_id=supplier_id,
                row_version=Contract.row_version + 1,
                updated_by=actor_id,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
            .returning(Contract.id)
        )
        if updated_id is None:
            return False
        self._session.expire(contract)
        self._session.refresh(contract)
        return True

    def cas_invoice_supplier(
        self,
        invoice: Invoice,
        supplier_id: UUID,
        actor_id: UUID,
        now: datetime,
    ) -> bool:
        expected = invoice.row_version
        updated_id = self._session.scalar(
            update(Invoice)
            .where(
                Invoice.id == invoice.id,
                Invoice.organization_id == invoice.organization_id,
                Invoice.deleted_at.is_(None),
                Invoice.row_version == expected,
            )
            .values(
                supplier_id=supplier_id,
                row_version=Invoice.row_version + 1,
                updated_by=actor_id,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
            .returning(Invoice.id)
        )
        if updated_id is None:
            return False
        self._session.expire(invoice)
        self._session.refresh(invoice)
        return True

    def cas_supplier(
        self,
        supplier: Supplier,
        expected_row_version: int,
        values: dict[str, object],
    ) -> bool:
        updated_id = self._session.scalar(
            update(Supplier)
            .where(
                Supplier.id == supplier.id,
                Supplier.organization_id == supplier.organization_id,
                Supplier.deleted_at.is_(None),
                Supplier.row_version == expected_row_version,
            )
            .values(**values, row_version=Supplier.row_version + 1)
            .execution_options(synchronize_session=False)
            .returning(Supplier.id)
        )
        if updated_id is None:
            return False
        self._session.expire(supplier)
        self._session.refresh(supplier)
        return True

    def add(self, value: object) -> None:
        self._session.add(value)

    def flush(self) -> None:
        self._session.flush()


__all__ = ["SupplierWriteRepository"]
