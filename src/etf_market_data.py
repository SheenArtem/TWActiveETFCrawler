"""
ETF 市場資料模組 - 從證交所及 Yahoo Finance 取得 ETF 基金規模、市價、成交金額等資訊
"""
import json
import re
import requests
import time
import urllib3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any
from loguru import logger
from fake_useragent import UserAgent

# TWSE 的 SSL 憑證在某些環境下會驗證失敗，停用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ETFMarketDataFetcher:
    """從 TWSE 取得 ETF 市場資料（市價、成交金額、漲跌等）"""

    # TWSE OpenData API - 每日收盤行情（全部）
    TWSE_STOCK_DAY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"

    # TWSE 即時行情 API
    TWSE_STOCK_INFO_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or Path("docs")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ua = UserAgent()

    def _get_headers(self) -> dict:
        return {
            "User-Agent": self.ua.random,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.twse.com.tw/",
        }

    def fetch_stock_day_all(self) -> Dict[str, Dict[str, Any]]:
        """
        從 TWSE OpenData 取得所有上市股票/ETF 每日收盤行情

        Returns:
            Dict[str, Dict]: 證券代號 -> 行情資料
        """
        logger.info("Fetching STOCK_DAY_ALL from TWSE OpenData")

        try:
            resp = requests.get(
                self.TWSE_STOCK_DAY_ALL_URL,
                headers=self._get_headers(),
                timeout=30,
                verify=False,
            )
            resp.raise_for_status()
            data = resp.json()

            results = {}
            for item in data:
                code = item.get("Code", "")
                results[code] = {
                    "name": item.get("Name", ""),
                    "trade_volume": int(item.get("TradeVolume", "0") or "0"),
                    "trade_value": int(item.get("TradeValue", "0") or "0"),
                    "close": float(item.get("ClosingPrice", "0") or "0"),
                    "change": float(item.get("Change", "0") or "0"),
                    "open": float(item.get("OpeningPrice", "0") or "0"),
                    "high": float(item.get("HighestPrice", "0") or "0"),
                    "low": float(item.get("LowestPrice", "0") or "0"),
                    "transaction": int(item.get("Transaction", "0") or "0"),
                }

            logger.info(f"Fetched STOCK_DAY_ALL: {len(results)} records")
            return results

        except Exception as e:
            logger.error(f"Failed to fetch STOCK_DAY_ALL: {e}")
            return {}

    def fetch_realtime_price(self, etf_codes: List[str]) -> Dict[str, Dict]:
        """
        從 TWSE 即時行情取得 ETF 市價

        Args:
            etf_codes: ETF 代碼列表

        Returns:
            Dict[str, Dict]: ETF 代碼 -> 行情資料
        """
        ex_ch = "|".join(f"tse_{code}.tw" for code in etf_codes)

        logger.info(f"Fetching realtime price for {len(etf_codes)} ETFs")

        try:
            resp = requests.get(
                self.TWSE_STOCK_INFO_URL,
                params={"ex_ch": ex_ch},
                headers=self._get_headers(),
                timeout=30,
                verify=False,
            )
            resp.raise_for_status()
            data = resp.json()

            results = {}
            for item in data.get("msgArray", []):
                code = item.get("c", "")
                results[code] = {
                    "price": item.get("z", "-"),       # 成交價
                    "yesterday": item.get("y", "-"),    # 昨收
                    "open": item.get("o", "-"),         # 開盤價
                    "high": item.get("h", "-"),         # 最高
                    "low": item.get("l", "-"),          # 最低
                    "volume": item.get("v", "-"),       # 成交量（張）
                    "name": item.get("n", ""),          # 名稱
                    "full_name": item.get("nf", ""),    # 全名
                }

            logger.info(f"Fetched realtime price for {len(results)} ETFs")
            return results

        except Exception as e:
            logger.error(f"Failed to fetch realtime price: {e}")
            return {}

    def fetch_yahoo_fund_size(self, etf_codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        從 Yahoo Finance TW 的 profile 頁面爬取 ETF 基金規模 (totalAssets)

        Yahoo Finance 的 profile 頁面 HTML 中內嵌了 totalAssets 欄位，
        可透過簡單的 HTTP GET + regex 擷取，無需 Playwright。

        Args:
            etf_codes: ETF 代碼列表

        Returns:
            Dict[str, Dict]: ETF 代碼 -> {total_assets, total_assets_date}
        """
        results = {}
        yahoo_url = "https://tw.stock.yahoo.com/quote/{code}/profile"

        logger.info(f"Fetching fund size from Yahoo Finance for {len(etf_codes)} ETFs")

        for i, code in enumerate(etf_codes):
            try:
                url = yahoo_url.format(code=code)
                resp = requests.get(
                    url,
                    headers={
                        "User-Agent": self.ua.random,
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Language": "zh-TW,zh;q=0.9",
                    },
                    timeout=15,
                    verify=False,
                )
                resp.raise_for_status()
                html = resp.text

                # 擷取 totalAssets（基金總資產，單位：元）
                m_assets = re.search(r'"totalAssets":"([^"]+)"', html)
                total_assets = 0
                if m_assets:
                    try:
                        total_assets = float(m_assets.group(1))
                    except ValueError:
                        pass

                # 擷取 totalAssetsDate（資產日期）
                m_date = re.search(r'"totalAssetsDate":"([^"]+)"', html)
                assets_date = ""
                if m_date:
                    assets_date = m_date.group(1).replace("\\u002F", "/")

                if total_assets > 0:
                    results[code] = {
                        "total_assets": total_assets,
                        "total_assets_billion": round(total_assets / 1e8, 2),  # 億元
                        "total_assets_date": assets_date,
                    }
                    logger.debug(
                        f"{code}: totalAssets={total_assets/1e8:.2f} 億 ({assets_date})"
                    )

                # 禮貌性延遲，避免被封鎖
                if i < len(etf_codes) - 1:
                    time.sleep(0.5)

            except Exception as e:
                logger.warning(f"Failed to fetch Yahoo Finance data for {code}: {e}")

        logger.info(f"Fetched fund size for {len(results)}/{len(etf_codes)} ETFs from Yahoo Finance")
        return results

    def get_etf_market_data(self, tracked_etf_codes: List[str]) -> List[Dict[str, Any]]:
        """
        取得追蹤中 ETF 的完整市場資料

        Args:
            tracked_etf_codes: 追蹤中的 ETF 代碼列表

        Returns:
            List[Dict]: 每檔 ETF 的市場資料，按成交金額降序排列
        """
        tracked_set = set(tracked_etf_codes)
        etf_map = {}

        # 1. 從 STOCK_DAY_ALL 取得前一交易日收盤行情
        day_all = self.fetch_stock_day_all()
        for code in tracked_set:
            if code in day_all:
                d = day_all[code]
                etf_map[code] = {
                    "etf_code": code,
                    "etf_name": d["name"],
                    "price": d["close"],
                    "change": d["change"],
                    "change_pct": round(d["change"] / (d["close"] - d["change"]) * 100, 2)
                        if (d["close"] - d["change"]) != 0 else 0,
                    "trade_value": d["trade_value"],          # 成交金額（元）
                    "trade_value_billion": round(d["trade_value"] / 1e8, 2),  # 成交金額（億元）
                    "trade_volume": d["trade_volume"],        # 成交股數
                    "trade_volume_lots": d["trade_volume"] // 1000,  # 成交張數
                    "high": d["high"],
                    "low": d["low"],
                }

        # 2. 用即時行情補充/更新資料
        realtime = self.fetch_realtime_price(list(tracked_set))
        for code, rt in realtime.items():
            if code not in tracked_set:
                continue

            rt_price = 0
            if rt["price"] != "-":
                try:
                    rt_price = float(rt["price"])
                except ValueError:
                    pass

            rt_yesterday = 0
            if rt["yesterday"] != "-":
                try:
                    rt_yesterday = float(rt["yesterday"])
                except ValueError:
                    pass

            if code in etf_map:
                # 用即時價格更新（如果有更新的數據）
                if rt_price > 0:
                    etf_map[code]["price"] = rt_price
                    if rt_yesterday > 0:
                        change = round(rt_price - rt_yesterday, 2)
                        etf_map[code]["change"] = change
                        etf_map[code]["change_pct"] = round(change / rt_yesterday * 100, 2)
            else:
                # 日收盤資料中沒有的 ETF，用即時行情建立
                change = round(rt_price - rt_yesterday, 2) if rt_price > 0 and rt_yesterday > 0 else 0
                change_pct = round(change / rt_yesterday * 100, 2) if rt_yesterday > 0 else 0
                etf_map[code] = {
                    "etf_code": code,
                    "etf_name": rt.get("name", code),
                    "price": rt_price,
                    "change": change,
                    "change_pct": change_pct,
                    "trade_value": 0,
                    "trade_value_billion": 0,
                    "trade_volume": 0,
                    "trade_volume_lots": int(rt["volume"]) if rt["volume"] != "-" else 0,
                    "high": float(rt["high"]) if rt["high"] != "-" else 0,
                    "low": float(rt["low"]) if rt["low"] != "-" else 0,
                }

        # 3. 從 Yahoo Finance 取得基金規模（totalAssets）
        yahoo_data = self.fetch_yahoo_fund_size(list(tracked_set))
        for code, yd in yahoo_data.items():
            if code in etf_map:
                etf_map[code]["aum"] = yd["total_assets"]
                etf_map[code]["aum_billion"] = yd["total_assets_billion"]
                etf_map[code]["aum_date"] = yd["total_assets_date"]
            elif code in tracked_set:
                etf_map[code] = {
                    "etf_code": code,
                    "etf_name": code,
                    "price": 0, "change": 0, "change_pct": 0,
                    "trade_value": 0, "trade_value_billion": 0,
                    "trade_volume": 0, "trade_volume_lots": 0,
                    "high": 0, "low": 0,
                    "aum": yd["total_assets"],
                    "aum_billion": yd["total_assets_billion"],
                    "aum_date": yd["total_assets_date"],
                }

        # 4. 確保所有追蹤的 ETF 都有記錄
        for code in tracked_set:
            if code not in etf_map:
                etf_map[code] = {
                    "etf_code": code,
                    "etf_name": code,
                    "price": 0, "change": 0, "change_pct": 0,
                    "trade_value": 0, "trade_value_billion": 0,
                    "trade_volume": 0, "trade_volume_lots": 0,
                    "high": 0, "low": 0,
                    "aum": 0, "aum_billion": 0, "aum_date": "",
                }
            # 確保 aum 欄位存在
            etf_map[code].setdefault("aum", 0)
            etf_map[code].setdefault("aum_billion", 0)
            etf_map[code].setdefault("aum_date", "")

        # 5. 按基金規模降序排列（AUM 優先；若無 AUM 則按成交金額）
        result = sorted(
            etf_map.values(),
            key=lambda x: (x.get("aum_billion", 0), x.get("trade_value", 0)),
            reverse=True,
        )

        logger.info(f"Compiled market data for {len(result)} tracked ETFs")
        return result

    def save_market_data(self, tracked_etf_codes: List[str], etf_info_dict: Dict[str, str] = None) -> Path:
        """
        取得並儲存 ETF 市場資料為 JSON

        Args:
            tracked_etf_codes: 追蹤中的 ETF 代碼列表
            etf_info_dict: ETF 代碼 -> 名稱 對照（用於補充名稱）

        Returns:
            Path: JSON 檔案路徑
        """
        market_data = self.get_etf_market_data(tracked_etf_codes)

        # 用 etf_info_dict 補充名稱
        if etf_info_dict:
            for item in market_data:
                code = item["etf_code"]
                if code in etf_info_dict and (
                    not item.get("etf_name") or item["etf_name"] == code
                ):
                    item["etf_name"] = etf_info_dict[code]

        output = {
            "update_time": (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"),
            "etf_count": len(market_data),
            "data": market_data,
        }

        output_file = self.output_dir / "etf_market_data.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(f"ETF market data saved to {output_file}")
        return output_file
