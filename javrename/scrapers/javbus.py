"""主源資料庫：javbus.com"""
import asyncio
import logging
import random

import aiohttp
from bs4 import BeautifulSoup

from .base import Scraper, BROWSER_UA

logger = logging.getLogger("javrename")


class JavBusScraper(Scraper):
    name = "javbus"

    def __init__(self):
        self.base_url = "https://www.javbus.com"
        self.headers = {
            'User-Agent': BROWSER_UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
        }

    @staticmethod
    def parse_actresses(html: str) -> list[str]:
        """從詳情頁 HTML 解析所有女優名（演員區塊為 span.genre[onmouseover*=hoverdiv]）"""
        soup = BeautifulSoup(html, 'html.parser')
        spans = soup.find_all('span', class_='genre',
                              attrs={'onmouseover': lambda x: x and 'hoverdiv' in x})
        names = []
        for span in spans:
            link = span.find('a')
            if link:
                name = link.get_text(strip=True)
                if name and name not in names:
                    names.append(name)
        return names

    async def get_actresses(self, code: str, session: aiohttp.ClientSession) -> list[str]:
        await asyncio.sleep(random.uniform(1, 3))

        url = f"{self.base_url}/{code}"
        logger.info(f"[{self.name}] 正在訪問: {url}")

        html = await self.fetch_html(session, url)
        if html is None:
            return []

        try:
            names = self.parse_actresses(html)
        except Exception as e:
            logger.error(f"[{self.name}] 解析 {code} 時發生錯誤: {type(e).__name__}: {e}")
            return []

        if names:
            logger.info(f"[{self.name}] 獲取到女優資訊: {code} -> {'、'.join(names)}")
        else:
            logger.warning(f"[{self.name}] 未找到女優資訊: {code}")
        return names
