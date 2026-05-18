"""[Network] patches — relax RFC1918 blocking for intranet deployments."""

from __future__ import annotations

import ipaddress


_RFC1918_RANGES = {
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
}


def apply() -> None:
    from nanobot.security import network

    blocked = getattr(network, "_BLOCKED_NETWORKS", None)
    if not isinstance(blocked, list):
        return

    network._BLOCKED_NETWORKS = [
        net for net in blocked
        if net not in _RFC1918_RANGES
    ]
