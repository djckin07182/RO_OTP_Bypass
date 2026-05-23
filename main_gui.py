import os
import customtkinter as ctk
import keyboard
import threading
import pyperclip
import time
import winreg
import hmac
import struct
import hashlib
import base64
import winsound
import pystray
from PIL import Image, ImageDraw
from db_manager import DatabaseManager

# 設定整體 UI 主題
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

def create_tray_image():
    """產生系統匣的小圖示"""
    image = Image.new('RGB', (64, 64), color=(40, 44, 52))
    dc = ImageDraw.Draw(image)
    dc.rectangle([16, 16, 48, 48], fill=(97, 175, 239))
    return image

class ROAuthenticatorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.db = DatabaseManager()
        self.title("RO 登入 TOTP 輔助機 v2.0")
        self.geometry("700x480")
        self.resizable(False, False)

        # 攔截 X 按鈕，直接關閉程式
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        # 攔截 - (縮小) 按鈕，觸發隱藏至系統匣
        self.bind("<Unmap>", self.on_minimize)

        self.hotkey = "f12"
        self.is_paused = False 
        self.tray_icon = None
        
        # 建立左右兩大區塊
        self.left_frame = ctk.CTkFrame(self)
        self.left_frame.pack(side="left", fill="both", expand=True, padx=(20, 10), pady=20)
        
        self.right_frame = ctk.CTkFrame(self, width=280)
        self.right_frame.pack(side="right", fill="y", padx=(10, 20), pady=20)

        # 頂部全域狀態提示
        self.status_label = ctk.CTkLabel(self, text=f"🟢 目前狀態：{self.hotkey.upper()} 快捷鍵監聽中...", text_color="#2ecc71", font=("Arial", 14, "bold"))
        self.status_label.place(relx=0.5, rely=0.02, anchor="n")

        self.build_left_panel()
        self.build_right_panel()
        self.start_hotkey_listener()

    # ================== 左側：帳號清單區 ==================
    def build_left_panel(self):
        ctk.CTkLabel(self.left_frame, text="🎮 我的帳號庫", font=("Arial", 16, "bold")).pack(pady=(10, 5))
        
        self.scroll_frame = ctk.CTkScrollableFrame(self.left_frame)
        self.scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.refresh_account_list()

    def refresh_account_list(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
            
        accounts = self.db.get_all_accounts()
        if not accounts:
            ctk.CTkLabel(self.scroll_frame, text="目前沒有帳號，請從右側新增或匯入。").pack(pady=20)
            return

        for game_id, secret in accounts.items():
            row_frame = ctk.CTkFrame(self.scroll_frame, fg_color="#2b2b2b")
            row_frame.pack(fill="x", pady=2, padx=2)
            
            lbl_btn = ctk.CTkButton(row_frame, text=game_id, width=150, anchor="w", fg_color="transparent", hover_color="#3a3a3a",
                                    command=lambda id=game_id: self.fill_entries(id))
            lbl_btn.pack(side="left", padx=5)
            
            btn = ctk.CTkButton(row_frame, text="複製", width=60, 
                                command=lambda s=secret: self.manual_copy(s))
            btn.pack(side="right", padx=5, pady=5)

    def fill_entries(self, game_id):
        self.entry_id.delete(0, 'end')
        self.entry_id.insert(0, game_id)

    # ================== 右側：操作與設定區 ==================
    def build_right_panel(self):
        # 區塊 1：快捷鍵控制
        self.switch_var = ctk.StringVar(value="on")
        self.hotkey_switch = ctk.CTkSwitch(self.right_frame, text=f"啟用 {self.hotkey.upper()} 快捷鍵", 
                                           variable=self.switch_var, onvalue="on", offvalue="off",
                                           command=self.toggle_hotkey)
        self.hotkey_switch.pack(pady=(20, 15), padx=15, anchor="w")
        
        ctk.CTkFrame(self.right_frame, height=2, fg_color="#444444").pack(fill="x", padx=15, pady=5)

        # 區塊 2：單筆新增/修改/刪除
        ctk.CTkLabel(self.right_frame, text="⚙️ 編輯帳號", font=("Arial", 14, "bold")).pack(pady=(5, 5), anchor="w", padx=15)
        
        self.entry_id = ctk.CTkEntry(self.right_frame, placeholder_text="遊戲帳號 (ID)")
        self.entry_id.pack(fill="x", padx=15, pady=5)
        
        self.entry_secret = ctk.CTkEntry(self.right_frame, placeholder_text="TOTP 金鑰 (Secret)")
        self.entry_secret.pack(fill="x", padx=15, pady=5)
        
        btn_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=5)
        
        ctk.CTkButton(btn_frame, text="儲存", width=100, fg_color="#2980b9", hover_color="#3498db", command=self.save_account).pack(side="left", expand=True, padx=(0, 5))
        ctk.CTkButton(btn_frame, text="刪除", width=100, fg_color="#c0392b", hover_color="#e74c3c", command=self.delete_account).pack(side="right", expand=True, padx=(5, 0))

        ctk.CTkFrame(self.right_frame, height=2, fg_color="#444444").pack(fill="x", padx=15, pady=10)

        # 區塊 3：檔案操作
        ctk.CTkLabel(self.right_frame, text="📁 檔案管理", font=("Arial", 14, "bold")).pack(pady=(0, 5), anchor="w", padx=15)
        ctk.CTkButton(self.right_frame, text="📥 匯入 txt", fg_color="#27ae60", hover_color="#2ecc71", command=self.import_data).pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(self.right_frame, text="📤 匯出備份", fg_color="#d35400", hover_color="#e67e22", command=self.export_data).pack(fill="x", padx=15, pady=5)

        ctk.CTkFrame(self.right_frame, height=2, fg_color="#444444").pack(fill="x", padx=15, pady=10)

        # 區塊 4：視窗控制 (隱藏至系統匣)
        ctk.CTkButton(self.right_frame, text="👀 隱藏至系統匣 (背景運行)", fg_color="#8e44ad", hover_color="#9b59b6", 
                      command=self.hide_to_tray).pack(fill="x", padx=15, pady=5)

    # ================== 核心功能邏輯 ==================
    def save_account(self):
        game_id = self.entry_id.get()
        secret = self.entry_secret.get()
        if self.db.add_account(game_id, secret):
            self.entry_id.delete(0, 'end')
            self.entry_secret.delete(0, 'end')
            self.refresh_account_list()
            self.show_temp_status(f"✅ 已儲存：{game_id}")

    def delete_account(self):
        game_id = self.entry_id.get()
        if self.db.delete_account(game_id):
            self.entry_id.delete(0, 'end')
            self.refresh_account_list()
            self.show_temp_status(f"🗑️ 已刪除：{game_id}")

    def toggle_hotkey(self):
        if self.switch_var.get() == "on":
            self.is_paused = False
            self.status_label.configure(text=f"🟢 目前狀態：{self.hotkey.upper()} 快捷鍵監聽中...", text_color="#2ecc71")
        else:
            self.is_paused = True
            self.status_label.configure(text="⏸ 已暫停監聽快捷鍵", text_color="#e74c3c")

    def import_data(self):
        file_path = ctk.filedialog.askopenfilename(title="選擇匯入檔", filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if file_path:
            imported = self.db.import_from_txt(file_path)
            if imported > 0:
                self.refresh_account_list()
                self.show_temp_status(f"✅ 成功匯入 {imported} 筆帳號！")
            else:
                self.show_temp_status("❌ 匯入失敗", is_error=True)

    def export_data(self):
        file_path = ctk.filedialog.asksaveasfilename(title="儲存備份檔", initialfile="RO_Backup.txt", defaultextension=".txt")
        if file_path:
            if self.db.export_to_txt(file_path):
                self.show_temp_status("✅ 成功匯出備份檔！")
            else:
                self.show_temp_status("❌ 匯出失敗", is_error=True)

    def manual_copy(self, secret):
        try:
            otp_code = self.generate_totp_code(secret) 
            pyperclip.copy(otp_code)
            self.show_temp_status(f"✅ 已複製驗證碼：{otp_code}")
        except Exception:
            self.show_temp_status("❌ 驗證碼產生失敗！", is_error=True)

    def generate_totp_code(self, secret_key, digits=6, period=30):
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

    def show_temp_status(self, msg, is_error=False):
        color = "#e74c3c" if is_error else "#f1c40f"
        self.status_label.configure(text=msg, text_color=color)
        self.after(2500, lambda: self.status_label.configure(text=f"🟢 目前狀態：{self.hotkey.upper()} 快捷鍵監聽中..." if not self.is_paused else "⏸ 已暫停監聽", text_color="#2ecc71" if not self.is_paused else "#e74c3c"))

    # ================== 背景監聽邏輯 ==================
    def start_hotkey_listener(self):
        thread = threading.Thread(target=self.hotkey_loop, daemon=True)
        thread.start()

    def hotkey_loop(self):
        keyboard.add_hotkey(self.hotkey, self.trigger_otp)
        keyboard.wait()
        
    def trigger_otp(self):
        if self.is_paused:
            return
            
        try:
            key_path = r"SOFTWARE\WOW6432Node\Gravity Soft\Ragnarok"
            registry_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            value, _ = winreg.QueryValueEx(registry_key, "ID")
            winreg.CloseKey(registry_key)
            game_id = str(value).strip('\x00').strip()
        except Exception:
            game_id = None

        if not game_id:
            self.after(0, lambda: self.show_temp_status("❌ 找不到遊戲ID，請確認已開啟 RO。", is_error=True))
            winsound.Beep(500, 300)
            return
            
        secret = self.db.get_secret(game_id)
        if not secret:
            self.after(0, lambda: self.show_temp_status(f"❌ 找不到帳號 ({game_id}) 的金鑰。", is_error=True))
            winsound.Beep(500, 300)
            return
            
        try:
            otp_code = self.generate_totp_code(secret)
            pyperclip.copy(otp_code)
            self.after(0, lambda: self.show_temp_status(f"✅ {game_id} 驗證碼已複製！"))
            winsound.Beep(2000, 150)
            time.sleep(0.5) 
        except Exception:
            self.after(0, lambda: self.show_temp_status("❌ 解密或產生 OTP 失敗。", is_error=True))
            winsound.Beep(500, 300)

    # ================== 系統匣隱藏邏輯 ==================
    
    def on_closing(self):
        """按下 X 鍵直接關閉程式"""
        os._exit(0)

    def on_minimize(self, event):
        """攔截視窗縮小事件，將其隱藏到系統匣"""
        # 確保觸發事件的是主視窗，而不是視窗內的其他小元件
        if str(event.widget) == str(self):
            if self.wm_state() == 'iconic':  # 'iconic' 是 Tkinter 中代表「已縮小」的狀態
                self.hide_to_tray()

    def hide_to_tray(self):
        self.withdraw() # 隱藏視窗
        menu = pystray.Menu(
            pystray.MenuItem("▶ 顯示視窗", self.restore_from_tray, default=True),
            pystray.MenuItem("❌ 關閉程式", self.quit_from_tray)
        )
        self.tray_icon = pystray.Icon("RO_OTP", create_tray_image(), "RO OTP 輔助機", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def restore_from_tray(self, icon, item):
        icon.stop()
        self.after(0, self.show_window)

    def show_window(self):
        """恢復視窗並確保它不是處於縮小狀態"""
        self.deiconify()
        self.state('normal') # 強制將視窗從 iconic(縮小) 恢復成 normal(正常)

    def quit_from_tray(self, icon, item):
        icon.stop()
        os._exit(0)

if __name__ == "__main__":
    app = ROAuthenticatorApp()
    app.mainloop()