import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.api.dependencies.auth import load_auth_keyring


def _write_key_files(tmp_path: Path) -> tuple[Path, Path]:
    private_key = Ed25519PrivateKey.generate()
    private_file = tmp_path / "private.pem"
    private_file.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    keyring_file = tmp_path / "keyring.json"
    keyring_file.write_text(json.dumps({"authkey01": public_pem}), encoding="utf-8")
    return private_file, keyring_file


def test_keyring_loads_matching_ed25519_signer(tmp_path: Path) -> None:
    private_file, keyring_file = _write_key_files(tmp_path)

    keyring = load_auth_keyring("authkey01", str(private_file), str(keyring_file))

    assert keyring.active_kid == "authkey01"
    assert tuple(keyring.public_keys) == ("authkey01",)


def test_keyring_rejects_duplicate_or_invalid_kids(tmp_path: Path) -> None:
    private_file, keyring_file = _write_key_files(tmp_path)
    public_pem = json.loads(keyring_file.read_text(encoding="utf-8"))["authkey01"]
    keyring_file.write_text(
        '{"authkey01":' + json.dumps(public_pem) + ',"authkey01":' + json.dumps(public_pem) + "}",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_auth_keyring("authkey01", str(private_file), str(keyring_file))

    keyring_file.write_text(json.dumps({"short": public_pem}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid entry"):
        load_auth_keyring("authkey01", str(private_file), str(keyring_file))


def test_keyring_rejects_mismatched_signer(tmp_path: Path) -> None:
    private_file, keyring_file = _write_key_files(tmp_path)
    other_private = Ed25519PrivateKey.generate()
    private_file.write_bytes(
        other_private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    with pytest.raises(ValueError, match="do not match"):
        load_auth_keyring("authkey01", str(private_file), str(keyring_file))
