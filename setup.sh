#!/bin/bash
# ============================================================
# SETUP SCRIPT - Discord Voice 24/7 Self-Bot trên Ubuntu 22.04
# Chạy: chmod +x setup.sh && sudo ./setup.sh
# ============================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════╗"
echo "║   Discord Voice 24/7 Self-Bot - Installer   ║"
echo "║   Ubuntu 22.04                               ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

# ----------------------------------------------------------
# 1. Cập nhật hệ thống & cài dependencies cơ bản
# ----------------------------------------------------------
echo -e "${GREEN}[1/5] Cập nhật hệ thống & cài dependencies...${NC}"
apt update -y
apt install -y python3 python3-pip python3-venv ffmpeg curl git screen

# ----------------------------------------------------------
# 2. Tạo user riêng để chạy bot (bảo mật)
# ----------------------------------------------------------
echo -e "${GREEN}[2/5] Tạo user 'discord-bot' để chạy service...${NC}"
if ! id "discord-bot" &>/dev/null; then
    useradd -r -s /bin/false discord-bot
    echo -e "${GREEN}  ✅ Đã tạo user discord-bot${NC}"
else
    echo -e "${YELLOW}  ⚠ User discord-bot đã tồn tại, bỏ qua.${NC}"
fi

# ----------------------------------------------------------
# 3. Tạo thư mục & virtualenv
# ----------------------------------------------------------
APP_DIR="/opt/treo-voice"
echo -e "${GREEN}[3/5] Tạo thư mục ứng dụng tại ${APP_DIR}...${NC}"

if [ ! -d "$APP_DIR" ]; then
    mkdir -p "$APP_DIR"
fi

# Copy code nếu đang chạy từ thư mục chứa script này
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/selfbot.py" ]; then
    echo -e "${GREEN}  📁 Copy code từ $SCRIPT_DIR vào $APP_DIR${NC}"
    cp "$SCRIPT_DIR/selfbot.py" "$APP_DIR/"
    cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/" 2>/dev/null || true
fi

# Tạo virtualenv
if [ ! -d "$APP_DIR/venv" ]; then
    python3 -m venv "$APP_DIR/venv"
    echo -e "${GREEN}  ✅ Đã tạo virtualenv${NC}"
fi

# ----------------------------------------------------------
# 4. Cài Python dependencies
# ----------------------------------------------------------
echo -e "${GREEN}[4/5] Cài Python dependencies...${NC}"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install discord.py-self python-dotenv

# Tạo requirements.txt để reference
cat > "$APP_DIR/requirements.txt" << 'EOF'
discord.py-self>=2.0.0
python-dotenv>=1.0.0
EOF

echo -e "${GREEN}  ✅ Đã cài dependencies${NC}"

# ----------------------------------------------------------
# 5. Tạo file .env nếu chưa có
# ----------------------------------------------------------
echo -e "${GREEN}[5/5] Cấu hình...${NC}"

if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" << 'EOF'
# ============================================================
# DISCORD SELF-BOT CONFIG
# ============================================================

# Token tài khoản Discord (nhiều token cách nhau dấu ,)
# Cách lấy: F12 -> Network -> tìm request có header "authorization"
DISCORD_TOKENS=PASTE_YOUR_TOKEN_HERE

# ID Voice Channel muốn tham gia (nhiều ID cách nhau dấu ,)
# Cách lấy: Discord Settings -> Advanced -> Enable Developer Mode
#           Chuột phải vào Voice Channel -> Copy ID
VOICE_CHANNEL_IDS=123456789012345678

# Tự động mute khi join (true/false) - Nên để true
SELF_MUTE=true

# Tự động deafen khi join (true/false)
SELF_DEAF=false

# Thời gian chờ reconnect khi bị disconnect (giây)
RECONNECT_DELAY=10

# Log level: DEBUG | INFO | WARNING | ERROR
LOG_LEVEL=INFO
EOF
    echo -e "${YELLOW}  ⚠ ĐÃ TẠO FILE .env - BẠN PHẢI SỬA TOKEN TRƯỚC KHI CHẠY!${NC}"
    echo -e "${YELLOW}  Sửa file: nano $APP_DIR/.env${NC}"
    echo -e "${YELLOW}  Thay PASTE_YOUR_TOKEN_HERE bằng token thật của bạn${NC}"
else
    echo -e "${YELLOW}  ⚠ File .env đã tồn tại, không ghi đè.${NC}"
fi

# ----------------------------------------------------------
# 6. Tạo systemd service
# ----------------------------------------------------------
echo -e "${GREEN}[Bonus] Tạo systemd service...${NC}"

cat > /etc/systemd/system/treo-voice.service << EOF
[Unit]
Description=Discord Voice 24/7 Self-Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=discord-bot
Group=discord-bot
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/selfbot.py
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal

# Bảo mật cơ bản
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$APP_DIR
ReadOnlyPaths=/

[Install]
WantedBy=multi-user.target
EOF

chown -R discord-bot:discord-bot "$APP_DIR"
chmod 600 "$APP_DIR/.env"
chmod 644 /etc/systemd/system/treo-voice.service

systemctl daemon-reload

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║           INSTALL HOÀN TẤT! 🎉               ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}📌 CÁC BƯỚC TIẾP THEO:${NC}"
echo ""
echo -e " 1️⃣  SỬA TOKEN DISCORD:"
echo -e "    ${GREEN}nano $APP_DIR/.env${NC}"
echo -e "    Thay PASTE_YOUR_TOKEN_HERE = token thật của bạn"
echo -e "    Lấy token: F12 → Network → tìm header 'authorization'"
echo ""
echo -e " 2️⃣  SỬA VOICE CHANNEL ID:"
echo -e "    Bật Developer Mode trong Discord Settings"
echo -e "    Chuột phải vào Voice Channel → Copy ID"
echo -e "    Dán vào VOICE_CHANNEL_IDS trong file .env"
echo ""
echo -e " 3️⃣  KHỞI ĐỘNG BOT:"
echo -e "    ${GREEN}systemctl start treo-voice${NC}"
echo ""
echo -e " 4️⃣  KIỂM TRA TRẠNG THÁI:"
echo -e "    ${GREEN}systemctl status treo-voice${NC}"
echo ""
echo -e " 5️⃣  XEM LOG:"
echo -e "    ${GREEN}journalctl -u treo-voice -f${NC}"
echo ""
echo -e " 6️⃣  TỰ ĐỘNG CHẠY KHI REBOOT:"
echo -e "    ${GREEN}systemctl enable treo-voice${NC}"
echo ""
echo -e "${RED}⚠ CẢNH BÁO: Self-bot vi phạm Discord ToS.${NC}"
echo -e "${RED}  Có thể bị khóa tài khoản bất cứ lúc nào.${NC}"
echo -e "${RED}  Bạn tự chịu trách nhiệm khi sử dụng.${NC}"
echo ""
