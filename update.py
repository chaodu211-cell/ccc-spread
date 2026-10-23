"""一条龙：从 FRED 下载 → 重算信号 → 生成 dashboard.html。

  python3 update.py             本地：data/ 只读，新数据写进 cache/
  python3 update.py --offline   不下载，只用本地已有数据重算
  python3 update.py --ci        GitHub 流水线：新数据写回 data/；环境变量 CCC_SNAPSHOT=1 时追加信号快照
"""
import csv
import json
import os
import sys
from datetime import datetime

import fetch
import make_page

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "信号快照.csv")
SNAP_COLS = ["截止日", "利差", "252日分位", "200日均线", "纳指", "距一年高点", "阶段",
             "见顶预警", "见顶条件满足", "见底预警", "见底条件满足", "记录时间"]


def snapshot(c):
    """只追加、不改写：每个截止日一行，记下当时页面显示的读数与信号（防止以后重算改写历史）。"""
    rows = []
    if os.path.exists(SNAP):
        with open(SNAP, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
    if any(r and r[0] == c["date"] for r in rows[1:]):
        return False
    new = not rows
    f = lambda x, k: "" if x is None else ("%." + str(k) + "f") % x  # noqa: E731
    with open(SNAP, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(SNAP_COLS)
        w.writerow([c["date"], f(c["s"], 2), f(c["pct"], 1), f(c["ma200"], 3), f(c["n"], 2), f(c["dd"], 4), c["phase"],
                    int(c["top_today"]), int(c["top_raw_today"]), int(c["bot_today"]), int(c["bot_raw_today"]),
                    datetime.now().strftime("%Y-%m-%d %H:%M")])
    return True


def main(argv):
    ci, offline = "--ci" in argv, "--offline" in argv
    if offline:
        print("① 跳过下载（--offline）")
        status = {}
    else:
        print("① 从 FRED 下载最新数据…")
        status = fetch.update(ci=ci)
    ccc, nas = fetch.load_local("ccc_oas"), fetch.load_local("nasdaq")
    if not ccc or not nas:
        print("❌ 本地没有可用数据（data/ 里的 CSV 缺失），也没下载到。")
        return 2

    print("② 重算信号…")
    data, _ = make_page.build(ccc, nas, status)
    out = make_page.render(data)
    c = data["cur"]
    pct = "—" if c["pct"] is None else "%.0f" % c["pct"]
    print("   截至 %s：利差 %.2f%%，252 日分位 %s，阶段「%s」，纳指距一年高点 %+.1f%%"
          % (c["date"], c["s"], pct, c["phase"], c["dd"] * 100))
    for key, name in (("top", "见顶预警"), ("bot", "见底预警")):
        last = c["last_" + key]
        state = "今日触发！" if c[key + "_today"] else ("条件满足（冷却期内）" if c[key + "_raw_today"] else "未触发")
        print("   %s：%s；最近一次 %s" % (name, state, "%s（%d 个交易日前）" % (last["date"], last["ago"]) if last else "无"))
    print("③ 页面已生成：%s" % out)

    with open(os.path.join(HERE, "status.json"), "w", encoding="utf-8") as fh:
        json.dump({"as_of": c["date"], "generated": data["generated"], "fetch": status,
                   "top_today": c["top_today"], "bot_today": c["bot_today"], "phase": c["phase"]},
                  fh, ensure_ascii=False, indent=1)
    if ci and os.environ.get("CCC_SNAPSHOT") == "1":
        print("④ 信号快照：%s" % ("追加 " + c["date"] if snapshot(c) else c["date"] + " 已记过，不重复追加"))
    if ci and status and not any(v.get("ok") for v in status.values()):
        print("❌ 两个序列都没下载到")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
