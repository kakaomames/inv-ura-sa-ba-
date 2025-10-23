# main.py (完全版)
import sys
import os

# 1. パス修正 (前回のステップで追加済み)
# main.pyがあるディレクトリ(プロジェクトのルート)をパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


import uvicorn
from fastapi import FastAPI
import asyncio
import signal
import sys
import os
import time
import json
import logging

# Denoコードの parseConfig の代わり
from lib.helpers.config import parse_config 
# Denoコードの videoPlaybackProxy の代わり
from videoplayback import video_playback_router 
# Note: Denoコードの Innertube, poTokenGenerate などは今回は省略し、
# サーバー起動とプロキシ機能の再現に焦点を当てます。

# ロギング設定（Denoの console.log の代わりに）
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# Deno L304-L318 のシグナルハンドリングを Python で再現
class GracefulExit:
    def __init__(self, app: FastAPI):
        self.keep_running = True
        self.app = app
        # Denoの AbortController() の代わりに uvicorn の停止を使用しますが、
        # SIGTERM/SIGINTをキャッチするロジックは再現します。
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        
    def exit_gracefully(self, signum, frame):
        # Deno L314 / L318: console.log("Caught SIGINT, shutting down...")
        print("Caught SIGINT/SIGTERM, shutting down...")
        self.keep_running = False
        # Deno L315 / L319: controller.abort(); Deno.exit(0); に相当
        # uvicornサーバーが停止するのを待つため、ここでは sys.exit(0) は避け、
        # uvicornが SIGINT/SIGTERM を受け取って停止するのを待ちます。
        # 今回は uvicorn のデフォルトのシグナルハンドリングに任せるため、
        # ログ出力のみに留めます。
        os._exit(0) # 強制終了（Deno.exit(0)に相当）

# Deno L299: export function run(signal: AbortSignal, port: number, hostname: string)
def run_server(config: dict):
    # Deno L266: const app = new Hono(...)
    app = FastAPI(title="Invidious Companion Proxy")
    
    # Deno L262-L265 の Context変数の設定を app.state で再現
    # c.set("config", config) に相当し、他のルーターからアクセス可能にする
    app.state.config = config
    
    # Deno L270: routes(app, config); の代わり
    # /videoplayback パスにルーターを組み込む
    app.include_router(video_playback_router, prefix="/videoplayback")

    host = config["server"]["host"]
    port = config["server"]["port"]
    use_uds = config["server"]["use_unix_socket"]
    uds_path = config["server"]["unix_socket_path"]

    # Deno L272-L297: Unix Domain Socket の処理を uvicorn で再現
    if use_uds:
        logging.info(f"Unix Domain Socket ({uds_path}) を使用して起動します。")
        try:
            # Deno L278: Deno.removeSync(udsPath);
            if os.path.exists(uds_path):
                os.remove(uds_path)
        except Exception as e:
            # Deno L282-L287 のエラーログを再現
            logging.error(f"Failed to delete unix domain socket '{uds_path}' before starting the server: {e}")
            pass

        # Uvicorn の Unix Domain Socket 設定
        server_config = uvicorn.Config(app, uds=uds_path)
        server = uvicorn.Server(server_config)
        
        # Deno L295: Deno.chmodSync(udsPath, 0o777);
        def set_permissions():
            logging.info(f"Setting unix domain socket '{uds_path}' permissions to 777")
            try:
                os.chmod(uds_path, 0o777)
            except Exception as e:
                logging.warning(f"Failed to set permissions on UDS: {e}")

        # Uvicorn起動後に権限設定を実行するためのハック
        async def startup_event():
            await asyncio.to_thread(set_permissions)
        
        app.add_event_handler("startup", startup_event)
    
    else:
        # 通常のホスト:ポート設定
        server_config = uvicorn.Config(app, host=host, port=port)
        server = uvicorn.Server(server_config)
        logging.info(f"Serving on http://{host}:{port}")
    
    # Uvicornサーバーの起動
    server.run()


# Deno L301: if (import.meta.main) { ... }
if __name__ == "__main__":
    # Deno L306: const controller = new AbortController();
    # Deno L309: run(signal, config.server.port, config.server.host);
    
    # 設定ファイルの読み込み
    try:
        config_data = parse_config()
    except SystemExit:
        sys.exit(1)

    # シグナルハンドラのセットアップ (実際には uvicorn に任せますが、ロジックは残す)
    # run_server(config_data)
    
    # GracefulExit(FastAPI(config=config_data))
    
    # Uvicorn にシグナルハンドリングを任せてサーバーを起動
    try:
        run_server(config_data)
    except SystemExit:
        # SIGTERM/SIGINT による正常終了を許可
        pass
    except Exception as e:
        logging.critical(f"Unhandled error during server runtime: {e}")
        sys.exit(1)
