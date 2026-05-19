import os
import time
import hmac
import struct
import winreg
import base64
import hashlib
import keyboard
import pyperclip
import configparser
import urllib.parse
import threading
import winsound
import ctypes
import traceback
import colorama
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import wmi
import pystray
from PIL import Image, ImageDraw

def show_message(title, msg, is_error=False):
    """彈出 Windows 系統提示視窗"""
    icon_type = 0x10 if is_error else 0x40
    ctypes.windll.user32.MessageBoxW(0, msg, title, icon_type | 0x40000)

def get_cpu_serial():
    """獲取 CPU 序號作為硬體綁定金鑰"""
    c = wmi.WMI()
    for processor in c.Win32_Processor():
        return processor.ProcessorId.strip()

# 全域設定與狀態變數
cpu_serial = get_cpu_serial() 
PASSWORD = "KU9Q7DyEGWxcQuwKwancGCCs5texammX" + cpu_serial

DELAY_BEFORE = 0.3
DELAY_AFTER = 0.5
HOTKEY = 'f12'  # ★ 已經將全域預設快捷鍵改為 f12
is_paused = False 
console_visible = True 

def load_config():
    """讀取或建立設定檔 config.ini"""
    global DELAY_BEFORE, DELAY_AFTER, HOTKEY
    config = configparser.ConfigParser()
    config_file = 'config.ini'

    if not os.path.exists(config_file):
        config['Settings'] = {
            '; 這是按下快捷鍵後，寫入剪貼簿前的延遲時間 (秒)': '',
            'delay_before_copy': '0.3',
            '; 這是寫入剪貼簿後，防止連續觸發的冷卻時間 (秒)': '',
            'delay_after_copy': '0.5',
            '; 觸發自動輸入的快捷鍵 (例如: f12, home, page up, end)': '',
            'hotkey': 'f12'  # ★ 產生的預設設定檔也改為 f12
        }
        try:
            with open(config_file, 'w', encoding='utf-8') as configfile:
                config.write(configfile)
        except Exception:
            pass
    else:
        try:
            config.read(config_file, encoding='utf-8')
            DELAY_BEFORE = float(config['Settings'].get('delay_before_copy', 0.3))
            DELAY_AFTER = float(config['Settings'].get('delay_after_copy', 0.5))
            HOTKEY = config['Settings'].get('hotkey', 'f12').lower()  # ★ 讀取不到時的備案也改為 f12
        except Exception:
            pass

def generate_random_without_comma(length: int) -> bytes:
    while True:
        random_bytes = os.urandom(length)
        if b',' not in random_bytes:
            return random_bytes

class AESCipher:
    @staticmethod
    def generate_key(password: str, salt: bytes = None) -> bytes:
        if salt is None:
            salt = generate_random_without_comma(16)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
        return base64.urlsafe_b64encode(kdf.derive(password.encode())), salt

    @staticmethod
    def encrypt(message: str, password: str) -> tuple:
        key, salt = AESCipher.generate_key(password)
        return Fernet(key).encrypt(message.encode()), salt

    @staticmethod
    def decrypt(encrypted_message: bytes, password: str, salt: bytes) -> str:
        key, _ = AESCipher.generate_key(password, salt)
        return Fernet(key).decrypt(encrypted_message).decode()

def process_file(input_file: str, output_file: str):
    """處理並加密 authenticator.txt"""
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        modified_lines = []
        parsed_count = 0
        for line in lines:
            line = line.strip()
            if not line: continue
            
            account, secret = None, None
            already_encrypted = False

            if line.startswith("otpauth://"):
                parsed_url = urllib.parse.urlparse(line)
                raw_path = urllib.parse.unquote(parsed_url.path).replace('/totp/', '')
                account = raw_path.strip(':/').split(':')[-1]
                query_params = urllib.parse.parse_qs(parsed_url.query)
                if 'secret' in query_params:
                    secret = query_params['secret'][0]
            elif ',' in line:
                parts = line.split(',')
                account = parts[0].strip()
                secret_part = parts[1].strip()
                if len(secret_part) >= 30:
                    already_encrypted = True
                    secret = secret_part
                else:
                    secret = secret_part

            if account and secret:
                if not already_encrypted:
                    encrypted_message, salt = AESCipher.encrypt(secret, PASSWORD)
                    final_secret = str(salt + encrypted_message)
                    parsed_count += 1
                else:
                    final_secret = secret 
                modified_lines.append(f"{account},{final_secret}")

        temp_file = output_file + '.tmp'
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(modified_lines))
        os.replace(temp_file, output_file)
        if parsed_count > 0:
            print(f">> 成功加密了 {parsed_count} 筆新帳號！")
        return parsed_count
    except Exception as e:
        show_message("檔案處理錯誤", f"處理 {input_file} 時發生錯誤：\n{str(e)}", True)
        return 0

def get_registry_value():
    """讀取登錄檔抓取遊戲 ID"""
    try:
        key_path = r"SOFTWARE\WOW6432Node\Gravity Soft\Ragnarok"
        registry_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        value, _ = winreg.QueryValueEx(registry_key, "ID")
        winreg.CloseKey(registry_key)
        return str(value).strip('\x00').strip()
    except Exception:
        return None

def generate_totp(secret_key, digits=6, period=30):
    """計算 TOTP 六位數"""
    secret_key = secret_key.upper().replace(' ', '')
    missing_padding = len(secret_key) % 8
    if missing_padding != 0:
        secret_key += '=' * (8 - missing_padding)
    secret_bytes = base64.b32decode(secret_key)
    time_step = int(time.time()) // period
    hmac_digest = hmac.new(secret_bytes, struct.pack('>Q', time_step), hashlib.sha1).digest()
    offset = hmac_digest[-1] & 0xf
    otp_int = struct.unpack('>I', hmac_digest[offset:offset + 4])[0] & 0x7fffffff
    return str(otp_int % (10 ** digits)).zfill(digits)

def read_encrypted_data(file_path, target_id):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                parts = line.strip().split(',')
                if len(parts) >= 2 and parts[0] == target_id:
                    encrypted_data = eval(parts[1])
                    return encrypted_data[:16], encrypted_data[16:]
    except Exception:
        pass
    return None, None

def on_trigger():
    """按下快捷鍵後的執行邏輯"""
    if is_paused:
        return
        
    result = get_registry_value()
    if not result:
        print(colorama.Fore.RED + ">> [錯誤] 找不到遊戲ID，請確認已開啟 RO 登入畫面。" + colorama.Style.RESET_ALL)
        winsound.Beep(500, 300) 
        return
        
    salt, ciphertext = read_encrypted_data('authenticator.txt', result)
    if not salt or not ciphertext:
        print(colorama.Fore.RED + f">> [錯誤] 找不到對應帳號 ({result}) 的金鑰。" + colorama.Style.RESET_ALL)
        winsound.Beep(500, 300)
        return
        
    try:
        decrypted_message = AESCipher.decrypt(ciphertext, PASSWORD, salt)
        otp_code = generate_totp(decrypted_message)
    except Exception:
        print(colorama.Fore.RED + ">> [錯誤] 解密失敗，硬體環境可能已變更，或密碼檔毀損。" + colorama.Style.RESET_ALL)
        winsound.Beep(500, 300)
        return

    print(f">> 遊戲ID：{result} ｜ OTP：{otp_code} (準備複製...)")
    time.sleep(DELAY_BEFORE)
    
    pyperclip.copy(otp_code)
    winsound.Beep(2000, 150) 
    
    print(colorama.Fore.CYAN + ">> OTP 已複製！請在遊戲內按 [Ctrl + V] 貼上。" + colorama.Style.RESET_ALL)
    print("-" * 40)
    time.sleep(DELAY_AFTER)

def create_tray_image():
    """產生系統列的小圖示"""
    image = Image.new('RGB', (64, 64), color=(40, 44, 52))
    dc = ImageDraw.Draw(image)
    dc.rectangle([16, 16, 48, 48], fill=(97, 175, 239))
    return image

def toggle_pause(icon, item):
    global is_paused
    is_paused = not is_paused
    if is_paused:
        print(colorama.Fore.YELLOW + ">> [狀態] ⏸ 已暫停監聽快捷鍵。" + colorama.Style.RESET_ALL)
    else:
        print(colorama.Fore.GREEN + ">> [狀態] ▶ 已恢復監聽快捷鍵。" + colorama.Style.RESET_ALL)

def toggle_console(icon, item):
    global console_visible
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        if console_visible:
            ctypes.windll.user32.ShowWindow(hwnd, 0) # 隱藏
            console_visible = False
        else:
            ctypes.windll.user32.ShowWindow(hwnd, 5) # 顯示
            console_visible = True

def on_quit_callback(icon, item):
    icon.stop()
    os._exit(0)

def background_listener():
    keyboard.add_hotkey(HOTKEY, on_trigger)
    keyboard.wait()

def main():
    try:
        colorama.init() 

        print("=" * 65)
        print(" 歡迎使用 RO 登入 TOTP 驗證輔助機 (動態視窗版)")
        print("=" * 65)
        
        load_config()
        
        print("【操作說明】")
        print(" 1. 請將匯出的 authenticator.txt 備份檔放在本程式同一資料夾")
        print(" 2. 程式啟動時會自動將資料轉換成硬體專屬加密格式")
        print(f" 3. 進入遊戲需要驗證碼時，按下 [{HOTKEY.upper()}] 鍵")
        print(" 4. 聽到「嗶」聲後，直接按 [Ctrl + V] 貼上即可")
        print("=" * 65)
        print(colorama.Fore.YELLOW + " ※ 提示：對系統匣圖示「左鍵單擊」即可快速隱藏/顯示視窗" + colorama.Style.RESET_ALL)
        print("=" * 65)

        input_file = 'authenticator.txt'
        
        if os.path.exists(input_file):
            process_file(input_file, input_file)
        else:
            show_message("找不到備份檔", f"找不到 {input_file}。\n請將備份檔放在同一個資料夾，然後重啟程式。", True)
            os._exit(0)

        listener_thread = threading.Thread(target=background_listener, daemon=True)
        listener_thread.start()

        menu = pystray.Menu(
            pystray.MenuItem(f"快捷鍵: [{HOTKEY.upper()}]", lambda item: None, enabled=False),
            pystray.MenuItem(lambda item: "▶ 恢復運作" if is_paused else "⏸ 暫停監聽", toggle_pause),
            pystray.MenuItem(lambda item: "👀 隱藏黑視窗" if console_visible else "💻 顯示黑視窗", toggle_console, default=True),
            pystray.MenuItem("❌ 關閉程式", on_quit_callback)
        )
        
        icon = pystray.Icon("RO_OTP", create_tray_image(), "RO OTP 輔助機", menu)
        icon.run()

    except Exception as e:
        error_msg = traceback.format_exc()
        show_message("嚴重錯誤 (Crash Report)", f"程式遇到無法處理的錯誤而關閉。錯誤詳情如下供排查參考：\n\n{error_msg}", True)
        os._exit(1)

if __name__ == "__main__":
    main()