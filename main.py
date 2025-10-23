# main.py (Vercel対応済みかつローカル実行対応の最終版)
import sys
import os
import asyncio
import signal
import logging
import uvicorn
from fastapi import FastAPI
import sys
import os

# --- 1. システムパスの修正 ---
# main.pyがあるディレクトリ(プロジェクトのルート)をパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


# --- 2. 外部モジュールのインポート ---
# Denoコードの parseConfig の代わり
from lib.helpers.config import parse_config 
# Denoコードの videoPlaybackProxy の代わり
from videoplayback import video_playback_router 


# --- 3. ロギング設定 ---
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# --- 4. GracefulExit クラス（ローカル実行時のみ使用） ---
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


# --- 5. グローバルスコープ: Vercel/Gunicorn が使用する部分 ---

# 設定の読み込みは、サーバーレス環境でも必要
try:
    config_data = parse_config()
except SystemExit:
    # 設定ファイルがない場合はここで終了
    sys.exit(1)

# **最重要**: FastAPIアプリケーションインスタンスをグローバル変数 `app` として定義
app = FastAPI(title="Invidious Companion Proxy")

# Context変数の設定 (Deno c.set("config", config) に相当)
app.state.config = config_data

# ルーティングの組み込み (Deno routes(app, config); の代わり)
app.include_router(video_playback_router, prefix="/videoplayback")


# --- 6. ローカル実行用のエントリーポイント ---
# main.py の app.include_router(...) の付近に追加

@app.get("/")
async def root_status():
    """
    サーバーのステータスチェック用ルート
    """
    return {"status": "ok", "message": "Invidious Companion Proxy is running!", "endpoint": "/videoplayback"}

# 既存のルーターの組み込み
#app.include_router(video_playback_router, prefix="/videoplayback")
# Deno L301: if (import.meta.main) { ... } に相当
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
            # Deno L278: Deno.removeSync(udsPath);
            if os.path.exists(uds_path):
                os.remove(uds_path)
        except Exception as e:
            logging.error(f"Failed to delete unix domain socket '{uds_path}' before starting the server: {e}")
            pass

        # Uvicorn の Unix Domain Socket 設定
        server_config = uvicorn.Config(app, uds=uds_path)
        
        # Deno L295: Deno.chmodSync(udsPath, 0o777); の再現ロジック
        def set_permissions():
            logging.info(f"Setting unix domain socket '{uds_path}' permissions to 777")
            try:
                os.chmod(uds_path, 0o777)
            except Exception as e:
                logging.warning(f"Failed to set permissions on UDS: {e}")

        # Uvicorn起動後に権限設定を実行
        async def startup_event():
            # blocking IO operation (os.chmod) は別スレッドで実行
            await asyncio.to_thread(set_permissions)
        
        app.add_event_handler("startup", startup_event)
    
    else:
        # 通常のホスト:ポート設定
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
