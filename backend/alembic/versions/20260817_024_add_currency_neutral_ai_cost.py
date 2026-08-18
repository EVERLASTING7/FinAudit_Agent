"""增加 CR-022 Event v2 的币种中立 AI 费用事实。

Revision ID: 20260817_024
Revises: 20260816_023
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260817_024"
down_revision: str | None = "20260816_023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _preflight_upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout='5s'"))
    op.execute(
        sa.text("LOCK TABLE public.ai_call_logs, public.outbox_events IN ACCESS EXCLUSIVE MODE")
    )
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM public.ai_call_logs WHERE status='pending' LIMIT 1
                ) OR EXISTS (
                    SELECT 1 FROM public.outbox_events
                     WHERE aggregate_type='ai_call' AND status<>'published' LIMIT 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='pending AI audit facts block currency migration';
                END IF;
            END; $$;
            """
        )
    )


def _create_runtime_guard_v2() -> None:
    op.execute(
        sa.text(
            r"""
            CREATE FUNCTION public.enforce_ai_call_logs_runtime_v2()
            RETURNS trigger
            LANGUAGE plpgsql VOLATILE SECURITY INVOKER PARALLEL UNSAFE
            SET search_path=pg_catalog,pg_temp
            AS $$
            BEGIN
                IF TG_OP='DELETE' THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='ai call logs are append-only';
                ELSIF TG_OP='UPDATE' THEN
                    IF OLD.status<>'pending' OR NEW.status='pending' OR NEW.event_sequence<>2
                       OR ROW(NEW.id,NEW.event_version,NEW.organization_id,
                              NEW.business_operation_id,NEW.job_id,NEW.request_id,
                              NEW.resource_type,NEW.resource_id,NEW.trace_id,NEW.call_type,
                              NEW.logical_generation_no,NEW.provider_attempt_no,NEW.adapter_id,
                              NEW.endpoint_id,NEW.model_id,NEW.model_version,NEW.prompt_id,
                              NEW.prompt_version,NEW.prompt_hash,NEW.schema_version,
                              NEW.policy_version,NEW.policy_hash,NEW.pricing_version,
                              NEW.input_hash,NEW.reserved_input_tokens,
                              NEW.reserved_output_tokens,NEW.reserved_cost_micro_usd,
                              NEW.cost_currency,NEW.reserved_cost_microunits,
                              NEW.attempt_count,NEW.is_fallback,NEW.breaker_state,NEW.started_at)
                          IS DISTINCT FROM
                          ROW(OLD.id,OLD.event_version,OLD.organization_id,
                              OLD.business_operation_id,OLD.job_id,OLD.request_id,
                              OLD.resource_type,OLD.resource_id,OLD.trace_id,OLD.call_type,
                              OLD.logical_generation_no,OLD.provider_attempt_no,OLD.adapter_id,
                              OLD.endpoint_id,OLD.model_id,OLD.model_version,OLD.prompt_id,
                              OLD.prompt_version,OLD.prompt_hash,OLD.schema_version,
                              OLD.policy_version,OLD.policy_hash,OLD.pricing_version,
                              OLD.input_hash,OLD.reserved_input_tokens,
                              OLD.reserved_output_tokens,OLD.reserved_cost_micro_usd,
                              OLD.cost_currency,OLD.reserved_cost_microunits,
                              OLD.attempt_count,OLD.is_fallback,OLD.breaker_state,OLD.started_at)
                    THEN
                        RAISE EXCEPTION USING ERRCODE='55000',
                            MESSAGE='ai call terminal projection invalid';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$;
            REVOKE ALL ON FUNCTION public.enforce_ai_call_logs_runtime_v2() FROM PUBLIC;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER trg_ai_call_logs_state_v1 ON public.ai_call_logs"))
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_ai_call_logs_state_v1 "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.ai_call_logs "
            "FOR EACH ROW EXECUTE FUNCTION public.enforce_ai_call_logs_runtime_v2()"
        )
    )


def upgrade() -> None:
    _preflight_upgrade()
    op.drop_constraint(
        op.f("ck_ai_call_logs_event_version_one"),
        "ai_call_logs",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_ai_call_logs_reservation_nonnegative"),
        "ai_call_logs",
        schema="public",
        type_="check",
    )
    op.alter_column(
        "ai_call_logs",
        "reserved_cost_micro_usd",
        existing_type=sa.BigInteger(),
        nullable=True,
        schema="public",
    )
    op.add_column(
        "ai_call_logs",
        sa.Column("cost_currency", sa.String(length=3), nullable=True),
        schema="public",
    )
    op.add_column(
        "ai_call_logs",
        sa.Column("reserved_cost_microunits", sa.BigInteger(), nullable=True),
        schema="public",
    )
    op.add_column(
        "ai_call_logs",
        sa.Column("actual_cost_microunits", sa.BigInteger(), nullable=True),
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_ai_call_logs_event_version_allowed"),
        "ai_call_logs",
        "event_version IN (1,2)",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_ai_call_logs_reservation_nonnegative"),
        "ai_call_logs",
        "reserved_input_tokens>=0 AND reserved_output_tokens>=0 "
        "AND (reserved_cost_micro_usd IS NULL OR reserved_cost_micro_usd>=0) "
        "AND (reserved_cost_microunits IS NULL OR reserved_cost_microunits>=0) "
        "AND (actual_cost_microunits IS NULL OR actual_cost_microunits>=0)",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_ai_call_logs_cost_version_matrix"),
        "ai_call_logs",
        "(event_version=1 AND reserved_cost_micro_usd IS NOT NULL "
        "AND cost_currency IS NULL AND reserved_cost_microunits IS NULL "
        "AND actual_cost_microunits IS NULL) OR "
        "(event_version=2 AND reserved_cost_micro_usd IS NULL "
        "AND reserved_cost_microunits IS NOT NULL "
        "AND (cost_currency IN ('USD','CNY') OR "
        "(cost_currency IS NULL AND reserved_cost_microunits=0 "
        "AND (actual_cost_microunits IS NULL OR actual_cost_microunits=0))))",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_ai_call_logs_actual_cost_matrix"),
        "ai_call_logs",
        "event_version=1 OR "
        "(status IN ('pending','outcome_unknown') AND actual_cost_microunits IS NULL) OR "
        "(status='succeeded' AND actual_cost_microunits IS NOT NULL) OR "
        "status IN ('failed','degraded','rejected')",
        schema="public",
    )
    _create_runtime_guard_v2()


def downgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout='5s'"))
    op.execute(
        sa.text("LOCK TABLE public.ai_call_logs, public.outbox_events IN ACCESS EXCLUSIVE MODE")
    )
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM public.ai_call_logs WHERE event_version=2 LIMIT 1
                ) OR EXISTS (
                    SELECT 1 FROM public.outbox_events
                     WHERE aggregate_type='ai_call' AND event_version=2 LIMIT 1
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='55000',
                        MESSAGE='Event v2 facts block currency migration downgrade';
                END IF;
            END; $$;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER trg_ai_call_logs_state_v1 ON public.ai_call_logs"))
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_ai_call_logs_state_v1 "
            "BEFORE INSERT OR UPDATE OR DELETE ON public.ai_call_logs "
            "FOR EACH ROW EXECUTE FUNCTION public.enforce_audit_report_runtime_v1()"
        )
    )
    op.execute(sa.text("DROP FUNCTION public.enforce_ai_call_logs_runtime_v2()"))
    for constraint_name in (
        "actual_cost_matrix",
        "cost_version_matrix",
        "reservation_nonnegative",
        "event_version_allowed",
    ):
        op.drop_constraint(
            op.f(f"ck_ai_call_logs_{constraint_name}"),
            "ai_call_logs",
            schema="public",
            type_="check",
        )
    op.drop_column("ai_call_logs", "actual_cost_microunits", schema="public")
    op.drop_column("ai_call_logs", "reserved_cost_microunits", schema="public")
    op.drop_column("ai_call_logs", "cost_currency", schema="public")
    op.alter_column(
        "ai_call_logs",
        "reserved_cost_micro_usd",
        existing_type=sa.BigInteger(),
        nullable=False,
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_ai_call_logs_event_version_one"),
        "ai_call_logs",
        "event_version=1",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_ai_call_logs_reservation_nonnegative"),
        "ai_call_logs",
        "reserved_input_tokens>=0 AND reserved_output_tokens>=0 AND reserved_cost_micro_usd>=0",
        schema="public",
    )
