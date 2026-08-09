"""
配置管理模組
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 專案根目錄
BASE_DIR = Path(__file__).parent.parent

# 資料庫設定
DB_PATH = os.getenv("DB_PATH", "data/etf_holdings.db")
DB_FULL_PATH = BASE_DIR / DB_PATH

# 資料保留設定
DATA_RETENTION_DAYS = int(os.getenv("DATA_RETENTION_DAYS", "365"))

# 爬蟲設定
REQUEST_DELAY_MIN = float(os.getenv("REQUEST_DELAY_MIN", "1.0"))
REQUEST_DELAY_MAX = float(os.getenv("REQUEST_DELAY_MAX", "3.0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
BATCH_DELAY_MIN = float(os.getenv("BATCH_DELAY_MIN", "5.0"))
BATCH_DELAY_MAX = float(os.getenv("BATCH_DELAY_MAX", "10.0"))

# 日誌設定
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_PATH = BASE_DIR / os.getenv("LOG_PATH", "logs/etf_crawler.log")

# 日期錯位防護
# 若某 ETF 這次抓到的持股與「前一交易日」逐列完全相同（股票、股數、權重都一樣），
# 判定為投信尚未更新當日 PCF，不寫入並記錄警告，避免把前一日資料標成當日。
#
# 只對「用請求日期當資料日期」的來源生效。2026-08-09（新增兆豐/凱基/永豐）後：
# - source_dated 豁免（scraper 從來源取得日期）：中信、富邦、第一金、聯博、
#   統一（Excel 路徑）、台新、安聯、群益（buyback API 路徑）、
#   兆豐、凱基、永豐（三家都是自頁面取得基準日）、
#   摩根（僅當 PCF 估值日領先請求日＝當日新檔時；舊檔維持防護）。
# - 仍受防護：國泰（API 無日期欄位且會靜默回退，唯一真正依賴防護的來源）、
#   野村、復華（API 嚴格遵守請求日期、結構上不會錯位，防護對它們只是備而不用）、
#   統一 API 路徑，以及所有 scraper 的「解析失敗退回請求日期」備援路徑。
# 豁免的理由：那些來源不會錯位，擋下來只會誤擋，而且誤擋無法補救
# （來源日期會往前走，被擋掉那天再也抓不回來）。
# 判斷邏輯與理由見 Database._reject_duplicate_snapshots。
#
# 背景：2026-02~08 期間錯位共發生 15 個交易日。詳見 .ai/guides/date-alignment.md。
REJECT_DUPLICATE_OF_PREVIOUS_DAY = os.getenv("REJECT_DUPLICATE_OF_PREVIOUS_DAY", "True").lower() == "true"

# 變動追蹤設定
ENABLE_CHANGE_TRACKING = os.getenv("ENABLE_CHANGE_TRACKING", "True").lower() == "true"
WEIGHT_CHANGE_THRESHOLD = float(os.getenv("WEIGHT_CHANGE_THRESHOLD", "0.5"))  # 權重變動閾值（%）
SAVE_CHANGE_REPORTS = os.getenv("SAVE_CHANGE_REPORTS", "True").lower() == "true"
REPORTS_DIR = BASE_DIR / os.getenv("REPORTS_DIR", "reports")

# 確保必要目錄存在
def ensure_directories():
    """確保必要的目錄存在"""
    (BASE_DIR / "data").mkdir(exist_ok=True)
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SAVE_CHANGE_REPORTS:
        REPORTS_DIR.mkdir(exist_ok=True)

# 初始化時建立目錄
ensure_directories()
