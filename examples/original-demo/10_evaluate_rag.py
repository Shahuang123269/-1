r"""Day 10: run a no-cost regression benchmark for the local RAG retriever.

Run:
    .\.venv\Scripts\python.exe 10_evaluate_rag.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag_evaluation import evaluate_retrieval, hit_rate, load_cases


DEFAULT_CASES_PATH = Path(__file__).with_name("evals") / "rag_retrieval_cases.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local RAG retrieval regression tests.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH, help="评测样例 JSON 文件路径。")
    parser.add_argument("--top-k", type=int, default=3, help="每个问题检查前几个检索结果。")
    parser.add_argument("--min-hit-rate", type=float, default=1.0, help="最低通过率，默认 1.0。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.top_k < 1 or not 0 <= args.min_hit_rate <= 1:
        print("--top-k 必须大于 0，--min-hit-rate 必须在 0 到 1 之间。")
        return 2
    try:
        results = evaluate_retrieval(load_cases(args.cases), limit=args.top_k)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"无法运行评测：{error}")
        return 2

    for result in results:
        state = "通过" if result.passed else "失败"
        sources = ", ".join(result.retrieved_sources) or "无结果"
        expected = ", ".join(result.case.expected_sources)
        print(f"[{state}] {result.case.case_id}: 期望 {expected}；检索到 {sources}")
    score = hit_rate(results)
    print(f"\n[评测结果] Hit@{args.top_k}: {score:.0%}（{sum(item.passed for item in results)}/{len(results)}）")
    return 0 if score >= args.min_hit_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
