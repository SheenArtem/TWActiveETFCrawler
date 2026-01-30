"""
测试 EZMoney Excel 下载方法
"""
from datetime import datetime
from src.ezmoney_scraper import EZMoneyScraper
from loguru import logger

def test_ezmoney_excel_download():
    """测试 EZMoney 的 Excel 下载功能"""
    scraper = EZMoneyScraper()
    
    etf_code = '00981A'
    fund_code = scraper.get_fund_code(etf_code)
    
    if not fund_code:
        logger.error(f"ETF {etf_code} not found in mapping")
        return
    
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    
    logger.info("="*60)
    logger.info(f"Testing EZMoney Excel download for {etf_code}")
    logger.info(f"Fund Code: {fund_code}")
    logger.info(f"Date: {today_str}")
    logger.info("="*60)
    
    # 測試 Excel 下載方法
    logger.info("\n[Test] Downloading portfolio Excel from website")
    holdings = scraper.get_etf_holdings(etf_code, today_str, use_excel=True)
    
    if holdings:
        logger.info(f"\n✅ SUCCESS: Downloaded and parsed {len(holdings)} holdings")
        logger.info("\nFirst 5 holdings:")
        for i, holding in enumerate(holdings[:5], 1):
            logger.info(f"  {i}. {holding['stock_code']} {holding['stock_name']}: "
                       f"{holding['shares']:,} shares, weight={holding['weight']:.2f}%")
        
        if len(holdings) > 5:
            logger.info(f"  ... and {len(holdings) - 5} more holdings")
    else:
        logger.error("\n❌ FAILED: No holdings found")
    
    logger.info("\n" + "="*60)

if __name__ == '__main__':
    test_ezmoney_excel_download()
