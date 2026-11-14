#!/usr/bin/env bash
# 证源 Evidence —— 服务器加固（在重装后的干净系统上执行）
#
# 背景：2026-11-14 这台机器因 SSH 密码登录被爆破植入挖矿木马
# （/tmp/.net/.a 与 /opt/evidence/web/x86_64.dusk）。本脚本做四件事：
#   1. SSH 只允许密钥登录，禁止密码与 root 密码登录
#   2. ufw 只放行 22 与 3000
#   3. fail2ban 封禁暴力破解源
#   4. 打开自动安全更新
set -euo pipefail

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# ---------- 1. SSH 加固 ----------
say "1/4 SSH 改为仅密钥登录"
cp -a /etc/ssh/sshd_config "/etc/ssh/sshd_config.bak.$(date +%s)"

set_kv() {
  local key="$1" val="$2" f=/etc/ssh/sshd_config
  if grep -qE "^#?[[:space:]]*${key}[[:space:]]" "$f"; then
    sed -i -E "s|^#?[[:space:]]*${key}[[:space:]].*|${key} ${val}|" "$f"
  else
    echo "${key} ${val}" >> "$f"
  fi
}

set_kv PasswordAuthentication no
set_kv KbdInteractiveAuthentication no
set_kv ChallengeResponseAuthentication no
set_kv PermitRootLogin prohibit-password
set_kv PubkeyAuthentication yes
set_kv MaxAuthTries 3
set_kv LoginGraceTime 20
set_kv X11Forwarding no

# 校验语法，避免改坏后 sshd 起不来把自己锁在外面
sshd -t
systemctl restart ssh
echo "sshd 已重启，当前生效配置："
sshd -T 2>/dev/null | grep -E "^(passwordauthentication|permitrootlogin|pubkeyauthentication|maxauthtries) "

# ---------- 2. 防火墙 ----------
say "2/4 防火墙只放行 22 与 3000"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ufw fail2ban unattended-upgrades

ufw --force reset >/dev/null 2>&1 || true
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp >/dev/null
ufw allow 3000/tcp >/dev/null
ufw --force enable >/dev/null
ufw status verbose | sed -n '1,12p'

# ---------- 3. fail2ban ----------
say "3/4 fail2ban 封禁 SSH 爆破"
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
findtime = 600
bantime = 3600
bantime.increment = true
EOF
systemctl enable --now fail2ban >/dev/null 2>&1
systemctl restart fail2ban
fail2ban-client status sshd 2>/dev/null | sed -n '1,8p' || true

# ---------- 4. 自动安全更新 ----------
say "4/4 打开自动安全更新与时间同步"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
timedatectl set-ntp true 2>/dev/null || true

say "加固完成"
echo "当前登录用户：$(whoami)"
echo "SSH 密码登录：已禁用（只能用密钥）"
echo "开放端口：22、3000"
