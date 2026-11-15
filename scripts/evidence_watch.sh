#!/usr/bin/env bash
# 证源 Evidence —— 服务器安全巡检
#
# 背景：2026-11-14 这台机器被 React2Shell（CVE-2025-55182）打穿，植入 Dusk 挖矿木马，
# 做了 cron.d / init.d / systemd / root crontab 四重持久化。虽然已升级 Next.js 修复版
# 并重装加固，但"被入侵过"的经历值得一份每日巡检，而不是靠人想起来才查。
#
# 由 evidence-watch.timer 每 15 分钟调用一次：
#   * 结果追加到 /var/log/evidence-watch.log（保留最近 2000 行）
#   * 发现异常时写 /run/EVIDENCE_ALERT 并记 auth.alert 级别日志
#
# 手动查看：sudo tail -n 40 /var/log/evidence-watch.log
# 有无告警：ls /run/EVIDENCE_ALERT
set -uo pipefail

LOG=/var/log/evidence-watch.log
ALERT=/run/EVIDENCE_ALERT
FINDINGS=()

note() { FINDINGS+=("$1"); }

# 1. 已知木马的落地位置与命名
for p in /var/lib/.net /tmp/.net /tmp/DUSKNET.ONTOPDUSKBOT /tmp/.net-helper215.pid; do
  [[ -e "$p" ]] && note "发现木马路径：$p"
done

# 2. 疑似持久化项
for f in /etc/cron.d/* /etc/init.d/* /etc/systemd/system/*.service; do
  [[ -f "$f" ]] || continue
  if grep -qE '/var/lib/\.net|net-helper|DUSKNET' "$f" 2>/dev/null; then
    note "持久化命中：$f"
  fi
done

# 3. root crontab
if crontab -l 2>/dev/null | grep -qE '\.net|net-helper|logic\.sh'; then
  note "root crontab 含可疑条目"
fi

# 4. web 根目录下的可执行/未知文件（上次木马就写在 web/ 里）
if [[ -d /opt/evidence/web ]]; then
  while IFS= read -r f; do
    note "web 目录可疑文件：$f"
  done < <(find /opt/evidence/web -maxdepth 1 -type f \
             \( -name "*.dusk" -o -name "*.sh" -o -name "*.elf" \) 2>/dev/null)
fi

# 5. 可疑进程（ftp 外联、.net 可执行、logic.sh）
if ps -eo args 2>/dev/null | grep -qE 'ftp -n [0-9]|/var/lib/\.net/\.a|/tmp/logic\.sh'; then
  note "可疑进程在运行"
fi

# 6. 对外监听端口必须只有 22 与 3000
#    例外：53 是 systemd-resolved 的本地域名解析桩（127.0.0.53），属系统自带；
#    8000 是后端，必须绑在 127.0.0.1，不允许对外。
LISTEN=$(ss -lntH 2>/dev/null | awk '{print $4}' | grep -oE ':[0-9]+$' | tr -d ':' | sort -u)
for port in $LISTEN; do
  case "$port" in
    22|3000|8000|53) ;;
    *) note "意外监听端口：$port" ;;
  esac
done
if ss -lntH 2>/dev/null | grep -q ':8000 ' && ! ss -lntH 2>/dev/null | grep -q '127.0.0.1:8000'; then
  note "后端 8000 未绑定在 127.0.0.1"
fi
# 公开监听面（非 loopback）只允许 22 与 3000
PUBLIC=$(ss -lntH 2>/dev/null | awk '{print $4}' | grep -vE '^(127\.|\[::1\]|::1)' | grep -oE ':[0-9]+$' | tr -d ':' | sort -u)
for port in $PUBLIC; do
  case "$port" in
    22|3000) ;;
    *) note "公网监听端口异常：$port" ;;
  esac
done

# 7. Next.js 版本必须仍是修复版
NEXT_VER=$(node -e "try{console.log(require('/opt/evidence/web/node_modules/next/package.json').version)}catch(e){console.log('missing')}" 2>/dev/null)
case "$NEXT_VER" in
  15.5.7|15.5.8|15.5.9|15.6.*|16.0.7|16.0.8|16.0.9|16.1.*|17.*) ;;
  *) note "Next.js 版本异常（$NEXT_VER），应 >= 15.5.7" ;;
esac

# 8. authorized_keys 是否被改（基线在安装时写入）
BASE=/var/lib/evidence-watch/authorized_keys.sha256
if [[ -f "$BASE" ]]; then
  CUR=$(cat /home/ubuntu/.ssh/authorized_keys /root/.ssh/authorized_keys 2>/dev/null | sha256sum | cut -d' ' -f1)
  [[ "$CUR" != "$(cat "$BASE")" ]] && note "authorized_keys 与基线不一致"
fi

# 9. 服务状态
for svc in evidence-api evidence-web; do
  systemctl is-active --quiet "$svc" || note "服务未运行：$svc"
done

# ---------- 输出 ----------
TS=$(date '+%F %T')
if [[ ${#FINDINGS[@]} -eq 0 ]]; then
  echo "$TS OK next=$NEXT_VER listen=$(echo $LISTEN | tr '\n' ' ')" >> "$LOG"
  [[ -f "$ALERT" ]] && rm -f "$ALERT"
else
  {
    echo "$TS ALERT count=${#FINDINGS[@]}"
    for f in "${FINDINGS[@]}"; do echo "  - $f"; done
  } >> "$LOG"
  printf '%s\n' "${FINDINGS[@]}" > "$ALERT"
  logger -p auth.alert -t evidence-watch "发现 ${#FINDINGS[@]} 项异常，详见 $LOG"
fi

# 只保留最近 2000 行，避免撑爆 40G 小盘
if [[ $(wc -l < "$LOG" 2>/dev/null || echo 0) -gt 2000 ]]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

exit 0
