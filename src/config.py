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

# 台灣證交所 API 端點
TWSE_ETF_LIST_URL = os.getenv(
    "TWSE_ETF_LIST_URL",
    "https://www.twse.com.tw/zh/ETF/etfList"
)
TWSE_ETF_HOLDINGS_URL = os.getenv(
    "TWSE_ETF_HOLDINGS_URL",
    "https://www.twse.com.tw/rwd/zh/fund/etfHoldings"
)

# 爬蟲設定
REQUEST_DELAY_MIN = float(os.getenv("REQUEST_DELAY_MIN", "1.0"))
REQUEST_DELAY_MAX = float(os.getenv("REQUEST_DELAY_MAX", "3.0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
BATCH_DELAY_MIN = float(os.getenv("BATCH_DELAY_MIN", "5.0"))
BATCH_DELAY_MAX = float(os.getenv("BATCH_DELAY_MAX", "10.0"))

# 日誌設定
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_PATH = BASE_DIR / os.getenv("LOG_PATH", "logs/etf_crawler.log")

# 確保必要目錄存在
def ensure_directories():
    """確保必要的目錄存在"""
    (BASE_DIR / "data").mkdir(exist_ok=True)
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# 初始化時建立目錄
ensure_directories()
