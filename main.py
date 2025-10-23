# main.py (Vercel対応済みかつローカル実行対応の最終版)
import sys
import os
import asyncio
import signal
import logging
import uvicorn
from fastapi import FastAPI

# --- 1. 外部モジュールのインポート ---
# Vercel環境でインポートできるように、パッケージのパス依存性を避けるため、
# lib.helpers.configとvideoplaybackは直接インポートします。
from lib.helpers.config import parse_config 
from videoplayback import video_playback_router 


# --- 2. グローバルスコープ: Vercel/Gunicorn が使用する部分 ---

# **最重要**: FastAPIアプリケーションインスタンスをグローバル変数 `app` として定義
# Vercelはインポート時にこの変数を探します。
app = FastAPI(title="Invidious Companion Proxy")

# ロギング設定 (FastAPIの初期化後に行う)
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')


# 2.1. 設定の読み込みと適用 (appが定義された後で実行)
try:
    config_data = parse_config()
except SystemExit:
    # 設定ファイルがない場合は、アプリの動作が保証できないためプロセスを終了
    sys.exit(1)

# Context変数の設定 (Deno c.set("config", config) に相当)
app.state.config = config_data

# ルーティングの組み込み (Deno routes(app, config); の代わり)
app.include_router(video_playback_router, prefix="/videoplayback")

# ルートパスの追加 (サーバーの状態確認用)
@app.get("/")
async def root_status():
    """
    サーバーのステータスチェック用ルート
    """
    return {"status": "ok", "message": "Invidious Companion Proxy is running!", "endpoint": "/videoplayback"}


# --- 3. GracefulExit クラス（ローカル実行時のみ使用） ---
# Deno L304-L318 のシグナルハンドリングを Python で再現
class GracefulExit:
    def __init__(self, app: FastAPI):
        self.keep_running = True
        self.app = app
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        
    def exit_gracefully(self, signum, frame):
        print("Caught SIGINT/SIGTERM, shutting down...")
        self.keep_running = False
        os._exit(0) 


# --- 4. ローカル実行用のエントリーポイント ---
if __name__ == "__main__":
    
    # シグナルハンドラのセットアップ
    gracer = GracefulExit(app) 
    
    host = config_data["server"]["host"]
    port = config_data["server"]["port"]
    use_uds = config_data["server"]["use_unix_socket"]
    uds_path = config_data["server"]["unix_socket_path"]

    # Unix Domain Socket または通常の起動を設定
    if use_uds:
        logging.info(f"Unix Domain Socket ({uds_path}) を使用して起動します。")
        try:
            if os.path.exists(uds_path):
                os.remove(uds_path)
        except Exception as e:
            logging.error(f"Failed to delete unix domain socket '{uds_path}' before starting the server: {e}")
            pass

        server_config = uvicorn.Config(app, uds=uds_path)
        
        def set_permissions():
            logging.info(f"Setting unix domain socket '{uds_path}' permissions to 777")
            try:
                os.chmod(uds_path, 0o777)
            except Exception as e:
                logging.warning(f"Failed to set permissions on UDS: {e}")

        async def startup_event():
            await asyncio.to_thread(set_permissions)
        
        app.add_event_handler("startup", startup_event)
    
    else:
        logging.info(f"Serving on http://{host}:{port}")
        server_config = uvicorn.Config(app, host=host, port=port)
    
    # Uvicornサーバーの起動
    server = uvicorn.Server(server_config)
    
    try:
        server.run()
    except SystemExit:
        pass
    except Exception as e:
        logging.critical(f"Unhandled error during server runtime: {e}")
        sys.exit(1)
