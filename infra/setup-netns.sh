#!/bin/bash
# Multiverse - Creation des network namespaces et paires veth
# Doit s'executer AVANT NetworkManager (voir setup-netns.service)
set -e

create_pair () {
    local NS=$1
    local VETH_HOST=$2
    local VETH_NS=$3

    # Idempotent : ne recree rien si deja present (utile au reboot)
    ip netns list | grep -q "^$NS" || ip netns add "$NS"

    if ! ip link show "$VETH_HOST" &>/dev/null; then
        ip link add "$VETH_HOST" type veth peer name "$VETH_NS"
        ip link set "$VETH_NS" netns "$NS"
    fi

    ip link set "$VETH_HOST" up
    ip netns exec "$NS" ip link set "$VETH_NS" up
    ip netns exec "$NS" ip link set lo up
}

# Paire 1 : netns "netns" <-> veth0 (host, sera attache a br0)
create_pair netns veth0 veth1

# Paire 2 : netns "ns2" <-> veth2 (host, sera attache a br0)
create_pair ns2 veth2 veth3


echo "[setup-netns] OK : netns/veth crees."
