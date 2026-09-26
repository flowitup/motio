#!/usr/bin/env bash
# Chuẩn bị một server Hetzner Cloud mới (Ubuntu 24.04) cho Motio + Postiz. Chạy MỘT lần bằng root:
#
#   ssh root@<ip> "DEPLOY_PUBKEY='$(cat motio-deploy.pub)' bash -s" < deploy/bootstrap.sh
#
# Cài Docker + Compose, tạo user `deploy` (SSH bằng key, chạy docker), thư mục /opt/motio, swap,
# tường lửa (22, 80, 443), tắt đăng nhập SSH bằng mật khẩu. Chạy lại nhiều lần không sao.
set -euo pipefail

DEPLOY_USER=${DEPLOY_USER:-deploy}
APP_DIR=${APP_DIR:-/opt/motio}
SWAP_GB=${SWAP_GB:-4}
DEPLOY_PUBKEY=${DEPLOY_PUBKEY:-}   # public key của GitHub Actions (tuỳ chọn)

if [ "$(id -u)" -ne 0 ]; then
  echo "Chạy bằng root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get install -y ca-certificates curl ufw unattended-upgrades

# ---------- Docker Engine + Compose plugin (repo chính thức của Docker) ----------
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $codename stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

# ---------- user deploy ----------
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
ssh_dir="/home/$DEPLOY_USER/.ssh"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ssh_dir"
touch "$ssh_dir/authorized_keys"
# Key bạn dùng để vào root cũng vào được deploy
if [ -f /root/.ssh/authorized_keys ]; then
  while IFS= read -r key; do
    if [ -n "$key" ] && ! grep -qxF "$key" "$ssh_dir/authorized_keys"; then
      echo "$key" >> "$ssh_dir/authorized_keys"
    fi
  done < /root/.ssh/authorized_keys
fi
if [ -n "$DEPLOY_PUBKEY" ] && ! grep -qxF "$DEPLOY_PUBKEY" "$ssh_dir/authorized_keys"; then
  echo "$DEPLOY_PUBKEY" >> "$ssh_dir/authorized_keys"
fi
chown "$DEPLOY_USER:$DEPLOY_USER" "$ssh_dir/authorized_keys"
chmod 600 "$ssh_dir/authorized_keys"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR"

# ---------- swap (Whisper + Elasticsearch có lúc ăn nhiều RAM) ----------
if ! swapon --show | grep -q .; then
  fallocate -l "${SWAP_GB}G" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Elasticsearch (Temporal) khuyến nghị giá trị này
echo 'vm.max_map_count=262144' > /etc/sysctl.d/99-motio.conf
sysctl --system >/dev/null

# ---------- tường lửa ----------
# Docker publish cổng đi vòng qua ufw; compose chỉ publish 80/443 (Caddy) và 127.0.0.1:8080 (tuỳ chọn).
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

# ---------- SSH: chỉ dùng key ----------
cat > /etc/ssh/sshd_config.d/99-motio.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
systemctl try-reload-or-restart ssh  # 24.04 dùng socket activation; kết nối mới đọc cấu hình mới

echo
echo "Xong. Tiếp theo (xem docs/DEPLOY.md):"
echo "  1. ssh $DEPLOY_USER@<ip>, tạo $APP_DIR/.env từ deploy/env.example"
echo "  2. Chạy workflow 'Deploy (Hetzner)' trên GitHub"
