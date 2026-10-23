"""把现行见顶 / 见底预警画到 2007–2016 的纳指与 CCC 利差上（规则与参数取自 signals.py，未改动）。"""
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("MPLCONFIGDIR", os.path.join(HERE, ".mplconfig"))
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter, MultipleLocator, NullLocator  # noqa: E402

from calc import A, B, G, run  # noqa: E402  （calc 会把上级目录放进 sys.path）

FONT = FontProperties(fname="/System/Library/Fonts/PingFang.ttc")
plt.rcParams.update({"font.family": FONT.get_name(), "axes.unicode_minus": False, "font.size": 11,
                     "svg.fonttype": "none", "savefig.facecolor": "#FAFBFD"})
INK, MUTED, STOCK, RISK, BOTTOM, SPREAD, MA = "#17283D", "#69778A", "#245FC3", "#CA493B", "#008B7D", "#D76A31", "#5E6B7D"

# 逐条注释：(日期, 文字, 偏移)
NOTES = {
    "2007-07-11": ("提前 79 日 · 2007-10 顶", (-30, 46)),
    "2011-07-05": ("之后 63 日 −17%\n（7 月高点比 4 月低 0.03%，\n按定义不算下跌顶）", (-150, 40)),
    "2012-02-10": ("提前 30 日 · 2012-03 顶", (-70, 52)),
    "2013-09-30": ("之后没跌（63 日 +10%）", (-60, 44)),
    "2014-08-01": ("之后没跌（63 日 +5%）", (-20, 50)),
    "2008-02-27": ("底前 8 日 · 2008-03 底", (-120, -46)),
    "2008-07-23": ("过早：之后 63 日 −27%", (-125, -89)),
    "2008-12-26": ("底后 24 日 · 2008-11 底\n之后 63 日内又跌 17%", (60, -20)),
    "2016-02-25": ("底后 9 日 · 2016-02 底", (-150, -40)),
}


def main():
    dates, S, N, r, tr, br, tops, bots, summ = run()
    w = [i for i in range(len(dates)) if A <= dates[i] <= B]
    X = [date.fromisoformat(dates[i]) for i in w]
    xs = lambda idx: [date.fromisoformat(dates[i]) for i in idx]

    fig = plt.figure(figsize=(17, 10.8), facecolor="#FAFBFD")
    gs = fig.add_gridspec(2, 1, height_ratios=[2.6, 1.4], left=.065, right=.95, bottom=.20, top=.84, hspace=.08)
    ax = fig.add_subplot(gs[0])
    cr = fig.add_subplot(gs[1], sharex=ax)

    # 纳指
    ax.plot(X, [N[i] for i in w], color=STOCK, lw=1.6, zorder=2)
    ax.set_yscale("log")
    lo, hi = min(N[i] for i in w) * .82, max(N[i] for i in w) * 1.15
    ax.set_ylim(lo, hi)
    ax.yaxis.set_major_locator(FixedLocator([t for t in [1000, 1500, 2000, 3000, 4000, 5000, 6000] if lo <= t <= hi]))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: "%s" % format(int(v), ",")))

    # 利差 + 200 日线 + 95 分位以上的日子
    cr.plot(X, [S[i] for i in w], color=SPREAD, lw=1.3, zorder=3)
    cr.plot(X, [r["ma200"][i] for i in w], color=MA, lw=1.1, ls="--", zorder=2)
    panic = [r["pct"][i] is not None and r["pct"][i] >= G.BOT_PCT for i in w]
    cr.fill_between(X, 0, 1, where=panic, transform=cr.get_xaxis_transform(), color=BOTTOM, alpha=.09, lw=0, step="mid")
    cr.set_ylim(0, max(S[i] for i in w) * 1.12)
    cr.yaxis.set_major_locator(MultipleLocator(10))
    cr.yaxis.set_major_formatter(FuncFormatter(lambda v, _: "%.0f%%" % v))
    cr.xaxis.set_major_locator(mdates.YearLocator())
    cr.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    cr.set_xlim(X[0], X[-1])

    for p in (ax, cr):
        p.set_facecolor("white")
        p.grid(axis="both", color="#E9EDF3", lw=.65)
        p.tick_params(axis="both", length=0, colors=MUTED, pad=8)
        for s in p.spines.values():
            s.set_visible(False)
    ax.tick_params(axis="x", labelbottom=False)
    ax.text(.004, 1.02, "纳斯达克综合指数 · 对数刻度", transform=ax.transAxes, color=INK, fontsize=10.5)
    cr.text(.004, .90, "CCC 及以下 OAS（橙）· 200 日均线（虚线）· 浅绿底 = 一年 95 分位以上", transform=cr.transAxes,
            color=INK, fontsize=10, bbox={"facecolor": "white", "alpha": .85, "edgecolor": "none", "pad": 2})

    # 事后顶底（空心圈，只用于评分）
    ax.scatter(xs(tops), [N[t] for t in tops], s=120, facecolors="none", edgecolors=RISK, linewidths=1.0, alpha=.55, zorder=3)
    ax.scatter(xs(bots), [N[b] for b in bots], s=120, facecolors="none", edgecolors=BOTTOM, linewidths=1.0, alpha=.55, zorder=3)

    # 预警
    for rows, color, mk, off in ((tr, RISK, "v", 1.06), (br, BOTTOM, "^", .94)):
        idx = [x["i"] for x in rows]
        ax.scatter(xs(idx), [N[i] * off for i in idx], marker=mk, s=95, color=color, edgecolors="white", linewidths=1.2, zorder=6)
        cr.scatter(xs(idx), [S[i] for i in idx], marker=mk, s=60, color=color, edgecolors="white", linewidths=1, zorder=6)
        for x in rows:
            t, o = NOTES[x["date"]]
            d = date.fromisoformat(x["date"])
            ax.annotate("%s\n%s" % (x["date"], t), (d, N[x["i"]] * off), xytext=o, textcoords="offset points",
                        fontsize=9, color=INK, linespacing=1.3,
                        arrowprops={"arrowstyle": "-", "color": color, "lw": .8, "shrinkA": 2, "shrinkB": 6})

    st, sb = summ["top"], summ["bot"]
    fig.text(.065, .95, "现行 CCC 利差预警放到 2007–2016：规则定于 2016-10 以后的数据，这段没参与制定", fontsize=17, color=INK, weight="bold")
    fig.text(.065, .915, "▼ 见顶：利差上穿 200 日线且纳指距一年高点 < 5%（冷却 63 日）    "
             "▲ 见底：利差 20 日内到过一年 95 分位、跌破下行的 10 日线，且纳指距高点已跌 ≥ 10%（冷却 20 日）",
             fontsize=10.5, color=MUTED)
    fig.text(.065, .89, "参数与 signals.py 完全相同、未调整；均线与分位用 1997 年起的数据预热。空心圈 = 事后标出的下跌顶 / 底部（只用于评分）。",
             fontsize=10.5, color=MUTED)

    pc = lambda v: "%+.1f%%" % (v * 100)
    lines = [
        ("▼ 见顶预警", RISK,
         "亮 %d 次；4 个下跌顶抓到 %d 个（2007-10、2012-03），漏 2010-04、2015-07。亮灯后 63 日纳指 %s，基准（纳指在高点 5%% 内的日子）%s；"
         "126 日内最大回撤 %s vs 基准 %s。" % (st["n"], len(st["caught"]), pc(st["fwd"]), pc(st["base_fwd"]), pc(st["mdd"]), pc(st["base_mdd"]))),
        ("▲ 见底预警", BOTTOM,
         "亮 %d 次；6 个底部抓到 %d 个（2008-03、2008-11、2016-02），漏 2009-03（一年窗口里有 08 年 12 月的 44%%，分位只到 93）、"
         "2010-07（利差没恐慌）、2011-10（回落确认时纳指已反弹到高点 10%% 内）。" % (sb["n"], len(sb["caught"]))),
        ("", BOTTOM,
         "亮灯后 63 日纳指平均 %s，%d 次里 %d 次为负；基准（全部日子）%s，纳指已跌 10%% 以上的日子 %s。2008 年这条规则亮得太早。"
         % (pc(sb["fwd"]), sb["n"], round(sb["neg"] * sb["n"]), pc(sb["base_fwd"]), pc(sb["base_down"]))),
    ]
    y = .145
    for head, color, body in lines:
        if head:
            fig.text(.065, y, head, fontsize=11, color=color, weight="bold")
        fig.text(.135, y, body, fontsize=10.5, color=INK)
        y -= .03
    fig.text(.065, .045, "数据：ICE BofA US High Yield CCC & Lower OAS（FRED BAMLH0A3HYC，早期取自已核对的 FRED 历史存档）；纳斯达克综合指数（FRED NASDAQCOM）。"
             "事件数很少（5 次见顶、4 次见底），百分比只代表几次事件。", fontsize=9, color=MUTED)

    ax.legend(handles=[Line2D([], [], marker="v", ls="", color=RISK, ms=9, label="见顶预警"),
                       Line2D([], [], marker="^", ls="", color=BOTTOM, ms=9, label="见底预警"),
                       Line2D([], [], marker="o", ls="", mfc="none", mec=RISK, ms=10, label="下跌顶（事后）"),
                       Line2D([], [], marker="o", ls="", mfc="none", mec=BOTTOM, ms=10, label="底部（事后）")],
              loc="upper left", bbox_to_anchor=(0, .97), frameon=False, fontsize=10, ncol=4, handletextpad=.3, columnspacing=1.4)

    for ext in ("png", "svg"):
        fig.savefig(os.path.join(HERE, "现行预警_2007-2016.%s" % ext), dpi=150 if ext == "png" else None)
    print("ok")


if __name__ == "__main__":
    main()
