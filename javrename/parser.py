"""番號解析與檔名安全處理（純函式，無 I/O，易於測試）"""
import os
import re
from dataclasses import dataclass

from . import config

# 番號格式：2-6 個英文字母 + 分隔符（可省略）+ 2-5 位數字，如 SONE-123、HND_765
CODE_PATTERN = re.compile(r'([A-Za-z]{2,6})[-_ ]?(\d{2,5})')
# 版本後綴：-C（中文字幕）、-U（破解）、-UC（破解+字幕），後面不可再接英數字
SUFFIX_PATTERN = re.compile(r'^[-_ ]?(uc|u|c)(?![a-z0-9])', re.IGNORECASE)
# Windows 檔名非法字元
ILLEGAL_FS_CHARS = re.compile(r'[\\/:*?"<>|]')


@dataclass(frozen=True)
class ParsedCode:
    """解析後的番號：code 為標準化番號，suffix 為版本後綴（含連字號，可為空）"""
    code: str    # 例：SONE-123
    suffix: str  # 例：""、"-C"、"-U"、"-UC"

    @property
    def full(self) -> str:
        return f"{self.code}{self.suffix}"


def sanitize_folder_name(name: str) -> str:
    """過濾 Windows 資料夾名稱的非法字元與結尾空白/句點"""
    cleaned = ILLEGAL_FS_CHARS.sub('', name).strip().rstrip('.')
    return cleaned if cleaned else "Unknown"


def extract_code(filename: str) -> ParsedCode | None:
    """從檔名解析出標準化番號與版本後綴，無法解析時回傳 None"""
    stem = os.path.splitext(filename)[0]
    for remove_str in config.settings.remove_strings:
        stem = stem.replace(remove_str, "")
    # 移除常見前綴雜訊：[xxx]、xxx@、開頭的數字與符號
    stem = re.sub(r'^\[[^\]]*\]', '', stem)
    stem = re.sub(r'^[^A-Za-z]*@', '', stem)
    stem = re.sub(r'^[\d\W_]+', '', stem)

    match = CODE_PATTERN.search(stem)
    if not match:
        return None

    code = f"{match.group(1).upper()}-{match.group(2)}"
    suffix_match = SUFFIX_PATTERN.match(stem[match.end():])
    suffix = f"-{suffix_match.group(1).upper()}" if suffix_match else ""
    return ParsedCode(code=code, suffix=suffix)
