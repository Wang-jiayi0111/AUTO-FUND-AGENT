import unittest
from datetime import date

from src.models import FundCandidate
from src.parse.llm_extractor import filter_trade_image_urls
from src.parse.fund_resolver import FundResolver
from src.parse.pipeline import (
    ParsePipeline,
    _append_risk_alerts_to_merged,
    _drop_sector_alias_duplicates,
    _enrich_fund_ops_from_annotations,
    _enrich_fund_ops_from_text_analysis,
    _filter_analytical_text_operations,
    _looks_like_sector_alias,
    _merge_operations,
    _to_parsed_operation,
)
from src.utils.fund_name import (
    fund_name_core,
    fund_names_equivalent,
    fund_search_queries,
    is_valid_fund_code,
    normalize_fund_name,
)
from src.utils.trading_calendar import is_trading_day


class FundNameTests(unittest.TestCase):
    def test_filter_trade_image_urls_skips_gif(self):
        urls = [
            "https://mmbiz.qpic.cn/mmbiz_gif/ecdn1e8/header.gif",
            "https://mmbiz.qpic.cn/mmbiz_jpg/ecdn1e8/trade1.jpg",
            "https://mmbiz.qpic.cn/sz_mmbiz_jpg/ecdn1e8/trade2.jpg",
        ]
        filtered = filter_trade_image_urls(urls)
        self.assertEqual(len(filtered), 2)
        self.assertTrue(all("gif" not in u for u in filtered))

    def test_normalize(self):
        self.assertEqual(normalize_fund_name("华夏成长混合"), "华夏成长")
        self.assertEqual(normalize_fund_name("  沪深300  "), "沪深300")

    def test_valid_code(self):
        self.assertTrue(is_valid_fund_code("000001"))
        self.assertFalse(is_valid_fund_code("00001"))

    def test_fund_name_core_handles_optional_tokens(self):
        self.assertEqual(fund_name_core("东吴多策略灵活配置混合C"), "东吴多策略混合")
        self.assertEqual(
            fund_name_core("招商中证半导体产业ETF发起式联接C"),
            "招商中证半导体产业ETF联接",
        )

    def test_fund_names_equivalent_ocr_vs_api(self):
        self.assertTrue(
            fund_names_equivalent(
                "东吴多策略灵活配置混合C",
                "东吴多策略混合C",
            )
        )
        self.assertTrue(
            fund_names_equivalent(
                "招商中证半导体产业ETF联接C",
                "招商中证半导体产业ETF发起式联接C",
            )
        )

    def test_fund_search_queries_include_short_keys(self):
        queries = fund_search_queries("招商中证半导体产业ETF联接C")
        self.assertIn("招商中证半导体产业ETF联接C", queries)
        self.assertTrue(any("招商中证半导体" in q for q in queries))

    def test_sector_alias_detection(self):
        self.assertTrue(_looks_like_sector_alias("CPO", "科技"))
        self.assertTrue(_looks_like_sector_alias("上海金", "黄金"))
        self.assertFalse(_looks_like_sector_alias("景顺港药", "医药"))
        self.assertFalse(_looks_like_sector_alias("富国上海金ETF联接C", "黄金"))


class FundResolverTests(unittest.TestCase):
    def test_resolve_with_code(self):
        resolver = FundResolver(__import__("pathlib").Path("/tmp/fund-test-cache"))
        result = resolver.resolve("华夏成长", "000001")
        self.assertEqual(result.fund_code, "000001")
        self.assertEqual(result.fund_code_source, "ocr")
        self.assertTrue(result.unique_match)

    def test_pick_c_share_for_lianjie_c_name(self):
        resolver = FundResolver(__import__("pathlib").Path("/tmp/fund-test-cache"))
        candidates = [
            FundCandidate("023597", "景顺长城中证港股通创新药ETF联接A"),
            FundCandidate("023598", "景顺长城中证港股通创新药ETF联接C"),
        ]
        match = resolver._pick_unique_match(
            "景顺长城中证港股通创新药ETF联接C",
            candidates,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.code, "023598")

    def test_pick_dongwu_flexible_name_from_candidates(self):
        resolver = FundResolver(__import__("pathlib").Path("/tmp/fund-test-cache"))
        candidates = [
            FundCandidate("011949", "东吴多策略混合C"),
            FundCandidate("011948", "东吴多策略混合A"),
        ]
        match = resolver._pick_unique_match("东吴多策略灵活配置混合C", candidates)
        self.assertIsNotNone(match)
        self.assertEqual(match.code, "011949")

    def test_pick_zhaoshang_faqishi_name_from_candidates(self):
        resolver = FundResolver(__import__("pathlib").Path("/tmp/fund-test-cache"))
        candidates = [
            FundCandidate("020464", "招商中证半导体产业ETF发起式联接A"),
            FundCandidate("020465", "招商中证半导体产业ETF发起式联接C"),
        ]
        match = resolver._pick_unique_match("招商中证半导体产业ETF联接C", candidates)
        self.assertIsNotNone(match)
        self.assertEqual(match.code, "020465")

    def test_resolve_jingshun_lianjie_c_via_eastmoney(self):
        resolver = FundResolver(__import__("pathlib").Path("data/cache"))
        result = resolver.resolve("景顺长城中证港股通创新药ETF联接C", "")
        self.assertEqual(result.fund_code, "023598")
        self.assertTrue(result.unique_match)
        self.assertEqual(result.fund_code_source, "search")

    def test_resolve_dongwu_flexible_name_via_eastmoney(self):
        resolver = FundResolver(__import__("pathlib").Path("data/cache"))
        result = resolver.resolve("东吴多策略灵活配置混合C", "")
        self.assertEqual(result.fund_code, "011949")
        self.assertTrue(result.unique_match)

    def test_resolve_zhaoshang_semiconductor_via_eastmoney(self):
        resolver = FundResolver(__import__("pathlib").Path("data/cache"))
        result = resolver.resolve("招商中证半导体产业ETF联接C", "")
        self.assertEqual(result.fund_code, "020465")
        self.assertTrue(result.unique_match)


class TradingCalendarTests(unittest.TestCase):
    def test_weekend_not_trading(self):
        # 2026-06-20 is Saturday
        self.assertFalse(is_trading_day(date(2026, 6, 20)))


class MergeOperationsTests(unittest.TestCase):
    def test_lanjing_624_merge_dedupes_text_and_image(self):
        text_ops = [
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "上海金",
                "sector": "黄金",
                "amount_or_ratio": "5万",
                "reason": "均衡配置",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "CPO",
                "sector": "科技",
                "amount_or_ratio": "1万",
                "reason": "核心科技依然是主线",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "减仓",
                "fund_code": "",
                "fund_name": "景顺港药",
                "sector": "医药",
                "amount_or_ratio": "约6万（出一半）",
                "reason": "走势墨迹，进行调仓",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "卖出",
                "fund_code": "",
                "fund_name": "天弘药",
                "sector": "医药",
                "amount_or_ratio": "约1万",
                "reason": "走势墨迹，清仓调仓",
                "confidence": 0.9,
                "source": "text",
            },
        ]
        image_ops = [
            {
                "action": "买入确认中",
                "time": "06-24 13:59:41",
                "amount": "10,000.00元",
                "fund_name": "华泰柏瑞质量成长混合C",
                "fund_code": "011452",
            },
            {
                "action": "买入确认中",
                "time": "06-24 13:59:18",
                "amount": "50,000.00元",
                "fund_name": "富国上海金ETF联接C",
                "fund_code": "009505",
            },
            {
                "action": "卖出确认中",
                "time": "06-24 13:58:16",
                "shares": "51,690.12份",
                "fund_name": "景顺长城中证港股通创新药ETF联接C",
                "fund_code": None,
            },
            {
                "action": "卖出确认中",
                "time": "06-24 13:57:36",
                "shares": "16,130.33份",
                "fund_name": "天弘恒生沪深港创新药精选50ETF发起联接C",
                "fund_code": None,
            },
            {"action": "种植", "target": "CPO"},
            {"action": "种植", "target": "上海金"},
        ]

        merged = _merge_operations(text_ops, image_ops)

        self.assertEqual(len(merged), 4)
        by_code = {op.get("fund_code"): op for op in merged if op.get("fund_code")}
        self.assertEqual(by_code["009505"]["action"], "定投")
        self.assertEqual(by_code["009505"]["amount_or_ratio"], "5万")
        self.assertEqual(by_code["009505"]["sector"], "黄金")
        self.assertEqual(by_code["011452"]["action"], "定投")
        self.assertEqual(by_code["011452"]["amount_or_ratio"], "1万")
        self.assertEqual(by_code["011452"]["sector"], "科技")

        names = {_coerce_str(op.get("fund_name")) for op in merged}
        self.assertIn("景顺长城中证港股通创新药ETF联接C", names)
        self.assertIn("天弘恒生沪深港创新药精选50ETF发起联接C", names)

        actions = {op.get("fund_name"): op.get("action") for op in merged}
        self.assertEqual(actions["景顺长城中证港股通创新药ETF联接C"], "减仓")
        self.assertEqual(actions["天弘恒生沪深港创新药精选50ETF发起联接C"], "卖出")

    def test_vision_type_field_merge(self):
        """Vision model may return type/amount instead of action/amount_or_ratio."""
        text_ops = [
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "上海金",
                "sector": "黄金",
                "amount_or_ratio": "5万",
                "reason": "均衡配置",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "CPO",
                "sector": "科技",
                "amount_or_ratio": "1万",
                "reason": "核心科技",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "减仓",
                "fund_code": "",
                "fund_name": "景顺港药",
                "sector": "医药",
                "amount_or_ratio": "6万",
                "reason": "调仓",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "卖出",
                "fund_code": "",
                "fund_name": "天弘药",
                "sector": "医药",
                "amount_or_ratio": "1万",
                "reason": "清仓",
                "confidence": 0.9,
                "source": "text",
            },
        ]
        image_ops = [
            {
                "type": "买入",
                "status": "确认中",
                "amount": 10000.0,
                "fund_name": "华泰柏瑞质量成长混合C",
                "fund_code": "011452",
            },
            {
                "type": "买入",
                "status": "确认中",
                "amount": 50000.0,
                "fund_name": "富国上海金ETF联接C",
                "fund_code": "009505",
            },
            {
                "type": "卖出",
                "status": "确认中",
                "shares": 51690.12,
                "fund_name": "景顺长城中证港股通创新药ETF联接C",
                "fund_code": None,
            },
            {
                "type": "卖出",
                "status": "确认中",
                "shares": 16130.33,
                "fund_name": "天弘恒生沪深港创新药精选50ETF发起联接C",
                "fund_code": None,
            },
            {"action": "种植", "target": "CPO"},
            {"action": "种植", "target": "上海金"},
        ]

        merged = _merge_operations(text_ops, image_ops)

        self.assertEqual(len(merged), 4)
        by_code = {op.get("fund_code"): op for op in merged if op.get("fund_code")}
        self.assertEqual(by_code["009505"]["action"], "定投")
        self.assertEqual(by_code["011452"]["action"], "定投")
        self.assertEqual(by_code["009505"]["amount_or_ratio"], "5万")
        self.assertEqual(by_code["011452"]["amount_or_ratio"], "1万")

    def test_drop_sector_alias_when_real_fund_covers_same_trade(self):
        ops = [
            {
                "action": "定投",
                "fund_code": "011452",
                "fund_name": "华泰柏瑞质量成长混合C",
                "sector": "科技",
                "amount_or_ratio": "1万",
                "source": "merged",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "CPO",
                "sector": "科技",
                "amount_or_ratio": "1万",
                "source": "text",
            },
            {
                "action": "定投",
                "fund_code": "009505",
                "fund_name": "富国上海金ETF联接C",
                "sector": "黄金",
                "amount_or_ratio": "5万",
                "source": "merged",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "上海金",
                "sector": "黄金",
                "amount_or_ratio": "5万",
                "source": "text",
            },
        ]

        filtered = _drop_sector_alias_duplicates(ops)

        self.assertEqual(len(filtered), 2)
        names = {_coerce_str(op.get("fund_name")) for op in filtered}
        self.assertIn("华泰柏瑞质量成长混合C", names)
        self.assertIn("富国上海金ETF联接C", names)
        self.assertNotIn("CPO", names)
        self.assertNotIn("上海金", names)

    def test_lanjing_623_sector_only_text_matches_fund_by_amount(self):
        text_ops = [
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "",
                "sector": "国产算力",
                "amount_or_ratio": "5万",
                "reason": "科技回踩，定投小加",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "",
                "sector": "CPO",
                "amount_or_ratio": "1万",
                "reason": "科技回踩，定投小加",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "观望",
                "fund_code": "",
                "fund_name": "",
                "sector": "有色",
                "amount_or_ratio": "20万",
                "reason": "波动比较大，不建议贸然去抄底",
                "confidence": 0.9,
                "source": "text",
            },
        ]
        image_ops = [
            {
                "action": "买入",
                "fund_name": "华泰柏瑞质量成长混合C",
                "fund_code": "011452",
                "amount": "10,000.00元",
                "shares": "",
            },
            {
                "action": "买入",
                "fund_name": "宏利半导体产业混合发起C",
                "fund_code": "021511",
                "amount": "50,000.00元",
                "shares": "",
            },
            {"action": "买入", "fund_name": "CPO"},
            {"action": "买入", "fund_name": "国产算力"},
        ]

        merged = _merge_operations(text_ops, image_ops)

        self.assertEqual(len(merged), 3)
        by_code = {op.get("fund_code"): op for op in merged if op.get("fund_code")}
        self.assertEqual(by_code["021511"]["action"], "定投")
        self.assertEqual(by_code["021511"]["sector"], "国产算力")
        self.assertEqual(by_code["021511"]["amount_or_ratio"], "5万")
        self.assertEqual(by_code["021511"]["source"], "merged")
        self.assertEqual(by_code["011452"]["action"], "定投")
        self.assertEqual(by_code["011452"]["sector"], "CPO")
        self.assertEqual(by_code["011452"]["amount_or_ratio"], "1万")
        alerts = [op for op in merged if op.get("action") == "观望"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["sector"], "有色")

    def test_lanjing_623_sector_alert_parsed_for_storage(self):
        merged = [{
            "action": "观望",
            "sector": "有色",
            "amount_or_ratio": "20万",
            "reason": "波动比较大，不建议贸然去抄底",
            "source": "text",
        }]
        settings = __import__("src.config", fromlist=["get_settings"]).get_settings()
        pipeline = ParsePipeline(settings)
        ops = [_to_parsed_operation(item, pipeline.resolver, settings) for item in merged]
        self.assertEqual(len(ops), 1)
        self.assertTrue(pipeline.should_save_sector_alert(ops[0]))
        self.assertFalse(pipeline.should_auto_store(ops[0]))
        self.assertFalse(pipeline.should_review(ops[0]))

    def test_append_risk_alerts_when_no_trades(self):
        merged = _append_risk_alerts_to_merged([], [
            {
                "sector": "有色",
                "reason": "波动比较大，不建议贸然去抄底",
                "amount_or_ratio": "20万",
            },
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["action"], "观望")
        self.assertEqual(merged[0]["sector"], "有色")
        self.assertTrue(merged[0]["_sector_alert"])

    def test_append_risk_alerts_dedupes_existing_sector_alert(self):
        merged = _append_risk_alerts_to_merged([
            {
                "action": "观望",
                "sector": "有色",
                "reason": "已有",
                "_sector_alert": True,
            },
        ], [
            {"sector": "有色", "reason": "重复"},
            {"sector": "黄金", "reason": "金价高位谨慎"},
        ])
        self.assertEqual(len(merged), 2)
        sectors = {op["sector"] for op in merged}
        self.assertEqual(sectors, {"有色", "黄金"})

    def test_tiantian_626_analytical_text_image_first(self):
        """正文按板块分析、截图才是成交：过滤模糊 sector 行，并把 reason 挂到截图基金上。"""
        text_ops = [
            {
                "action": "减仓",
                "fund_code": "",
                "fund_name": "",
                "sector": "航天",
                "amount_or_ratio": "2w和1W",
                "reason": "调仓到cpo和半导体",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "加仓",
                "fund_code": "",
                "fund_name": "",
                "sector": "CPO",
                "amount_or_ratio": "调仓",
                "reason": "调仓2w和1W航天到cpo和半导体",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "加仓",
                "fund_code": "",
                "fund_name": "",
                "sector": "半导体",
                "amount_or_ratio": "调仓",
                "reason": "调仓2w和1W航天到cpo和半导体",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "",
                "sector": "海外",
                "amount_or_ratio": "",
                "reason": "定投海外，总体可以不动",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "",
                "sector": "半导体",
                "amount_or_ratio": "一点",
                "reason": "趁回调今天定投一点，存储短缺、产能扩建、半导体材料提价，业绩确定",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "",
                "sector": "存储芯片",
                "amount_or_ratio": "",
                "reason": "趁回调，定投一下存储芯片，存储超级周期并未结束",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "加仓",
                "fund_code": "",
                "fund_name": "",
                "sector": "CPO",
                "amount_or_ratio": "重仓",
                "reason": "补一点cpo，利用此次回调继续布局一下重仓，AI算力扩张对高速互联的需求是确定性趋势",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "",
                "sector": "中小盘",
                "amount_or_ratio": "一点",
                "reason": "继续定投一点中小盘，科技整体回调，趁回调继续布局",
                "confidence": 0.9,
                "source": "text",
            },
            {
                "action": "定投",
                "fund_code": "",
                "fund_name": "",
                "sector": "海外",
                "amount_or_ratio": "1k",
                "reason": "定投1k海外基，适合长期持有，拿它来平衡风险",
                "confidence": 0.9,
                "source": "text",
            },
        ]
        image_ops = [
            {
                "action": "买入",
                "fund_name": "招商中证半导体产业ETF联接C",
                "amount": "11,881.65元",
                "shares": "",
            },
            {
                "action": "买入",
                "fund_name": "东吴多策略灵活配置混合C",
                "amount": "14,205.55元",
            },
        ]

        filtered = _filter_analytical_text_operations(text_ops, image_ops)
        self.assertEqual(len(filtered), 0)

        annotations = [
            {
                "sector": "半导体",
                "reason": "趁回调今天定投一点，存储短缺、产能扩建、半导体材料提价，业绩确定",
                "keywords": ["半导体", "芯片", "存储"],
            },
            {
                "sector": "中小盘",
                "reason": "继续定投一点中小盘，科技整体回调，趁回调继续布局",
                "keywords": ["中小盘", "多策略"],
            },
        ]

        merged = _merge_operations(filtered, image_ops)
        merged = _enrich_fund_ops_from_annotations(merged, annotations)
        merged = _enrich_fund_ops_from_text_analysis(merged, [])

        self.assertEqual(len(merged), 2)
        by_name = {op["fund_name"]: op for op in merged}
        semi = by_name["招商中证半导体产业ETF联接C"]
        self.assertEqual(semi["sector"], "半导体")
        self.assertIn("存储", semi["reason"])
        duo = by_name["东吴多策略灵活配置混合C"]
        self.assertEqual(duo["sector"], "中小盘")
        self.assertIn("中小盘", duo["reason"])

    def test_infer_sector_from_fund_name(self):
        from src.parse.pipeline import _infer_sector_from_fund_name

        self.assertEqual(_infer_sector_from_fund_name("招商中证半导体产业ETF联接C"), "半导体")
        self.assertEqual(_infer_sector_from_fund_name("东吴多策略灵活配置混合C"), "中小盘")


def _coerce_str(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "null" else text


if __name__ == "__main__":
    unittest.main()
