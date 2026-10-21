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
- 只有内容真的变化时才覆盖 `.srs` 文件；`manifest.json` 的 `generated_at` 每次运行都会更新，因此正常情况下每天会有一个仅包含时间戳变化的提交，可作为“同步仍在正常工作”的心跳。提交信息形如 `chore: sync rulesets 2026-10-21 08:07 UTC`。
- 若某个上游文件 404 或返回内容不是合法 `.srs`（缺少 `SRS` 魔数），该文件不会被覆盖，job 标记失败以便提醒。

## 外链下载地址

两种等价写法（`main` 为分支名）：

| 方式 | 地址模板 | 说明 |
| --- | --- | --- |
| GitHub Raw | `https://raw.githubusercontent.com/seklure/singbox-rule/main/ruleset/<文件名>` | 官方直链，国内可能需要代理 |
| GitHub `/raw/` | `https://github.com/seklure/singbox-rule/raw/main/ruleset/<文件名>` | 会 302 跳转到上面那条 raw 地址，效果相同，多一跳 |
| jsDelivr | `https://cdn.jsdelivr.net/gh/seklure/singbox-rule@main/ruleset/<文件名>` | CDN 加速，国内一般可直连，适合直接写进配置 |

> ⚠️ **不要用网页上的 `/blob/main/...` 地址**（如 `https://github.com/seklure/singbox-rule/blob/main/ruleset/AI.srs`）。它返回的是 GitHub 文件查看器页面（`Content-Type: text/html`，约 200 KB 的 HTML），不是规则集本体，sing-box 拉下来会把 HTML 当 `.srs` 解析并报错。网页上对应「Download raw file」按钮的地址才是上面三种之一。


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

## 修改规则内容（`.srs` 不能直接文本编辑）

`.srs` 是编译产物：`SRS` + 1 字节版本号（本仓库全是 `2`）+ zlib 压缩的二进制域名匹配器。文本条目虽然以「长度前缀字符串」形式出现在解压后的尾部，但整体偏移由匹配器结构决定，**手改任何一个字节都会让整个文件失效**，所以不要用文本编辑器打开，也不要用 sed 之类去替换字符串。

正确姿势是官方工具链（sing-box 1.10+ 起提供）：

```bash
# 1) 二进制 → 可读 JSON（无损，见下方验证）
sing-box rule-set decompile ruleset/AI.srs -o custom/AI.json

# 2) 用任意编辑器改 custom/AI.json，加/删/改数组里的条目

# 3) JSON → 二进制（可选，需要外链 .srs 时）
sing-box rule-set compile custom/AI.json -o custom/AI.srs
```

> 验证过的无损性：`AI.srs` 反编译再编译，产物与原文件**字节完全一致**（527 字节，SHA256 `1e84897202c839cd…`）。本仓库 34 个 `.srs` 全部可以成功反编译。

`AI.srs` 的实际结构（1 条规则、45 个条目）：

| 字段 | 数量 | 含义 |
| --- | --- | --- |
| `domain` | 10 | 完整域名精确匹配，如 `chatgpt.com` 之外的 `ai.google.dev`、`api.groq.com` |
| `domain_suffix` | 32 | 后缀匹配，如 `openai.com`、`claude.ai`、`perplexity.ai`、`cursor.com` |
| `domain_keyword` | 3 | 关键词匹配，`anthropic`、`claude`、`openai` |

`custom/AI.json` 就是它的反编译副本，可直接编辑。

### 落地方式（三选一）

**A. 直接用 JSON 源格式外链（推荐，改完即生效，不用编译）**

配置里把该条目换成：

```json
{
  "tag": "AI",
  "type": "remote",
  "format": "source",
  "url": "https://cdn.jsdelivr.net/gh/seklure/singbox-rule@main/custom/AI.json",
  "http_client": "direct-http"
}
```

`.json` 结尾时 `format` 可省略（自动推断为 `source`）。改完 JSON 推送到仓库即可，sing-box 按 `update_interval`（默认 `1d`）重新拉取。

**B. 编译成 `.srs` 再外链（binary 格式，体积更小、加载更快）**

```bash
sing-box rule-set compile custom/AI.json -o custom/AI.srs
```

地址写 `.../custom/AI.srs`，`format` 写 `binary` 或省略。

**C. 不动任何文件，直接内联规则**

在 `compatible-config.json` 的 `route.rules` 里加一条内联规则（优先级高于 `rule_set`），可用于临时「抽走」或补充某个域名：

```json
{
  "domain_suffix": ["deepseek.com"],
  "outbound": "🚀 节点选择"
}
```

> 注意：`ruleset/` 下的文件每天会被同步覆盖，**自己的改动一律放 `custom/`**（`scripts/sync.sh` 只写 `ruleset/`）。

### 装 sing-box（用于 compile / decompile）

```bash
brew install sing-box
# 或从发布页下压缩包（国内可用镜像前缀 https://gh-proxy.com/ 加速）
curl -L -o sb.tar.gz "https://gh-proxy.com/https://github.com/SagerNet/sing-box/releases/download/v1.14.3/sing-box-1.14.3-darwin-arm64.tar.gz"
tar xzf sb.tar.gz && ./sing-box-1.14.3-darwin-arm64/sing-box version
```

## 新增 / 删除规则集

编辑 `urls.txt`（每行一个上游 URL，`#` 开头为注释），本地跑一次 `bash scripts/sync.sh` 即可。同步脚本以 URL 最后一段作为文件名。
