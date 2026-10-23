#!/bin/bash
# 双击我：从 FRED 下载最新 CCC 利差与纳指 → 重算见顶 / 见底预警 → 打开网页
#
# 只用 macOS 自带的 python3 与 curl，不需要安装任何依赖。
# 如果这个文件夹是 git clone 下来的、并且配了远端，会先顺手 git pull 一下（拿代码更新与存档数据），
# 拉不下来也不影响后面的步骤。

cd "$(dirname "$0")" || { echo "无法进入脚本所在目录"; exit 1; }

die() {
  echo
  echo "────────────────────────────────────────"
  echo "❌ $*"
  echo "────────────────────────────────────────"
  echo
  read -n 1 -s -r -p "按任意键关闭此窗口…"
  echo
  exit 1
}

echo "════════════════════════════════════════"
echo "  CCC 垃圾债利差 · 见顶 / 见底预警 · 更新并打开"
echo "  目录：$(pwd)"
echo "════════════════════════════════════════"
echo

# ---------- 0. 解除 macOS 隔离标记 ----------
xattr -dr com.apple.quarantine . 2>/dev/null || true

# ---------- 1. 找 python3 ----------
PY="$(command -v python3 2>/dev/null)"
[ -n "$PY" ] || die "找不到 python3。
   macOS 自带的命令行工具里就有，装一下即可：
       xcode-select --install
   装完重新双击本文件。"
echo "Python：${PY}（$("${PY}" -V 2>&1)）"

# ---------- 2. 若是 git 仓库，先同步 ----------
if [ -d .git ] && command -v git >/dev/null 2>&1 && git remote get-url origin >/dev/null 2>&1; then
  echo "同步 GitHub 仓库…"
  if git pull --ff-only --quiet 2>/dev/null; then
    echo "   已是最新"
  else
    echo "   同步失败（没网、没权限或本地有改动），继续用本地版本"
  fi
fi
echo

# ---------- 3. 下载 + 重算 ----------
set -o pipefail
"${PY}" update.py 2>&1 | tee run.log
STATUS=$?
set +o pipefail
echo "────────────────────────────────────────"
[ "${STATUS}" -eq 0 ] || die "更新失败（退出码 ${STATUS}）。
   上面的日志里有具体原因，也存在同目录的 run.log 里。"

# ---------- 4. 打开网页 ----------
[ -f dashboard.html ] || die "没有生成 dashboard.html，请把 run.log 的内容发出来排查。"
echo
echo "正在打开网页…"
open dashboard.html 2>/dev/null || die "网页生成好了但打不开，手动双击同目录下的 dashboard.html 即可。"

echo
echo "✅ 完成。此窗口可以关掉了。"
echo
read -n 1 -s -r -t 20 -p "按任意键关闭（20 秒后自动关闭）…"
echo
