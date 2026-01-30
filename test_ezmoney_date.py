"""
测试 EZMoney API 的日期逻辑
验证是 T+0 (当天公布当天数据) 还是 T+1 (明天公布今天数据)
"""
from datetime import datetime, timedelta
from src.ezmoney_scraper import EZMoneyScraper
from loguru import logger

def test_ezmoney_date_logic():
    """测试 EZMoney 的数据公告日期逻辑"""
    scraper = EZMoneyScraper()
    
    etf_code = '00981A'
    fund_code = scraper.get_fund_code(etf_code)
    
    if not fund_code:
        logger.error(f"ETF {etf_code} not found in mapping")
        return
    
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    
    today_str = today.strftime('%Y-%m-%d')
    tomorrow_str = tomorrow.strftime('%Y-%m-%d')
    
    logger.info("="*60)
    logger.info(f"Testing EZMoney date logic for {etf_code}")
    logger.info(f"Today: {today_str}")
    logger.info(f"Tomorrow: {tomorrow_str}")
    logger.info("="*60)
    
    # 测试1: 查询明天的日期 (T+1 逻辑)
    logger.info("\n[Test 1] Querying with TOMORROW's date (T+1 logic)")
    data_tomorrow = scraper.get_pcf_data(fund_code, tomorrow_str)
    
    if data_tomorrow and data_tomorrow.get('asset'):
        logger.info("✅ SUCCESS: Data found with TOMORROW's date")
        logger.info(f"   Found {len(data_tomorrow.get('asset', []))} asset categories")
    else:
        logger.warning("❌ FAILED: No data found with TOMORROW's date")
    
    # 测试2: 查询今天的日期 (T+0 逻辑)
    logger.info("\n[Test 2] Querying with TODAY's date (T+0 logic)")
    data_today = scraper.get_pcf_data(fund_code, today_str)
    
    if data_today and data_today.get('asset'):
        logger.info("✅ SUCCESS: Data found with TODAY's date")
        logger.info(f"   Found {len(data_today.get('asset', []))} asset categories")
    else:
        logger.warning("❌ FAILED: No data found with TODAY's date")
    
    # 测试3: 查询昨天的日期
    yesterday = today - timedelta(days=1)
    yesterday_str = yesterday.strftime('%Y-%m-%d')
    
    logger.info(f"\n[Test 3] Querying with YESTERDAY's date ({yesterday_str})")
    data_yesterday = scraper.get_pcf_data(fund_code, yesterday_str)
    
    if data_yesterday and data_yesterday.get('asset'):
        logger.info("✅ SUCCESS: Data found with YESTERDAY's date")
        logger.info(f"   Found {len(data_yesterday.get('asset', []))} asset categories")
    else:
        logger.warning("❌ FAILED: No data found with YESTERDAY's date")
    
    # 总结
    logger.info("\n" + "="*60)
    logger.info("SUMMARY:")
    logger.info("="*60)
    
    if data_tomorrow and data_tomorrow.get('asset'):
        logger.info("📊 EZMoney uses T+1 logic: Use TOMORROW's date to query TODAY's holdings")
    elif data_today and data_today.get('asset'):
        logger.info("📊 EZMoney uses T+0 logic: Use TODAY's date to query TODAY's holdings")
    elif data_yesterday and data_yesterday.get('asset'):
        logger.info("📊 EZMoney uses T-1 logic: Use YESTERDAY's date (delayed data)")
    else:
        logger.error("❌ No data found with any date! Check API or network issues")

if __name__ == '__main__':
    test_ezmoney_date_logic()
