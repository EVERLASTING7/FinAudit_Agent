"""Scanner Registry Profile 的数据库事实模型。"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, LargeBinary, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ScannerRegistryProfile(Base):
    __tablename__ = "scanner_registry_profiles"
    __table_args__ = (
        CheckConstraint(
            "profile_class IN ('contract','local_offline','fixed_test','staging','production')",
            name="class",
        ),
        CheckConstraint(
            "registry_version ~ '^[a-z0-9][a-z0-9._-]{0,99}$'",
            name="version",
        ),
        CheckConstraint(
            "scanner_registry_hash ~ '^[0-9a-f]{64}$' "
            "AND approval_artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="hashes",
        ),
        CheckConstraint("octet_length(profile_jcs_bytes) > 0", name="bytes"),
        CheckConstraint(
            "(activated_at IS NULL AND retired_at IS NULL) OR "
            "(activated_at IS NOT NULL AND retired_at IS NULL) OR "
            "(activated_at IS NOT NULL AND retired_at IS NOT NULL "
            "AND retired_at >= activated_at)",
            name="lifecycle",
        ),
        Index(
            "uq_scanner_registry_profiles_current",
            text("(true)"),
            unique=True,
            postgresql_where=text("activated_at IS NOT NULL AND retired_at IS NULL"),
        ),
    )

    profile_class: Mapped[str] = mapped_column(String(20), primary_key=True)
    registry_version: Mapped[str] = mapped_column(String(100), primary_key=True, unique=True)
    scanner_registry_hash: Mapped[str] = mapped_column(String(64), primary_key=True, unique=True)
    profile_jcs_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    approval_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("transaction_timestamp()")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["ScannerRegistryProfile"]
