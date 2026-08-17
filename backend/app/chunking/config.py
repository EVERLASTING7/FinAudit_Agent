"""P0 首版组织级分块配置的纯合同。"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, model_validator

from app.ai.policy import canonicalize_jcs

CHUNK_PROFILE_VERSION = "chunk-profile-v1"


class ChunkTitleHandling(BaseModel):
    """标题处理合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inherit_title_path: StrictBool


class ChunkTableHandling(BaseModel):
    """表格处理合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    keep_whole_if_under_max: StrictBool
    repeat_header_on_split: StrictBool


class ChunkNoiseHandling(BaseModel):
    """噪声处理合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exclude_approved_noise: StrictBool


class P0InitialChunkingConfig(BaseModel):
    """已批准的首版分块参数；后续版本不得复用此固定合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: StrictStr
    target_length: StrictInt
    max_length: StrictInt
    min_length: StrictInt
    overlap_length: StrictInt
    title_handling: ChunkTitleHandling
    table_handling: ChunkTableHandling
    noise_handling: ChunkNoiseHandling

    @model_validator(mode="after")
    def validate_approved_initial_contract(self) -> P0InitialChunkingConfig:
        if (
            self.strategy != "markdown_ast_structural"
            or self.target_length != 700
            or self.max_length != 1200
            or self.min_length != 50
            or self.overlap_length != 100
            or self.title_handling.inherit_title_path is not True
            or self.table_handling.keep_whole_if_under_max is not True
            or self.table_handling.repeat_header_on_split is not True
            or self.noise_handling.exclude_approved_noise is not True
        ):
            raise ValueError("分块配置不符合已批准的 P0 首版合同")
        return self


P0_CHUNK_PROFILE = P0InitialChunkingConfig(
    strategy="markdown_ast_structural",
    target_length=700,
    max_length=1200,
    min_length=50,
    overlap_length=100,
    title_handling=ChunkTitleHandling(inherit_title_path=True),
    table_handling=ChunkTableHandling(
        keep_whole_if_under_max=True,
        repeat_header_on_split=True,
    ),
    noise_handling=ChunkNoiseHandling(exclude_approved_noise=True),
)


def chunk_profile_payload(
    config: P0InitialChunkingConfig = P0_CHUNK_PROFILE,
) -> dict[str, object]:
    """返回进入 ChunkSet 的唯一应用 Profile 投影。"""

    return {
        "profile_version": CHUNK_PROFILE_VERSION,
        **config.model_dump(mode="json"),
    }


def chunk_profile_hash(config: P0InitialChunkingConfig = P0_CHUNK_PROFILE) -> str:
    """按 RFC 8785 JCS 对应用 Profile 计算稳定 SHA-256。"""

    return hashlib.sha256(canonicalize_jcs(chunk_profile_payload(config))).hexdigest()


CHUNK_PROFILE_HASH = chunk_profile_hash()


__all__ = [
    "CHUNK_PROFILE_HASH",
    "CHUNK_PROFILE_VERSION",
    "P0_CHUNK_PROFILE",
    "ChunkNoiseHandling",
    "ChunkTableHandling",
    "ChunkTitleHandling",
    "P0InitialChunkingConfig",
    "chunk_profile_hash",
    "chunk_profile_payload",
]
