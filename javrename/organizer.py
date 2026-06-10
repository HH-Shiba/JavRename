"""檔案歸檔：決定目標路徑並搬移影片（支援 dry-run 與失敗佇列）"""
import logging
import os
import shutil

from . import config
from .parser import ParsedCode, sanitize_folder_name

logger = logging.getLogger("javrename")


def build_actress_folder_name(actresses: list[str]) -> str:
    """依設定的策略產生女優資料夾名稱"""
    names = [sanitize_folder_name(a) for a in actresses]
    if config.settings.actress_strategy == "all":
        return "、".join(names[:config.settings.max_actresses_in_folder])
    return names[0]


def _resolve_conflict(target_dir: str, filename: str) -> str:
    """目標檔已存在時自動加 _1、_2 序號"""
    final_path = os.path.join(target_dir, filename)
    if not os.path.exists(final_path):
        return final_path
    base_name, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = os.path.join(target_dir, f"{base_name}_{counter}{ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def move_video(file_path: str, root_folder: str, parsed: ParsedCode,
               actresses: list[str], dry_run: bool = False) -> dict:
    """搬移影片到目標位置：
    - 查得女優 → <root>/<女優資料夾>/<番號><後綴>.<副檔名>（標準化重新命名）
    - 查無資料 → <root>/failed/<番號>/<原檔名>（失敗佇列，重跑時自動重試）
    回傳 dict 含 status：moved / failed / skipped / preview
    """
    ext = os.path.splitext(file_path)[1].lower()

    if actresses:
        target_dir = os.path.join(root_folder, build_actress_folder_name(actresses))
        target_name = f"{parsed.full}{ext}"
        status = "moved"
    else:
        target_dir = os.path.join(root_folder, config.settings.failed_dir_name, parsed.code)
        target_name = os.path.basename(file_path)
        status = "failed"

    target_path = os.path.join(target_dir, target_name)

    # 檔案已在正確位置時不重複處理（重跑安全）
    if os.path.normcase(os.path.abspath(file_path)) == os.path.normcase(os.path.abspath(target_path)):
        logger.info(f"檔案已在正確位置，跳過: {os.path.relpath(target_path, root_folder)}")
        return {"status": "skipped", "target": target_path, "actresses": actresses}

    rel_target = os.path.relpath(target_path, root_folder)

    if dry_run:
        logger.info(f"[預覽] {os.path.basename(file_path)} → {rel_target}")
        return {"status": "preview", "target": target_path, "actresses": actresses}

    os.makedirs(target_dir, exist_ok=True)
    target_path = _resolve_conflict(target_dir, target_name)
    shutil.move(file_path, target_path)

    if status == "failed":
        logger.warning(f"查無資料，移入失敗佇列: {os.path.basename(file_path)} → {rel_target}")
    else:
        logger.info(f"成功移動: {os.path.basename(file_path)} → {os.path.relpath(target_path, root_folder)}")

    return {"status": status, "target": target_path, "actresses": actresses}
