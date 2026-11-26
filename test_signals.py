"""计算核心的自检（只用标准库）：python3 test_signals.py"""
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import fetch
import signals as G


class TestRolling(unittest.TestCase):
    def test_mean_and_pct(self):
        x = [1.0, 2.0, 3.0, None, 5.0, 6.0]
        self.assertEqual(G.rolling_mean(x, 3), [None, None, 2.0, None, None, None])
        self.assertEqual(G.rolling_pct([3.0, 1.0, 2.0, 3.0], 3)[2:], [200 / 3, 100.0])

    def test_max_minp(self):
        self.assertEqual(G.rolling_max([1, 5, 2, None, 3], 3, 2), [None, 5, 5, 5, 3])

    def test_cooled(self):
        f = [False, True, True, False, False, True, False, False, False, False, True]
        self.assertEqual(G.cooled(f, 3), [1, 10])   # 5 距 2 只有 3 日，算同一次；10 距 5 有 5 日
        self.assertEqual(G.cooled(f, 2), [1, 5, 10])


class TestAlign(unittest.TestCase):
    def test_ffill_and_stale(self):
        ccc = {"2026-01-02": 9.0, "2026-01-05": 9.5}
        nas = {"2026-01-02": 100.0, "2026-01-05": 101.0, "2026-01-06": 102.0, "2026-01-20": 103.0}
        d, S, N = G.align(ccc, nas)
        self.assertEqual(S, [9.0, 9.5, 9.5, None])    # 01-20 离最近利差 15 天，算缺失


class TestSignals(unittest.TestCase):
    def test_top_cross_near_high(self):
        # 纳指一路新高；利差前 250 天在 8，之后跳到 10 → 上穿 200 日线那天报一次见顶预警
        n = 300
        dates = ["d%04d" % i for i in range(n)]
        N = [100 + i for i in range(n)]
        S = [8.0] * 250 + [10.0] * 50
        r = G.compute(dates, S, N)
        self.assertEqual(r["top_events"], [250])
        self.assertEqual(r["bot_events"], [])

    def test_bottom_after_panic(self):
        # 纳指先跌 30%；利差冲到一年最高后回落 → 跌破 10 日线、10 日线下行时报见底预警
        n = 320
        dates = ["d%04d" % i for i in range(n)]
        N = [100.0] * 260 + [100 - 0.5 * k for k in range(1, 61)]
        S = [8.0] * 280 + [8.0 + 0.5 * k for k in range(1, 21)] + [18.0 - 0.6 * k for k in range(1, 21)]
        r = G.compute(dates, S, N)
        self.assertTrue(r["bot_events"])
        e = r["bot_events"][0]
        self.assertGreaterEqual(e, 300)
        c = r["bot_cond"][e]
        self.assertTrue(all(c.values()))


class TestSeries(unittest.TestCase):
    def test_diff_series(self):
        self.assertEqual(G.diff_series({"a": 10.0, "b": 12.0, "c": 9.0}, {"a": 3.0, "c": 2.5}), {"a": 7.0, "c": 6.5})

    def test_build_two_series(self):
        # 有 BB 时页面数据里多一套 CCC−BB，日期与纳指共用；没有 BB 时只有 CCC
        import make_page
        days = ["2020-%02d-%02d" % (1 + k // 28, 1 + k % 28) for k in range(12 * 28)] + \
               ["2021-%02d-%02d" % (1 + k // 28, 1 + k % 28) for k in range(4 * 28)]
        nas = {d: 100.0 + i for i, d in enumerate(days)}
        ccc = {d: 8.0 + (i % 50) / 25 for i, d in enumerate(days)}
        bb = {d: 2.0 + (i % 30) / 30 for i, d in enumerate(days)}
        data, _ = make_page.build(ccc, nas, {}, bb)
        self.assertEqual(sorted(data["series"]), ["ccc", "ccc_bb"])
        x = data["series"]["ccc_bb"]
        self.assertAlmostEqual(x["cur"]["s"], ccc[days[-1]] - bb[days[-1]], places=6)
        self.assertEqual(len(x["s"]), len(data["d"]))
        only, _ = make_page.build(ccc, nas, {})
        self.assertEqual(list(only["series"]), ["ccc"])
        day = days[-1]
        bb_without_latest = {d: bb[d] for d in days[:-1]}
        data, _ = make_page.build(ccc, nas, {}, bb_without_latest)
        self.assertEqual(data["nas_latest"]["date"], day)
        self.assertEqual(data["series"]["ccc"]["cur"]["date"], day)
        self.assertEqual(data["series"]["ccc_bb"]["cur"]["date"], days[-2])
        self.assertIsNone(data["series"]["ccc_bb"]["s"][-1])

        ccc_without_latest = {d: ccc[d] for d in days[:-1]}
        data, _ = make_page.build(ccc_without_latest, nas, {}, bb)
        self.assertEqual(data["series"]["ccc"]["cur"]["date"], days[-2])
        self.assertEqual(data["series"]["ccc_bb"]["cur"]["date"], days[-2])
        self.assertEqual(data["d"][-1], day)
        self.assertIsNone(data["series"]["ccc"]["s"][-1])


class TestFetch(unittest.TestCase):
    def test_nasdaq_checks_fallback_when_fred_is_behind(self):
        old = {"2026-11-19": 23879.20}
        fri, mon = "2026-11-20", "2026-11-23"
        api = Mock(return_value={**old, fri: 22617.73})
        csv = Mock(side_effect=RuntimeError("下载失败"))
        yahoo = Mock(return_value={**old, fri: 22600.00, mon: 24089.56})
        sources = {"nasdaq": [("FRED API", api), ("FRED 网页", csv), ("Yahoo", yahoo)]}
        with TemporaryDirectory() as work:
            G.write_series(str(Path(work) / "data/nasdaq.csv"), old, fetch.HEADER["nasdaq"])
            with patch.object(fetch, "HERE", work), patch.object(fetch, "SOURCES", sources), \
                 patch.object(fetch, "nasdaq_target", return_value=mon):
                st = fetch.update(ci=True, log=lambda _: None)["nasdaq"]
                csv.assert_called_once()
                yahoo.assert_called_once()
                self.assertEqual(st["source"], "FRED API + Yahoo")
                self.assertEqual(st["src_last"], mon)
                self.assertEqual(fetch.load_local("nasdaq"), {**old, fri: 22617.73, mon: 24089.56})
                api.return_value = {**old, fri: 22617.73, mon: 24089.56}
                yahoo.reset_mock()
                fetch.update(ci=True, log=lambda _: None)
                yahoo.assert_not_called()

    def test_nasdaq_target_before_and_after_close(self):
        self.assertEqual(fetch.nasdaq_target(datetime(2026, 11, 23, 9)), "2026-11-20")
        self.assertEqual(fetch.nasdaq_target(datetime(2026, 11, 23, 18)), "2026-11-23")

    def test_parse_fred(self):
        txt = "observation_date,BAMLH0A3HYC\n2026-10-19,13.10\n2026-10-20,.\n2026-10-21,\n2026-10-22,13.30\n"
        self.assertEqual(fetch.parse_fred(txt), {"2026-10-19": 13.1, "2026-10-22": 13.3})
        with self.assertRaises(RuntimeError):
            fetch.parse_fred("<html>error</html>")

    def test_parse_fred_api(self):
        txt = '{"observations":[{"date":"2026-10-20","value":"13.27"},{"date":"2026-10-21","value":"."}]}'
        self.assertEqual(fetch.parse_fred_api(txt), {"2026-10-20": 13.27})
        with self.assertRaises(RuntimeError):
            fetch.parse_fred_api('{"error_code":400,"error_message":"Bad Request"}')

    def test_parse_yahoo_drops_live_bar(self):
        # 两根日 K：10-20 已收盘，10-21 盘中（now 落在当日交易时段内）→ 只留 10-20
        off = -14400
        t20, t21 = 1760967000, 1761053400            # 2025-10-20 / 21 美东 09:30（UTC 13:30）
        txt = ('{"chart":{"result":[{"meta":{"gmtoffset":%d,"currentTradingPeriod":{"regular":{"start":%d,"end":%d}}},'
               '"timestamp":[%d,%d],"indicators":{"quote":[{"close":[26424.82,26300.0]}]}}]}}') % (off, t21, t21 + 23400, t20, t21)
        self.assertEqual(fetch.parse_yahoo(txt, now=t21 + 3600), {"2025-10-20": 26424.82})
        self.assertEqual(fetch.parse_yahoo(txt, now=t21 + 86400),             # 收盘以后两根都留
                         {"2025-10-20": 26424.82, "2025-10-21": 26300.0})

    def test_merge(self):
        out, added, changed = fetch.merge({"a": 10.0, "b": 11.0}, {"b": 11.1, "c": 12.0})
        self.assertEqual((out, added, changed), ({"a": 10.0, "b": 11.1, "c": 12.0}, 1, 1))
        with self.assertRaises(RuntimeError):
            fetch.merge({"a": 10.0}, {"a": 5000.0})      # 下成了别的序列


if __name__ == "__main__":
    unittest.main(verbosity=1)
