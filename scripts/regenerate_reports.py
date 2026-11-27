"""
重畫全部已發布的報表：名稱對照表（data/stock_names.json）或報表資料改了之後用。
只改日報版面時，執行 python scripts/render_report_pages.py 可直接沿用已發布的 JSON。

每檔 ETF 的資料日期固定在發布當時的值，只有內容照 DB 與現行程式重畫
（scripts/pinned_reports.py 的 refresh 模式）；內容沒變的報表不會被改寫。

不要改回「每檔取不晚於報表日期的最新資料」的整份重生：固定落後一天的來源（第一金、00988A）
事後 DB 已經補齊，整份重生會把它們在舊報表裡的資料日期整串往前推，原本那一天的變動就不在任何
報表裡了（見 .ai/guides/date-alignment.md「整串平移」）。事後補了某幾檔的持股、要讓報表換成新資料，
用 scripts/pinned_reports.py --etf。

執行：
    python scripts/regenerate_reports.py            # 重畫並寫回
    python scripts/regenerate_reports.py --dry-run  # 只列出哪幾份會變
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loguru import logger  # noqa: E402

import pinned_reports  # noqa: E402
from src.database import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="重畫全部已發布的報表（資料日期固定在發布當時的值）")
    parser.add_argument("--dry-run", action="store_true", help="只核對、不寫回")
    args = parser.parse_args()
    logger.remove()

    etf_codes = [e["etf_code"] for e in Database(str(pinned_reports.DB_PATH)).get_active_etfs()]
    results = pinned_reports.regenerate(pinned_reports.published_dates(), refresh_etfs=etf_codes,
                                        write=not args.dry_run)
    ok = pinned_reports.print_results([r for r in results if r["status"] != "unchanged"])
    print(f"{sum(r['status'] == 'unchanged' for r in results)} 份內容沒變，"
          f"{sum(r['changed'] for r in results)} 份{'會' if args.dry_run else '已'}改寫")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
