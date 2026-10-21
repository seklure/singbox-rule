#!/usr/bin/env bash
# 按 urls.txt 从上游拉取全部 sing-box rule-set，写入 ruleset/
# 用法：bash scripts/sync.sh
# 退出码：0 全部成功；1 有文件下载失败或校验不通过（便于 Actions 报警）
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIST="$ROOT/urls.txt"
OUT="$ROOT/ruleset"
UA="Mozilla/5.0 (compatible; singbox-rule-sync/1.0; +https://github.com/seklure/singbox-rule)"

mkdir -p "$OUT"

total=0; ok=0; changed=0; failed=0
failed_list=()

while IFS= read -r url || [ -n "$url" ]; do
  url="${url%$'\r'}"                       # 去掉 CRLF 残留
  case "$url" in ''|'#'*) continue ;; esac
  total=$((total + 1))

  name="${url##*/}"
  tmp="$OUT/.${name}.part"

  if curl -fsSL --retry 3 --retry-delay 3 --retry-all-errors --max-time 120 \
        -A "$UA" -o "$tmp" "$url" \
     && [ "$(head -c 3 "$tmp" 2>/dev/null)" = "SRS" ]; then   # .srs 魔数校验
    if [ -f "$OUT/$name" ] && cmp -s "$tmp" "$OUT/$name"; then
      rm -f "$tmp"
    else
      mv "$tmp" "$OUT/$name"
      changed=$((changed + 1))
      echo "  updated  $name"
    fi
    ok=$((ok + 1))
  else
    rm -f "$tmp"
    failed=$((failed + 1))
    failed_list+=("$name")
    echo "  FAILED   $name <- $url"
  fi
done < "$LIST"

echo "-----------------------------------------------"
echo "共 ${total} 个 | 成功 ${ok} | 内容更新 ${changed} | 失败 ${failed}"
if [ "$failed" -gt 0 ]; then
  echo "失败清单：${failed_list[*]}"
  echo "::error::${failed} 个规则集下载失败"
  exit 1
fi
