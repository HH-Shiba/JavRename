import os
import shutil
import logging
import asyncio
import time
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup
import random
from concurrent.futures import ThreadPoolExecutor # 用於在背景運行爬蟲，不阻塞 GUI
import tkinter as tk
from tkinter import filedialog, messagebox

# =============================
# 核心設定區域
# =============================
# root_folder 已移除，由使用者透過 GUI 選擇
remove_strings = ["hhd800.com@"]  # 要移除的檔名字串
valid_extensions = [".mp4", ".mkv", ".wmv",".avi"]  # 支援的副檔名
MAX_CONCURRENT_REQUESTS = 5  # 最大同時請求數

# =============================
# 日誌系統設定
# =============================
# 設置一個空的日誌處理，以便在 GUI 模式下我們可以完全控制輸出
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 清除所有現有的 handlers，確保日誌只輸出到我們指定的地方
if logger.hasHandlers():
    logger.handlers.clear()

# 如果需要控制台輸出，可以加回一個 StreamHandler
# handler = logging.StreamHandler()
# handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
# logger.addHandler(handler)


# =============================
# 自訂日誌處理器：將日誌導向 Tkinter Text Widget
# =============================
class GuiLogHandler(logging.Handler):
    """自訂日誌處理器，用於將日誌訊息發送到 Tkinter 文本框"""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    def emit(self, record):
        msg = self.format(record)
        try:
            # 在文本框末尾插入日誌訊息
            self.text_widget.insert(tk.END, msg + '\n')
            # 自動滾動到底部
            self.text_widget.see(tk.END)
            # 強制 Tkinter 更新視窗，以顯示即時進度
            self.text_widget.update_idletasks()
        except Exception:
            # 視窗可能已經關閉，忽略錯誤
            pass


# =============================
# 爬蟲核心類別
# =============================
class JavBusScraper:
    def __init__(self):
        self.base_url = "https://www.javbus.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
        }
            
    async def get_actress_info(self, code: str, session: aiohttp.ClientSession) -> str:
        """獲取影片對應的女優資訊"""
        try:
            await asyncio.sleep(random.uniform(1, 3))
            
            url = f"{self.base_url}/{code}"
            logger.info(f"正在訪問: {url}")
            
            async with session.get(url, headers=self.headers) as response:
                if response.status != 200:
                    logger.error(f"訪問失敗，狀態碼: {response.status}")
                    return "Unknown"
                    
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                actress_span = soup.find('span', class_='genre', 
                    attrs={'onmouseover': lambda x: x and 'hoverdiv' in x})
                
                if actress_span:
                    actress_link = actress_span.find('a')
                    if actress_link:
                        actress_name = actress_link.text.strip()
                        logger.info(f"獲取到女優資訊: {code} -> {actress_name}")
                        return actress_name
                        
                logger.warning(f"未找到女優資訊: {code}")
                return "Unknown"
                    
        except Exception as e:
            logger.error(f"處理影片 {code} 時發生錯誤: {type(e).__name__}: {str(e)}")
            return "Unknown"
            
    async def process_file(self, file_info: tuple, session: aiohttp.ClientSession) -> dict:
        """處理單個檔案"""
        subfolder_path, filename, root_folder = file_info
        file_path = os.path.join(subfolder_path, filename)
        
        if not os.path.isfile(file_path):
            logger.warning(f"檔案不存在: {file_path}")
            return None
        
        _, ext = os.path.splitext(filename)
        if ext.lower() not in valid_extensions:
            logger.info(f"跳過不支援的檔案類型: {filename}")
            return None
        
        try:
            new_filename = filename
            for remove_str in remove_strings:
                new_filename = new_filename.replace(remove_str, "")
                
            code = os.path.splitext(new_filename)[0]
            if '-' in code:
                parts = code.split('-')
                if len(parts) >= 2:
                    code = parts[0] + '-' + parts[1]
            elif '_' in code:
                parts = code.split('_')
                if len(parts) >= 2:
                    code = parts[0] + '-' + parts[1] # 將 _ 轉換為 -
            
            logger.info(f"正在分析番號: {code}")
            actress_name = await self.get_actress_info(code, session)
            
            # 建立女優資料夾
            actress_folder = os.path.join(root_folder, actress_name)
            os.makedirs(actress_folder, exist_ok=True)
            
            # 處理檔案名稱衝突
            final_path = os.path.join(actress_folder, new_filename)
            if os.path.exists(final_path):
                base_name, extension = os.path.splitext(new_filename)
                counter = 1
                while True:
                    temp_name = f"{base_name}_{counter}{extension}"
                    final_path = os.path.join(actress_folder, temp_name)
                    if not os.path.exists(final_path):
                        new_filename = temp_name
                        break
                    counter += 1
            
            # 移動檔案
            shutil.move(file_path, final_path)
            logger.info(f"成功移動: {filename} → {actress_name}/{new_filename}")
            
            return {
                "filename": filename,
                "actress": actress_name,
                "new_path": final_path
            }
            
        except Exception as e:
            logger.error(f"處理檔案 {filename} 時發生致命錯誤: {str(e)}")
            return None

# =============================
# 檔案和處理邏輯
# =============================
def collect_files(root_folder: str) -> list:
    """收集所有需要處理的檔案，包括所有子資料夾"""
    file_list = []
    
    # 使用 os.walk 徹底遍歷根目錄下的所有層級
    for dirpath, dirnames, filenames in os.walk(root_folder):
        # 檢查當前目錄中的每一個檔案
        for filename in filenames:
            _, ext = os.path.splitext(filename)
            # 檢查副檔名是否符合設定
            if ext.lower() in valid_extensions:
                # 儲存 (檔案所在絕對路徑, 檔名, 使用者選定的根目錄)
                file_list.append((dirpath, filename, root_folder))
                logger.info(f"找到影片檔案: {filename} (位於: {os.path.relpath(dirpath, root_folder)})")
    
    logger.info(f"搜尋完畢，總共找到 {len(file_list)} 個需要處理的影片檔案")
    return file_list

async def process_files(root_folder: str):
    """處理所有檔案的核心非同步函數"""
    start_time = time.time()
    start_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("="*50)
    logger.info(f"開始處理時間: {start_datetime}")
    
    file_list = collect_files(root_folder)
    total_files = len(file_list)
    
    if total_files == 0:
        logger.info("沒有找到任何符合條件的影片檔案，處理結束。")
        return
    
    scraper = JavBusScraper()
    
    try:
        async with aiohttp.ClientSession() as session:
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
            
            async def process_with_semaphore(file_info):
                async with semaphore:
                    return await scraper.process_file(file_info, session)
            
            tasks = [process_with_semaphore(file_info) for file_info in file_list]
            results = await asyncio.gather(*tasks)
            results = [r for r in results if r is not None]
            
        successful = len(results)
        failed = total_files - successful
        
        end_time = time.time()
        end_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_time = end_time - start_time
        
        logger.info("\n" + "="*50)
        logger.info("處理完成摘要:")
        logger.info(f"結束時間: {end_datetime}")
        logger.info(f"成功處理檔案數: {successful}")
        logger.info(f"處理失敗檔案數: {failed}")
        logger.info(f"總處理時間: {total_time:.2f} 秒")
        if total_files > 0:
            logger.info(f"平均每個檔案處理時間: {total_time/total_files:.2f} 秒")
        logger.info("="*50)
        
    except Exception as e:
        logger.error(f"處理過程中發生嚴重錯誤: {str(e)}")
        raise

# =============================
# GUI 和主執行邏輯
# =============================
def run_processing_in_thread(selected_root_folder: str, progress_window: tk.Toplevel):
    """在單獨的執行緒中運行核心處理邏輯"""
    try:
        # 執行檔案處理
        asyncio.run(process_files(selected_root_folder))
        
        # 處理完成後，彈出提示並允許關閉視窗
        messagebox.showinfo("完成", "所有檔案處理已完成！")
        progress_window.protocol("WM_DELETE_WINDOW", progress_window.destroy) # 恢復可關閉
        
    except Exception as e:
        logger.error(f"程式執行出錯: {str(e)}")
        messagebox.showerror("程式錯誤", f"處理過程中發生嚴重錯誤: {e}")
        progress_window.protocol("WM_DELETE_WINDOW", progress_window.destroy) # 恢復可關閉
    finally:
        # 清理執行緒資源
        global executor
        if executor:
            executor.shutdown(wait=False)
            executor = None

def main_gui():
    """主 GUI 流程：選擇資料夾 -> 顯示進度視窗 -> 運行處理"""
    global executor # 用於在處理結束時清理執行緒
    executor = None
    
    # 步驟 1: 隱藏主根視窗
    root = tk.Tk()
    root.withdraw()
    
    # 步驟 2: 顯示資料夾選擇對話框
    folder_path = filedialog.askdirectory(
        title="請選擇要處理的影片根目錄 (例如 E:\\H\\Beauty)"
    )
    
    if not folder_path:
        messagebox.showinfo("取消", "您取消了資料夾選擇。程式將退出。")
        root.destroy()
        return
        
    if not os.path.exists(folder_path):
        messagebox.showerror("錯誤", f"目標目錄不存在: {folder_path}")
        root.destroy()
        return

    # 步驟 3: 創建進度顯示視窗
    progress_window = tk.Toplevel(root)
    progress_window.title(f"處理中... 目標: {os.path.basename(folder_path)}")
    
    tk.Label(progress_window, text="🎬 正在執行影片資訊爬取與重命名...").pack(pady=10)
    
    # 創建一個帶滾動條的文本框用於顯示日誌
    scrollbar = tk.Scrollbar(progress_window)
    log_text = tk.Text(progress_window, height=20, width=80, yscrollcommand=scrollbar.set)
    scrollbar.config(command=log_text.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    log_text.pack(padx=10, pady=5, side=tk.LEFT, fill=tk.BOTH, expand=True)

    # 步驟 4: 設置日誌處理器
    gui_handler = GuiLogHandler(log_text)
    logger.addHandler(gui_handler)
    
    # 處理進行中，不允許使用者關閉視窗 (直到處理完成)
    progress_window.protocol("WM_DELETE_WINDOW", lambda: messagebox.showerror("警告", "處理進行中，請勿關閉！"))

    # 步驟 5: 在單獨的執行緒中啟動耗時的處理
    executor = ThreadPoolExecutor(max_workers=1)
    # 將 run_processing 提交給執行緒，並傳遞選定的資料夾和進度視窗
    executor.submit(run_processing_in_thread, folder_path, progress_window)

    # 步驟 6: 運行 Tkinter 主循環
    # 這會保持 GUI 視窗開放，同時後臺執行緒在工作
    root.mainloop() 
    
    # 退出時移除 handler
    logger.removeHandler(gui_handler)

if __name__ == "__main__":
    main_gui()