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

# 小包/弱网下 git 的 HTTP/2 容易断（实测 curl 92 INTERNAL_ERROR、early EOF），
# 全局压回 HTTP/1.1 并加大缓冲，能显著降低断流概率
git config --global http.version HTTP/1.1 2>/dev/null || true
git config --global http.postBuffer 524288000 2>/dev/null || true

TARBALL_URL="${REPO_URL%.git}/archive/refs/heads/main.tar.gz"

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" pull --ff-only || warn "拉取失败，沿用现有代码"
elif [[ -f "$APP_DIR/docker-compose.yml" ]]; then
  say "已有源码目录，跳过下载"
else
  rm -rf "$APP_DIR"
  OK=0

  # 先试 git 克隆（镜像优先）
  for MIRROR in "https://ghproxy.net/" "https://gh-proxy.com/" "https://ghfast.top/" ""; do
    echo "尝试 git 克隆：${MIRROR}${REPO_URL}"
    if git clone --depth 1 --single-branch "${MIRROR}${REPO_URL}" "$APP_DIR" 2>/dev/null; then
      OK=1; break
    fi
    rm -rf "$APP_DIR"
  done

  # git 不通就退回整包下载：单次 HTTP 请求，比 git 的 pack 传输稳得多
  if [[ "$OK" -eq 0 ]]; then
    warn "git 克隆全部失败，改用 tarball 整包下载"
    for MIRROR in "https://ghproxy.net/" "https://gh-proxy.com/" "https://ghfast.top/" ""; do
      URL="${MIRROR}${TARBALL_URL}"
      echo "尝试下载：${URL}"
      if curl -fL --http1.1 --retry 3 --retry-delay 2 --connect-timeout 20 -o /tmp/evidence-src.tar.gz "$URL"; then
        mkdir -p "$APP_DIR"
        if tar xzf /tmp/evidence-src.tar.gz -C "$APP_DIR" --strip-components=1; then
          echo "tarball 解包成功（镜像：${MIRROR:-直连}）"
          OK=1; break
        fi
      fi
      rm -rf "$APP_DIR"
    done
  fi

  if [[ "$OK" -eq 0 ]]; then
    warn "自动获取均失败。请在能上网的电脑打开仓库，Code → Download ZIP，"
    warn "把 zip 上传到服务器 /tmp/evidence.zip，然后执行："
    warn "  sudo apt-get install -y unzip && sudo mkdir -p $APP_DIR && sudo unzip -q /tmp/evidence.zip -d /tmp/ev && sudo cp -r /tmp/ev/*/* $APP_DIR"
    warn "  cd $APP_DIR && sudo bash scripts/deploy_ubuntu_native.sh"
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

# 幂等：已经装好且构建过就跳过。部署中断后重跑时，不必再花 5–10 分钟重装重构建。
if [[ -d node_modules && -f .next/BUILD_ID ]]; then
  say "前端已安装并构建过，跳过（删除 .next 可强制重建）"
else

# 不管仓库里的 package.json 是不是最新，都就地写入 onlyBuiltDependencies。
# 这样即使 git pull 因网络失败、代码是旧版，也不会再被
# ERR_PNPM_IGNORED_BUILDS（sharp）拦死。
node -e "const fs=require('fs');const f='package.json';const p=JSON.parse(fs.readFileSync(f,'utf8'));p.pnpm=Object.assign({},p.pnpm,{onlyBuiltDependencies:['sharp']});fs.writeFileSync(f,JSON.stringify(p,null,2));console.log('已写入 pnpm.onlyBuiltDependencies=sharp')"

INSTALLED=0
if [[ -f pnpm-lock.yaml ]] && command -v pnpm >/dev/null 2>&1; then
  # 上一轮失败可能留下半截 node_modules（pnpm 的 .pnpm 符号链接结构），
  # 直接在上面跑 npm 会崩：Cannot read properties of null (reading 'isDescendantOf')
  rm -rf node_modules .next

  # --ignore-scripts 绕开 pnpm 的构建脚本门禁（pnpm v12 已不读 package.json 的
  # pnpm.onlyBuiltDependencies 字段，实测照样报 ERR_PNPM_IGNORED_BUILDS）。
  # sharp 只用于 Next 的图片优化，本项目页面不依赖它，装不上也能跑。
  pnpm install --ignore-scripts && INSTALLED=1 || warn "pnpm install --ignore-scripts 失败"
  if [[ "$INSTALLED" -eq 1 ]]; then
    pnpm rebuild sharp >/dev/null 2>&1 || warn "sharp 未重建（不影响本项目，忽略）"
  fi
  if [[ "$INSTALLED" -eq 0 ]]; then
    warn "退回 npm 安装"
    rm -rf node_modules .next
    npm install --no-audit --no-fund --registry=https://registry.npmmirror.com && INSTALLED=1 || true
  fi
else
  rm -rf node_modules .next
  npm install --no-audit --no-fund --registry=https://registry.npmmirror.com && INSTALLED=1 || true
fi

if [[ "$INSTALLED" -eq 0 ]]; then
  warn "前端依赖安装失败，见上方日志"
  exit 1
fi
pnpm build 2>/dev/null || npm run build
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
