"""處理流程：掃描 → 解析番號 → 主/備源查詢 → 歸檔"""
import asyncio
import logging
import os
import time
from datetime import datetime

import aiohttp

from . import config
from .organizer import move_video
from .parser import extract_code
from .scrapers import JavBusScraper, JavDBScraper, Scraper

logger = logging.getLogger("javrename")


class ScraperChain:
    """資料源 fallback 鏈：依序查詢，第一個有結果的資料源勝出"""

    def __init__(self, scrapers: list[Scraper] | None = None):
        self.scrapers = scrapers if scrapers is not None else [JavBusScraper(), JavDBScraper()]

    async def get_actresses(self, code: str, session: aiohttp.ClientSession) -> list[str]:
        for index, scraper in enumerate(self.scrapers):
            names = await scraper.get_actresses(code, session)
            if names:
                return names
            if index < len(self.scrapers) - 1:
                next_name = self.scrapers[index + 1].name
                logger.info(f"[{scraper.name}] 查詢失敗，切換備源 [{next_name}]: {code}")
        logger.warning(f"所有資料源皆查詢失敗: {code}")
        return []


def collect_files(root_folder: str) -> list:
    """收集所有需要處理的檔案，包括所有子資料夾"""
    file_list = []
    for dirpath, dirnames, filenames in os.walk(root_folder):
        for filename in filenames:
            _, ext = os.path.splitext(filename)
            if ext.lower() in config.settings.valid_extensions:
                file_list.append((dirpath, filename, root_folder))
                logger.info(f"找到影片檔案: {filename} (位於: {os.path.relpath(dirpath, root_folder)})")

    logger.info(f"搜尋完畢，總共找到 {len(file_list)} 個需要處理的影片檔案")
    return file_list


async def process_one(file_info: tuple, chain: ScraperChain,
                      session: aiohttp.ClientSession, dry_run: bool) -> dict | None:
    """處理單個檔案"""
    dirpath, filename, root_folder = file_info
    file_path = os.path.join(dirpath, filename)

    if not os.path.isfile(file_path):
        logger.warning(f"檔案不存在: {file_path}")
        return None

    parsed = extract_code(filename)
    if parsed is None:
        logger.warning(f"無法從檔名解析出有效番號，跳過: {filename}")
        return None

    try:
        logger.info(f"正在分析番號: {parsed.full}")
        actresses = await chain.get_actresses(parsed.code, session)
        return move_video(file_path, root_folder, parsed, actresses, dry_run=dry_run)
    except Exception as e:
        logger.error(f"處理檔案 {filename} 時發生致命錯誤: {type(e).__name__}: {e}")
        return None


async def process_files(root_folder: str, dry_run: bool = False) -> dict:
    """處理所有檔案的核心非同步函數，回傳統計摘要"""
    start_time = time.time()
    logger.info("=" * 50)
    logger.info(f"開始處理時間: {datetime.now():%Y-%m-%d %H:%M:%S}")
    if dry_run:
        logger.info("*** 預覽模式：只顯示將執行的搬移，不會實際搬移檔案 ***")

    file_list = collect_files(root_folder)
    total_files = len(file_list)
    summary = {"total": total_files, "moved": 0, "failed": 0, "skipped": 0, "preview": 0, "error": 0}

    if total_files == 0:
        logger.info("沒有找到任何符合條件的影片檔案，處理結束。")
        return summary

    chain = ScraperChain()

    async with aiohttp.ClientSession() as session:
        semaphore = asyncio.Semaphore(config.settings.max_concurrent_requests)

        async def process_with_semaphore(file_info):
            async with semaphore:
                return await process_one(file_info, chain, session, dry_run)

        tasks = [process_with_semaphore(file_info) for file_info in file_list]
        results = await asyncio.gather(*tasks)

    for result in results:
        if result is None:
            summary["error"] += 1
        else:
            summary[result["status"]] += 1

    total_time = time.time() - start_time
    logger.info("\n" + "=" * 50)
    logger.info("處理完成摘要:")
    logger.info(f"結束時間: {datetime.now():%Y-%m-%d %H:%M:%S}")
    logger.info(f"成功歸檔: {summary['moved']}")
    logger.info(f"查無資料（移入 failed/）: {summary['failed']}")
    logger.info(f"已在正確位置（跳過）: {summary['skipped']}")
    if dry_run:
        logger.info(f"預覽（未實際搬移）: {summary['preview']}")
    logger.info(f"解析/處理錯誤: {summary['error']}")
    logger.info(f"總處理時間: {total_time:.2f} 秒")
    if total_files > 0:
        logger.info(f"平均每個檔案處理時間: {total_time/total_files:.2f} 秒")
    logger.info("=" * 50)

    return summary
