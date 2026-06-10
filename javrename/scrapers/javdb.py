"""備源資料庫：javdb.com（繁體中文）

javdb.com 受 Cloudflare TLS 指紋檢測保護，aiohttp 與一般 curl 一律被擋 403，
因此本爬蟲不使用共用的 aiohttp session，改用 curl_cffi 模擬 Chrome 指紋。
"""
import asyncio
import logging
import random

import aiohttp
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from .. import config
from .base import Scraper

logger = logging.getLogger("javrename")

# curl_cffi 的瀏覽器模擬目標；"chrome" 代表該版本支援的最新 Chrome 指紋
IMPERSONATE = "chrome"


class JavDBScraper(Scraper):
    name = "javdb"

    def __init__(self):
        self.base_url = "https://javdb.com"
        # User-Agent 由 curl_cffi 依模擬目標自動設定（與 TLS 指紋一致），
        # 此處只補上語言偏好以取得繁體中文資料
        self.headers = {
            'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.5',
        }

    async def _fetch_once(self, session: AsyncSession, url: str) -> tuple[int, str]:
        """以 curl_cffi session 抓取（session 由 get_actresses 建立並共用 cookie）"""
        response = await session.get(url, timeout=config.settings.request_timeout)
        return response.status_code, response.text

    @staticmethod
    def parse_search(html: str, code: str) -> str | None:
        """從搜尋結果頁解析與番號完全相符（不分大小寫）的詳情頁路徑 /v/xxx"""
        soup = BeautifulSoup(html, 'html.parser')
        for link in soup.select('a[href^="/v/"]'):
            title_el = link.select_one('div.video-title strong')
            # 番號必須完全相符，避免模糊匹配到錯誤影片
            if title_el and title_el.get_text(strip=True).upper() == code.upper():
                return link.get('href')
        return None

    @staticmethod
    def parse_detail(html: str) -> list[str]:
        """從詳情頁解析女優名單（僅取 symbol female 標記的演員，跳過男優）"""
        soup = BeautifulSoup(html, 'html.parser')
        names = []
        # 演員欄格式：<a href="/actors/xxx">名字</a><strong class="symbol female"></strong>
        for actor_link in soup.select('a[href^="/actors/"]'):
            symbol = actor_link.find_next_sibling('strong')
            if symbol and 'female' in (symbol.get('class') or []):
                name = actor_link.get_text(strip=True)
                if name and name not in names:
                    names.append(name)
        return names

    async def get_actresses(self, code: str, session: aiohttp.ClientSession) -> list[str]:
        # 傳入的 aiohttp session 不適用於 javdb（Cloudflare 403），
        # 改以 curl_cffi session 處理搜尋＋詳情兩個請求（共用 cookie）
        try:
            await asyncio.sleep(random.uniform(1, 3))

            async with AsyncSession(impersonate=IMPERSONATE, headers=self.headers) as cf_session:
                search_url = f"{self.base_url}/search?q={code}&f=all"
                logger.info(f"[{self.name}] 正在搜尋: {search_url}")

                html = await self.fetch_html(cf_session, search_url)
                if html is None:
                    return []

                detail_path = self.parse_search(html, code)
                if not detail_path:
                    logger.warning(f"[{self.name}] 搜尋結果中無完全相符的番號: {code}")
                    return []

                # 搜尋與詳情頁之間加入延遲，降低被 javdb 反爬蟲封鎖的機率
                await asyncio.sleep(random.uniform(1, 2))

                detail_url = f"{self.base_url}{detail_path}"
                logger.info(f"[{self.name}] 正在訪問詳情頁: {detail_url}")

                html = await self.fetch_html(cf_session, detail_url)
                if html is None:
                    return []

            names = self.parse_detail(html)
            if names:
                logger.info(f"[{self.name}] 獲取到女優資訊: {code} -> {'、'.join(names)}")
            else:
                logger.warning(f"[{self.name}] 詳情頁未找到女優資訊: {code}")
            return names

        except Exception as e:
            logger.error(f"[{self.name}] 處理 {code} 時發生錯誤: {type(e).__name__}: {e}")
            return []
