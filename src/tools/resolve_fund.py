"""Test fund name → code resolution (East Money search)."""

from __future__ import annotations

import argparse
import sys

from src.config import get_settings
from src.parse.fund_resolver import FundResolver
from src.utils.fund_name import normalize_fund_name


def resolve_one(name: str, code: str = "") -> int:
    resolver = FundResolver(get_settings().cache_dir)
    result = resolver.resolve(name, code)

    print(f"输入名称: {name}")
    if code:
        print(f"输入代码: {code}")
    print(f"规范化:   {normalize_fund_name(name)}")
    print(f"解析名称: {result.fund_name}")
    print(f"原始名称: {result.fund_name_raw}")
    print(f"基金代码: {result.fund_code or '(未匹配)'}")
    print(f"来源:     {result.fund_code_source}")
    print(f"唯一匹配: {result.unique_match}")

    if result.candidates:
        print(f"\n东财候选 ({len(result.candidates)} 条，前 10 条):")
        for index, candidate in enumerate(result.candidates[:10], start=1):
            mark = "  ← 已选中" if candidate.code == result.fund_code else ""
            print(f"  {index:2}. {candidate.code}  {candidate.name}{mark}")
    else:
        print("\n东财候选: 无（可能网络问题，或关键词未命中基金）")

    return 0 if result.fund_code else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="测试基金名称/代码解析（FundResolver + 东财搜索）"
    )
    parser.add_argument("--name", required=True, help="基金名称，如 招商中证半导体产业ETF联接C")
    parser.add_argument("--code", default="", help="可选，截图/OCR 中的 6 位代码")
    args = parser.parse_args()
    sys.exit(resolve_one(args.name, args.code.strip()))


if __name__ == "__main__":
    main()
