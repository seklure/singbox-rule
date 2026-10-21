#!/usr/bin/env python3
"""把 compatible-config.json 里的 link.onlysing.com 规则集地址，替换成本仓库的外链地址。

用法：
  python3 scripts/rewrite-config.py -i compatible-config.json -o compatible-config.jsdelivr.json
  python3 scripts/rewrite-config.py -i compatible-config.json -o out.json --base https://raw.githubusercontent.com/seklure/singbox-rule/main/ruleset

只做文本级替换，除 URL 外其余格式（缩进、顺序、注释）保持不变。
"""
import argparse
import re
import sys

RAW = "https://raw.githubusercontent.com/seklure/singbox-rule/main/ruleset"
JSD = "https://cdn.jsdelivr.net/gh/seklure/singbox-rule@main/ruleset"
PATTERN = re.compile(r"https://link\.onlysing\.com/get/singbox/ruleset/([A-Za-z0-9_.\-]+\.srs)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--base", default=JSD, help=f"新地址前缀，默认 {JSD}")
    args = ap.parse_args()

    text = open(args.input, encoding="utf-8").read()
    hits = PATTERN.findall(text)
    if not hits:
        print("未找到 link.onlysing.com 规则集地址，未生成文件", file=sys.stderr)
        return 1

    new_text, n = PATTERN.subn(lambda m: f"{args.base.rstrip('/')}/{m.group(1)}", text)
    open(args.output, "w", encoding="utf-8").write(new_text)

    uniq = sorted(set(hits))
    print(f"替换 {n} 处（去重后 {len(uniq)} 个文件）→ {args.output}")
    print(f"地址前缀：{args.base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
