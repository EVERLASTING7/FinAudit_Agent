"""文件 Job 的真实 Handler：数据库 fencing、租约心跳与外部 I/O 补偿。"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.malware_scanner import MalwareScanner, ScanResult
from app.adapters.minio_file_runtime import FileStorageError, StoredFileObject
from app.models.reliability import (
    JOB_LEASE_POLICY_HASH,
    JOB_LEASE_POLICY_VERSION,
    JOB_RETRY_POLICY_HASH,
    JOB_RETRY_POLICY_VERSION,
    AsyncJob,
    OutboxEvent,
)
from app.repositories.document_processing import (
    DocumentProcessingRepository,
    ParseBlockWrite,
    ParsePageWrite,
    ParseVersionWrite,
)
from app.repositories.job_runtime import ClaimedJob, FileRuntimeSource, JobRuntimeRepository
from app.repositories.markdown_write import MarkdownWriteRepository
from app.services.document_parser import DocumentParseError, DocumentParser, ParsedDocument
from app.workers.contract_handler_registry import (
    CONTRACT_INPUT_SCHEMA_VERSION,
    ContractHandlerRuntime,
    load_contract_handler,
)
from app.workers.file_handler_registry import FileHandlerRuntime, FileJobType, load_file_handler
from app.workers.handler_registry import HandlerRegistryError
from app.workers.invoice_handler_registry import (
    INVOICE_INPUT_SCHEMA_VERSION,
    InvoiceHandlerRuntime,
    load_invoice_handler,
)


class FileJobExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FileRuntimeStorage(Protocol):
    def read_verified(
        self,
        *,
        bucket_name: str,
        object_key: str,
        expected_size: int,
        expected_sha256: str,
        max_bytes: int,
    ) -> bytes: ...

    def promote_clean(
        self,
        *,
        source_bucket: str,
        source_key: str,
        expected_size: int,
        expected_sha256: str,
    ) -> StoredFileObject: ...

    def delete_quarantine_after_commit(self, object_key: str) -> None: ...

    def delete_original_compensation(self, object_key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class FileJobExecutionResult:
    outcome: Literal["succeeded", "failed", "duplicate_or_stale"]
    job_id: UUID


class _LeaseKeeper:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        claim: ClaimedJob,
        *,
        interval_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._claim = claim
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._lost = False
        self._thread = threading.Thread(
            target=self._run,
            name=f"job-lease-{claim.job.id}",
            daemon=True,
        )

    def __enter__(self) -> _LeaseKeeper:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._interval + 1.0))
        if self._thread.is_alive():
            with self._lock:
                self._lost = True

    def claim(self) -> ClaimedJob:
        with self._lock:
            if self._lost:
                raise FileJobExecutionError("JOB_LEASE_LOST")
            return self._claim

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                with self._lock:
                    current = self._claim
                with self._session_factory.begin() as session:
                    refreshed = JobRuntimeRepository(session).heartbeat(current)
                if refreshed is None:
                    raise RuntimeError
                with self._lock:
                    self._claim = refreshed
            except Exception:
                with self._lock:
                    self._lost = True
                self._stop.set()
                return


class FileJobExecutor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        storage: FileRuntimeStorage,
        scanner: MalwareScanner,
        parser: DocumentParser,
        *,
        max_file_bytes: int,
        heartbeat_interval_seconds: float = 20,
    ) -> None:
        if max_file_bytes <= 0 or not 0 < heartbeat_interval_seconds < 60:
            raise ValueError("invalid file job runtime limits")
        self._session_factory = session_factory
        self._storage = storage
        self._scanner = scanner
        self._parser = parser
        self._max_file_bytes = max_file_bytes
        self._heartbeat_interval = heartbeat_interval_seconds

    def execute(
        self,
        *,
        job_id: UUID,
        event_id: UUID,
        event_schema_version: int,
        worker_id: str,
    ) -> FileJobExecutionResult:
        if not worker_id or len(worker_id) > 100:
            raise FileJobExecutionError("WORKER_ID_INVALID")
        with self._session_factory.begin() as session:
            repository = JobRuntimeRepository(session)
            snapshot = repository.peek_job(job_id)
            if snapshot is None:
                raise FileJobExecutionError("JOB_NOT_FOUND")
            try:
                job_type = cast(FileJobType, snapshot.job_type)
                handler = load_file_handler(job_type)
                handler.validate_input(snapshot.input_json)
            except (HandlerRegistryError, ValueError):
                raise FileJobExecutionError("HANDLER_REGISTRY_INVALID") from None
            if (
                snapshot.job_type not in {"file_process", "file_scan"}
                or snapshot.resource_type != "file"
                or snapshot.handler_registry_version != handler.registry_version
                or snapshot.handler_registry_hash != handler.registry_hash
                or snapshot.input_json.get("file_id") != str(snapshot.resource_id)
            ):
                raise FileJobExecutionError("HANDLER_REGISTRY_INVALID")
            start_step_seq = next(
                (
                    index
                    for index, step in enumerate(handler.handler.steps, start=1)
                    if step.step_code == snapshot.current_attempt_start_step_code
                ),
                0,
            )
            if start_step_seq == 0:
                raise FileJobExecutionError("HANDLER_REGISTRY_INVALID")
            claim = repository.claim_job(
                job_id=job_id,
                event_id=event_id,
                event_schema_version=event_schema_version,
                worker_id=worker_id,
                start_step_seq=start_step_seq,
            )
            if claim is None:
                return FileJobExecutionResult("duplicate_or_stale", job_id)
            source = repository.file_runtime_source(claim)
            if source is None:
                raise FileJobExecutionError("FILE_RUNTIME_SOURCE_MISSING")

        return self._execute_claimed(claim, source, handler=handler)

    def execute_claimed(self, claim: ClaimedJob) -> FileJobExecutionResult:
        """执行已由租约恢复事务重领的 claim，不再消费第二条 Broker 消息。"""

        try:
            job_type = cast(FileJobType, claim.job.job_type)
            handler = load_file_handler(job_type)
            handler.validate_input(claim.job.input_json)
        except (HandlerRegistryError, ValueError):
            raise FileJobExecutionError("HANDLER_REGISTRY_INVALID") from None
        if (
            claim.job.job_type not in {"file_process", "file_scan"}
            or claim.job.resource_type != "file"
            or claim.job.handler_registry_version != handler.registry_version
            or claim.job.handler_registry_hash != handler.registry_hash
            or claim.job.input_json.get("file_id") != str(claim.job.resource_id)
        ):
            raise FileJobExecutionError("HANDLER_REGISTRY_INVALID")
        source = self._load_source(claim)
        return self._execute_claimed(claim, source, handler=handler)

    def _execute_claimed(
        self,
        claim: ClaimedJob,
        source: FileRuntimeSource,
        *,
        handler: FileHandlerRuntime,
    ) -> FileJobExecutionResult:
        current_claim = claim
        if (
            current_claim.step_code == "scan"
            and source.status == "stored"
            and source.security_scan_status == "clean"
        ):
            with self._session_factory.begin() as session:
                skipped = JobRuntimeRepository(session).skip_recovered_clean_scan(
                    current_claim,
                    next_step_code="parse",
                    next_step_seq=2,
                )
            if skipped is None:
                raise FileJobExecutionError("JOB_FENCING_REJECTED")
            current_claim = skipped
            source = self._load_source(current_claim)

        if current_claim.step_code == "scan":
            scan_result, next_claim = self._execute_scan(
                current_claim,
                source,
                handler=handler,
            )
            if scan_result.outcome != "clean":
                return FileJobExecutionResult("failed", claim.job.id)
            if next_claim is None:
                return FileJobExecutionResult("succeeded", claim.job.id)
            current_claim = next_claim
            source = self._load_source(current_claim)

        if current_claim.step_code != "parse":
            raise FileJobExecutionError("HANDLER_STEP_INVALID")
        return self._execute_parse(current_claim, source, handler=handler)

    def _load_source(self, claim: ClaimedJob) -> FileRuntimeSource:
        with self._session_factory.begin() as session:
            source = JobRuntimeRepository(session).file_runtime_source(claim)
        if source is None:
            raise FileJobExecutionError("FILE_RUNTIME_SOURCE_MISSING")
        return source

    def _execute_scan(
        self,
        claim: ClaimedJob,
        source: FileRuntimeSource,
        *,
        handler: FileHandlerRuntime,
    ) -> tuple[ScanResult, ClaimedJob | None]:
        promoted: StoredFileObject | None = None
        committed = False
        try:
            lease = _LeaseKeeper(
                self._session_factory,
                claim,
                interval_seconds=self._heartbeat_interval,
            )
            with lease:
                try:
                    payload = self._storage.read_verified(
                        bucket_name=source.quarantine_bucket,
                        object_key=source.quarantine_object_key,
                        expected_size=source.size_bytes,
                        expected_sha256=source.sha256,
                        max_bytes=self._max_file_bytes,
                    )
                except FileStorageError:
                    result = ScanResult(
                        "scan_failed",
                        False,
                        None,
                        None,
                        None,
                        "STORAGE_TRANSIENT",
                    )
                else:
                    try:
                        result = self._scanner.scan(payload)
                    except Exception:
                        result = ScanResult(
                            "scan_failed",
                            True,
                            None,
                            None,
                            None,
                            "DEPENDENCY_UNAVAILABLE",
                        )
                    if result.outcome == "clean":
                        try:
                            promoted = self._storage.promote_clean(
                                source_bucket=source.quarantine_bucket,
                                source_key=source.quarantine_object_key,
                                expected_size=source.size_bytes,
                                expected_sha256=source.sha256,
                            )
                        except FileStorageError:
                            result = ScanResult(
                                "scan_failed",
                                True,
                                result.adapter_code,
                                result.scanner_version,
                                result.definition_version,
                                "STORAGE_TRANSIENT",
                            )
            current = lease.claim()
            handler.validate_summary("scan", result.summary())
            if result.outcome != "clean":
                self._persist_scan_failure(current, result, handler=handler)
                return result, None
            if promoted is None:
                raise FileJobExecutionError("STORAGE_PROMOTION_MISSING")
            next_step = "parse" if claim.job.job_type == "file_process" else None
            next_sequence = claim.step_seq + 1 if next_step is not None else None
            with self._session_factory.begin() as session:
                persisted = JobRuntimeRepository(session).complete_file_scan_clean(
                    current,
                    summary=result.summary(),
                    original_bucket=promoted.bucket_name,
                    original_object_key=promoted.object_key,
                    next_step_code=next_step,
                    next_step_seq=next_sequence,
                )
                if persisted is None or persisted is False:
                    raise FileJobExecutionError("JOB_FENCING_REJECTED")
                next_claim = persisted if isinstance(persisted, ClaimedJob) else None
            committed = True
            try:
                self._storage.delete_quarantine_after_commit(source.quarantine_object_key)
            except FileStorageError:
                pass
            return result, next_claim
        finally:
            if promoted is not None and not committed:
                try:
                    self._storage.delete_original_compensation(promoted.object_key)
                except FileStorageError:
                    pass

    def _persist_scan_failure(
        self,
        claim: ClaimedJob,
        result: ScanResult,
        *,
        handler: FileHandlerRuntime,
    ) -> None:
        handler.validate_summary("scan", result.summary())
        job_error_code = result.error_code or "DEPENDENCY_UNAVAILABLE"
        scan_status = cast(
            Literal["infected", "scan_failed", "unsupported", "not_configured"],
            result.outcome,
        )
        rejection_code = job_error_code if result.outcome in {"infected", "unsupported"} else None
        with self._session_factory.begin() as session:
            persisted = JobRuntimeRepository(session).fail_file_scan(
                claim,
                summary=result.summary(),
                scan_status=scan_status,
                job_error_code=job_error_code,
                rejection_code=rejection_code,
            )
            if not persisted:
                raise FileJobExecutionError("JOB_FENCING_REJECTED")

    def _execute_parse(
        self,
        claim: ClaimedJob,
        source: FileRuntimeSource,
        *,
        handler: FileHandlerRuntime,
    ) -> FileJobExecutionResult:
        if source.original_bucket is None or source.original_object_key is None:
            raise FileJobExecutionError("FILE_ORIGINAL_LOCATOR_MISSING")
        with self._session_factory.begin() as session:
            existing = DocumentProcessingRepository(session).completed_result_for_trace(
                organization_id=source.organization_id,
                file_id=source.id,
                trace_id=claim.job.trace_id,
            )
            if existing is not None:
                existing_summary: dict[str, object] = {
                    "parse_version_id": str(existing.parse_version_id),
                    "page_count": existing.page_count,
                    "parser_name": existing.parser_name,
                    "parser_version": existing.parser_version,
                    "ocr_name": existing.ocr_name,
                    "ocr_version": existing.ocr_version,
                }
                handler.validate_summary("parse", existing_summary)
                existing_next_claim = JobRuntimeRepository(session).advance_step(
                    claim,
                    summary=existing_summary,
                    next_step_code="markdown",
                    next_step_seq=claim.step_seq + 1,
                )
                if existing_next_claim is None:
                    raise FileJobExecutionError("JOB_FENCING_REJECTED")
        if existing is not None:
            if existing_next_claim is None:
                raise FileJobExecutionError("JOB_FENCING_REJECTED")
            return self._execute_markdown(
                existing_next_claim,
                source,
                parse_version_id=existing.parse_version_id,
                handler=handler,
            )
        parse_error: tuple[str, str] | None = None
        parsed: ParsedDocument | None = None
        lease = _LeaseKeeper(
            self._session_factory,
            claim,
            interval_seconds=self._heartbeat_interval,
        )
        with lease:
            try:
                payload = self._storage.read_verified(
                    bucket_name=source.original_bucket,
                    object_key=source.original_object_key,
                    expected_size=source.size_bytes,
                    expected_sha256=source.sha256,
                    max_bytes=self._max_file_bytes,
                )
                parsed = self._parser.parse(payload, mime_type=source.mime_type)
            except FileStorageError:
                parse_error = ("STORAGE_TRANSIENT", "STORAGE_READ_FAILED")
            except DocumentParseError as error:
                parse_error = (_job_error_code(error), error.code)
        current = lease.claim()
        if parse_error is not None:
            return self._persist_parse_failure(
                current,
                source,
                error_code=parse_error[0],
                version_error_code=parse_error[1],
            )
        if parsed is None:
            raise FileJobExecutionError("PARSE_RESULT_MISSING")

        write = _parse_write(parsed)
        with self._session_factory.begin() as session:
            parse_version_id = DocumentProcessingRepository(session).append_result(
                organization_id=source.organization_id,
                file_id=source.id,
                trace_id=current.job.trace_id,
                result=write,
            )
            summary: dict[str, object] = {
                "parse_version_id": str(parse_version_id),
                "page_count": len(parsed.pages),
                "parser_name": parsed.parser_name,
                "parser_version": parsed.parser_version,
                "ocr_name": parsed.ocr_name,
                "ocr_version": parsed.ocr_version,
            }
            handler.validate_summary("parse", summary)
            if (
                source.intended_business_type in {"contract", "invoice"}
                and source.auto_process_requested
            ):
                extraction_input: dict[str, object] = {
                    "file_id": str(source.id),
                    "parse_version_id": str(parse_version_id),
                }
                extraction_handler: InvoiceHandlerRuntime | ContractHandlerRuntime
                if source.intended_business_type == "invoice":
                    extraction_handler = load_invoice_handler()
                    extraction_job_type = "invoice_extract"
                    extraction_schema_version = INVOICE_INPUT_SCHEMA_VERSION
                else:
                    extraction_handler = load_contract_handler()
                    extraction_job_type = "contract_extract"
                    extraction_schema_version = CONTRACT_INPUT_SCHEMA_VERSION
                extraction_handler.validate_input(extraction_input)
                encoded_input = json.dumps(
                    extraction_input,
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                extraction_job = AsyncJob(
                    id=uuid4(),
                    organization_id=source.organization_id,
                    job_type=extraction_job_type,
                    resource_type="file",
                    resource_id=source.id,
                    status="queued",
                    stage=None,
                    attempt_no=0,
                    max_attempts=extraction_handler.handler.max_attempts,
                    current_attempt_start_step_code="extract",
                    input_hash=hashlib.sha256(encoded_input).hexdigest(),
                    input_json=extraction_input,
                    input_schema_version=extraction_schema_version,
                    idempotency_record_id=None,
                    handler_registry_version=extraction_handler.registry_version,
                    handler_registry_hash=extraction_handler.registry_hash,
                    retry_policy_version=JOB_RETRY_POLICY_VERSION,
                    retry_policy_hash=JOB_RETRY_POLICY_HASH,
                    lease_policy_version=JOB_LEASE_POLICY_VERSION,
                    lease_policy_hash=JOB_LEASE_POLICY_HASH,
                    row_version=1,
                    trace_id=current.job.trace_id,
                    created_by=source.uploaded_by,
                )
                session.add(extraction_job)
                session.flush()
                session.add(
                    OutboxEvent(
                        id=uuid4(),
                        aggregate_type="async_job",
                        aggregate_id=extraction_job.id,
                        event_id=uuid4(),
                        event_type="job.dispatch.requested",
                        event_version=1,
                        event_sequence=1,
                        payload_json={"job_id": str(extraction_job.id)},
                        status="pending",
                        attempt_count=0,
                        trace_id=current.job.trace_id,
                    )
                )
            next_claim = JobRuntimeRepository(session).advance_step(
                current,
                summary=summary,
                next_step_code="markdown",
                next_step_seq=current.step_seq + 1,
            )
            if next_claim is None:
                raise FileJobExecutionError("JOB_FENCING_REJECTED")
        return self._execute_markdown(
            next_claim,
            source,
            parse_version_id=parse_version_id,
            handler=handler,
        )

    def _execute_markdown(
        self,
        claim: ClaimedJob,
        source: FileRuntimeSource,
        *,
        parse_version_id: UUID,
        handler: FileHandlerRuntime,
    ) -> FileJobExecutionResult:
        if claim.step_code != "markdown":
            raise FileJobExecutionError("HANDLER_STEP_INVALID")
        try:
            with self._session_factory.begin() as session:
                result = MarkdownWriteRepository(session).generate_and_activate(
                    organization_id=source.organization_id,
                    file_id=source.id,
                    parse_version_id=parse_version_id,
                    trace_id=claim.job.trace_id,
                    actor_id=source.uploaded_by,
                )
                summary: dict[str, object] = {
                    "outcome": result.outcome,
                    "parse_version_id": str(result.parse_version_id),
                    "markdown_version_id": (
                        None
                        if result.markdown_version_id is None
                        else str(result.markdown_version_id)
                    ),
                    "version_no": result.version_no,
                    "content_sha256": result.content_sha256,
                    "char_count": result.char_count,
                    "source_mapping_count": result.source_mapping_count,
                }
                handler.validate_summary("markdown", summary)
                if not JobRuntimeRepository(session).finish_job(
                    claim,
                    status="succeeded",
                    summary=summary,
                ):
                    raise FileJobExecutionError("JOB_FENCING_REJECTED")
        except ValueError:
            with self._session_factory.begin() as session:
                if not JobRuntimeRepository(session).finish_job(
                    claim,
                    status="failed",
                    summary={},
                    error_code="MARKDOWN_CONVERSION_FAILED",
                    error_message="document markdown conversion failed",
                ):
                    raise FileJobExecutionError("JOB_FENCING_REJECTED") from None
            return FileJobExecutionResult("failed", claim.job.id)
        return FileJobExecutionResult("succeeded", claim.job.id)

    def _persist_parse_failure(
        self,
        claim: ClaimedJob,
        source: FileRuntimeSource,
        *,
        error_code: str,
        version_error_code: str,
    ) -> FileJobExecutionResult:
        with self._session_factory.begin() as session:
            DocumentProcessingRepository(session).append_failure(
                organization_id=source.organization_id,
                file_id=source.id,
                trace_id=claim.job.trace_id,
                error_code=version_error_code,
            )
            if not JobRuntimeRepository(session).finish_job(
                claim,
                status="failed",
                summary={},
                error_code=error_code,
                error_message="document parsing failed",
            ):
                raise FileJobExecutionError("JOB_FENCING_REJECTED")
        return FileJobExecutionResult("failed", claim.job.id)


def _job_error_code(error: DocumentParseError) -> str:
    if not error.retryable:
        return error.code
    if error.code == "OCR_TIMEOUT":
        return "DEPENDENCY_TIMEOUT"
    return "DEPENDENCY_UNAVAILABLE"


def _parse_write(parsed: ParsedDocument) -> ParseVersionWrite:
    return ParseVersionWrite(
        source_type=parsed.source_type,
        parser_name=parsed.parser_name,
        parser_version=parsed.parser_version,
        ocr_name=parsed.ocr_name,
        ocr_version=parsed.ocr_version,
        average_confidence=parsed.average_confidence,
        pages=tuple(
            ParsePageWrite(
                page_no=page.page_no,
                width=page.width,
                height=page.height,
                unit=page.unit,
                text=page.text,
                confidence=page.confidence,
                blocks=tuple(
                    ParseBlockWrite(
                        block_index=block.block_index,
                        block_type=block.block_type,
                        text=block.text,
                        bbox=block.bbox,
                        confidence=block.confidence,
                    )
                    for block in page.blocks
                ),
            )
            for page in parsed.pages
        ),
    )


__all__ = [
    "FileJobExecutionError",
    "FileJobExecutionResult",
    "FileJobExecutor",
    "FileRuntimeStorage",
]
