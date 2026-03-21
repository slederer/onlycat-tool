#!/bin/bash
# Run this on a fresh Amazon Linux 2023 or Ubuntu EC2 instance.
# Usage: ssh into your instance, then:
#   curl -sSL <raw-url-to-this-script> | bash
# Or copy it over and run: bash setup-ec2.sh

set -euo pipefail

echo "==> Installing Docker..."
if command -v dnf &>/dev/null; then
    # Amazon Linux 2023
    sudo dnf update -y
    sudo dnf install -y docker git
    sudo systemctl enable --now docker
elif command -v apt-get &>/dev/null; then
    # Ubuntu
    sudo apt-get update -y
    sudo apt-get install -y docker.io docker-compose-plugin git
    sudo systemctl enable --now docker
fi

# Let current user run docker without sudo
sudo usermod -aG docker "$USER"

echo "==> Installing Docker Compose plugin..."
if ! docker compose version &>/dev/null; then
    sudo mkdir -p /usr/local/lib/docker/cli-plugins
    ARCH=$(uname -m)
    sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${ARCH}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

echo "==> Cloning repo..."
if [ ! -d ~/onlycat-tool ]; then
    git clone https://github.com/YOUR_USERNAME/onlycat-tool.git ~/onlycat-tool
fi

cd ~/onlycat-tool

echo "==> Creating .env file..."
if [ ! -f .env ]; then
    read -rp "Enter your ONLYCAT_TOKEN: " token
    echo "ONLYCAT_TOKEN=${token}" > .env
    echo ".env created"
else
    echo ".env already exists, skipping"
fi

echo "==> Building and starting..."
sudo docker compose up -d --build

echo ""
echo "==> Done! Dashboard is running on port 80."
echo "    Visit: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo '<your-ec2-public-ip>')"
echo ""
echo "    Useful commands:"
echo "      cd ~/onlycat-tool"
echo "      sudo docker compose logs -f     # view logs"
echo "      sudo docker compose restart     # restart"
echo "      sudo docker compose down        # stop"
echo "      sudo docker compose up -d --build  # rebuild & restart"
