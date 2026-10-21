# singbox-rule

sing-box 远程规则集（`.srs`）镜像仓库。每天由 GitHub Actions 从上游自动同步一次，内容保持与原站一致（二进制原样保存）。

## 目录结构

```
.
├── .github/workflows/sync-rules.yml   # 每日定时同步 workflow
├── scripts/
│   ├── sync.sh                        # 下载 + 魔数校验（SRS）
│   └── make_manifest.py               # 生成 manifest.json
├── ruleset/                           # 34 个 .srs 规则集
├── urls.txt                           # 上游源地址清单（新增规则集只需加一行）
├── manifest.json                      # 文件名 / 大小 / SHA256 / 下载地址
└── README.md
```

## 定时同步

- 频率：每天一次，北京时间 **04:17**（UTC `17 20 * * *`）。
- 触发方式：定时 + 手动（Actions 页面 → Sync sing-box rulesets → Run workflow）。
- 只有内容真的变化时才产生提交，提交信息形如 `chore: sync rulesets 2026-10-21 08:02 UTC`。
- 若某个上游文件 404 或返回内容不是合法 `.srs`（缺少 `SRS` 魔数），该文件不会被覆盖，job 标记失败以便提醒。

## 外链下载地址

两种等价写法（`main` 为分支名）：

| 方式 | 地址模板 | 说明 |
| --- | --- | --- |
| GitHub Raw | `https://raw.githubusercontent.com/seklure/singbox-rule/main/ruleset/<文件名>` | 官方直链，国内可能需要代理 |
| jsDelivr | `https://cdn.jsdelivr.net/gh/seklure/singbox-rule@main/ruleset/<文件名>` | CDN 加速，国内一般可直连，适合直接写进配置 |

示例：

```
https://raw.githubusercontent.com/seklure/singbox-rule/main/ruleset/BanAD.srs
https://cdn.jsdelivr.net/gh/seklure/singbox-rule@main/ruleset/BanAD.srs
```

完整清单见 `manifest.json` 中每个文件的 `raw` / `jsdelivr` 字段。

> 注意：jsDelivr 对文件有缓存（通常数小时），上游刚同步完成时可能读到旧版本；需要立即生效可改用 GitHub Raw，或在 URL 后加 `?t=时间戳` 破缓存（sing-box 的 `url` 字段允许带查询参数）。

## 本地手动同步

```bash
bash scripts/sync.sh              # 下载全部规则集
python3 scripts/make_manifest.py  # 重建 manifest.json
git add -A && git commit -m "sync" && git push
```

## 把配置里的旧地址换成本仓库地址

```bash
# 换成 jsDelivr CDN 地址（国内直连更稳）
python3 scripts/rewrite-config.py -i compatible-config.json -o compatible-config.jsdelivr.json

# 换成 GitHub Raw 地址
python3 scripts/rewrite-config.py -i compatible-config.json -o compatible-config.github.json \
  --base https://raw.githubusercontent.com/seklure/singbox-rule/main/ruleset
```

脚本只替换 `link.onlysing.com/get/singbox/ruleset/*.srs` 这类 URL，其余内容与格式原样保留。

## 新增 / 删除规则集

编辑 `urls.txt`（每行一个上游 URL，`#` 开头为注释），本地跑一次 `bash scripts/sync.sh` 即可。同步脚本以 URL 最后一段作为文件名。
