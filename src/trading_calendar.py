"""
證交所交易日曆：週末與國定假日都不是交易日。

請求日期與報表日期都必須落在交易日。只避開週末的話，國定假日會被當成交易日：
摩根 PCF 的估值日是下一交易日，會被夾回假日寫進 DB，DB 最新日期變成假日，
產生一份內容等於前一交易日的假報表（2026-09-25 中秋即為一例）。

休市日取自證交所 OpenAPI（Date 為民國年 YYYMMDD）：
    https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule
這份清單混有「國曆新年開始交易日」「農曆春節前最後交易日」等**有開盤**的日子，
只收名稱不含「開始交易」「最後交易」的列；「市場無交易，僅辦理結算交割作業」要收。
週末本來就休市，不必列。

**每年要補下一年的清單**，未涵蓋的年份只排除週末（假日又會產生假報表）。
颱風假不在證交所的清單內，發生時手動補上。
"""
from datetime import date, timedelta

from loguru import logger

# 證交所平日休市日（不含週末），以年份分組
TWSE_CLOSED_WEEKDAYS = {
    2026: frozenset({
        "2026-01-01",  # 開國紀念日
        "2026-02-12", "2026-02-13",  # 市場無交易，僅辦理結算交割作業
        "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",  # 農曆春節（含補假）
        "2026-02-27",  # 和平紀念日補假
        "2026-04-03",  # 兒童節補假
        "2026-04-06",  # 民族掃墓節補假
        "2026-05-01",  # 勞動節
        "2026-06-19",  # 端午節
        "2026-09-25",  # 中秋節
        "2026-09-28",  # 教師節
        "2026-10-09",  # 國慶日補假
        "2026-10-26",  # 臺灣光復暨金門古寧頭大捷紀念日補假
        "2026-12-25",  # 行憲紀念日
    }),
}

_warned_years = set()


def is_trading_day(day: date) -> bool:
    """day 是否為證交所交易日（接受 date 或 datetime）。"""
    if day.weekday() >= 5:
        return False
    closed = TWSE_CLOSED_WEEKDAYS.get(day.year)
    if closed is None:
        if day.year not in _warned_years:
            _warned_years.add(day.year)
            logger.warning(
                f"No TWSE holiday list for {day.year} in src/trading_calendar.py; "
                f"only weekends are treated as closed until that year is added"
            )
        return True
    return day.strftime("%Y-%m-%d") not in closed


def last_trading_day(day: date) -> date:
    """不晚於 day 的最近一個交易日：週末與國定假日都往前退（傳入 datetime 就回 datetime）。"""
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day
