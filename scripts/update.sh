#!/usr/bin/env bash
# 一键更新：拉取最新代码 + 更新依赖 + 跑测试
# 用法（在项目根目录）：bash scripts/update.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> 拉取最新代码"
git pull

echo "==> 更新依赖"
.venv/bin/pip install -r requirements.txt

echo "==> 运行测试"
.venv/bin/python -m pytest -q

echo "✅ 更新完成"
