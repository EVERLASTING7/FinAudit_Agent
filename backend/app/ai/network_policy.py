"""CR-011 Gate B 的纯值出站网络策略判断；不执行 DNS、socket 或文件读取。"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import unicodedata
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from enum import Enum
from types import FunctionType
from typing import Literal, NoReturn, SupportsIndex, TypeAlias, cast
from urllib.parse import urlsplit
from weakref import WeakSet

from app.ai.strict_json import parse_strict_json

NetworkScope: TypeAlias = Literal["external_public", "internal_service"]
BillingMode: TypeAlias = Literal["external_usd", "internal_unmetered"]
IpAddress: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address
IpNetwork: TypeAlias = ipaddress.IPv4Network | ipaddress.IPv6Network
_BindingState: TypeAlias = tuple[object, ...]
_BindingCapability: TypeAlias = Callable[[object, _BindingState], bool]

_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_INTERNAL_DENY_CATEGORIES = frozenset({"loopback", "link_local", "metadata"})
_APPROVED_REGISTRY_VERSION = "ip-deny-cidrs-v1"
_APPROVED_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"
_BINDING_CAPABILITIES: WeakSet[_BindingCapability] = WeakSet()


@dataclass(frozen=True, slots=True)
class OutboundNetworkPolicy:
    """已由 Policy Schema+companion 验证链投影出的最小网络字段。"""

    endpoint_id: str
    network_scope: NetworkScope
    base_url: str
    approved_hostnames: tuple[str, ...]
    allowed_cidrs: tuple[str, ...]
    billing_mode: BillingMode
    address_policy_version: str
    registry_sha256: str


@dataclass(frozen=True, slots=True, init=False)
class ResolutionBinding:
    """把一次合成解析结果绑定到完整网络策略快照。"""

    policy: OutboundNetworkPolicy
    hostname: str
    resolved_addresses: tuple[str, ...]
    _capability: _BindingCapability = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("ResolutionBinding is created by authorize_resolution")

    def __copy__(self) -> NoReturn:
        raise TypeError("ResolutionBinding cannot be copied")

    def __deepcopy__(self, memo: object) -> NoReturn:
        del memo
        raise TypeError("ResolutionBinding cannot be copied")

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        del protocol
        raise TypeError("ResolutionBinding cannot be serialized")


class NetworkDecisionStatus(str, Enum):
    RESOLUTION_ALLOWED = "resolution_allowed"
    PEER_ALLOWED = "peer_allowed"
    POLICY_INVALID = "policy_invalid"
    REGISTRY_INVALID = "registry_invalid"
    HOST_BINDING_INVALID = "host_binding_invalid"
    RESOLUTION_INVALID = "resolution_invalid"
    RESOLVED_ADDRESS_DENIED = "resolved_address_denied"
    BINDING_MISMATCH = "binding_mismatch"
    PEER_INVALID = "peer_invalid"
    PEER_DENIED = "peer_denied"
    PEER_DRIFT = "peer_drift"


@dataclass(frozen=True, slots=True)
class NetworkPolicyDecision:
    status: NetworkDecisionStatus
    binding: ResolutionBinding | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        has_binding = self.binding is not None
        if has_binding != (self.status is NetworkDecisionStatus.RESOLUTION_ALLOWED):
            raise ValueError("only resolution_allowed carries a binding")

    @property
    def allowed(self) -> bool:
        return self.status in {
            NetworkDecisionStatus.RESOLUTION_ALLOWED,
            NetworkDecisionStatus.PEER_ALLOWED,
        }


@dataclass(frozen=True, slots=True)
class _RegistryEntry:
    network: IpNetwork
    categories: frozenset[str]


@dataclass(frozen=True, slots=True)
class _PreparedPolicy:
    hostname: str
    allowed_networks: tuple[IpNetwork, ...]
    denied_networks: tuple[IpNetwork, ...]
    network_scope: NetworkScope


def _hostname_is_canonical(hostname: object) -> bool:
    if type(hostname) is not str or not 1 <= len(hostname) <= 253:
        return False
    try:
        hostname.encode("ascii")
    except UnicodeEncodeError:
        return False
    labels = hostname.split(".")
    if any(
        not label or label.startswith("xn--") or not _HOST_LABEL.fullmatch(label)
        for label in labels
    ):
        return False
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return False


def _base_url_hostname(policy: OutboundNetworkPolicy) -> str | None:
    value = policy.base_url
    if (
        type(value) is not str
        or "%" in value
        or any(
            character.isspace() or unicodedata.category(character) == "Cc" for character in value
        )
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    netloc = parsed.netloc
    if not netloc or "@" in netloc or netloc.startswith("["):
        return None
    port_text: str | None = None
    if ":" in netloc:
        raw_host, port_text = netloc.rsplit(":", 1)
        if not port_text.isdigit():
            return None
    else:
        raw_host = netloc
    if (
        not _hostname_is_canonical(raw_host)
        or parsed.hostname != raw_host
        or parsed.path != "/v1"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or (port is not None and not 1 <= port <= 65535)
    ):
        return None
    expected_netloc = raw_host if port_text is None else f"{raw_host}:{port_text}"
    if value != f"{parsed.scheme}://{expected_netloc}/v1":
        return None
    if policy.network_scope == "external_public" and parsed.scheme != "https":
        return None
    if policy.network_scope == "internal_service" and parsed.scheme not in {"http", "https"}:
        return None
    return raw_host


def _normalize_address(address: IpAddress) -> IpAddress:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _normalize_network(network: IpNetwork) -> IpNetwork:
    if isinstance(network, ipaddress.IPv6Network) and network.prefixlen >= 96:
        mapped = network.network_address.ipv4_mapped
        if mapped is not None:
            return ipaddress.IPv4Network((mapped, network.prefixlen - 96), strict=True)
    return network


def _parse_network(value: object, *, normalize_mapped: bool) -> IpNetwork | None:
    if type(value) is not str:
        return None
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError:
        return None
    if str(network) != value:
        return None
    return _normalize_network(network) if normalize_mapped else network


def _parse_address(value: object) -> IpAddress | None:
    if type(value) is not str or not value or "%" in value or value.strip() != value:
        return None
    try:
        return _normalize_address(ipaddress.ip_address(value))
    except ValueError:
        return None


def _address_sort_key(address: IpAddress) -> tuple[int, int]:
    return address.version, int(address)


def _network_sort_key(network: IpNetwork) -> tuple[int, int, int]:
    return network.version, int(network.network_address), network.prefixlen


def _network_overlaps(left: IpNetwork, right: IpNetwork) -> bool:
    return left.version == right.version and left.overlaps(right)


def _network_contains_network(left: IpNetwork, right: IpNetwork) -> bool:
    if isinstance(left, ipaddress.IPv4Network) and isinstance(right, ipaddress.IPv4Network):
        return right.subnet_of(left)
    if isinstance(left, ipaddress.IPv6Network) and isinstance(right, ipaddress.IPv6Network):
        return right.subnet_of(left)
    return False


def _network_contains_address(network: IpNetwork, address: IpAddress) -> bool:
    if isinstance(network, ipaddress.IPv4Network) and isinstance(address, ipaddress.IPv4Address):
        return address in network
    if isinstance(network, ipaddress.IPv6Network) and isinstance(address, ipaddress.IPv6Address):
        return address in network
    return False


def _load_registry(
    policy: OutboundNetworkPolicy,
    registry_bytes: bytes,
) -> tuple[_RegistryEntry, ...] | None:
    if type(registry_bytes) is not bytes:
        return None
    if (
        policy.address_policy_version != _APPROVED_REGISTRY_VERSION
        or policy.registry_sha256 != _APPROVED_REGISTRY_SHA256
        or hashlib.sha256(registry_bytes).hexdigest() != _APPROVED_REGISTRY_SHA256
    ):
        return None
    try:
        value = parse_strict_json(registry_bytes).value
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    root = value
    if root.get("registry_version") != _APPROVED_REGISTRY_VERSION:
        return None
    raw_entries = root.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        return None

    entries: list[_RegistryEntry] = []
    seen: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            return None
        entry = raw_entry
        cidr = entry.get("cidr")
        categories = entry.get("categories")
        try:
            # Registry source spelling is already pinned by its raw-byte hash.
            network = ipaddress.ip_network(cidr, strict=True) if type(cidr) is str else None
        except ValueError:
            network = None
        if (
            type(cidr) is not str
            or cidr in seen
            or network is None
            or not isinstance(categories, list)
            or not categories
            or not all(type(category) is str for category in categories)
        ):
            return None
        seen.add(cidr)
        entries.append(
            _RegistryEntry(
                network=network,
                categories=frozenset(cast(list[str], categories)),
            )
        )
    return tuple(entries)


def _prepare_policy(
    policy: OutboundNetworkPolicy,
    registry_bytes: bytes,
) -> tuple[_PreparedPolicy | None, NetworkDecisionStatus]:
    if type(policy) is not OutboundNetworkPolicy:
        return None, NetworkDecisionStatus.POLICY_INVALID
    entries = _load_registry(policy, registry_bytes)
    if entries is None:
        return None, NetworkDecisionStatus.REGISTRY_INVALID
    hostname = _base_url_hostname(policy)
    if (
        type(policy.endpoint_id) is not str
        or not policy.endpoint_id
        or hostname is None
        or type(policy.approved_hostnames) is not tuple
        or not policy.approved_hostnames
        or len(set(policy.approved_hostnames)) != len(policy.approved_hostnames)
        or not all(_hostname_is_canonical(item) for item in policy.approved_hostnames)
        or hostname not in policy.approved_hostnames
        or type(policy.allowed_cidrs) is not tuple
        or (policy.network_scope == "internal_service" and not policy.allowed_cidrs)
        or policy.network_scope not in {"external_public", "internal_service"}
        or policy.billing_mode not in {"external_usd", "internal_unmetered"}
        or (
            policy.network_scope == "internal_service"
            and policy.billing_mode != "internal_unmetered"
        )
    ):
        return None, NetworkDecisionStatus.POLICY_INVALID

    parsed = tuple(_parse_network(value, normalize_mapped=False) for value in policy.allowed_cidrs)
    if any(network is None or network.prefixlen == 0 for network in parsed):
        return None, NetworkDecisionStatus.POLICY_INVALID
    source_networks = cast(tuple[IpNetwork, ...], parsed)
    if source_networks != tuple(sorted(source_networks, key=_network_sort_key)):
        return None, NetworkDecisionStatus.POLICY_INVALID
    networks = tuple(_normalize_network(network) for network in source_networks)
    if any(
        _network_overlaps(network, other)
        for index, network in enumerate(networks)
        for other in networks[index + 1 :]
    ):
        return None, NetworkDecisionStatus.POLICY_INVALID

    for network in networks:
        if policy.network_scope == "external_public":
            if any(_network_overlaps(network, entry.network) for entry in entries):
                return None, NetworkDecisionStatus.POLICY_INVALID
            continue
        eligible = any(
            "app_network_eligible" in entry.categories
            and _network_contains_network(entry.network, network)
            for entry in entries
        )
        denied = any(
            bool(entry.categories & _INTERNAL_DENY_CATEGORIES)
            and _network_overlaps(network, entry.network)
            for entry in entries
        )
        if not eligible or denied:
            return None, NetworkDecisionStatus.POLICY_INVALID
    # 地址本身已把 IPv4-mapped IPv6 归一为 IPv4；保留 Registry 原始网络族，
    # 避免把 ``::ffff:0:0/96`` 错投影成禁止全部原生 IPv4 的 ``0.0.0.0/0``。
    denied_networks = tuple(entry.network for entry in entries)
    return (
        _PreparedPolicy(
            hostname=hostname,
            allowed_networks=networks,
            denied_networks=denied_networks,
            network_scope=policy.network_scope,
        ),
        NetworkDecisionStatus.RESOLUTION_ALLOWED,
    )


def _parse_resolution_set(values: Collection[str]) -> tuple[IpAddress, ...] | None:
    if isinstance(values, (str, bytes, bytearray)) or not values:
        return None
    parsed = tuple(_parse_address(value) for value in values)
    if any(address is None for address in parsed):
        return None
    unique = set(cast(tuple[IpAddress, ...], parsed))
    return tuple(sorted(unique, key=_address_sort_key))


def _address_is_allowed(address: IpAddress, prepared: _PreparedPolicy) -> bool:
    if prepared.network_scope == "external_public" and not prepared.allowed_networks:
        return not any(
            _network_contains_address(network, address) for network in prepared.denied_networks
        )
    return any(_network_contains_address(network, address) for network in prepared.allowed_networks)


def _binding_state(
    policy: OutboundNetworkPolicy,
    hostname: str,
    resolved_addresses: tuple[str, ...],
) -> _BindingState:
    return (
        policy.endpoint_id,
        policy.network_scope,
        policy.base_url,
        policy.approved_hostnames,
        policy.allowed_cidrs,
        policy.billing_mode,
        policy.address_policy_version,
        policy.registry_sha256,
        hostname,
        resolved_addresses,
    )


def _create_binding_capability(
    owner: ResolutionBinding,
    state: _BindingState,
) -> _BindingCapability:
    def verify(candidate: object, current_state: _BindingState) -> bool:
        return candidate is owner and current_state == state

    _BINDING_CAPABILITIES.add(verify)
    return verify


def _create_resolution_binding(
    policy: OutboundNetworkPolicy,
    hostname: str,
    addresses: tuple[IpAddress, ...],
) -> ResolutionBinding:
    values = tuple(str(item) for item in addresses)
    binding = object.__new__(ResolutionBinding)
    object.__setattr__(binding, "policy", policy)
    object.__setattr__(binding, "hostname", hostname)
    object.__setattr__(binding, "resolved_addresses", values)
    capability = _create_binding_capability(
        binding,
        _binding_state(policy, hostname, values),
    )
    object.__setattr__(binding, "_capability", capability)
    return binding


def _binding_matches_policy(
    binding: object,
    policy: OutboundNetworkPolicy,
    prepared: _PreparedPolicy,
) -> bool:
    if type(binding) is not ResolutionBinding:
        return False
    try:
        binding_policy = binding.policy
        hostname = binding.hostname
        values = binding.resolved_addresses
        capability = binding._capability
    except AttributeError:
        return False
    if (
        type(capability) is not FunctionType
        or capability not in _BINDING_CAPABILITIES
        or type(binding_policy) is not OutboundNetworkPolicy
        or binding_policy != policy
        or type(hostname) is not str
        or hostname != prepared.hostname
        or not _hostname_is_canonical(hostname)
        or type(values) is not tuple
        or not values
    ):
        return False
    if not capability(binding, _binding_state(binding_policy, hostname, values)):
        return False
    parsed = tuple(_parse_address(value) for value in values)
    if any(address is None for address in parsed):
        return False
    addresses = cast(tuple[IpAddress, ...], parsed)
    canonical = tuple(sorted(set(addresses), key=_address_sort_key))
    return (
        addresses == canonical
        and values == tuple(str(address) for address in canonical)
        and all(_address_is_allowed(address, prepared) for address in addresses)
    )


def authorize_resolution(
    policy: OutboundNetworkPolicy,
    *,
    hostname: str,
    resolved_addresses: Collection[str],
    registry_bytes: bytes,
) -> NetworkPolicyDecision:
    """验证调用方注入的完整 A/AAAA 集合并返回纯值连接绑定。"""

    prepared, failure = _prepare_policy(policy, registry_bytes)
    if prepared is None:
        return NetworkPolicyDecision(failure)
    if hostname != prepared.hostname or not _hostname_is_canonical(hostname):
        return NetworkPolicyDecision(NetworkDecisionStatus.HOST_BINDING_INVALID)
    addresses = _parse_resolution_set(resolved_addresses)
    if addresses is None:
        return NetworkPolicyDecision(NetworkDecisionStatus.RESOLUTION_INVALID)
    if any(not _address_is_allowed(address, prepared) for address in addresses):
        return NetworkPolicyDecision(NetworkDecisionStatus.RESOLVED_ADDRESS_DENIED)
    binding = _create_resolution_binding(policy, hostname, addresses)
    return NetworkPolicyDecision(NetworkDecisionStatus.RESOLUTION_ALLOWED, binding)


def authorize_peer(
    policy: OutboundNetworkPolicy,
    binding: ResolutionBinding,
    *,
    peer_address: str,
    registry_bytes: bytes,
) -> NetworkPolicyDecision:
    """复核实际 peer 与原解析集合、scope、URL、allowlist 和 registry 绑定。"""

    prepared, failure = _prepare_policy(policy, registry_bytes)
    if prepared is None:
        return NetworkPolicyDecision(failure)
    if not _binding_matches_policy(binding, policy, prepared):
        return NetworkPolicyDecision(NetworkDecisionStatus.BINDING_MISMATCH)
    peer = _parse_address(peer_address)
    if peer is None:
        return NetworkPolicyDecision(NetworkDecisionStatus.PEER_INVALID)
    if not _address_is_allowed(peer, prepared):
        return NetworkPolicyDecision(NetworkDecisionStatus.PEER_DENIED)
    if str(peer) not in binding.resolved_addresses:
        return NetworkPolicyDecision(NetworkDecisionStatus.PEER_DRIFT)
    return NetworkPolicyDecision(NetworkDecisionStatus.PEER_ALLOWED)
