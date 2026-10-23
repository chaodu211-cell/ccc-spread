"""CCC 利差技术面见顶 / 见底预警：指标、信号与事后评估的计算核心（只用标准库）。

规则（2026-10-23 定；参数全取整数，没有按结果优化，相邻参数的表现见 README「稳健性」）：

  见顶预警  CCC 利差上穿 200 日均线（前一日在线下、当日在线上），且纳指收盘距过去一年最高收盘不到 5%。
           含义：信用趋势转坏、股价还在高位——两者背离。距上一次满足条件不到 63 个交易日的不再报。
  见底预警  利差 20 日内曾到过去一年的第 95 分位以上（恐慌），当日跌破 10 日均线且 10 日均线比 3 日前低
           （回落确认），且纳指距过去一年最高收盘已跌 10% 以上。距上一次满足条件不到 20 个交易日的不再报。

日历以纳指交易日为准：ICE 利差在美股休市日（感恩节、部分月末周末）也有数，每个交易日取当日或之前最近
的一个利差值；最近的利差比交易日早 7 个自然日以上就当作缺失。
"""
import csv
import os
from datetime import date

PCT_WIN = 252                       # 利差分位的回看窗口（交易日）
HI_WIN, HI_MINP = 252, 126          # 纳指「一年最高收盘」的窗口与最少样本
TOP_MA, TOP_NEAR, TOP_COOL = 200, 0.05, 63
BOT_PCT, BOT_LOOK, BOT_MA, BOT_SLOPE, BOT_DD, BOT_COOL = 95.0, 20, 10, 3, 0.10, 20
STALE_DAYS = 7
DESIGN_FROM = "2016-10-24"          # 规则是看这一天以后的数据定的；更早的部分（data/ 从 2005-10 起）是样本外

# 事后评估口径（只用于页面上的历史表，不进信号）
DD_TOP, DD_LOOK = 0.11, 63          # 下跌顶：一年新高，之后 63 日内回撤 ≥ 11%（与 best-weights 的 alt_engine.drawdown_tops 相同）
BOTTOM_DD, BOTTOM_HALF = 0.15, 63   # 底部：前后各 63 日的最低收盘，且比一年最高收盘低 15% 以上
TOP_PRE, TOP_LEAD = 5, 126          # 见顶预警之后 126 日内（或之前 5 日内）出现下跌顶算抓到
BOT_PRE, BOT_POST = 21, 42          # 见底预警落在底部前 21 日至后 42 日内算抓到
FWD, FWD_LONG = 63, 126              # 见顶预警主要看亮灯后 126 日内距最高收盘多远、最大跌多少；63 日收益只作参考


# ---------------- 读数据 ----------------
def read_series(path):
    """读 date,value 两列的 CSV，返回 {日期字符串: 浮点}。缺失值（'.' 或空）跳过。"""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 2 or not row[0][:4].isdigit():
                continue
            try:
                out[row[0][:10]] = float(row[1])
            except ValueError:
                pass
    return out


def write_series(path, data, header):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for k in sorted(data):
            w.writerow([k, ("%.4f" % data[k]).rstrip("0").rstrip(".")])
    os.replace(tmp, path)


def diff_series(a, b):
    """两个利差逐日相减（只取两边都有的日期），例如 CCC − BB。"""
    return {d: a[d] - b[d] for d in a if d in b}


def align(ccc, nas):
    """以纳指交易日为日历，把利差对齐上去（取当日或之前最近一个值）。"""
    dates = sorted(nas)
    cdates = sorted(ccc)
    S, j, last = [], -1, None
    for d in dates:
        while j + 1 < len(cdates) and cdates[j + 1] <= d:
            j += 1
        if j < 0:
            S.append(None)
            continue
        gap = (date.fromisoformat(d) - date.fromisoformat(cdates[j])).days
        S.append(ccc[cdates[j]] if gap <= STALE_DAYS else None)
    return dates, S, [nas[d] for d in dates]


# ---------------- 滚动计算 ----------------
def rolling_mean(x, n):
    out = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        if None not in w:
            out[i] = sum(w) / n
    return out


def rolling_pct(x, n):
    """当日值在含当日的过去 n 个值里的分位（≤ 当日值的占比 × 100）。"""
    out = [None] * len(x)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        if None not in w:
            v = x[i]
            out[i] = sum(1 for a in w if a <= v) * 100.0 / n
    return out


def rolling_max(x, n, minp):
    out = [None] * len(x)
    for i in range(len(x)):
        w = [a for a in x[max(0, i - n + 1):i + 1] if a is not None]
        if len(w) >= minp:
            out[i] = max(w)
    return out


def cooled(flags, cool):
    """把逐日条件切成事件：距上一个满足条件的日子超过 cool 个交易日才算新的一次。"""
    out, last = [], -10 ** 9
    for i, f in enumerate(flags):
        if f:
            if i - last > cool:
                out.append(i)
            last = i
    return out


# ---------------- 指标与信号 ----------------
def compute(dates, S, N):
    n = len(dates)
    pct = rolling_pct(S, PCT_WIN)
    ma10 = rolling_mean(S, BOT_MA)
    ma50 = rolling_mean(S, 50)
    ma200 = rolling_mean(S, TOP_MA)
    hi = rolling_max(N, HI_WIN, HI_MINP)
    dd = [N[i] / hi[i] - 1 if hi[i] else None for i in range(n)]

    top_raw, bot_raw = [False] * n, [False] * n
    top_cond, bot_cond = [None] * n, [None] * n
    for i in range(1, n):
        s, m, s0, m0 = S[i], ma200[i], S[i - 1], ma200[i - 1]
        if None not in (s, m, s0, m0, dd[i]):
            c = {"above": s > m, "cross": s > m and s0 <= m0, "near": dd[i] >= -TOP_NEAR}
            top_cond[i] = c
            top_raw[i] = c["cross"] and c["near"]
        w = pct[max(0, i - BOT_LOOK + 1):i + 1]
        if i >= BOT_SLOPE and None not in (S[i], ma10[i], ma10[i - BOT_SLOPE], dd[i]) and any(a is not None for a in w):
            c = {"panic": max(a for a in w if a is not None) >= BOT_PCT,
                 "below": S[i] < ma10[i], "falling": ma10[i] < ma10[i - BOT_SLOPE], "drawdown": dd[i] <= -BOT_DD}
            bot_cond[i] = c
            bot_raw[i] = all(c.values())
    return {"pct": pct, "ma10": ma10, "ma50": ma50, "ma200": ma200, "hi": hi, "dd": dd,
            "top_raw": top_raw, "bot_raw": bot_raw, "top_cond": top_cond, "bot_cond": bot_cond,
            "top_events": cooled(top_raw, TOP_COOL), "bot_events": cooled(bot_raw, BOT_COOL)}


def phase(s, ma200, pct):
    """信用周期所处阶段——只是读数说明，不进任何信号，没有检验过。"""
    if s is None or pct is None:
        return "—"
    if pct >= BOT_PCT:
        return "压力"
    if pct <= 10:
        return "自满"
    if ma200 is not None and s > ma200:
        return "走阔"
    return "平稳"


# ---------------- 事后评估 ----------------
def drawdown_tops(N):
    """下跌顶：收盘是过去 252 日最高（熊市反弹不算），之后 63 日内回撤 ≥ 11%。返回顶的下标。"""
    hi = rolling_max(N, HI_WIN, HI_WIN)
    out, last = [], None
    for q in range(1, len(N)):
        a = max(0, q - DD_LOOK)
        seg = N[a:q]
        p = a + seg.index(max(seg))
        if last is not None and p - last <= DD_LOOK:
            continue
        if hi[p] is not None and N[p] >= hi[p] and N[q] <= N[p] * (1 - DD_TOP):
            out.append(p)
            last = p
    return out


def bottoms(N):
    """底部：前后各 63 日里的最低收盘，且比一年最高收盘低 15% 以上；后 63 日没走完的不算（还没确认）。"""
    hi = rolling_max(N, HI_WIN, 1)
    out = []
    for i in range(BOTTOM_HALF, len(N) - BOTTOM_HALF):
        if N[i] == min(N[i - BOTTOM_HALF:i + BOTTOM_HALF + 1]) and N[i] <= hi[i] * (1 - BOTTOM_DD):
            if not out or i - out[-1] > BOTTOM_HALF:
                out.append(i)
    return out


def _ret(N, i, k):
    return N[i + k] / N[i] - 1 if i + k < len(N) else None


def _below_peak(N, i, k):
    """当日收盘比之后 k 日内（含当日）最高收盘低多少：≤ 0，越接近 0 说明越接近顶部。"""
    return N[i] / max(N[i:i + k + 1]) - 1 if i + k < len(N) else None


def _min_ret(N, i, k):
    return min(N[i:i + k + 1]) / N[i] - 1 if i + k < len(N) else None


def _mean(v):
    v = [a for a in v if a is not None]
    return sum(v) / len(v) if v else None


def evaluate(dates, S, N, r):
    tops, bots = drawdown_tops(N), bottoms(N)
    top_rows, bot_rows = [], []
    for e in r["top_events"]:
        hit = [t for t in tops if -TOP_PRE <= t - e <= TOP_LEAD]
        top_rows.append({"i": e, "date": dates[e], "s": S[e], "ma200": r["ma200"][e], "dd": r["dd"][e],
                         "fwd": _ret(N, e, FWD), "mdd": _min_ret(N, e, FWD_LONG), "below": _below_peak(N, e, FWD_LONG),
                         "hit": dates[hit[0]] if hit else None, "lead": hit[0] - e if hit else None,
                         "open": e + FWD_LONG >= len(N)})
    for e in r["bot_events"]:
        hit = [b for b in bots if -BOT_PRE <= e - b <= BOT_POST]
        bot_rows.append({"i": e, "date": dates[e], "s": S[e], "pct": max(a for a in r["pct"][max(0, e - BOT_LOOK + 1):e + 1] if a is not None),
                         "dd": r["dd"][e], "fwd": _ret(N, e, FWD), "fwd_long": _ret(N, e, FWD_LONG),
                         "worse": _min_ret(N, e, FWD), "hit": dates[hit[0]] if hit else None,
                         "lag": e - hit[0] if hit else None, "open": e + FWD >= len(N)})

    live = [i for i in range(len(N)) if r["ma200"][i] is not None]     # 两条规则都有读数的区间
    start = live[0] if live else len(N)
    tops = [t for t in tops if t >= start]
    bots = [b for b in bots if b >= start]
    near = [i for i in live if r["dd"][i] is not None and r["dd"][i] >= -TOP_NEAR]
    down = [i for i in live if r["dd"][i] is not None and r["dd"][i] <= -BOT_DD]
    summary = {
        "from": dates[start] if start < len(N) else None,
        "top": {"n": len(top_rows), "tops": len(tops),
                "caught": sum(any(-TOP_PRE <= t - e <= TOP_LEAD for e in r["top_events"]) for t in tops),
                "missed": [dates[t] for t in tops if not any(-TOP_PRE <= t - e <= TOP_LEAD for e in r["top_events"])],
                "mdd": _mean([x["mdd"] for x in top_rows]), "fwd": _mean([x["fwd"] for x in top_rows]),
                "below": _mean([x["below"] for x in top_rows]),
                "base_mdd": _mean([_min_ret(N, i, FWD_LONG) for i in near]), "base_fwd": _mean([_ret(N, i, FWD) for i in near]),
                "base_below": _mean([_below_peak(N, i, FWD_LONG) for i in near])},
        "bot": {"n": len(bot_rows), "bottoms": len(bots),
                "caught": sum(any(-BOT_PRE <= e - b <= BOT_POST for e in r["bot_events"]) for b in bots),
                "missed": [dates[b] for b in bots if not any(-BOT_PRE <= e - b <= BOT_POST for e in r["bot_events"])],
                "fwd": _mean([x["fwd"] for x in bot_rows]), "neg": _mean([(x["fwd"] < 0) * 1.0 for x in bot_rows if x["fwd"] is not None]),
                "base_fwd": _mean([_ret(N, i, FWD) for i in live]), "base_down": _mean([_ret(N, i, FWD) for i in down])},
        "top_dates": [dates[t] for t in tops], "bot_dates": [dates[b] for b in bots],
    }
    return top_rows, bot_rows, summary
