#!/bin/bash
# Multiverse - Installation de la config reseau (bridge + netns + veth)
# A executer sur le Raspberry Pi, en root : sudo bash infra/install.sh
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Merci de lancer ce script avec sudo : sudo bash infra/install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Copie du script netns/veth"
cp "$SCRIPT_DIR/setup-netns.sh" /usr/local/bin/setup-netns.sh
chmod +x /usr/local/bin/setup-netns.sh

echo "==> Copie du script attach-bridge"
cp "$SCRIPT_DIR/attach-bridge.sh" /usr/local/bin/attach-bridge.sh
chmod +x /usr/local/bin/attach-bridge.sh

echo "==> Installation du service attach-bridge"
cp "$SCRIPT_DIR/attach-bridge.service" /etc/systemd/system/attach-bridge.service

echo "==> Installation du service systemd"
cp "$SCRIPT_DIR/setup-netns.service" /etc/systemd/system/setup-netns.service

echo "==> Installation des profils NetworkManager"
cp "$SCRIPT_DIR"/*.nmconnection /etc/NetworkManager/system-connections/
chmod 600 /etc/NetworkManager/system-connections/br0.nmconnection
chmod 600 /etc/NetworkManager/system-connections/br0-veth0.nmconnection
chmod 600 /etc/NetworkManager/system-connections/br0-veth2.nmconnection
chown root:root /etc/NetworkManager/system-connections/br0*.nmconnection

echo "==> Activation du service au boot"
systemctl enable setup-netns.service
systemctl enable attach-bridge.service

echo "==> Recharge de NetworkManager"
nmcli connection reload

echo ""
echo "Installation terminee."
echo "Un reboot est recommande pour valider l'ordre de demarrage :"
echo "  sudo reboot"
echo ""
echo "Apres reboot, verifier avec :"
echo "  ip netns list"
echo "  nmcli connection show"
echo "  bridge link show br0"
