"""核心設定：預設值與執行期可調整的 Settings

GUI 的「設定」對話框可修改 settings 單例，並持久化到 settings.json
（位於專案根目錄；打包成 exe 後位於 exe 所在目錄），重啟後自動載入。
"""
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field, fields

logger = logging.getLogger("javrename")

# 打包成 exe（PyInstaller --onefile）時 __file__ 指向解壓暫存目錄（_MEIPASS），
# 程式結束即被清除，因此凍結狀態下改以 exe 所在目錄為準
if getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
SETTINGS_FILE = os.path.join(PROJECT_ROOT, "settings.json")


@dataclass
class Settings:
    # 檔名雜訊字串清單（解析番號前先移除）
    remove_strings: list = field(
        default_factory=lambda: ["hhd800.com@", "zzpp01.com@", "thzu@"])
    # 支援的影片副檔名（小寫、含點）
    valid_extensions: list = field(
        default_factory=lambda: [".mp4", ".mkv", ".wmv", ".avi"])
    # 最大同時請求數
    max_concurrent_requests: int = 5
    # 單一資料源請求失敗的重試次數
    retry_count: int = 2
    # 重試間隔基數（秒），實際間隔 = 基數 * 第幾次重試
    retry_backoff: int = 3
    # 單次請求逾時（秒）
    request_timeout: int = 20
    # 多女優資料夾命名策略："first"（第一位）或 "all"（「、」串接多位）
    actress_strategy: str = "first"
    # actress_strategy="all" 時資料夾名最多列出幾位
    max_actresses_in_folder: int = 3
    # 查無資料的影片歸檔目錄名稱（位於使用者選定的根目錄下）
    failed_dir_name: str = "failed"

    @classmethod
    def load(cls, path: str = SETTINGS_FILE) -> "Settings":
        """從 JSON 載入設定；檔案不存在或損壞時回傳預設值"""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            valid_keys = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in valid_keys})
        except FileNotFoundError:
            return cls()
        except Exception as e:
            logger.warning(f"讀取設定檔失敗，改用預設值: {type(e).__name__}: {e}")
            return cls()

    def save(self, path: str = SETTINGS_FILE):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)


# 全域設定單例：各模組於呼叫時讀取（config.settings.xxx），GUI 修改後立即生效
settings = Settings.load()
