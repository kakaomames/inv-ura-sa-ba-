# videoplayback.py (骨子)
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, Response
import aiohttp
import asyncio
from typing import AsyncGenerator

# 外部からのインポート（実際のパスに修正してください）
from lib.helpers.encrypt_query import decrypt_query # 移植した関数
from lib.helpers.rfc5987 import encode_rfc5987_value_chars # 移植した関数
# from lib.helpers.config import get_config # configはDIで受け取る想定

# Honoルーターの代わり
video_playback_router = APIRouter()

# Denoの getFetchClient(config) の代わりとして aiohttp.ClientSession を使う
async def get_fetch_client(config):
    # config.networking.proxy などを考慮した aiohttp.ClientSession を返す
    # 例：proxyを設定する場合
    # proxy_url = config.get("networking", {}).get("proxy_url")
    # connector = aiohttp.ProxyConnector(proxy=proxy_url) if proxy_url else None
    return aiohttp.ClientSession(
        connector_owner=True, 
        connector=None # プロキシ設定などを反映
    )

# --- 1. CORS OPTIONS メソッドの再現 ---
@video_playback_router.options("/")
async def options_handler():
    # L25-L33 の Hono コードを再現
    headers = {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET, OPTIONS",
        "access-control-allow-headers": "Content-Type, Range",
    }
    return Response(status_code=200, headers=headers, content="OK")

# --- 2. GET メソッドの再現 ---
@video_playback_router.get("/")
async def get_handler(request: Request):
    # Honoの c.req.query() からクエリパラメータを取得
    query_params = dict(request.query_params)
    host = query_params.get("host")
    expire = query_params.get("expire")
    client = query_params.get("c")
    title = query_params.get("title")

    # FastAPIではContext変数がないため、ここでは一時的にconfigを直接取得（DIが必要）
    # Denoコードの c.get("config") の代わり
    config = request.app.state.config # main.pyで設定する前提

    # --- 2.1. 暗号化クエリの復号化 (L37-L48) ---
    if query_params.get("enc") == "true":
        encrypted_data = query_params.get("data")
        if not encrypted_data:
            raise HTTPException(400, detail="Encrypted data 'data' is missing.")
            
        decrypted_query_string = decrypt_query(encrypted_data, config)
        decrypted_params = json.loads(decrypted_query_string) # Denoコードと同じくJSON.parseを想定
        
        # クエリパラメータを更新 (L43-L47を再現)
        del query_params["enc"]
        del query_params["data"]
        query_params["pot"] = decrypted_params.get("pot")
        query_params["ip"] = decrypted_params.get("ip")


    # --- 2.2. 検証ロジック (L49-L74) ---
    if not host or not re.match(r"[\w-]+.googlevideo.com", host):
        raise HTTPException(400, detail="ホストのクエリ文字列が一致しないか、未定義です。")

    current_timestamp = int(time.time())
    if not expire or int(expire) < current_timestamp:
        raise HTTPException(400, detail="クエリ文字列が未定義であるか、videoplayback の URL の有効期限が切れています。")
    
    if not client:
        raise HTTPException(400, detail="'c' クエリ文字列が未定義です。")

    del query_params["host"]
    del query_params["title"]

    # --- 2.3. Rangeヘッダーの処理 (L79-L90) ---
    range_header = request.headers.get("range")
    request_bytes = range_header.split("=")[1] if range_header else None
    
    if request_bytes:
        # DenoコードではURLSearchParamsにrangeを追加していた (L90)
        query_params["range"] = request_bytes 
        first_byte, last_byte = request_bytes.split("-") if "-" in request_bytes else (request_bytes, None)
    else:
        first_byte = "0"
        last_byte = None
    
    # --- 2.4. ヘッダーの準備 (L92-L102) と User-Agentの設定 ---
    # headers_to_sendを構築するロジック（Deno L92-L102を再現）
    # client に基づく User-Agent の設定も再現
    headers_to_send = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-us,en;q=0.5",
        "origin": "https://www.youtube.com",
        "referer": "https://www.youtube.com",
        "user-agent": get_user_agent(client) # Deno L105-L113 を再現する関数
    }

    # --- 2.5. リダイレクト追跡 (L115-L135) ---
    fetch_client = await get_fetch_client(config)
    location = f"https://{host}/videoplayback?{urllib.parse.urlencode(query_params)}"
    head_response: aiohttp.ClientResponse = None

    for i in range(5):
        # Deno L117-L121 を aiohttp で再現
        async with fetch_client.head(location, headers=headers_to_send, allow_redirects=False) as resp:
            if resp.status == 403:
                return Response(status_code=403, content=await resp.read(), headers=dict(resp.headers))
            
            new_location = resp.headers.get("Location")
            if new_location:
                location = new_location
                continue
            else:
                head_response = resp
                break
    
    if head_response is None:
        raise HTTPException(502, detail="Google headResponse redirected too many times")
    
    # --- 2.6. チャンク分割ストリーミング (L137-L177) ---
    
    async def chunked_streaming_generator() -> AsyncGenerator[bytes, None]:
        # Deno L137-L177 のロジックを非同期ジェネレータで再現
        
        chunk_size = config["networking"]["videoplayback"]["video_fetch_chunk_size_mb"] * 1_000_000
        total_bytes = int(head_response.headers.get("Content-Length") or "0")
        
        whole_request_start_byte = int(first_byte or "0")
        whole_request_end_byte = whole_request_start_byte + total_bytes - 1
        
        # locationのURLオブジェクトを作成
        google_video_url = urllib.parse.urlparse(location)
        google_video_url_base = google_video_url._replace(query="").geturl()

        for start_byte in range(whole_request_start_byte, whole_request_end_byte, chunk_size):
            end_byte = start_byte + chunk_size - 1
            if end_byte > whole_request_end_byte:
                end_byte = whole_request_end_byte
            
            # クエリパラメータに range を追加
            current_query = dict(urllib.parse.parse_qsl(google_video_url.query))
            current_query["range"] = f"{start_byte}-{end_byte}"
            post_url = f"{google_video_url_base}?{urllib.parse.urlencode(current_query)}"
            
            # Deno L164-L171 を再現
            async with fetch_client.post(
                post_url,
                data=b'\x78\x00', # Denoコードと同じボディ
                headers=headers_to_send,
            ) as post_resp:
                if post_resp.status != 200:
                    raise Exception("Non-200 response from google servers")

                # ストリームとして読み込み、クライアントへ yield
                async for chunk in post_resp.content.iter_chunked(8192):
                    yield chunk
            
            # Denoコードでは Promise.then() で順次実行していますが、
            # Pythonの for ループは本質的に順次実行なので、await は不要（ジェネレータが自動で一時停止するため）
            # ただし、FastAPIがチャンクを受け取る間はブロックしない

    # --- 2.7. 最終ヘッダーの構築とレスポンス (L180-L232) ---
    
    # Deno L180-L188 を再現 (必要なヘッダーを head_response からコピー)
    headers_for_response = {
        "content-length": head_response.headers.get("content-length", ""),
        "access-control-allow-origin": "*",
        "accept-ranges": head_response.headers.get("accept-ranges", ""),
        "content-type": head_response.headers.get("content-type", ""),
        "expires": head_response.headers.get("expires", ""),
        "last-modified": head_response.headers.get("last-modified", ""),
    }

    if title:
        # L191-L194 の content-disposition の構築を再現
        encoded_title_rfc5987 = encode_rfc5987_value_chars(title)
        headers_for_response["content-disposition"] = (
            f'attachment; filename="{urllib.parse.quote(title)}"; filename*=UTF-8''{encoded_title_rfc5987}'
        )
        
    # L198-L230 の responseStatus と content-range ヘッダーのロジックを再現
    response_status = head_response.status
    # ... 省略: 206 Partial Content のロジックを Range ヘッダーに基づいて設定 ...

    return StreamingResponse(
        chunked_streaming_generator(),
        status_code=response_status,
        headers=headers_for_response,
        media_type=head_response.headers.get("content-type", "application/octet-stream")
    )
