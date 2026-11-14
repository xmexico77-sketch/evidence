#!/usr/bin/env bash
# 证源 Evidence —— Ubuntu 原生部署（不用 Docker）
#
# 什么时候用这份：云主机内存小（2G），docker compose build 被 OOM 杀掉时。
# 原生安装省掉了容器层与应用构建的内存峰值，且与开发机验证过的环境一致。
#
# 用法（root 或 sudo）：
#   curl -fsSL https://raw.githubusercontent.com/xmexico77-sketch/evidence/main/scripts/deploy_ubuntu_native.sh -o deploy_native.sh
#   sudo bash deploy_native.sh
#
# 结果：后端 systemd 服务 evidence-api（8000），前端 systemd 服务 evidence-web（3000）。

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/xmexico77-sketch/evidence.git}"
APP_DIR="${APP_DIR:-/opt/evidence}"
WEB_PORT="${WEB_PORT:-3000}"
REVIEWER_PWD="${REVIEWER_PWD:-$(head -c 6 /dev/urandom | xxd -p)}"
SECRET="${SECRET:-$(head -c 24 /dev/urandom | xxd -p)}"
GIT_PROXY="${GIT_PROXY:-}"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

# ---------- 0. 释放 Docker 占用的资源（如果之前试过 Docker 方案）----------
if command -v docker >/dev/null 2>&1 && [[ -d "$APP_DIR" ]]; then
  say "0/7 清理上次的 Docker 容器（释放内存）"
  (cd "$APP_DIR" && docker compose down --remove-orphans 2>/dev/null) || true
  docker system prune -af --volumes >/dev/null 2>&1 || true
  free -h | head -2
fi

# ---------- 1. 基础依赖 ----------
say "1/7 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl git ca-certificates build-essential \
  libgl1 libglib2.0-0 fonts-noto-cjk

# ---------- 2. Python 3.12 ----------
say "2/7 安装 Python 3.12"
if ! command -v python3.12 >/dev/null 2>&1; then
  apt-get install -y -qq software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
  apt-get update -qq
  apt-get install -y -qq python3.12 python3.12-venv python3.12-dev
fi
python3.12 --version

# ---------- 3. Node 20 ----------
say "3/7 安装 Node 20"
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | cut -c2-3)" -lt 18 ]]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
  apt-get install -y -qq nodejs
fi
node -v && npm -v
command -v pnpm >/dev/null 2>&1 || npm install -g pnpm >/dev/null 2>&1 || warn "pnpm 安装失败，将退回 npm"

# ---------- 4. 代码 ----------
say "4/7 获取代码"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" pull --ff-only || warn "拉取失败，沿用现有代码"
else
  rm -rf "$APP_DIR"
  # 国内服务器直连 GitHub 常报 "GnuTLS recv error (-110): TLS connection was
  # non-properly terminated"，必须准备镜像回退，否则整个部署第一步就死。
  CLONED=0
  for MIRROR in "" "https://ghproxy.net/" "https://gh-proxy.com/" "https://ghfast.top/"; do
    URL="${MIRROR}${REPO_URL}"
    echo "尝试克隆：${URL}"
    if git clone --depth 1 "$URL" "$APP_DIR" 2>/dev/null; then
      echo "克隆成功（镜像：${MIRROR:-直连}）"
      CLONED=1
      break
    fi
    rm -rf "$APP_DIR"
  done
  if [[ "$CLONED" -eq 0 ]]; then
    warn "所有镜像都失败。请在浏览器打开仓库，用「Code → Download ZIP」下载后上传到 /opt/evidence-src.zip，再运行："
    warn "  cd /opt && unzip -q evidence-src.zip -d evidence && cd evidence && bash scripts/deploy_ubuntu_native.sh"
    exit 1
  fi
fi
cd "$APP_DIR"

# npm 也走国内镜像，否则前端安装会长时间卡住
npm config set registry https://registry.npmmirror.com 2>/dev/null || true

# ---------- 5. 后端 ----------
say "5/7 安装后端依赖并配置"
[[ -d .venv ]] || python3.12 -m venv .venv
./.venv/bin/pip install -q --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv/bin/pip install -q -r backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo "后端依赖安装完成"

if [[ -f .env ]]; then
  warn ".env 已存在，保留"
else
  cat > .env <<EOF
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}
DEEPSEEK_BASE_URL=https://api.deepseek.com
AUTH_ENABLED=1
EVIDENCE_USERS=reviewer:${REVIEWER_PWD},demo:${REVIEWER_PWD}
EVIDENCE_SECRET=${SECRET}
HF_ENDPOINT=https://hf-mirror.com
API_BASE=http://127.0.0.1:8000
EOF
  chmod 600 .env
fi
REVIEWER_PWD="$(grep -oP 'EVIDENCE_USERS=reviewer:\K[^,]+' .env || echo '见 .env')"

# ---------- 6. 前端构建 ----------
say "6/7 构建前端（2G 内存下约 5–10 分钟）"
cd "$APP_DIR/web"
export NODE_OPTIONS="--max-old-space-size=1024"
if [[ -f pnpm-lock.yaml ]] && command -v pnpm >/dev/null 2>&1; then
  pnpm install --frozen-lockfile || pnpm install
  pnpm build
else
  npm install --no-audit --no-fund
  npm run build
fi
cd "$APP_DIR"

# ---------- 7. systemd ----------
say "7/7 注册系统服务"
cat > /etc/systemd/system/evidence-api.service <<EOF
[Unit]
Description=Evidence API
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir ${APP_DIR}/backend
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/evidence-web.service <<EOF
[Unit]
Description=Evidence Web
After=network.target evidence-api.service
Requires=evidence-api.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}/web
Environment=NODE_ENV=production
Environment=API_BASE=http://127.0.0.1:8000
Environment=PORT=${WEB_PORT}
ExecStart=/usr/bin/node node_modules/next/dist/bin/next start -p ${WEB_PORT} -H 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now evidence-api
say "等待后端加载模型（首次约 1–3 分钟）"
for i in $(seq 1 60); do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "后端就绪"; break
  fi
  sleep 3
  [[ $i -eq 60 ]] && warn "后端 3 分钟未就绪，查看：journalctl -u evidence-api -n 50"
done

systemctl enable --now evidence-web
sleep 3

# ---------- 语料 ----------
say "下载语料并建索引（首次 3–6 分钟）"
if [[ -f data/index/evidence.db ]]; then
  echo "索引已存在，跳过"
else
  ./.venv/bin/python scripts/fetch_corpus.py || warn "语料下载失败，可手动放 PDF 到 data/pdf 后重建"
  ./.venv/bin/python scripts/index_cli.py build "data/pdf/*.pdf" || warn "建索引失败，见日志"
fi

IP="$(curl -fsS --max-time 5 https://api.ipify.org || echo '<服务器IP>')"
say "部署完成"
cat <<EOF

访问地址：http://${IP}:${WEB_PORT}
评审账号：reviewer
评审密码：${REVIEWER_PWD}

自检：
  cd ${APP_DIR} && ./.venv/bin/python scripts/check_deploy.py http://127.0.0.1:${WEB_PORT} --user reviewer --password '${REVIEWER_PWD}'

常用：
  systemctl status evidence-api evidence-web
  journalctl -u evidence-api -f
  systemctl restart evidence-api evidence-web
EOF
