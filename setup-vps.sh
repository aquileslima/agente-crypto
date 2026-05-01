#!/bin/bash
# Quick setup script for Ubuntu VPS (for manual deployment)
# Usage: bash setup-vps.sh

set -e

echo "🚀 Agente Crypto - VPS Setup Script"
echo "===================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
   echo "❌ This script must be run as root (use: sudo bash setup-vps.sh)"
   exit 1
fi

# ============================================================================
# 1. Update system
# ============================================================================
echo ""
echo "📦 Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq

# ============================================================================
# 2. Install Docker & Docker Compose
# ============================================================================
echo ""
echo "📦 Installing Docker..."

if ! command -v docker &> /dev/null; then
    apt-get install -y -qq \
        ca-certificates \
        curl \
        gnupg \
        lsb-release

    # Add Docker repo
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

    echo "✓ Docker installed"
else
    echo "✓ Docker already installed"
fi

# ============================================================================
# 3. Install Docker Compose V2
# ============================================================================
echo ""
echo "📦 Installing Docker Compose V2..."

if ! command -v docker-compose &> /dev/null; then
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    echo "✓ Docker Compose installed"
else
    echo "✓ Docker Compose already installed"
fi

# ============================================================================
# 4. Create app directory
# ============================================================================
APP_DIR="/opt/agente-crypto"

if [ ! -d "$APP_DIR" ]; then
    echo ""
    echo "📁 Creating app directory: $APP_DIR"
    mkdir -p "$APP_DIR"

    # Copy files if in repo directory
    if [ -f "docker-compose.yml" ]; then
        cp -r . "$APP_DIR"
        echo "✓ Files copied"
    else
        echo "⚠️  git clone the repo into $APP_DIR manually"
    fi
else
    echo "✓ App directory already exists at $APP_DIR"
fi

# ============================================================================
# 5. Setup environment file
# ============================================================================
echo ""
echo "⚙️  Configuring environment..."

if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo "✓ Created .env (edit with your credentials)"
    echo ""
    echo "📝 Edit: nano $APP_DIR/.env"
    echo ""
else
    echo "✓ .env file already exists"
fi

# ============================================================================
# 6. Create systemd service (optional)
# ============================================================================
echo ""
echo "🔧 Creating systemd service..."

cat > /etc/systemd/system/agente-crypto.service << 'EOF'
[Unit]
Description=Agente Crypto Trading Bot
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
WorkingDirectory=/opt/agente-crypto
RemainAfterExit=yes
ExecStart=/usr/local/bin/docker-compose -f docker-compose.yml up -d
ExecStop=/usr/local/bin/docker-compose -f docker-compose.yml down
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "✓ Systemd service created"

# ============================================================================
# 7. Summary
# ============================================================================
echo ""
echo "✅ Setup Complete!"
echo ""
echo "📋 Next Steps:"
echo ""
echo "1. Edit your credentials:"
echo "   nano $APP_DIR/.env"
echo ""
echo "2. Start the bot:"
echo "   cd $APP_DIR"
echo "   docker-compose up -d"
echo ""
echo "3. View logs:"
echo "   docker-compose logs -f crypto-bot"
echo ""
echo "4. (Optional) Enable auto-startup:"
echo "   systemctl enable agente-crypto"
echo "   systemctl start agente-crypto"
echo ""
echo "📊 Dashboard: http://localhost:5000"
echo ""
