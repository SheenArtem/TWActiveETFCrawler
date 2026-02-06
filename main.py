"""
台灣主動式 ETF 持股追蹤系統 - 主程式
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys

from src.config import (
    DB_FULL_PATH, 
    LOG_PATH, 
    LOG_LEVEL, 
    DATA_RETENTION_DAYS, 
    BASE_DIR,
    ENABLE_CHANGE_TRACKING,
    SAVE_CHANGE_REPORTS,
    REPORTS_DIR
)
from src.database import Database
# TWSE 爬蟲已移除，改為使用各家投信官網直接爬取
from src.ezmoney_scraper import EZMoneyScraper
from src.nomura_scraper import NomuraScraper
from src.capital_scraper import CapitalScraper
from src.fhtrust_scraper import FHTrustScraper
from src.ctbc_scraper import CTBCScraper
from src.fsitc_scraper import FSITCScraper
from src.tsit_scraper import TSITScraper
from src.allianz_scraper import AllianzScraper
from src.utils import setup_logging, cleanup_old_data, get_trading_days
from src.report_manager import ReportManager
from loguru import logger


# ============================================================
# TWSE 相關函數已於 2026-01-26 移除
# 系統現在完全基於各家投信官網的直接爬取
# ============================================================

def daily_update_ezmoney(generate_report=True):
    """每日更新 EZMoney ETF 作業"""
    logger.info("Starting EZMoney ETF daily update...")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = EZMoneyScraper()
    
    # EZMoney 使用網頁下載 Excel 的方式獲取最新持股資料
    # 注意：實際資料日期會從 Excel 檔案中自動提取，這裡的日期僅作為檔名和備用
    today = datetime.now()
    storage_date_str = today.strftime('%Y-%m-%d')
    
    logger.info(f"Downloading EZMoney ETF data (actual date will be extracted from Excel)")
    
    # 取得所有已配置的 EZMoney ETF
    ezmoney_etfs = scraper.get_all_mappings()
    logger.info(f"Found {len(ezmoney_etfs)} EZMoney ETFs to update")
    
    # 確保 ETF 存在於 etf_list 表中
    etf_list_data = []
    for etf_code in ezmoney_etfs.keys():
        etf_list_data.append({
            'etf_code': etf_code,
            'etf_name': f'{etf_code} (EZMoney)',  # 可以之後手動更新名稱
            'issuer': 'EZMoney',
            'listing_date': ''
        })
    
    if etf_list_data:
        db.insert_etf_list(etf_list_data)
    
    # 逐一抓取持股明細
    total_inserted = 0
    for i, etf_code in enumerate(ezmoney_etfs.keys(), 1):
        logger.info(f"[{i}/{len(ezmoney_etfs)}] Updating {etf_code}")
        
        try:
            # 使用 Excel 下載方式獲取持股（自動從網頁獲取最新日期）
            holdings = scraper.get_etf_holdings(etf_code, storage_date_str, use_excel=True)
            
            if holdings:
                inserted = db.insert_holdings(holdings)
                total_inserted += inserted
                logger.info(f"{etf_code}: Inserted {inserted} new holdings")
            else:
                logger.warning(f"{etf_code}: No holdings data found")
        except Exception as e:
            logger.error(f"Error updating {etf_code}: {e}")
            logger.exception(e)
    
    logger.info(f"EZMoney ETF daily update complete: {total_inserted} new holdings inserted")
    
    # 變動追蹤：分析並顯示成分股變動（僅在單獨執行時生成報告）
    if generate_report and ENABLE_CHANGE_TRACKING and SAVE_CHANGE_REPORTS:
        logger.info("Analyzing holdings changes...")
        report_mgr = ReportManager(db, REPORTS_DIR)
        changes_dict = report_mgr.analyzer.detect_changes_batch(list(ezmoney_etfs.keys()), storage_date_str)
        
        if changes_dict:
            report = report_mgr.analyzer.generate_report(changes_dict, storage_date_str)
            logger.info(report)
            # 生成所有格式的報告（TXT, Markdown, HTML）
            report_mgr.generate_all_reports(changes_dict, storage_date_str, append_txt=False)
        else:
            logger.info("No significant changes detected (this may be the first time fetching data).")

    
    # 清理舊資料
    logger.info("Cleaning up old data...")
    cleanup_result = cleanup_old_data(str(DB_FULL_PATH), DATA_RETENTION_DAYS)
    logger.info(f"Cleanup result: {cleanup_result}")
    
    # 顯示統計
    stats = db.get_statistics()
    logger.info(f"Database statistics:")
    logger.info(f"  Total ETFs: {stats['total_etfs']}")
    logger.info(f"  Total holdings: {stats['total_holdings']}")
    logger.info(f"  Date range: {stats['date_range']['start']} to {stats['date_range']['end']}")



def daily_update_nomura(generate_report=True):
    """每日更新野村投信ETF 作業"""
    logger.info("Starting Nomura Funds ETF daily update...")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = NomuraScraper()
    
    # 使用今天的日期（資料通常在當晚更新）
    target_date = datetime.now()
    while target_date.weekday() >= 5:  # 避免週末
        target_date -= timedelta(days=1)
    
    date_str = target_date.strftime('%Y-%m-%d')
    logger.info(f"Fetching Nomura ETF data for {date_str}")
    
    # 取得所有已配置的野村 ETF
    nomura_etfs = scraper.get_all_mappings()
    logger.info(f"Found {len(nomura_etfs)} Nomura ETFs to update")
    
    # 確保 ETF 存在於 etf_list 表中
    etf_list_data = []
    for etf_code, fund_id in nomura_etfs.items():
        etf_list_data.append({
            'etf_code': etf_code,
            'etf_name': f'Nomura ETF {etf_code}',
            'issuer': 'Nomura',
            'listing_date': ''
        })
    
    if etf_list_data:
        db.insert_etf_list(etf_list_data)
    
    # 逐一抓取持股明細
    total_inserted = 0
    for i, (etf_code, fund_id) in enumerate(nomura_etfs.items(), 1):
        logger.info(f"[{i}/{len(nomura_etfs)}] Updating {etf_code} (Fund ID: {fund_id})")
        
        try:
            holdings = scraper.get_etf_holdings(etf_code, date_str)
            if holdings:
                inserted = db.insert_holdings(holdings)
                total_inserted += inserted
                logger.info(f"{etf_code}: Inserted {inserted} new holdings")
            else:
                logger.warning(f"{etf_code}: No holdings data found")
        except Exception as e:
            logger.error(f"Error updating {etf_code}: {e}")
            logger.exception(e)
            
    logger.info(f"Nomura ETF daily update complete: {total_inserted} new holdings inserted")
    
    # 變動追蹤：分析並顯示成分股變動（僅在單獨執行時生成報告）
    if generate_report and ENABLE_CHANGE_TRACKING and SAVE_CHANGE_REPORTS:
        logger.info("Analyzing holdings changes...")
        report_mgr = ReportManager(db, REPORTS_DIR)
        changes_dict = report_mgr.analyzer.detect_changes_batch(list(nomura_etfs.keys()), date_str)
        
        if changes_dict:
            report = report_mgr.analyzer.generate_report(changes_dict, date_str)
            logger.info(report)
            # 生成所有格式的報告（TXT, Markdown, HTML）
            report_mgr.generate_all_reports(changes_dict, date_str, append_txt=True)
        else:
            logger.info("No significant changes detected.")


def daily_update_capital(generate_report=True):
    """每日更新群益投信ETF 作業"""
    logger.info("Starting Capital Funds ETF daily update...")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = CapitalScraper()
    
    # 使用今天的日期
    target_date = datetime.now()
    while target_date.weekday() >= 5:  # 避免週末
        target_date -= timedelta(days=1)
    
    date_str = target_date.strftime('%Y-%m-%d') # YYYY-MM-DD
    
    logger.info(f"Fetching Capital ETF data for {date_str}")
    
    # 取得所有已配置的群益 ETF
    capital_etfs = scraper.get_all_mappings()
    logger.info(f"Found {len(capital_etfs)} Capital ETFs to update")
    
    # 確保 ETF 存在於 etf_list 表中
    etf_list_data = []
    for etf_code in capital_etfs.keys():
        etf_list_data.append({
            'etf_code': etf_code,
            'etf_name': f'Capital ETF {etf_code}',
            'issuer': 'Capital',
            'listing_date': ''
        })
    
    if etf_list_data:
        db.insert_etf_list(etf_list_data)
    
    # 逐一抓取持股明細
    total_inserted = 0
    for i, etf_code in enumerate(capital_etfs.keys(), 1):
        logger.info(f"[{i}/{len(capital_etfs)}] Updating {etf_code}")
        
        try:
            holdings = scraper.get_etf_holdings(etf_code, date_str)
            if holdings:
                inserted = db.insert_holdings(holdings)
                total_inserted += inserted
                logger.info(f"{etf_code}: Inserted {inserted} new holdings")
            else:
                logger.warning(f"{etf_code}: No holdings data found")
        except Exception as e:
            logger.error(f"Error updating {etf_code}: {e}")
            logger.exception(e)
            
    logger.info(f"Capital ETF daily update complete: {total_inserted} new holdings inserted")
    
    # 變動追蹤：分析並顯示成分股變動（僅在單獨執行時生成報告）
    if generate_report and ENABLE_CHANGE_TRACKING and SAVE_CHANGE_REPORTS:
        logger.info("Analyzing holdings changes...")
        report_mgr = ReportManager(db, REPORTS_DIR)
        changes_dict = report_mgr.analyzer.detect_changes_batch(list(capital_etfs.keys()), date_str)
        
        if changes_dict:
            report = report_mgr.analyzer.generate_report(changes_dict, date_str)
            logger.info(report)
            # 生成所有格式的報告（TXT, Markdown, HTML）
            report_mgr.generate_all_reports(changes_dict, date_str, append_txt=True)
        else:
            logger.info("No significant changes detected.")


def daily_update_fhtrust(generate_report=True):
    """每日更新復華投信ETF 作業"""
    logger.info("Starting FHTrust Funds ETF daily update...")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = FHTrustScraper()
    
    # 使用今天的日期
    target_date = datetime.now()
    while target_date.weekday() >= 5:  # 避免週末
        target_date -= timedelta(days=1)
    
    date_str = target_date.strftime('%Y-%m-%d')
    logger.info(f"Fetching FHTrust ETF data for {date_str}")
    
    # 取得所有已配置的復華 ETF
    fhtrust_etfs = scraper.get_all_mappings()
    logger.info(f"Found {len(fhtrust_etfs)} FHTrust ETFs to update")
    
    # 確保 ETF 存在於 etf_list 表中
    etf_list_data = []
    for etf_code in fhtrust_etfs.keys():
        etf_list_data.append({
            'etf_code': etf_code,
            'etf_name': f'FHTrust ETF {etf_code}',
            'issuer': 'FHTrust',
            'listing_date': ''
        })
    
    if etf_list_data:
        db.insert_etf_list(etf_list_data)
    
    # 逐一抓取持股明細
    total_inserted = 0
    for i, etf_code in enumerate(fhtrust_etfs.keys(), 1):
        logger.info(f"[{i}/{len(fhtrust_etfs)}] Updating {etf_code}")
        
        try:
            holdings = scraper.get_etf_holdings(etf_code, date_str)
            if holdings:
                inserted = db.insert_holdings(holdings)
                total_inserted += inserted
                logger.info(f"{etf_code}: Inserted {inserted} new holdings")
            else:
                logger.warning(f"{etf_code}: No holdings data found")
        except Exception as e:
            logger.error(f"Error updating {etf_code}: {e}")
            logger.exception(e)
            
    logger.info(f"FHTrust ETF daily update complete: {total_inserted} new holdings inserted")
    
    # 變動追蹤：分析並顯示成分股變動（僅在單獨執行時生成報告）
    if generate_report and ENABLE_CHANGE_TRACKING and SAVE_CHANGE_REPORTS:
        logger.info("Analyzing holdings changes...")
        report_mgr = ReportManager(db, REPORTS_DIR)
        changes_dict = report_mgr.analyzer.detect_changes_batch(list(fhtrust_etfs.keys()), date_str)
        
        if changes_dict:
            report = report_mgr.analyzer.generate_report(changes_dict, date_str)
            logger.info(report)
            # 生成所有格式的報告（TXT, Markdown, HTML）
            report_mgr.generate_all_reports(changes_dict, date_str, append_txt=True)
        else:
            logger.info("No significant changes detected.")


def daily_update_ctbc(generate_report=True):
    """每日更新中信投信ETF 作業"""
    logger.info("Starting CTBC Funds ETF daily update...")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = CTBCScraper()
    
    # 使用今天的日期
    target_date = datetime.now()
    while target_date.weekday() >= 5:  # 避免週末
        target_date -= timedelta(days=1)
    
    date_str = target_date.strftime('%Y-%m-%d')
    logger.info(f"Fetching CTBC ETF data for {date_str}")
    
    # 取得所有已配置的中信 ETF
    ctbc_etfs = scraper.get_all_mappings()
    logger.info(f"Found {len(ctbc_etfs)} CTBC ETFs to update")
    
    # 確保 ETF 存在於 etf_list 表中
    etf_list_data = []
    for etf_code in ctbc_etfs.keys():
        etf_list_data.append({
            'etf_code': etf_code,
            'etf_name': f'CTBC ETF {etf_code}',
            'issuer': 'CTBC',
            'listing_date': ''
        })
    
    if etf_list_data:
        db.insert_etf_list(etf_list_data)
    
    # 逐一抓取持股明細
    total_inserted = 0
    for i, etf_code in enumerate(ctbc_etfs.keys(), 1):
        logger.info(f"[{i}/{len(ctbc_etfs)}] Updating {etf_code}")
        
        try:
            holdings = scraper.get_etf_holdings(etf_code, date_str)
            if holdings:
                inserted = db.insert_holdings(holdings)
                total_inserted += inserted
                logger.info(f"{etf_code}: Inserted {inserted} new holdings")
            else:
                logger.warning(f"{etf_code}: No holdings data found")
        except Exception as e:
            logger.error(f"Error updating {etf_code}: {e}")
            logger.exception(e)
            
    logger.info(f"CTBC ETF daily update complete: {total_inserted} new holdings inserted")
    
    # 變動追蹤：分析並顯示成分股變動（僅在單獨執行時生成報告）
    if generate_report and ENABLE_CHANGE_TRACKING and SAVE_CHANGE_REPORTS:
        logger.info("Analyzing holdings changes...")
        report_mgr = ReportManager(db, REPORTS_DIR)
        changes_dict = report_mgr.analyzer.detect_changes_batch(list(ctbc_etfs.keys()), date_str)
        
        if changes_dict:
            report = report_mgr.analyzer.generate_report(changes_dict, date_str)
            logger.info(report)
            # 生成所有格式的報告（TXT, Markdown, HTML）
            report_mgr.generate_all_reports(changes_dict, date_str, append_txt=True)
        else:
            logger.info("No significant changes detected.")

def daily_update_fsitc(generate_report=True):
    """每日更新第一金投信ETF 作業"""
    logger.info("Starting FSITC Funds ETF daily update...")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = FSITCScraper()
    
    # 檢查當前時間（UTC），決定使用哪一天的數據
    # 台股收盤時間為13:30（台北時間），數據更新通常在收盤後
    # 如果在10:00 UTC前執行（台北18:00前），使用前一個交易日的數據
    current_time = datetime.now()  # GitHub Actions uses UTC time
    
    if current_time.hour < 10:  # UTC 10:00 = 台北18:00
        # 在收盤整理時間前，使用前一個交易日
        target_date = current_time - timedelta(days=1)
        logger.info(f"Current time (UTC): {current_time.strftime('%H:%M')}, using previous trading day")
    else:
        # 收盤後，使用當天（如果是交易日）
        target_date = current_time
        logger.info(f"Current time (UTC): {current_time.strftime('%H:%M')}, using current day if it's a trading day")
    
    # 避免週末
    while target_date.weekday() >= 5:
        target_date -= timedelta(days=1)
    
    date_str = target_date.strftime('%Y-%m-%d')
    logger.info(f"Fetching FSITC ETF data for {date_str}")
    
    # 取得所有已配置的第一金 ETF
    fsitc_etfs = scraper.get_all_mappings()
    logger.info(f"Found {len(fsitc_etfs)} FSITC ETFs to update")
    
    # 確保 ETF 存在於 etf_list 表中
    etf_list_data = []
    for etf_code in fsitc_etfs.keys():
        etf_list_data.append({
            'etf_code': etf_code,
            'etf_name': f'FSITC ETF {etf_code}',
            'issuer': 'FSITC',
            'listing_date': ''
        })
    
    if etf_list_data:
        db.insert_etf_list(etf_list_data)
    
    # 逐一抓取持股明細
    total_inserted = 0
    actual_dates = {}  # 記錄每個ETF的實際數據日期
    for i, etf_code in enumerate(fsitc_etfs.keys(), 1):
        logger.info(f"[{i}/{len(fsitc_etfs)}] Updating {etf_code}")
        
        try:
            holdings, actual_date = scraper.get_etf_holdings(etf_code, date_str)
            
            # 强制使用我们计算的target_date，不信任API的sdate
            # 原因：API的sdate可能在台北时间11点就更新为当天，导致日期不一致
            if holdings:
                # 记录API日期与我们计算日期的差异
                if actual_date != date_str:
                    logger.warning(f"{etf_code}: API date ({actual_date}) differs from target date ({date_str}), using target date")
                
                # 强制覆盖所有holdings的date为target_date
                for holding in holdings:
                    holding['date'] = date_str
                
                inserted = db.insert_holdings(holdings)
                total_inserted += inserted
                logger.info(f"{etf_code}: Inserted {inserted} new holdings (using target date: {date_str})")
            else:
                logger.warning(f"{etf_code}: No holdings data found")
        except Exception as e:
            logger.error(f"Error updating {etf_code}: {e}")
            logger.exception(e)
            
    logger.info(f"FSITC ETF daily update complete: {total_inserted} new holdings inserted")
    
    # 變動追蹤：分析並顯示成分股變動（僅在單獨執行時生成報告）
    if generate_report and ENABLE_CHANGE_TRACKING and SAVE_CHANGE_REPORTS:
        logger.info("Analyzing holdings changes...")
        report_mgr = ReportManager(db, REPORTS_DIR)
        
        # 使用target_date生成報告，確保與數據日期一致
        report_date = date_str
        logger.info(f"Generating report for {report_date}")
        
        changes_dict = report_mgr.analyzer.detect_changes_batch(list(fsitc_etfs.keys()), report_date)
        
        if changes_dict:
            report = report_mgr.analyzer.generate_report(changes_dict, report_date)
            logger.info(report)
            # 生成所有格式的報告（TXT, Markdown, HTML）
            report_mgr.generate_all_reports(changes_dict, report_date, append_txt=True)
        else:
            logger.info("No significant changes detected.")

def daily_update_tsit(generate_report=True):
    """每日更新台新投信ETF 作業"""
    logger.info("Starting TSIT Funds ETF daily update...")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = TSITScraper()
    
    # 使用今天的日期
    target_date = datetime.now()
    while target_date.weekday() >= 5:  # 避免週末
        target_date -= timedelta(days=1)
    
    date_str = target_date.strftime('%Y-%m-%d')
    logger.info(f"Fetching TSIT ETF data for {date_str}")
    
    # 取得所有已配置的台新 ETF
    tsit_etfs = scraper.get_all_mappings()
    logger.info(f"Found {len(tsit_etfs)} TSIT ETFs to update")
    
    # 確保 ETF 存在於 etf_list 表中
    etf_list_data = []
    for etf_code in tsit_etfs.keys():
        etf_list_data.append({
            'etf_code': etf_code,
            'etf_name': f'TSIT ETF {etf_code}',
            'issuer': 'TSIT',
            'listing_date': ''
        })
    
    if etf_list_data:
        db.insert_etf_list(etf_list_data)
    
    # 逐一抓取持股明細
    total_inserted = 0
    for i, etf_code in enumerate(tsit_etfs.keys(), 1):
        logger.info(f"[{i}/{len(tsit_etfs)}] Updating {etf_code}")
        
        try:
            holdings = scraper.get_etf_holdings(etf_code, date_str)
            if holdings:
                inserted = db.insert_holdings(holdings)
                total_inserted += inserted
                logger.info(f"{etf_code}: Inserted {inserted} new holdings")
            else:
                logger.warning(f"{etf_code}: No holdings data found")
        except Exception as e:
            logger.error(f"Error updating {etf_code}: {e}")
            logger.exception(e)
            
    logger.info(f"TSIT ETF daily update complete: {total_inserted} new holdings inserted")
    
    # 變動追蹤：分析並顯示成分股變動（僅在單獨執行時生成報告）
    if generate_report and ENABLE_CHANGE_TRACKING and SAVE_CHANGE_REPORTS:
        logger.info("Analyzing holdings changes...")
        report_mgr = ReportManager(db, REPORTS_DIR)
        changes_dict = report_mgr.analyzer.detect_changes_batch(list(tsit_etfs.keys()), date_str)
        
        if changes_dict:
            report = report_mgr.analyzer.generate_report(changes_dict, date_str)
            logger.info(report)
            # 生成所有格式的報告（TXT, Markdown, HTML）
            report_mgr.generate_all_reports(changes_dict, date_str, append_txt=True)
        else:
            logger.info("No significant changes detected.")


def daily_update_allianz(generate_report=True):
    """每日更新安聯投信 ETF 作業（使用 Playwright DOM 提取）"""
    logger.info("Starting Allianz ETF daily update (Playwright DOM extraction)...")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = AllianzScraper()
    
    # 使用今天的日期
    target_date = datetime.now()
    while target_date.weekday() >= 5:  # 避免週末
        target_date -= timedelta(days=1)
    
    date_str = target_date.strftime('%Y-%m-%d')
    logger.info(f"Fetching Allianz ETF data for {date_str}")
    
    # 取得所有已配置的安聯投信 ETF
    allianz_etfs = scraper.get_all_mappings()
    logger.info(f"Found {len(allianz_etfs)} Allianz ETFs to update")

    
    # 確保 ETF 存在於 etf_list 表中
    etf_list_data = []
    for etf_code in allianz_etfs.keys():
        etf_list_data.append({
            'etf_code': etf_code,
            'etf_name': '安聯台灣高息成長主動式ETF' if etf_code == '00984A' else f'{etf_code} (安聯投信)',
            'issuer': '安聯投信',
            'listing_date': ''
        })
    
    if etf_list_data:
        db.insert_etf_list(etf_list_data)
    
    # 逐一抓取持股明細
    total_inserted = 0
    for i, etf_code in enumerate(allianz_etfs.keys(), 1):
        logger.info(f"[{i}/{len(allianz_etfs)}] Updating {etf_code}")
        
        try:
            holdings = scraper.get_etf_holdings(etf_code, date_str)
            if holdings:
                inserted = db.insert_holdings(holdings)
                total_inserted += inserted
                logger.info(f"{etf_code}: Inserted {inserted} new holdings")
            else:
                logger.warning(f"{etf_code}: No holdings data found")
        except Exception as e:
            logger.error(f"Error updating {etf_code}: {e}")
            logger.exception(e)
    
    logger.info(f"Allianz ETF daily update complete: {total_inserted} new holdings inserted")
    
    # 變動追蹤：分析並顯示成分股變動（僅在單獨執行時生成報告）
    if generate_report and ENABLE_CHANGE_TRACKING and SAVE_CHANGE_REPORTS:
        logger.info("Analyzing holdings changes...")
        report_mgr = ReportManager(db, REPORTS_DIR)
        changes_dict = report_mgr.analyzer.detect_changes_batch(list(allianz_etfs.keys()), date_str)
        
        if changes_dict:
            report = report_mgr.analyzer.generate_report(changes_dict, date_str)
            logger.info(report)
            # 生成所有格式的報告（TXT, Markdown, HTML）
            report_mgr.generate_all_reports(changes_dict, date_str, append_txt=True)
        else:
            logger.info("No significant changes detected.")
    
    # 清理舊資料
    logger.info("Cleaning up old data...")
    cleanup_result = cleanup_old_data(str(DB_FULL_PATH), DATA_RETENTION_DAYS)
    logger.info(f"Cleanup result: {cleanup_result}")
    
    # 顯示統計
    stats = db.get_statistics()
    logger.info(f"Database statistics:")
    logger.info(f"  Total ETFs: {stats['total_etfs']}")
    logger.info(f"  Total holdings: {stats['total_holdings']}")
    logger.info(f"  Date range: {stats['date_range']['start']} to {stats['date_range']['end']}")


def show_stats():
    """顯示資料庫統計資訊"""
    db = Database(DB_FULL_PATH)
    stats = db.get_statistics()
    
    print("\n=== 資料庫統計 ===")
    print(f"主動式 ETF 數量: {stats['total_etfs']}")
    print(f"持股記錄總數: {stats['total_holdings']}")
    print(f"資料日期範圍: {stats['date_range']['start']} ~ {stats['date_range']['end']}")
    print(f"\n最近更新的 ETF:")
    for item in stats['latest_updates']:
        print(f"  {item['etf_code']}: {item['date']}")
    print()


def generate_consolidated_reports():
    """
    在所有投信更新完成後，統一生成完整的報告
    這樣可以確保 HTML、JSON 和 Markdown 報告包含當天所有 ETF 的變動
    """
    logger.info("=" * 60)
    logger.info("Generating consolidated reports for all ETFs...")
    logger.info("=" * 60)
    
    db = Database(DB_FULL_PATH)
    
    # 取得今天的日期
    target_date = datetime.now()
    while target_date.weekday() >= 5:  # 避免週末
        target_date -= timedelta(days=1)
    date_str = target_date.strftime('%Y-%m-%d')
    
    # 取得所有活躍的 ETF
    active_etfs = db.get_active_etfs()
    etf_codes = [etf['etf_code'] for etf in active_etfs]
    
    logger.info(f"Analyzing changes for {len(etf_codes)} ETFs on {date_str}")
    
    # 分析所有 ETF 的變動
    report_mgr = ReportManager(db, REPORTS_DIR)
    all_changes_dict = report_mgr.analyzer.detect_changes_batch(etf_codes, date_str)
    
    if all_changes_dict:
        total_changes = sum(len(changes) for changes in all_changes_dict.values())
        logger.info(f"Found {len(all_changes_dict)} ETFs with {total_changes} total changes")
        
        # 生成所有格式的報告（覆蓋模式，包含完整數據）
        report_mgr.generate_all_reports(all_changes_dict, date_str, append_txt=False)
        logger.info("Consolidated reports generated successfully")
    else:
        logger.info("No changes detected across all ETFs")


def main():
    """主程式進入點"""
    parser = argparse.ArgumentParser(
        description="台灣主動式 ETF 持股追蹤系統（基於各家投信官網）",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--ezmoney',
        action='store_true',
        help='每日更新模式：抓取 EZMoney ETF 最新資料（建議於晚上 18:00 後執行）'
    )
    
    parser.add_argument(
        '--nomura',
        action='store_true',
        help='每日更新模式：抓取野村投信 ETF 最新資料'
    )
    
    parser.add_argument(
        '--capital',
        action='store_true',
        help='每日更新模式：抓取群益投信 ETF 最新資料'
    )

    parser.add_argument(
        '--fhtrust',
        action='store_true',
        help='每日更新模式：抓取復華投信 ETF 最新資料'
    )
    
    parser.add_argument(
        '--ctbc',
        action='store_true',
        help='每日更新模式：抓取中信投信 ETF 最新資料'
    )
    
    parser.add_argument(
        '--fsitc',
        action='store_true',
        help='每日更新模式：抓取第一金投信 ETF 最新資料'
    )

    parser.add_argument(
        '--tsit',
        action='store_true',
        help='每日更新模式：抓取台新投信 ETF 最新資料'
    )

    parser.add_argument(
        '--allianz',
        action='store_true',
        help='每日更新模式：抓取安聯投信 ETF 最新資料'
    )
    
    parser.add_argument(
        '--all',
        action='store_true',
        help='每日更新模式：抓取所有投信 ETF 最新資料'
    )
    
    parser.add_argument(
        '--stats',
        action='store_true',
        help='顯示資料庫統計資訊'
    )
    
    args = parser.parse_args()
    
    # 設定日誌
    setup_logging(str(LOG_PATH), LOG_LEVEL)
    logger.info("=" * 60)
    logger.info("Taiwan Active ETF Tracker Started")
    logger.info(f"Database: {DB_FULL_PATH}")
    logger.info("=" * 60)
    
    try:
        # 如果指定顯示統計
        if args.stats:
            show_stats()
            return

        # 檢查是否有參數，如果沒有則預設只跑 EZMoney (向後兼容)
        if not (args.ezmoney or args.nomura or args.capital or args.fhtrust or args.ctbc or args.fsitc or args.tsit or args.allianz or args.all):
            logger.info("No arguments provided, running default scrapers (EZMoney)")
            daily_update_ezmoney()
        else:
            # 在 --all 模式下，個別更新不生成報告，最後統一生成
            skip_individual_reports = args.all
            
            if args.ezmoney or args.all:
                daily_update_ezmoney(generate_report=not skip_individual_reports)
                
            if args.nomura or args.all:
                daily_update_nomura(generate_report=not skip_individual_reports)

            if args.capital or args.all:
                daily_update_capital(generate_report=not skip_individual_reports)

            if args.fhtrust or args.all:
                daily_update_fhtrust(generate_report=not skip_individual_reports)
                
            if args.ctbc or args.all:
                daily_update_ctbc(generate_report=not skip_individual_reports)
                
            if args.fsitc or args.all:
                daily_update_fsitc(generate_report=not skip_individual_reports)

            if args.tsit or args.all:
                daily_update_tsit(generate_report=not skip_individual_reports)

            if args.allianz or args.all:
                daily_update_allianz(generate_report=not skip_individual_reports)
            
            # 當使用 --all 時，在所有更新完成後生成完整報告
            if args.all:
                generate_consolidated_reports()
            
        logger.info("Main program finished")
    
    except KeyboardInterrupt:
        logger.warning("Program interrupted by user")
    except Exception as e:
        logger.error(f"Create program error: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
