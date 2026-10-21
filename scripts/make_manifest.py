#!/usr/bin/env python3
"""生成 manifest.json —— 记录每个规则集的大小、SHA256 与可直接外链的下载地址。"""
import hashlib
import json
import pathlib
import subprocess
import datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "ruleset"
REPO = "seklure/singbox-rule"


def main() -> None:
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        branch = "main"
    if branch in ("", "HEAD"):
        branch = "main"

    files = []
    for path in sorted(OUT.glob("*.srs")):
        data = path.read_bytes()
        files.append(
            {
                "name": path.name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "raw": f"https://raw.githubusercontent.com/{REPO}/{branch}/ruleset/{path.name}",
                "jsdelivr": f"https://cdn.jsdelivr.net/gh/{REPO}@{branch}/ruleset/{path.name}",
            }
        )

    manifest = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "branch": branch,
        "count": len(files),
        "total_size": sum(f["size"] for f in files),
        "files": files,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"manifest.json 已生成：{len(files)} 个文件，共 {manifest['total_size']} 字节")


if __name__ == "__main__":
    main()
