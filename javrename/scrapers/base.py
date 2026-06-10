"""Scraper 抽象介面與共用的 HTTP 抓取邏輯"""
import asyncio
import logging
from abc import ABC, abstractmethod

import aiohttp

from .. import config

logger = logging.getLogger("javrename")

BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36')


class Scraper(ABC):
    """資料源抽象介面：實作 get_actresses 即可加入 fallback 鏈"""

    name: str = "base"
    headers: dict = {}

    async def fetch_html(self, session, url: str) -> str | None:
        """帶重試機制的 HTML 抓取，全部失敗時回傳 None"""
        retry_count = config.settings.retry_count
        for attempt in range(1, retry_count + 2):
            try:
                status, text = await self._fetch_once(session, url)
                if status == 200:
                    return text
                logger.warning(
                    f"[{self.name}] 訪問失敗，狀態碼: {status}（第 {attempt} 次嘗試）: {url}")
            except Exception as e:
                logger.warning(
                    f"[{self.name}] 請求錯誤 {type(e).__name__}: {e}（第 {attempt} 次嘗試）: {url}")
            if attempt <= retry_count:
                await asyncio.sleep(config.settings.retry_backoff * attempt)
        return None

    async def _fetch_once(self, session: aiohttp.ClientSession, url: str) -> tuple[int, str]:
        """單次抓取（預設 aiohttp 實作），子類可改用其他 HTTP 客戶端"""
        timeout = aiohttp.ClientTimeout(total=config.settings.request_timeout)
        async with session.get(url, headers=self.headers, timeout=timeout) as response:
            return response.status, await response.text()

    @abstractmethod
    async def get_actresses(self, code: str, session: aiohttp.ClientSession) -> list[str]:
        """查詢番號對應的女優名單；查無資料或失敗時回傳空清單"""
        raise NotImplementedError
