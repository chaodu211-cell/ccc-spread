"""从 FRED 下载 CCC 利差与纳指收盘，并入本地数据（只增补、不删旧历史）。

  BAMLH0A3HYC  ICE BofA 美国 CCC 及以下高收益债期权调整利差（OAS，百分点）
  NASDAQCOM    纳斯达克综合指数收盘

FRED 上 ICE 系列只给最近约 3 年，更早的部分来自仓库里的 data/（种子取自 JustHodl 保存的 FRED 历史存档）。
所以本地数据只增不减：下载到的日期覆盖本地同日的值（FRED 偶尔修订），下载里没有的老日期原样保留。

两种写法：
  · 本地（默认）：data/ 只读，并入后写到 cache/（不进 git）。这样本地更新不会弄脏工作区，
    `git pull` 拿到 GitHub 每日流水线更新过的 data/ 时不会冲突。
  · 流水线（--ci）：直接写回 data/，由 GitHub Actions 提交。
"""
import csv
import io
import os
import shutil
import ssl
import subprocess
import time
import urllib.request
from datetime import date, timedelta

from signals import read_series, write_series

HERE = os.path.dirname(os.path.abspath(__file__))
SERIES = {"ccc_oas": "BAMLH0A3HYC", "nasdaq": "NASDAQCOM"}
HEADER = {"ccc_oas": ["date", "ccc_oas_pct"], "nasdaq": ["date", "close"]}
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
OVERLAP_DAYS = 120   # 每次往回多拉一段，接住 FRED 的修订
SEED_START = "2016-01-01"
MAX_JUMP = 0.25      # 同一天新旧值相差超过 25% 视为下错了数据，整次不并入


def _get(url, tries=3):
    err = None
    for k in range(tries):
        if shutil.which("curl"):
            p = subprocess.run(["curl", "-fsSL", "-m", "60", "-A", UA, url], capture_output=True)
            if p.returncode == 0 and p.stdout:
                return p.stdout.decode("utf-8", "replace")
            err = "curl 退出码 %d：%s" % (p.returncode, p.stderr.decode("utf-8", "replace").strip()[:200])
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 —— 网络错误种类很多，统一记下来重试
            err = "%s：%s" % (type(e).__name__, e)
        time.sleep(2 * (k + 1))
    raise RuntimeError(err or "下载失败")


def parse_fred(text):
    """FRED fredgraph.csv：首行表头（observation_date 或 DATE），之后 日期,值；缺失值为 '.' 或空。"""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2 or "date" not in rows[0][0].lower():
        raise RuntimeError("返回的不是 FRED 的 CSV（开头：%r）" % text[:80])
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
    status = {}
    for name, sid in SERIES.items():
        local = load_local(name)
        last = max(local) if local else None
        start = (date.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)).isoformat() if last else SEED_START
        st = {"series": sid, "local_last": last}
        try:
            new = parse_fred(_get(URL.format(sid=sid, start=start)))
            merged, added, changed = merge(local, new)
            out = os.path.join(HERE, "data" if ci else "cache", name + ".csv")
            write_series(out, merged, HEADER[name])
            st.update(ok=True, last=max(merged), added=added, changed=changed, fred_last=max(new))
            log("  %-10s %s：FRED 最新 %s，新增 %d 天、修订 %d 天" % (sid, "成功", max(new), added, changed))
        except Exception as e:  # noqa: BLE001
            st.update(ok=False, last=last, error=str(e))
            log("  %-10s 失败：%s（沿用本地数据，最新 %s）" % (sid, e, last))
        status[name] = st
    return status


if __name__ == "__main__":
    import sys
    update(ci="--ci" in sys.argv)
