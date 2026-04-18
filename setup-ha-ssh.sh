#!/bin/bash
# Home Assistant SSH Setup Script
# Run this in your Mac Terminal: bash ~/path/to/setup-ha-ssh.sh

set -e

KEY_FILE="$HOME/.ssh/homeassistant"
SSH_CONFIG="$HOME/.ssh/config"

echo "=== Home Assistant SSH Setup ==="
echo ""

# Create .ssh dir if needed
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Generate key if it doesn't exist
if [ -f "$KEY_FILE" ]; then
  echo "✓ SSH key already exists at $KEY_FILE"
else
  echo "Generating SSH key..."
  ssh-keygen -t ed25519 -C "brett-mac-homeassistant" -f "$KEY_FILE" -N ""
  echo "✓ SSH key generated"
fi

echo ""
echo "=== Your Public Key (copy this into HA) ==="
cat "$KEY_FILE.pub"
echo ""
echo "==========================================="

# Add SSH config entry if not already there
if grep -q "Host homeassistant" "$SSH_CONFIG" 2>/dev/null; then
  echo "✓ SSH config entry already exists"
else
  # Prompt for HA IP
  echo ""
  read -p "Enter your Home Assistant IP address (e.g. 192.168.1.100): " HA_IP

  cat >> "$SSH_CONFIG" << EOF

Host homeassistant
  HostName $HA_IP
  User root
  Port 22
  IdentityFile ~/.ssh/homeassistant
  StrictHostKeyChecking no
EOF
  chmod 600 "$SSH_CONFIG"
  echo "✓ SSH config entry added for 'homeassistant'"
fi

echo ""
echo "=== Next Steps ==="
echo "1. Copy the public key above"
echo "2. In HA: Settings → Add-ons → SSH & Web Terminal → Configuration"
echo "3. Paste the key into the 'authorized_keys' field and save"
echo "4. Restart the SSH add-on"
echo "5. Run: ssh homeassistant"
echo ""
echo "Done! Once the key is added to HA, you can connect with: ssh homeassistant"
