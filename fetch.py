"""下载 CCC 利差、BB 利差与纳指收盘，并入本地数据（只增补、不删旧历史）。

  CCC 利差  ICE BofA 美国 CCC 及以下高收益债 OAS（FRED: BAMLH0A3HYC，百分点）
  BB 利差   ICE BofA 美国 BB 级高收益债 OAS（FRED: BAMLH0A1HYBB，百分点）——只用来算 CCC−BB
  纳指      纳斯达克综合指数收盘（FRED: NASDAQCOM；备用 Yahoo ^IXIC）

每个序列按顺序试几个来源，第一个成功的为准，失败的原因全部记下来：
  1. FRED 官方 API —— 需要免费的 API key（环境变量 FRED_API_KEY，或同目录 fred_api_key.txt 里写一行）。
     这是 FRED 给程序用的正门，最稳；没有 key 就跳过。
  2. FRED 网页下载（fredgraph.csv）—— 不要 key，但对脚本请求时好时坏，有时直接断开。
  3. 纳指另有 Yahoo 图表接口兜底。两个利差都只有 FRED 一个免费来源。
本地连不上 FRED 时，还有一条路：GitHub 每日流水线在美国机房拉好数据提交进 data/，
本地双击「更新并打开.command」会先 git pull 拿到它（需要这个文件夹是 git clone 下来的）。

FRED 上 ICE 系列只给最近约 3 年，更早的部分来自仓库里的 data/。所以本地数据只增不减：
下载到的日期覆盖本地同日的值（FRED 偶尔修订），下载里没有的老日期原样保留。
  · 本地（默认）：data/ 只读，并入后写到 cache/（不进 git），git pull 不会冲突。
  · 流水线（--ci）：直接写回 data/，由 GitHub Actions 提交。
"""
import csv
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from signals import read_series, write_series

HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = {"ccc_oas": ["date", "ccc_oas_pct"], "bb_oas": ["date", "bb_oas_pct"], "nasdaq": ["date", "close"]}
FRED_ID = {"ccc_oas": "BAMLH0A3HYC", "bb_oas": "BAMLH0A1HYBB", "nasdaq": "NASDAQCOM"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
OVERLAP_DAYS = 120   # 每次往回多拉一段，接住修订
SEED_START = "2016-01-01"
MAX_JUMP = 0.25      # 同一天新旧值相差超过 25% 视为下错了数据，整次不并入
CONNECT_TIMEOUT, TIMEOUT, TRIES = 15, 45, 2


# ---------------- 网络 ----------------
def system_proxy():
    """浏览器走的系统代理（macOS 由 urllib 从系统设置里读出）。curl 默认不读系统设置，要手动传给它。"""
    try:
        p = urllib.request.getproxies()
    except Exception:  # noqa: BLE001
        return None
    return p.get("https") or p.get("http")


def _get(url, headers=None):
    """先 curl（macOS 证书最可靠），再 urllib；各试 TRIES 次。失败时报出每种方式最后一次的原因。"""
    h = {"User-Agent": UA, "Accept": "text/csv,application/json,text/plain,*/*", "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    errs = {}
    proxy = system_proxy()
    for k in range(TRIES):
        if shutil.which("curl"):
            cmd = ["curl", "-fsSL", "--compressed", "--connect-timeout", str(CONNECT_TIMEOUT), "-m", str(TIMEOUT)]
            for a, b in h.items():
                cmd += ["-H", "%s: %s" % (a, b)]
            if proxy and not any(os.environ.get(v) for v in ("https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")):
                cmd += ["-x", proxy]
            p = subprocess.run(cmd + [url], capture_output=True)
            if p.returncode == 0 and p.stdout:
                return p.stdout.decode("utf-8", "replace")
            errs["curl"] = "退出码 %d %s" % (p.returncode, p.stderr.decode("utf-8", "replace").strip()[:120])
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 —— 网络错误种类很多，统一记下来重试
            errs["urllib"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        if k + 1 < TRIES:
            time.sleep(3)
    raise RuntimeError("；".join("%s %s" % kv for kv in errs.items()) or "下载失败")


# ---------------- 各来源 ----------------
def fred_key():
    k = os.environ.get("FRED_API_KEY", "").strip()
    path = os.path.join(HERE, "fred_api_key.txt")
    if not k and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            k = fh.read().strip()
    return k if re.fullmatch(r"[0-9a-f]{32}", k or "") else None


def parse_fred(text):
    """FRED fredgraph.csv：首行表头（observation_date 或 DATE），之后 日期,值；缺失值为 '.' 或空。"""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2 or "date" not in rows[0][0].lower():
        raise RuntimeError("返回的不是 FRED 的 CSV（开头：%r）" % text[:60])
    out = {}
    for r in rows[1:]:
        if len(r) >= 2 and r[0][:4].isdigit():
            try:
                out[r[0][:10]] = float(r[1])
            except ValueError:
                pass
    if not out:
        raise RuntimeError("CSV 里没有任何数值")
    return out


def parse_fred_api(text):
    obs = json.loads(text).get("observations")
    if obs is None:
        raise RuntimeError("FRED API 返回里没有 observations（开头：%r）" % text[:80])
    out = {}
    for o in obs:
        try:
            out[o["date"]] = float(o["value"])
        except (KeyError, ValueError):
            pass
    if not out:
        raise RuntimeError("FRED API 没有返回任何数值")
    return out


def parse_yahoo(text, now=None):
    """Yahoo 图表接口 JSON → {日期: 收盘}。盘中那根还没收盘的 K 线丢掉。"""
    res = json.loads(text)["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    ts, close = res.get("timestamp") or [], res["indicators"]["quote"][0].get("close") or []
    out = {}
    for t, c in zip(ts, close):
        if c is not None:
            out[datetime.fromtimestamp(t + off, timezone.utc).strftime("%Y-%m-%d")] = float(c)
    reg = (res["meta"].get("currentTradingPeriod") or {}).get("regular") or {}
    now = now if now is not None else time.time()
    if reg.get("start") and reg.get("end") and reg["start"] <= now < reg["end"] + 900:
        out.pop(datetime.fromtimestamp(reg["start"] + off, timezone.utc).strftime("%Y-%m-%d"), None)
    if not out:
        raise RuntimeError("Yahoo 没有返回任何收盘价")
    return out


def src_fred_api(name, start):
    key = fred_key()
    if not key:
        return None
    q = urllib.parse.urlencode({"series_id": FRED_ID[name], "api_key": key, "file_type": "json", "observation_start": start})
    return parse_fred_api(_get("https://api.stlouisfed.org/fred/series/observations?" + q))


def src_fred_csv(name, start):
    sid = FRED_ID[name]
    return parse_fred(_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s&cosd=%s" % (sid, start),
                           {"Referer": "https://fred.stlouisfed.org/series/" + sid}))


def src_yahoo(name, start):
    p1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    p2 = int(time.time()) + 86400
    return parse_yahoo(_get("https://query1.finance.yahoo.com/v8/finance/chart/%%5EIXIC?period1=%d&period2=%d&interval=1d" % (p1, p2)))


SOURCES = {
    "ccc_oas": [("FRED API", src_fred_api), ("FRED 网页", src_fred_csv)],
    "bb_oas": [("FRED API", src_fred_api), ("FRED 网页", src_fred_csv)],
    "nasdaq": [("FRED API", src_fred_api), ("FRED 网页", src_fred_csv), ("Yahoo", src_yahoo)],
}


# ---------------- 合并 ----------------
def merge(old, new):
    """新数据并进旧数据。返回 (合并结果, 新增天数, 改动天数)；同日相差过大时抛错、不并入。"""
    for d, v in new.items():
        if d in old and old[d] and abs(v / old[d] - 1) > MAX_JUMP:
            raise RuntimeError("%s 新旧值差太多（%.4g → %.4g），疑似下错了序列，本次不并入" % (d, old[d], v))
    out = dict(old)
    added = sum(1 for d in new if d not in old)
    changed = sum(1 for d in new if d in old and abs(new[d] - old[d]) > 1e-9)
    out.update(new)
    return out, added, changed


def load_local(name):
    """data/（仓库存档）叠加 cache/（本地增量），同一天以 cache/ 为准。"""
    base = read_series(os.path.join(HERE, "data", name + ".csv"))
    base.update(read_series(os.path.join(HERE, "cache", name + ".csv")))
    return base


def update(ci=False, log=print):
    proxy = system_proxy()
    log("  系统代理：%s；FRED API key：%s" % (proxy or "无", "有" if fred_key() else "无（可选，见 README）"))
    status = {}
    for name in SOURCES:
        local = load_local(name)
        last = max(local) if local else None
        start = (date.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)).isoformat() if last else SEED_START
        st = {"series": FRED_ID[name], "local_last": last, "tried": {}}
        for label, fn in SOURCES[name]:
            try:
                new = fn(name, start)
                if new is None:
                    continue
                merged, added, changed = merge(local, new)
            except Exception as e:  # noqa: BLE001
                key = fred_key()
                st["tried"][label] = str(e).replace(key, "***") if key else str(e)
                continue
            write_series(os.path.join(HERE, "data" if ci else "cache", name + ".csv"), merged, HEADER[name])
            st.update(ok=True, source=label, last=max(merged), added=added, changed=changed, src_last=max(new))
            log("  %-10s 成功（%s）：最新 %s，新增 %d 天、修订 %d 天" % (FRED_ID[name], label, max(new), added, changed))
            break
        else:
            st.update(ok=False, last=last, error="；".join("%s：%s" % kv for kv in st["tried"].items()))
            log("  %-10s 失败，沿用本地数据（最新 %s）" % (FRED_ID[name], last))
            for label, e in st["tried"].items():
                log("      %s → %s" % (label, e))
        status[name] = st
    return status


if __name__ == "__main__":
    import sys
    update(ci="--ci" in sys.argv)
