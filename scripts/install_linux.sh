#!/usr/bin/env bash
set -e

echo "Starting Ganymede installation for Linux..."

# Check root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root or with sudo"
  exit 1
fi

INSTALL_DIR="/opt/ganymede"
VENV_DIR="$INSTALL_DIR/venv"

echo "Creating directories..."
mkdir -p "$INSTALL_DIR"

echo "Setting up Python virtual environment..."
python3 -m venv "$VENV_DIR"
$VENV_DIR/bin/pip install -U pip setuptools wheel

echo "Installing Ganymede..."
# Install from the current directory, or you can point to a release wheel
$VENV_DIR/bin/pip install .

echo "Symlinking executable to /usr/local/bin/ganymede..."
ln -sf "$VENV_DIR/bin/ganymede" /usr/local/bin/ganymede

echo "Creating systemd service..."
cat <<EOF > /etc/systemd/system/ganymede.service
[Unit]
Description=Ganymede Antigravity Gateway
After=network.target

[Service]
Type=simple
User=$SUDO_USER
ExecStart=ganymede
Restart=on-failure
Environment="GANYMEDE_DATA_DIR=/home/$SUDO_USER/.ganymede/data"

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd daemon..."
systemctl daemon-reload
systemctl enable ganymede.service

echo "Installation complete!"
echo "To start the gateway, run: sudo systemctl start ganymede"
echo "Check the dashboard at http://localhost:8080"
