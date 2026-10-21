#!/usr/bin/env python3
"""纯 Python 解析 sing-box 规则集（.srs），不依赖 sing-box 可执行文件。

用法：
    python3 scripts/srs-dump.py ruleset/AI.srs              # 打印 JSON 到 stdout
    python3 scripts/srs-dump.py ruleset/AI.srs -o AI.json    # 写文件
    python3 scripts/srs-dump.py https://.../AI.srs           # 直接从 URL 解析
    python3 scripts/srs-dump.py ruleset/AI.srs --summary     # 只看摘要
    python3 scripts/srs-dump.py ruleset/*.srs --summary      # 批量摘要

支持版本：1 / 2 / 3 / 4 / 5（版本号只决定允许出现哪些条目，读取结构一致）。
输出结构等价于 `sing-box rule-set decompile`（单元素数组会被折叠成标量，与官方一致）。

格式速查：
    "SRS" + 1 字节版本 + zlib( uvarint 规则数 + 规则... )
    规则 = 1 字节类型（0 普通 / 1 逻辑）；
      普通规则 = 若干「条目类型 + 载荷」，以 0xFF 结束，后跟 1 字节 invert；
      逻辑规则 = 1 字节目录（0=and,1=or）+ uvarint 子规则数 + 子规则 + 1 字节 invert。
    域名条目载荷 = succinct 域名树（leaves/labelBitmap/labels 三段）。
"""

import argparse
import ipaddress
import json
import sys
import urllib.request
import zlib

MAGIC = b"SRS"

# 条目类型编号，顺序与 sing-box common/srs/binary.go 中的 iota 一致
ITEM_QUERY_TYPE = 0
ITEM_NETWORK = 1
ITEM_DOMAIN = 2
ITEM_DOMAIN_KEYWORD = 3
ITEM_DOMAIN_REGEX = 4
ITEM_SOURCE_IP_CIDR = 5
ITEM_IP_CIDR = 6
ITEM_SOURCE_PORT = 7
ITEM_SOURCE_PORT_RANGE = 8
ITEM_PORT = 9
ITEM_PORT_RANGE = 10
ITEM_PROCESS_NAME = 11
ITEM_PROCESS_PATH = 12
ITEM_PACKAGE_NAME = 13
ITEM_WIFI_SSID = 14
ITEM_WIFI_BSSID = 15
ITEM_ADGUARD_DOMAIN = 16
ITEM_PROCESS_PATH_REGEX = 17
ITEM_NETWORK_TYPE = 18
ITEM_NETWORK_IS_EXPENSIVE = 19
ITEM_NETWORK_IS_CONSTRAINED = 20
ITEM_NETWORK_INTERFACE_ADDRESS = 21
ITEM_DEFAULT_INTERFACE_ADDRESS = 22
ITEM_PACKAGE_NAME_REGEX = 23
ITEM_FINAL = 0xFF

PREFIX_LABEL = "\r"   # 仅匹配子域（domain_suffix 以 . 开头）
ROOT_LABEL = "\n"     # 按后缀匹配


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def u8(self) -> int:
        if self.pos + 1 > len(self.data):
            raise EOFError("读越界：无法读取 1 字节")
        v = self.data[self.pos]
        self.pos += 1
        return v

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise EOFError(f"读越界：需要 {n} 字节，仅剩 {len(self.data) - self.pos}")
        v = self.data[self.pos:self.pos + n]
        self.pos += n
        return v

    def uvarint(self) -> int:
        result = 0
        shift = 0
        while True:
            b = self.u8()
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7
            if shift > 63:
                raise ValueError("uvarint 过长")

    def str_list(self):
        return [self.take(self.uvarint()).decode("utf-8", "replace") for _ in range(self.uvarint())]

    def uint16_list(self):
        return [int.from_bytes(self.take(2), "big") for _ in range(self.uvarint())]

    def uint8_list(self):
        return list(self.take(self.uvarint()))

    def uint64_list(self):
        return [int.from_bytes(self.take(8), "big") for _ in range(self.uvarint())]


# --------------------------------------------------------------------------
# succinct 域名树（对应 SagerNet/sing common/domain 的 succinctSet）
# --------------------------------------------------------------------------

class SuccinctSet:
    def __init__(self, leaves, label_bitmap, labels):
        self.leaves = leaves
        self.bitmap = label_bitmap
        self.labels = labels
        ranks = []
        ones = []
        n = 0
        for wi, w in enumerate(label_bitmap):
            ranks.append(n)
            if w:
                base = wi << 6
                x = w
                while x:
                    low = x & -x
                    ones.append(base + (low.bit_length() - 1))
                    x ^= low
                n += w.bit_count()
        self.ranks = ranks
        self.ones = ones

    @staticmethod
    def _bit(words, i):
        wi = i >> 6
        if wi >= len(words):
            return 0
        return (words[wi] >> (i & 63)) & 1

    def _rank(self, i: int) -> int:
        """前 i 位中 1 的个数"""
        wi, off = i >> 6, i & 63
        if wi >= len(self.bitmap):
            return len(self.ones)
        return self.ranks[wi] + (self.bitmap[wi] & ((1 << off) - 1)).bit_count()

    def _zeros(self, i: int) -> int:
        return i - self._rank(i)

    def keys(self):
        """按 Go 版 keys() 的遍历逻辑还原全部 key（已反转的域名字节串）"""
        result = []
        cur = bytearray()
        if self._bit(self.leaves, 0):
            result.append(b"")
        stack = [[0, 0]]  # [nodeId, bmIdx]
        while stack:
            node_id, bm_idx = stack[-1]
            if self._bit(self.bitmap, bm_idx):
                stack.pop()
                if stack:
                    del cur[-1:]
                    stack[-1][1] += 1
                continue
            cur.append(self.labels[bm_idx - node_id])
            next_node = self._zeros(bm_idx + 1)
            next_bm = self.ones[next_node - 1] + 1
            if self._bit(self.leaves, next_node):
                result.append(bytes(cur))
            stack.append([next_node, next_bm])
        return result


def read_succinct_set(r: Reader) -> SuccinctSet:
    r.u8()                       # 结构版本号，恒为 0
    leaves = r.uint64_list()
    bitmap = r.uint64_list()
    labels = r.take(r.uvarint())
    return SuccinctSet(leaves, bitmap, labels)


def reverse_domain(s: str) -> str:
    return s[::-1]


def dump_matcher(ss: SuccinctSet):
    """还原出 (domain, domain_suffix) 两个列表，等价于 Go 的 Matcher.Dump()"""
    domain_map = {}
    prefix_map = {}
    prefix_list = []
    for raw in ss.keys():
        key = reverse_domain(raw.decode("utf-8", "replace"))
        head = key[0] if key else ""
        if head == PREFIX_LABEL:
            prefix_map[key[1:]] = True
        elif head == ROOT_LABEL:
            prefix_list.append(key[1:])
        else:
            domain_map[key] = True
    for raw_prefix in prefix_map:
        if raw_prefix.startswith("."):
            root_domain = raw_prefix[1:]
            if root_domain in domain_map:
                del domain_map[root_domain]
                prefix_list.append(root_domain)
                continue
        prefix_list.append(raw_prefix)
    return sorted(domain_map), sorted(prefix_list)


# --------------------------------------------------------------------------
# IP 集合
# --------------------------------------------------------------------------

def _merge_ranges(ranges):
    ranges = sorted(ranges, key=lambda t: (t[0], t[1]))
    merged = []
    for lo, hi in ranges:
        if merged and lo <= merged[-1][1] + 1:
            if hi > merged[-1][1]:
                merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return merged


def _range_to_prefixes(lo: int, hi: int, bits: int):
    """把 [lo, hi] 整数区间拆成 CIDR 前缀"""
    out = []
    while lo <= hi:
        # 能覆盖的最大块：受对齐与剩余长度限制
        max_size = (lo & -lo).bit_length() - 1 if lo else bits
        remaining = (hi - lo + 1).bit_length() - 1
        size = min(max_size, remaining, bits)
        out.append((lo, bits - size))
        lo += 1 << size
    return out


def read_ip_set(r: Reader):
    version = r.u8()
    if version != 1:
        raise ValueError(f"不支持的 ipset 版本 {version}")
    count = int.from_bytes(r.take(8), "big")
    r4, r6 = [], []
    for _ in range(count):
        from_bytes = r.take(r.uvarint())
        to_bytes = r.take(r.uvarint())
        if len(from_bytes) != len(to_bytes):
            raise ValueError("IP 区间两端地址长度不一致")
        if len(from_bytes) == 4:
            r4.append((int.from_bytes(from_bytes, "big"), int.from_bytes(to_bytes, "big")))
        else:
            r6.append((int.from_bytes(from_bytes, "big"), int.from_bytes(to_bytes, "big")))
    prefixes = []
    for lo, hi in _merge_ranges(r4):
        for addr, plen in _range_to_prefixes(lo, hi, 32):
            prefixes.append(f"{ipaddress.IPv4Address(addr)}/{plen}")
    for lo, hi in _merge_ranges(r6):
        for addr, plen in _range_to_prefixes(lo, hi, 128):
            prefixes.append(f"{ipaddress.IPv6Address(addr)}/{plen}")
    return prefixes


# --------------------------------------------------------------------------
# 规则解析
# --------------------------------------------------------------------------

class SrsRuleSet:
    def __init__(self, version: int, rules: list):
        self.version = version
        self.rules = rules

    def to_dict(self):
        obj = {"version": self.version}
        if self.rules:
            obj["rules"] = self.rules
        return obj


def _collapse(value):
    """单元素数组折叠成标量，贴近 sing-box 的 JSON 输出风格"""
    if isinstance(value, list) and len(value) == 1:
        return value[0]
    return value


def read_default_rule(r: Reader) -> dict:
    rule = {}
    while True:
        item = r.u8()
        if item == ITEM_FINAL:
            if r.u8():
                rule["invert"] = True
            return rule
        elif item == ITEM_QUERY_TYPE:
            rule["query_type"] = _collapse(r.uint16_list())
        elif item == ITEM_NETWORK:
            rule["network"] = _collapse(r.str_list())
        elif item == ITEM_DOMAIN:
            domains, suffixes = dump_matcher(read_succinct_set(r))
            if domains:
                rule["domain"] = _collapse(domains)
            if suffixes:
                rule["domain_suffix"] = _collapse(suffixes)
        elif item == ITEM_DOMAIN_KEYWORD:
            rule["domain_keyword"] = _collapse(r.str_list())
        elif item == ITEM_DOMAIN_REGEX:
            rule["domain_regex"] = _collapse(r.str_list())
        elif item == ITEM_SOURCE_IP_CIDR:
            rule["source_ip_cidr"] = _collapse(read_ip_set(r))
        elif item == ITEM_IP_CIDR:
            rule["ip_cidr"] = _collapse(read_ip_set(r))
        elif item == ITEM_SOURCE_PORT:
            rule["source_port"] = _collapse(r.uint16_list())
        elif item == ITEM_SOURCE_PORT_RANGE:
            rule["source_port_range"] = _collapse(r.str_list())
        elif item == ITEM_PORT:
            rule["port"] = _collapse(r.uint16_list())
        elif item == ITEM_PORT_RANGE:
            rule["port_range"] = _collapse(r.str_list())
        elif item == ITEM_PROCESS_NAME:
            rule["process_name"] = _collapse(r.str_list())
        elif item == ITEM_PROCESS_PATH:
            rule["process_path"] = _collapse(r.str_list())
        elif item == ITEM_PROCESS_PATH_REGEX:
            rule["process_path_regex"] = _collapse(r.str_list())
        elif item == ITEM_PACKAGE_NAME:
            rule["package_name"] = _collapse(r.str_list())
        elif item == ITEM_PACKAGE_NAME_REGEX:
            rule["package_name_regex"] = _collapse(r.str_list())
        elif item == ITEM_WIFI_SSID:
            rule["wifi_ssid"] = _collapse(r.str_list())
        elif item == ITEM_WIFI_BSSID:
            rule["wifi_bssid"] = _collapse(r.str_list())
        elif item == ITEM_NETWORK_TYPE:
            rule["network_type"] = _collapse(r.uint8_list())
        elif item == ITEM_NETWORK_IS_EXPENSIVE:
            rule["network_is_expensive"] = True
        elif item == ITEM_NETWORK_IS_CONSTRAINED:
            rule["network_is_constrained"] = True
        elif item in (ITEM_NETWORK_INTERFACE_ADDRESS, ITEM_DEFAULT_INTERFACE_ADDRESS):
            raise NotImplementedError(
                "network_interface_address / default_interface_address 暂未支持（v4+ 的接口地址规则，实际极少使用）")
        elif item == ITEM_ADGUARD_DOMAIN:
            raise NotImplementedError(
                "adguard_domain 条目暂未支持（AdGuard 规则集专用结构）")
        else:
            raise ValueError(f"未知条目类型 {item}（文件可能已损坏或版本不兼容）")


def read_rule(r: Reader, depth: int = 0) -> dict:
    if depth > 100:
        raise ValueError("逻辑规则嵌套过深")
    rule_type = r.u8()
    if rule_type == 0:
        return read_default_rule(r)
    if rule_type == 1:
        mode = r.u8()
        if mode not in (0, 1):
            raise ValueError(f"未知逻辑模式 {mode}")
        count = r.uvarint()
        rule = {"type": "logical", "mode": "and" if mode == 0 else "or",
                "rules": [read_rule(r, depth + 1) for _ in range(count)]}
        if r.u8():
            rule["invert"] = True
        return rule
    raise ValueError(f"未知规则类型 {rule_type}")


def parse_srs(data: bytes) -> SrsRuleSet:
    if len(data) < 5 or data[:3] != MAGIC:
        raise ValueError("不是合法的 sing-box 规则集（缺少 SRS 魔数）")
    version = data[3]
    if version > 5:
        raise ValueError(f"不支持的规则集版本 {version}")
    body = zlib.decompress(data[4:])
    r = Reader(body)
    count = r.uvarint()
    rules = [read_rule(r) for _ in range(count)]
    return SrsRuleSet(version, rules)


# --------------------------------------------------------------------------
# 摘要输出
# --------------------------------------------------------------------------

def summarize(rs: SrsRuleSet) -> str:
    lines = [f"version={rs.version}  规则数={len(rs.rules)}"]
    for idx, rule in enumerate(rs.rules):
        counts = []
        for key, value in rule.items():
            if isinstance(value, list):
                counts.append(f"{key}×{len(value)}")
            elif isinstance(value, str):
                counts.append(f"{key}×1")
            elif isinstance(value, bool) and value:
                counts.append(key)
        lines.append(f"  rule[{idx}] " + (" ".join(counts) if counts else "(空规则)"))
        for key in ("domain", "domain_suffix", "domain_keyword", "ip_cidr"):
            value = rule.get(key)
            if isinstance(value, str):
                value = [value]
            if isinstance(value, list) and value:
                sample = ", ".join(str(v) for v in value[:3])
                more = " …" if len(value) > 3 else ""
                lines.append(f"      {key}: {sample}{more}")
    return "\n".join(lines)


def load(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": "srs-dump/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    with open(source, "rb") as fh:
        return fh.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="解析 sing-box .srs 规则集（纯 Python）")
    parser.add_argument("source", nargs="+", help="本地文件路径或 http(s) URL")
    parser.add_argument("-o", "--output", help="输出 JSON 文件（仅单个输入时可用）")
    parser.add_argument("--summary", action="store_true", help="只输出摘要")
    parser.add_argument("--indent", type=int, default=2, help="JSON 缩进，默认 2")
    args = parser.parse_args()

    if args.output and len(args.source) > 1:
        parser.error("-o 只能配合单个输入使用")

    exit_code = 0
    for source in args.source:
        try:
            rs = parse_srs(load(source))
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {source}: {exc}", file=sys.stderr)
            exit_code = 1
            continue
        text = summarize(rs) if args.summary else json.dumps(
            rs.to_dict(), ensure_ascii=False, indent=args.indent)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"[完成] {source} → {args.output}")
        else:
            if len(args.source) > 1:
                print(f"===== {source}")
            print(text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
