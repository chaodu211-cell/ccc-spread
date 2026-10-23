"""用 signals.py 的现行规则（参数不改）跑 1997 年起的全历史，取 2007–2016 段看预警与事后顶底。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import signals as G  # noqa: E402

RAW = os.path.join(os.path.dirname(os.path.dirname(HERE)), "最优拟合")
CCC = os.path.join(RAW, "图表/CCC利差与纳斯达克_十年/raw/BAMLH0A3HYC_historical.csv")
NAS = os.path.join(RAW, "研究/CCC利差纳指预警_2007-2016检验/raw/NASDAQCOM_mirror_1997_2026.csv")
A, B = "2007-01-01", "2016-12-31"


def run():
    ccc, nas = G.read_series(CCC), G.read_series(NAS)
    dates, S, N = G.align(ccc, nas)
    r = G.compute(dates, S, N)
    top_rows, bot_rows, _ = G.evaluate(dates, S, N, r)
    inw = lambda i: A <= dates[i] <= B
    tops = [t for t in G.drawdown_tops(N) if inw(t)]
    bots = [b for b in G.bottoms(N) if inw(b)]
    tr = [x for x in top_rows if inw(x["i"])]
    br = [x for x in bot_rows if inw(x["i"])]
    w = [i for i in range(len(dates)) if inw(i)]
    near = [i for i in w if r["dd"][i] is not None and r["dd"][i] >= -G.TOP_NEAR]
    down = [i for i in w if r["dd"][i] is not None and r["dd"][i] <= -G.BOT_DD]
    caught_t = [t for t in tops if any(-G.TOP_PRE <= t - x["i"] <= G.TOP_LEAD for x in tr)]
    caught_b = [b for b in bots if any(-G.BOT_PRE <= x["i"] - b <= G.BOT_POST for x in br)]
    summ = {
        "top": {"n": len(tr), "tops": [dates[t] for t in tops], "caught": [dates[t] for t in caught_t],
                "fwd": G._mean([x["fwd"] for x in tr]), "mdd": G._mean([x["mdd"] for x in tr]),
                "base_fwd": G._mean([G._ret(N, i, G.FWD) for i in near]), "base_mdd": G._mean([G._min_ret(N, i, G.FWD_LONG) for i in near])},
        "bot": {"n": len(br), "bottoms": [dates[b] for b in bots], "caught": [dates[b] for b in caught_b],
                "fwd": G._mean([x["fwd"] for x in br]), "neg": G._mean([(x["fwd"] < 0) * 1.0 for x in br]),
                "base_fwd": G._mean([G._ret(N, i, G.FWD) for i in w]), "base_down": G._mean([G._ret(N, i, G.FWD) for i in down])},
    }
    return dates, S, N, r, tr, br, tops, bots, summ


if __name__ == "__main__":
    dates, S, N, r, tr, br, tops, bots, summ = run()
    print("首个有 200 日线读数:", next(dates[i] for i in range(len(dates)) if r["ma200"][i] is not None))
    for x in tr:
        print("▼", x["date"], "利差 %.2f MA200 %.2f 距高 %+.1f%% 63日 %+.1f%% 126日回撤 %+.1f%% 抓到 %s 提前 %s"
              % (x["s"], x["ma200"], x["dd"] * 100, x["fwd"] * 100, x["mdd"] * 100, x["hit"], x["lead"]))
    for x in br:
        print("▲", x["date"], "利差 %.2f 分位 %.0f 距高 %+.1f%% 63日 %+.1f%% 126日 %+.1f%% 63日内最差 %+.1f%% 底 %s 滞后 %s"
              % (x["s"], x["pct"], x["dd"] * 100, x["fwd"] * 100, x["fwd_long"] * 100, x["worse"] * 100, x["hit"], x["lag"]))
    print("下跌顶:", [dates[t] for t in tops]); print("底部:", [dates[b] for b in bots])
    print(json.dumps(summ, ensure_ascii=False, indent=1))
