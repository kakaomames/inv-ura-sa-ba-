# main.py (FastAPIサーバーの起動)
import uvicorn
from fastapi import FastAPI
import asyncio
# Denoコードの parseConfig の代わり
from lib.helpers.config import parse_config 
# Denoコードの videoPlaybackProxy の代わり
from videoplayback import video_playback_router 
import signal
import sys

# Deno L304-L318 のシグナルハンドリングを Python で再現
class GracefulExit:
    def __init__(self):
        self.keep_running = True
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        
    def exit_gracefully(self, *args):
        print("Caught SIGINT/SIGTERM, shutting down...")
        self.keep_running = False
        sys.exit(0)

# Deno L301-L302 の run(signal, port, hostname) の代わり
async def run_server(config):
    app = FastAPI(title="Invidious Companion Proxy")
    # Deno L262-L265 の Context変数の設定を app.state で再現
    app.state.config = config
    # 他の Context 変数もここで設定 (innertubeClient, tokenMinterなど)
    
    # Denoコードのルーティング (routes(app, config)) の代わり
    app.include_router(video_playback_router, prefix="/videoplayback") # 例としてパスを設定

    server_config = uvicorn.Config(
        app, 
        host=config["server"]["host"], 
        port=config["server"]["port"]
    )
    server = uvicorn.Server(server_config)
    
    # Unix Socket の処理 (Deno L272-L297) もここで再現可能
    if config["server"]["use_unix_socket"]:
        # Deno.removeSync/Deno.chmodSync に相当する処理を実行
        pass 
        
    await server.serve()

if __name__ == "__main__":
    # Deno L306-L309 の初期化とシグナル設定
    gracer = GracefulExit()
    config_data = parse_config() # await parseConfig() の代わり
    
    # サーバーの実行
    try:
        asyncio.run(run_server(config_data))
    except (SystemExit, KeyboardInterrupt):
        pass # SIGTERM/SIGINTで終了
