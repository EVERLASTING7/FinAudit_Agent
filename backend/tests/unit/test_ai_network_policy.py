from __future__ import annotations

import hashlib
import os
import socket
import time
from copy import copy, deepcopy
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

import pytest

from app.ai.network_policy import (
    BillingMode,
    NetworkDecisionStatus,
    OutboundNetworkPolicy,
    ResolutionBinding,
    authorize_peer,
    authorize_resolution,
)

_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[3] / "docs" / "change-requests" / "artifacts" / "CR-011"
)
_REGISTRY_BYTES = (_ARTIFACT_ROOT / "ip-deny-cidrs-v1.json").read_bytes()
_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"


def internal_policy(
    *,
    endpoint_id: str = "synthetic-internal-001",
    base_url: str = "http://synthetic-internal:8000/v1",
    approved_hostnames: tuple[str, ...] = ("synthetic-internal",),
    allowed_cidrs: tuple[str, ...] = ("10.250.1.0/24",),
    billing_mode: BillingMode = "internal_unmetered",
) -> OutboundNetworkPolicy:
    return OutboundNetworkPolicy(
        endpoint_id=endpoint_id,
        network_scope="internal_service",
        base_url=base_url,
        approved_hostnames=approved_hostnames,
        allowed_cidrs=allowed_cidrs,
        billing_mode=billing_mode,
        address_policy_version="ip-deny-cidrs-v1",
        registry_sha256=_REGISTRY_SHA256,
    )


def external_policy(
    *,
    endpoint_id: str = "synthetic-external-001",
    base_url: str = "https://api.synthetic.test:443/v1",
    approved_hostnames: tuple[str, ...] = ("api.synthetic.test",),
    allowed_cidrs: tuple[str, ...] = ("8.8.8.0/24", "2606:4700:4700::/48"),
) -> OutboundNetworkPolicy:
    return OutboundNetworkPolicy(
        endpoint_id=endpoint_id,
        network_scope="external_public",
        base_url=base_url,
        approved_hostnames=approved_hostnames,
        allowed_cidrs=allowed_cidrs,
        billing_mode="external_usd",
        address_policy_version="ip-deny-cidrs-v1",
        registry_sha256=_REGISTRY_SHA256,
    )


def test_frozen_registry_identity_and_internal_fixed_vector() -> None:
    assert hashlib.sha256(_REGISTRY_BYTES).hexdigest() == _REGISTRY_SHA256
    policy = internal_policy()

    resolution = authorize_resolution(
        policy,
        hostname="synthetic-internal",
        resolved_addresses=("10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert resolution.status is NetworkDecisionStatus.RESOLUTION_ALLOWED
    assert resolution.allowed is True
    assert resolution.binding is not None

    peer = authorize_peer(
        policy,
        resolution.binding,
        peer_address="10.250.1.10",
        registry_bytes=_REGISTRY_BYTES,
    )
    assert peer.status is NetworkDecisionStatus.PEER_ALLOWED
    assert peer.allowed is True


def test_external_requires_every_a_and_aaaa_address_to_be_allowed() -> None:
    policy = external_policy()
    allowed = authorize_resolution(
        policy,
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8", "2606:4700:4700::1111"),
        registry_bytes=_REGISTRY_BYTES,
    )
    denied = authorize_resolution(
        policy,
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8", "2001:db8::1"),
        registry_bytes=_REGISTRY_BYTES,
    )

    assert allowed.status is NetworkDecisionStatus.RESOLUTION_ALLOWED
    assert denied.status is NetworkDecisionStatus.RESOLVED_ADDRESS_DENIED
    assert denied.binding is None


def test_external_dynamic_dns_mode_uses_pinned_deny_registry() -> None:
    policy = external_policy(allowed_cidrs=())

    allowed = authorize_resolution(
        policy,
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8", "2606:4700:4700::1111"),
        registry_bytes=_REGISTRY_BYTES,
    )
    denied = authorize_resolution(
        policy,
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8", "127.0.0.1"),
        registry_bytes=_REGISTRY_BYTES,
    )

    assert allowed.status is NetworkDecisionStatus.RESOLUTION_ALLOWED
    assert allowed.binding is not None
    assert denied.status is NetworkDecisionStatus.RESOLVED_ADDRESS_DENIED
    assert denied.binding is None


@pytest.mark.parametrize(
    "denied_address",
    [
        "127.0.0.1",
        "169.254.169.254",
        "10.0.0.1",
        "100.100.100.200",
        "203.0.113.1",
        "8.8.9.1",
        "::1",
        "fe80::1",
    ],
)
def test_one_denied_resolution_poisoning_the_set_fails_closed(denied_address: str) -> None:
    decision = authorize_resolution(
        external_policy(),
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8", denied_address),
        registry_bytes=_REGISTRY_BYTES,
    )

    assert decision.status is NetworkDecisionStatus.RESOLVED_ADDRESS_DENIED


@pytest.mark.parametrize(
    "allowed_cidrs",
    [
        ("10.0.0.0/8",),
        ("127.0.0.0/8",),
        ("169.254.0.0/16",),
        ("192.0.2.0/24",),
        ("2001:db8::/32",),
        ("::ffff:0:0/96",),
    ],
)
def test_external_allowlist_cannot_overlap_any_deny_registry_entry(
    allowed_cidrs: tuple[str, ...],
) -> None:
    decision = authorize_resolution(
        external_policy(allowed_cidrs=allowed_cidrs),
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8",),
        registry_bytes=_REGISTRY_BYTES,
    )

    assert decision.status is NetworkDecisionStatus.POLICY_INVALID


@pytest.mark.parametrize(
    "allowed_cidrs",
    [
        ("8.8.8.0/24",),
        ("100.64.0.0/10",),
        ("127.0.0.0/8",),
        ("169.254.169.254/32",),
        ("fc00::/7",),
        ("fd00:ec2::254/128",),
    ],
)
def test_internal_allowlist_requires_app_eligible_without_forbidden_overlap(
    allowed_cidrs: tuple[str, ...],
) -> None:
    decision = authorize_resolution(
        internal_policy(allowed_cidrs=allowed_cidrs),
        hostname="synthetic-internal",
        resolved_addresses=("10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )

    assert decision.status is NetworkDecisionStatus.POLICY_INVALID


def test_internal_accepts_rfc1918_and_ula_subnets() -> None:
    vectors = [
        (("10.250.1.0/24",), "10.250.1.10"),
        (("172.20.0.0/16",), "172.20.0.1"),
        (("192.168.50.0/24",), "192.168.50.254"),
        (("fd12:3456:789a::/48",), "fd12:3456:789a::1"),
    ]

    for cidrs, address in vectors:
        decision = authorize_resolution(
            internal_policy(allowed_cidrs=cidrs),
            hostname="synthetic-internal",
            resolved_addresses=(address,),
            registry_bytes=_REGISTRY_BYTES,
        )
        assert decision.status is NetworkDecisionStatus.RESOLUTION_ALLOWED


def test_ipv4_mapped_ipv6_is_normalized_for_resolution_and_peer_binding() -> None:
    policy = internal_policy()
    resolution = authorize_resolution(
        policy,
        hostname="synthetic-internal",
        resolved_addresses=("::ffff:10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert resolution.binding is not None
    assert resolution.binding.resolved_addresses == ("10.250.1.10",)

    peer = authorize_peer(
        policy,
        resolution.binding,
        peer_address="10.250.1.10",
        registry_bytes=_REGISTRY_BYTES,
    )
    assert peer.status is NetworkDecisionStatus.PEER_ALLOWED


def test_peer_drift_is_rejected_even_when_the_new_peer_is_in_the_allowlist() -> None:
    policy = internal_policy()
    resolution = authorize_resolution(
        policy,
        hostname="synthetic-internal",
        resolved_addresses=("10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert resolution.binding is not None

    decision = authorize_peer(
        policy,
        resolution.binding,
        peer_address="10.250.1.11",
        registry_bytes=_REGISTRY_BYTES,
    )
    assert decision.status is NetworkDecisionStatus.PEER_DRIFT


def test_peer_outside_allowlist_is_denied_before_it_can_be_used() -> None:
    policy = internal_policy()
    resolution = authorize_resolution(
        policy,
        hostname="synthetic-internal",
        resolved_addresses=("10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert resolution.binding is not None

    decision = authorize_peer(
        policy,
        resolution.binding,
        peer_address="10.250.2.10",
        registry_bytes=_REGISTRY_BYTES,
    )
    assert decision.status is NetworkDecisionStatus.PEER_DENIED


def test_resolution_binding_cannot_be_replayed_across_network_scopes() -> None:
    internal = internal_policy(
        base_url="https://api.synthetic.test:443/v1",
        approved_hostnames=("api.synthetic.test",),
    )
    resolution = authorize_resolution(
        internal,
        hostname="api.synthetic.test",
        resolved_addresses=("10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert resolution.binding is not None
    external = external_policy()

    decision = authorize_peer(
        external,
        resolution.binding,
        peer_address="8.8.8.8",
        registry_bytes=_REGISTRY_BYTES,
    )
    assert decision.status is NetworkDecisionStatus.BINDING_MISMATCH


@pytest.mark.parametrize(
    ("policy", "hostname"),
    [
        (external_policy(base_url="http://api.synthetic.test:443/v1"), "api.synthetic.test"),
        (external_policy(base_url="https://API.synthetic.test:443/v1"), "api.synthetic.test"),
        (external_policy(base_url="https://xn--example.test:443/v1"), "xn--example.test"),
        (external_policy(base_url="https://127.0.0.1:443/v1"), "127.0.0.1"),
        (external_policy(base_url="https://api.synthetic.test:443/v2"), "api.synthetic.test"),
        (
            external_policy(approved_hostnames=("other.synthetic.test",)),
            "api.synthetic.test",
        ),
        (
            internal_policy(billing_mode="external_usd"),
            "synthetic-internal",
        ),
    ],
)
def test_hostname_base_url_and_scope_binding_fail_closed(
    policy: OutboundNetworkPolicy,
    hostname: str,
) -> None:
    decision = authorize_resolution(
        policy,
        hostname=hostname,
        resolved_addresses=("8.8.8.8",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert decision.status is NetworkDecisionStatus.POLICY_INVALID


def test_resolver_hostname_must_equal_the_bound_base_url_hostname() -> None:
    decision = authorize_resolution(
        external_policy(),
        hostname="other.synthetic.test",
        resolved_addresses=("8.8.8.8",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert decision.status is NetworkDecisionStatus.HOST_BINDING_INVALID


@pytest.mark.parametrize(
    "addresses",
    [(), ("",), ("not-an-ip",), (" 8.8.8.8",), ("fe80::1%eth0",)],
)
def test_empty_or_malformed_resolution_sets_fail_closed(addresses: tuple[str, ...]) -> None:
    decision = authorize_resolution(
        external_policy(),
        hostname="api.synthetic.test",
        resolved_addresses=addresses,
        registry_bytes=_REGISTRY_BYTES,
    )
    assert decision.status is NetworkDecisionStatus.RESOLUTION_INVALID


def test_registry_version_hash_and_strict_json_are_rechecked() -> None:
    wrong_hash = replace(external_policy(), registry_sha256="0" * 64)
    wrong_version = replace(external_policy(), address_policy_version="ip-deny-cidrs-v2")
    duplicate_key_registry = b'{"registry_version":"x","registry_version":"x","entries":[]}'
    duplicate_key_policy = replace(
        external_policy(),
        address_policy_version="x",
        registry_sha256=hashlib.sha256(duplicate_key_registry).hexdigest(),
    )

    for policy, registry in (
        (wrong_hash, _REGISTRY_BYTES),
        (wrong_version, _REGISTRY_BYTES),
        (external_policy(), b"not-json"),
        (duplicate_key_policy, duplicate_key_registry),
    ):
        decision = authorize_resolution(
            policy,
            hostname="api.synthetic.test",
            resolved_addresses=("8.8.8.8",),
            registry_bytes=registry,
        )
        assert decision.status is NetworkDecisionStatus.REGISTRY_INVALID


def test_registry_identity_cannot_be_replaced_by_self_consistent_policy_pins() -> None:
    alternate_registry = (
        b'{"entries":[{"categories":["private","app_network_eligible"],'
        b'"cidr":"10.0.0.0/8"}],"registry_version":"attacker-v1"}'
    )
    self_pinned_policy = replace(
        external_policy(),
        address_policy_version="attacker-v1",
        registry_sha256=hashlib.sha256(alternate_registry).hexdigest(),
    )

    decision = authorize_resolution(
        self_pinned_policy,
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8",),
        registry_bytes=alternate_registry,
    )

    assert decision.status is NetworkDecisionStatus.REGISTRY_INVALID


@pytest.mark.parametrize(
    "allowed_cidrs",
    [
        ("2606:4700:4700::/48", "8.8.8.0/24"),
        ("8.8.9.0/24", "8.8.8.0/24"),
    ],
)
def test_allowed_cidrs_must_use_the_exact_canonical_network_sort_order(
    allowed_cidrs: tuple[str, ...],
) -> None:
    decision = authorize_resolution(
        external_policy(allowed_cidrs=allowed_cidrs),
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8",),
        registry_bytes=_REGISTRY_BYTES,
    )

    assert decision.status is NetworkDecisionStatus.POLICY_INVALID


@pytest.mark.parametrize(
    "base_url",
    [
        "\x00https://api.synthetic.test:443/v1",
        "https://api.synthetic.test:443/v1\x1f",
        "https://api.synthetic.test:443/v1\x7f",
        "https://api.synthetic.test:443/v1\x85",
        "HTTPS://api.synthetic.test:443/v1",
    ],
)
def test_base_url_rejects_controls_and_any_urlsplit_source_normalization(
    base_url: str,
) -> None:
    decision = authorize_resolution(
        external_policy(base_url=base_url),
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8",),
        registry_bytes=_REGISTRY_BYTES,
    )

    assert decision.status is NetworkDecisionStatus.POLICY_INVALID


def test_resolution_binding_has_no_public_construction_path() -> None:
    with pytest.raises(TypeError, match="authorize_resolution"):
        ResolutionBinding()


def test_low_level_binding_forgery_without_private_capability_is_rejected() -> None:
    policy = internal_policy()
    forged = object.__new__(ResolutionBinding)
    object.__setattr__(forged, "policy", policy)
    object.__setattr__(forged, "hostname", "synthetic-internal")
    object.__setattr__(forged, "resolved_addresses", ("10.250.1.10",))
    object.__setattr__(forged, "_capability", object())

    decision = authorize_peer(
        policy,
        forged,
        peer_address="10.250.1.10",
        registry_bytes=_REGISTRY_BYTES,
    )

    assert decision.status is NetworkDecisionStatus.BINDING_MISMATCH


def test_binding_copy_and_replayed_capability_cannot_replace_the_dns_set() -> None:
    policy = internal_policy()
    resolution = authorize_resolution(
        policy,
        hostname="synthetic-internal",
        resolved_addresses=("10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert resolution.binding is not None
    original = resolution.binding

    with pytest.raises(TypeError, match="cannot be copied"):
        copy(original)
    with pytest.raises(TypeError, match="cannot be copied"):
        deepcopy(original)
    replayed_capability = copy(original._capability)

    forged = object.__new__(ResolutionBinding)
    object.__setattr__(forged, "policy", policy)
    object.__setattr__(forged, "hostname", "synthetic-internal")
    object.__setattr__(forged, "resolved_addresses", ("10.250.1.11",))
    object.__setattr__(forged, "_capability", replayed_capability)

    decision = authorize_peer(
        policy,
        forged,
        peer_address="10.250.1.11",
        registry_bytes=_REGISTRY_BYTES,
    )

    assert decision.status is NetworkDecisionStatus.BINDING_MISMATCH


def test_original_binding_capability_seals_the_exact_resolution_state() -> None:
    policy = internal_policy()
    resolution = authorize_resolution(
        policy,
        hostname="synthetic-internal",
        resolved_addresses=("10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert resolution.binding is not None
    object.__setattr__(resolution.binding, "resolved_addresses", ("10.250.1.11",))

    decision = authorize_peer(
        policy,
        resolution.binding,
        peer_address="10.250.1.11",
        registry_bytes=_REGISTRY_BYTES,
    )

    assert decision.status is NetworkDecisionStatus.BINDING_MISMATCH


@pytest.mark.parametrize(
    "tampered_addresses",
    [
        [],
        (),
        ("10.250.1.10", "10.250.1.10"),
        ("10.250.1.11", "10.250.1.10"),
        ("::ffff:10.250.1.10",),
        ("10.250.2.10",),
    ],
)
def test_capable_binding_revalidates_strict_canonical_nonempty_allowed_tuple(
    tampered_addresses: object,
) -> None:
    policy = internal_policy()
    resolution = authorize_resolution(
        policy,
        hostname="synthetic-internal",
        resolved_addresses=("10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert resolution.binding is not None
    object.__setattr__(resolution.binding, "resolved_addresses", tampered_addresses)

    decision = authorize_peer(
        policy,
        resolution.binding,
        peer_address="10.250.1.10",
        registry_bytes=_REGISTRY_BYTES,
    )

    assert decision.status is NetworkDecisionStatus.BINDING_MISMATCH


@pytest.mark.parametrize(
    ("cidr", "inside", "outside"),
    [
        ("8.8.8.0/30", ("8.8.8.0", "8.8.8.3"), "8.8.8.4"),
        ("2606:4700:4700::/126", ("2606:4700:4700::", "2606:4700:4700::3"), "2606:4700:4700::4"),
    ],
)
def test_cidr_membership_includes_exact_edges_and_rejects_one_address_beyond(
    cidr: str,
    inside: tuple[str, str],
    outside: str,
) -> None:
    policy = external_policy(allowed_cidrs=(cidr,))
    for address in inside:
        decision = authorize_resolution(
            policy,
            hostname="api.synthetic.test",
            resolved_addresses=(address,),
            registry_bytes=_REGISTRY_BYTES,
        )
        assert decision.status is NetworkDecisionStatus.RESOLUTION_ALLOWED

    denied = authorize_resolution(
        policy,
        hostname="api.synthetic.test",
        resolved_addresses=(outside,),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert denied.status is NetworkDecisionStatus.RESOLVED_ADDRESS_DENIED


def test_resolution_set_is_order_independent_and_deduplicated_after_mapping() -> None:
    policy = external_policy(allowed_cidrs=("8.8.8.0/24",))
    first = authorize_resolution(
        policy,
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.9", "::ffff:8.8.8.8", "8.8.8.8"),
        registry_bytes=_REGISTRY_BYTES,
    )
    second = authorize_resolution(
        policy,
        hostname="api.synthetic.test",
        resolved_addresses=("8.8.8.8", "8.8.8.9"),
        registry_bytes=_REGISTRY_BYTES,
    )

    assert first.status is NetworkDecisionStatus.RESOLUTION_ALLOWED
    assert first.binding == second.binding


def test_network_policy_uses_only_injected_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> NoReturn:
        del args, kwargs
        raise AssertionError("network policy must not perform runtime I/O")

    monkeypatch.setattr(socket, "socket", unexpected_call)
    monkeypatch.setattr(socket, "create_connection", unexpected_call)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_call)
    monkeypatch.setattr(os, "getenv", unexpected_call)
    monkeypatch.setattr(Path, "read_bytes", unexpected_call)
    monkeypatch.setattr(time, "sleep", unexpected_call)

    policy = internal_policy()
    resolution = authorize_resolution(
        policy,
        hostname="synthetic-internal",
        resolved_addresses=("10.250.1.10",),
        registry_bytes=_REGISTRY_BYTES,
    )
    assert resolution.binding is not None
    peer = authorize_peer(
        policy,
        resolution.binding,
        peer_address="10.250.1.10",
        registry_bytes=_REGISTRY_BYTES,
    )
    assert peer.status is NetworkDecisionStatus.PEER_ALLOWED
