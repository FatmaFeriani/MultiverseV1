#!/bin/bash
set -e
nmcli connection up br0
nmcli connection up br0-veth0
nmcli connection up br0-veth2
echo "[attach-bridge] OK : veth attachees au bridge."