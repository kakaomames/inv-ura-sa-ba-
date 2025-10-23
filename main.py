# main.py (Vercel対応済みかつローカル実行対応の最終最終版)
import sys
import os
import asyncio
import signal
import logging
import uvicorn
from fastapi import FastAPI
from typing import Dict, Any, Optional

# --- 0. Vercel/インポートパスの修正 ---
# Vercel環境で兄弟ファイルやサブディレクトリのモジュールを確実にインポートします。
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# --- ロギング初期化 ---
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# --- 1. グローバルスコープ: Vercel/Gunicorn が使用する部分 (最重要) ---

# **最重要**: FastAPIアプリケーションインスタンスをグローバル変数 `app` として定義
# Vercelはこの変数を探します。この行以前でクラッシュしてはいけません。
app = FastAPI(title="Invidious Companion Proxy")

# --- 2. 外部モジュールのインポート ---
# app定義後、インポートを行います。
try:
    from lib.helpers.config import parse_config 
    from videoplayback import video_playback_router 
except ImportError as e:
    logger.critical(f"FATAL: Module Import Failed. Vercel likely failed to find a file: {e}")
    sys.exit(1)


# --- 3. 設定の読み込みと適用 (グローバルスコープで実行) ---

config_data: Optional[Dict[str, Any]] = parse_config()

# videoplayback.py が要求するキーを含む、最小限の安全な設定
DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 8000, "use_unix_socket": False, "unix_socket_path": ""},
    "invidious": {"instance_url": "https://invidious.example.com"},
    # videoplayback.py L150 で必要とされるキーを定義
    "networking": {
        "videoplayback": {
            "video_fetch_chunk_size_mb": 1 # 1MBをデフォルト値とする
        }
    }
}

if config_data is None:
    logger.critical("FATAL: Configuration data is missing or invalid. Application will run in a minimal state.")
    # 設定がない場合は、最小限の構造を持つダミー設定を格納
    app.state.config = DEFAULT_CONFIG
else:
    # 読み込んだ設定に、デフォルト値が不足している場合はマージするなどの工夫が必要ですが、
    # ここではシンプルな設定格納のみを行います
    app.state.config = config_data


# --- 4. ルーティングの組み込み ---

# 設定ロード後にルーターを組み込みます。
try:
    app.include_router(video_playback_router, prefix="/videoplayback")
except Exception as e:
    logger.critical(f"FATAL: Failed to include video_playback_router: {e}")

# ルートパスの追加 (サーバーの状態確認用)
@app.get("/")
async def root_status():
    """
    サーバーのステータスチェック用ルート
    """
    # 設定がデフォルトかどうかをチェック
    status = "ok" if app.state.config != DEFAULT_CONFIG else "degraded (default config used)"
    message = "Invidious Companion Proxy is running!" if app.state.config != DEFAULT_CONFIG else "Proxy running but configuration failed to load. Using default networking settings."
    
    return {"status": status, "message": message, "endpoint": "/videoplayback"}


# --- 5. GracefulExit クラス（ローカル実行時のみ使用） ---
class GracefulExit:
    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        
    def exit_gracefully(self, signum, frame):
        print("Caught SIGINT/SIGTERM, forcing shutdown...")
        os._exit(0) 


# --- 6. ローカル実行用のエントリーポイント ---
if __name__ == "__main__":
    # Uvicornをインポート（ローカル実行時のみ必要）
    import uvicorn
    
    # シグナルハンドラのセットアップ
    gracer = GracefulExit() 
    
    # app.state.config からサーバー設定を取得
    local_config = app.state.config["server"]
    host = local_config["host"]
    port = local_config["port"]
    use_uds = local_config["use_unix_socket"]
    uds_path = local_config["unix_socket_path"]

    # Uvicornの起動ロジック
    if use_uds:
        logger.info(f"Unix Domain Socket ({uds_path}) を使用して起動します。")
        # ... UDS ロジックは省略 ...
        server_config = uvicorn.Config(app, uds=uds_path)
    else:
        logger.info(f"Serving on http://{host}:{port}")
        server_config = uvicorn.Config(app, host=host, port=port)
    
    server = uvicorn.Server(server_config)
    
    try:
        server.run()
    except SystemExit:
        pass
    except Exception as e:
        logger.critical(f"Unhandled error during server runtime: {e}")
        sys.exit(1)
