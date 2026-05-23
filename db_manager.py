import os
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import wmi
import urllib.parse

class DatabaseManager:
    
    def __init__(self, db_filename="ro_accounts.json"):
        # --- 隱藏資料夾魔法開始 ---
        # 取得 Windows 的 Local AppData 隱藏路徑 (C:\Users\你的名字\AppData\Local)
        local_appdata = os.environ.get('LOCALAPPDATA')
        if not local_appdata:
            local_appdata = os.path.expanduser('~\\AppData\\Local')
            
        # 在 AppData 裡面建立一個專屬的資料夾
        self.app_dir = os.path.join(local_appdata, 'RO_Authenticator')
        
        # 確保資料夾存在，如果不存在就自動偷偷建立
        os.makedirs(self.app_dir, exist_ok=True)
        
        # 最終的資料庫檔案完整路徑
        self.db_file = os.path.join(self.app_dir, db_filename)
        # --- 隱藏資料夾魔法結束 ---

        self.cpu_serial = self._get_cpu_serial()
        self.password = "KU9Q7DyEGWxcQuwKwancGCCs5texammX" + self.cpu_serial
        self.accounts_cache = {} 
        self.load_database()

    def _get_cpu_serial(self):
        """獲取 CPU 序號作為硬體綁定金鑰"""
        c = wmi.WMI()
        for processor in c.Win32_Processor():
            return processor.ProcessorId.strip()
        return "DEFAULT_CPU_ID_IF_FAIL"

    def _generate_key(self, salt: bytes = None) -> tuple:
        if salt is None:
            salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000
        )
        return base64.urlsafe_b64encode(kdf.derive(self.password.encode())), salt

    def encrypt(self, message: str) -> str:
        """加密明文，回傳 salt + ciphertext 的 Base64 字串"""
        key, salt = self._generate_key()
        encrypted_message = Fernet(key).encrypt(message.encode())
        return base64.b64encode(salt + encrypted_message).decode('utf-8')

    def decrypt(self, combined_data_b64: str) -> str:
        """解密資料，還原出明文"""
        try:
            combined_data = base64.b64decode(combined_data_b64)
            salt = combined_data[:16]
            encrypted_message = combined_data[16:]
            key, _ = self._generate_key(salt)
            return Fernet(key).decrypt(encrypted_message).decode()
        except Exception:
            return None 

    def load_database(self):
        """啟動時讀取 JSON 並解密到記憶體中"""
        if not os.path.exists(self.db_file):
            self.accounts_cache = {}
            return

        try:
            with open(self.db_file, 'r', encoding='utf-8') as f:
                encrypted_db = json.load(f)
            
            self.accounts_cache = {}
            for game_id, encrypted_secret in encrypted_db.items():
                decrypted_secret = self.decrypt(encrypted_secret)
                if decrypted_secret:
                    self.accounts_cache[game_id] = decrypted_secret
        except Exception as e:
            print(f"讀取資料庫失敗: {e}")
            self.accounts_cache = {}

    def save_database(self):
        """將記憶體中的帳號加密並寫入 JSON 檔"""
        encrypted_db = {}
        for game_id, secret in self.accounts_cache.items():
            encrypted_db[game_id] = self.encrypt(secret)
            
        with open(self.db_file, 'w', encoding='utf-8') as f:
            json.dump(encrypted_db, f, indent=4)

    def add_account(self, game_id: str, secret: str) -> bool:
        game_id = game_id.strip()
        secret = secret.strip()
        if not game_id or not secret:
            return False
            
        self.accounts_cache[game_id] = secret
        self.save_database()
        return True

    def delete_account(self, game_id: str) -> bool:
        if game_id in self.accounts_cache:
            del self.accounts_cache[game_id]
            self.save_database()
            return True
        return False

    def get_all_accounts(self) -> dict:
        return self.accounts_cache

    def get_secret(self, game_id: str) -> str:
        return self.accounts_cache.get(game_id)

    def import_from_txt(self, file_path: str) -> int:
        """從 authenticator.txt 匯入並轉換"""
        count = 0
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    
                    if line.startswith("otpauth://"):
                        parsed_url = urllib.parse.urlparse(line)
                        raw_path = urllib.parse.unquote(parsed_url.path).replace('/totp/', '')
                        account = raw_path.strip(':/').split(':')[-1]
                        query_params = urllib.parse.parse_qs(parsed_url.query)
                        if 'secret' in query_params:
                            secret = query_params['secret'][0]
                            self.accounts_cache[account] = secret
                            count += 1
            if count > 0:
                self.save_database()
            return count
        except Exception:
            return -1

    def export_to_txt(self, export_path: str) -> bool:
        """將目前所有帳號匯出為未加密的 otpauth 格式"""
        try:
            lines = []
            for game_id, secret in self.accounts_cache.items():
                line = f"otpauth://totp/{game_id}:?secret={secret}&issuer={game_id}"
                lines.append(line)
                
            with open(export_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            return True
        except Exception:
            return False