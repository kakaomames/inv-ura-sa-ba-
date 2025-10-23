# lib/helpers/encrypt_query.py
import base64
import json
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# ❗ 注: この関数は、Invidious Companionが使用する特定の暗号化スキームを再現したものです。
# 実際の設定値 (config.secret.video_playback_decryption_key, IVなど) に依存します。
# 動作させるには、configから適切な値をロードし、bytes型に変換する必要があります。

def decrypt_query(encrypted_query: str, config: dict) -> str:
    """
    Invidious Companionの暗号化された動画クエリ文字列を複合化する。
    AES-256-CBCを使用していると仮定して実装。
    """
    try:
        # 設定から鍵とIVを取得（Denoコードと一致させるため、Base64デコードを想定）
        key_base64 = config.get("secret", {}).get("video_playback_decryption_key")
        iv_base64 = config.get("secret", {}).get("video_playback_decryption_iv")

        if not key_base64 or not iv_base64:
            raise ValueError("Decryption key or IV not found in config.")

        key = base64.b64decode(key_base64)
        iv = base64.b64decode(iv_base64)
        
        # URLセーフなBase64を通常のBase64に戻してからデコード
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_query + '==')

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        
        decrypted_padded = decryptor.update(encrypted_bytes) + decryptor.finalize()
        
        # PKCS7パディングの除去
        padding_size = decrypted_padded[-1]
        decrypted_unpadded = decrypted_padded[:-padding_size]

        return decrypted_unpadded.decode("utf-8")

    except Exception as e:
        print(f"[ERROR] クエリの複合化に失敗しました: {e}")
        # Denoコードと同じくエラーとして処理
        raise Exception("Failed to decrypt query string.") from e

# Denoコードにはありませんが、テスト用に暗号化関数も提供（オプション）
def encrypt_query(query_data: dict, config: dict) -> str:
    """
    動画クエリデータを暗号化し、URLセーフなBase64文字列として返す。
    """
    try:
        key_base64 = config.get("secret", {}).get("video_playback_decryption_key")
        iv_base64 = config.get("secret", {}).get("video_playback_decryption_iv")
        key = base64.b64decode(key_base64)
        iv = base64.b64decode(iv_base64)
        
        data_bytes = json.dumps(query_data, separators=(',', ':')).encode("utf-8")
        
        # PKCS7パディングを追加
        padding_size = 16 - (len(data_bytes) % 16)
        padded_data = data_bytes + bytes([padding_size]) * padding_size
        
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        
        encrypted_bytes = encryptor.update(padded_data) + encryptor.finalize()
        
        # URLセーフなBase64にエンコード
        return base64.urlsafe_b64encode(encrypted_bytes).rstrip(b'=').decode('utf-8')
        
    except Exception as e:
        raise Exception("Failed to encrypt query string.") from e
