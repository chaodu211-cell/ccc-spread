"""把计算结果填进 template.html，生成 dashboard.html（单个文件，离线可开）。"""
import json
import os
from datetime import datetime

import signals as G

HERE = os.path.dirname(os.path.abspath(__file__))


def _r(x, k):
    return None if x is None else round(x, k)


# 页面上可切换的利差序列。规则与参数对两者完全相同；CCC−BB 是原样套用，没有为它调过参。
SERIES = {
    "ccc": {"short": "CCC 利差", "title": "CCC 及以下高收益债利差（OAS，%）",
            "note": "ICE BofA 美国 CCC 及以下高收益债的期权调整利差。规则和参数是按它定的。"},
    "ccc_bb": {"short": "CCC−BB 利差", "title": "CCC−BB 信用质量利差（CCC 利差减 BB 利差，百分点）",
               "note": "CCC 利差减 BB 级利差，主要反映最弱那批公司特有的违约和困境压力。"
                       "规则和参数与 CCC 相同、原样套用；但加进来之前已经看过它的回测，所以它的「样本外」不算干净。"},
}


def _block(key, sp, nas):
    """一个利差序列的指标、信号、事后评估与当前读数。"""
    dates, S, N = G.align(sp, nas)
    r = G.compute(dates, S, N)
    top_rows, bot_rows, summary = G.evaluate(dates, S, N, r)
    last = max(i for i in range(len(dates)) if S[i] is not None)

    def ago(events):
        return {"date": dates[events[-1]], "ago": last - events[-1]} if events else None

    s20 = S[last - 20] if last >= 20 else None
    k = last                                  # 利差连续在 200 日线上方从哪天开始
    while k > 0 and None not in (S[k], r["ma200"][k]) and S[k] > r["ma200"][k]:
        k -= 1
    above_since = {"date": dates[k + 1], "days": last - k} if k < last else None
    cur = {
        "date": dates[last], "s": S[last], "chg20": S[last] - s20 if s20 is not None else None,
        "pct": r["pct"][last], "ma200": r["ma200"][last], "n": N[last], "dd": r["dd"][last],
        "gap200": S[last] / r["ma200"][last] - 1 if r["ma200"][last] else None,
        "phase": G.phase(S[last], r["ma200"][last], r["pct"][last]),
        "top_cond": r["top_cond"][last], "bot_cond": r["bot_cond"][last],
        "top_today": last in r["top_events"], "bot_today": last in r["bot_events"],
        "top_raw_today": r["top_raw"][last], "bot_raw_today": r["bot_raw"][last],
        "last_top": ago(r["top_events"]), "last_bot": ago(r["bot_events"]), "above_since": above_since,
        "panic_max20": max([a for a in r["pct"][max(0, last - G.BOT_LOOK + 1):last + 1] if a is not None], default=None),
    }
    # 页面时间轴从三项指标（200 日线、252 日分位、一年高点）都有读数的那天开始，前面只是预热
    start = next(i for i in range(len(dates)) if None not in (r["ma200"][i], r["pct"][i], r["dd"][i]))
    sd = max(sp)
    block = dict(SERIES[key], latest={"date": sd, "v": sp[sd]},
                 s=[_r(x, 3) for x in S], ma200=[_r(x, 3) for x in r["ma200"]], pct=[_r(x, 1) for x in r["pct"]],
                 top_events=[dict(x) for x in top_rows], bot_events=[dict(x) for x in bot_rows],
                 summary=summary, cur=cur, i_start=start)
    return block, (dates, S, N, r)


def build(ccc, nas, fetch_status=None, bb=None):
    """bb 有数据时多算一套 CCC−BB；两套共用纳指日历，页面上一键切换。"""
    series, calc = {}, {}
    series["ccc"], calc["ccc"] = _block("ccc", ccc, nas)
    if bb:
        series["ccc_bb"], calc["ccc_bb"] = _block("ccc_bb", G.diff_series(ccc, bb), nas)
    dates, S, N, r = calc["ccc"]
    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "nas_latest": {"date": max(nas), "v": nas[max(nas)]},
        "fetch": fetch_status or {},
        "d": dates, "n": [_r(x, 2) for x in N], "dd": [_r(x, 4) for x in r["dd"]],
        "i_start": max(b["i_start"] for b in series.values()),
        "series": series,
        "params": {"top_ma": G.TOP_MA, "top_near": G.TOP_NEAR, "top_cool": G.TOP_COOL,
                   "bot_pct": G.BOT_PCT, "bot_look": G.BOT_LOOK, "bot_ma": G.BOT_MA, "bot_slope": G.BOT_SLOPE,
                   "bot_dd": G.BOT_DD, "bot_cool": G.BOT_COOL, "fwd": G.FWD, "fwd_long": G.FWD_LONG,
                   "top_lead": G.TOP_LEAD, "top_pre": G.TOP_PRE, "design_from": G.DESIGN_FROM, "bot_pre": G.BOT_PRE, "bot_post": G.BOT_POST},
    }
    return data, calc


def render(data, out=None):
    out = out or os.path.join(HERE, "dashboard.html")
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as fh:
        tpl = fh.read()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = tpl.replace("/*__DATA__*/null", blob)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(html)
    os.replace(tmp, out)
    return out
