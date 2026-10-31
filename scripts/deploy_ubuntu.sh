#!/usr/bin/env bash
# 证源 Evidence —— Ubuntu 云主机一键部署
#
# 用法（在服务器上以 root 或 sudo 用户执行）：
#   curl -fsSL https://raw.githubusercontent.com/xmexico77-sketch/evidence/main/scripts/deploy_ubuntu.sh -o deploy.sh
#   sudo bash deploy.sh
#
# 它会做：
#   1. 安装 Docker 与 compose 插件
#   2. 克隆代码到 /opt/evidence
#   3. 生成 .env（随机会话密钥、评审账号密码）
#   4. docker compose 构建并启动
#   5. 容器内下载语料并建索引（首次约 3–6 分钟）
#   6. 打印访问地址与账号
#
# 前置条件：Ubuntu 22.04 / 24.04，2 核 4G 起，已放行安全组端口 3000。
# 若只想用 IP 访问，不需要域名，也不需要备案。

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/xmexico77-sketch/evidence.git}"
APP_DIR="${APP_DIR:-/opt/evidence}"
WEB_PORT="${WEB_PORT:-3000}"
REVIEWER_PWD="${REVIEWER_PWD:-$(head -c 6 /dev/urandom | xxd -p)}"
SECRET="${SECRET:-$(head -c 24 /dev/urandom | xxd -p)}"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
  warn "建议用 root 运行（sudo bash $0）"
fi

# ---------- 1. Docker ----------
say "1/6 安装 Docker"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl git
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
else
  echo "已安装，跳过"
fi

# ---------- 2. 代码 ----------
say "2/6 获取代码"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" pull --ff-only || warn "拉取失败，继续用现有代码"
else
  rm -rf "$APP_DIR"
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# ---------- 3. .env ----------
say "3/6 生成配置"
if [[ -f .env ]]; then
  warn ".env 已存在，保留原配置（如需重建请先删除）"
else
  cat > .env <<EOF
# 由 deploy_ubuntu.sh 生成于 $(date -u +%FT%TZ)

# 模型（有 Key 则翻译/综述/写作走真模型；留空则降级为抽取式）
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 认证：公网必须开启
AUTH_ENABLED=1
EVIDENCE_USERS=reviewer:${REVIEWER_PWD},demo:${REVIEWER_PWD}
EVIDENCE_SECRET=${SECRET}

# 国内网络走镜像（首次启动要下约 640MB 模型）
HF_ENDPOINT=https://hf-mirror.com

# 前端代理到后端容器
API_BASE=http://api:8000
EOF
  chmod 600 .env
fi

# 读回账号密码（无论新建还是复用）
REVIEWER_PWD="$(grep -oP 'EVIDENCE_USERS=reviewer:\K[^,]+' .env || echo '见 .env')"

# ---------- 4. 构建启动 ----------
say "4/6 构建并启动容器（首次约 3–8 分钟，含下载依赖）"
docker compose up -d --build

say "等待后端就绪"
for i in $(seq 1 90); do
  if docker compose exec -T api python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3).status==200 else 1)" >/dev/null 2>&1; then
    echo "后端已就绪（第 ${i} 次探测）"
    break
  fi
  sleep 4
  [[ $i -eq 90 ]] && warn "90 次探测仍未就绪，请查看日志：docker compose logs -f api"
done

# ---------- 5. 语料与索引 ----------
say "5/6 下载语料并建索引"
if docker compose exec -T api ls data/index/evidence.db >/dev/null 2>&1; then
  echo "索引已存在，跳过"
else
  docker compose exec -T api python scripts/fetch_corpus.py || warn "语料下载失败，可手动上传 PDF 后重跑：docker compose exec api python scripts/index_cli.py build 'data/pdf/*.pdf'"
  docker compose exec -T api python scripts/index_cli.py build "data/pdf/*.pdf" || warn "建索引失败，见上方日志"
fi

# ---------- 6. 汇总 ----------
IP="$(curl -fsS --max-time 5 https://api.ipify.org || echo '<服务器IP>')"
say "6/6 部署完成"
cat <<EOF

访问地址：http://${IP}:${WEB_PORT}
评审账号：reviewer
评审密码：${REVIEWER_PWD}

首次自检（在服务器上跑）：
  cd ${APP_DIR} && docker compose exec -T api python scripts/check_deploy.py http://127.0.0.1:${WEB_PORT} --user reviewer --password '${REVIEWER_PWD}'

常用命令：
  docker compose logs -f api     # 看后端日志
  docker compose restart api     # 重启后端
  docker compose down            # 停止
  docker compose up -d           # 再启动

注意：
  - 安全组/防火墙需放行 ${WEB_PORT} 端口
  - 用 IP 访问不需要域名，也不需要 ICP 备案
  - 想绑定域名 + HTTPS：见仓库 docs/部署手册.md 的 Caddy 部分
EOF
