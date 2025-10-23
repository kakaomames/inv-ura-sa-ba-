# videoplayback.py (前半: インポート、検証、ヘッダー設定)
import re
import json
import time
import urllib.parse
from typing import AsyncGenerator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, Response
import aiohttp

# 移植したヘルパー関数のインポート
from lib.helpers.encrypt_query import decrypt_query 
from lib.helpers.rfc5987 import encode_rfc5987_value_chars 

# FastAPIルーター (HonoのvideoPlaybackProxyの代わり)
video_playback_router = APIRouter()

# DenoコードのUser-Agent設定ロジックを関数化 (L105-L113)
def get_user_agent(client: str) -> str:
    if client == "ANDROID":
        return (
            "com.google.android.youtube/1537338816 (Linux; U; Android 13; en_US; ; "
            "Build/TQ2A.230505.002; Cronet/113.0.5672.24)"
        )
    elif client == "IOS":
        return (
            "com.google.ios.youtube/19.32.8 (iPhone14,5; U; CPU iOS 17_6 like Mac OS X;)"
        )
    else:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        )

# Denoコードの getFetchClient(config) の代わり（aiohttpセッションを生成）
async def get_fetch_client(config: dict) -> aiohttp.ClientSession:
    # 実際には config から proxy などを考慮したコネクタを生成する必要があります
    # 今回はシンプルに作成
    return aiohttp.ClientSession()

# --- OPTIONS メソッドの再現 (L25-L33) ---
@video_playback_router.options("/", include_in_schema=False)
async def options_handler():
    headers = {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET, OPTIONS",
        "access-control-allow-headers": "Content-Type, Range",
    }
    return Response(status_code=200, headers=headers, content="OK")

# --- GET メソッドの再現 (L35から開始) ---
@video_playback_router.get("/")
async def get_handler(request: Request):
    
    # Context変数 (c.get("config")) の取得
    config = request.app.state.config
    
    # クエリパラメータの取得と加工（Mutableな辞書として扱う）
    query_params = dict(request.query_params)
    
    host = query_params.get("host")
    expire = query_params.get("expire")
    client = query_params.get("c")
    title = query_params.get("title")
    
    # --- 1. 暗号化クエリの復号化 (L37-L48) ---
    if query_params.get("enc") == "true":
        encrypted_data = query_params.get("data")
        
        # decryptedQueryParams = decryptQuery(encryptedQuery, config); (L40)
        try:
            decrypted_query_string = decrypt_query(encrypted_data, config)
            # DenoコードはJSON.parseを使っているので、JSON形式で復号化されると仮定
            parsed_decrypted_params = json.loads(decrypted_query_string)
        except Exception as e:
            # 複合化失敗は400
            raise HTTPException(400, detail=f"クエリの複合化に失敗しました: {e}")
            
        # クエリパラメータを更新 (L43-L47)
        del query_params["enc"]
        del query_params["data"]
        
        # Denoコードと同じロジックで 'pot' と 'ip' を設定
        if parsed_decrypted_params.get("pot"):
             query_params["pot"] = parsed_decrypted_params["pot"]
        if parsed_decrypted_params.get("ip"):
             query_params["ip"] = parsed_decrypted_params["ip"]

    # --- 2. 検証ロジック (L49-L74) ---
    # hostの検証
    if host is None or not re.match(r"[\w-]+.googlevideo.com", host):
        raise HTTPException(400, detail="ホストのクエリ文字列が一致しないか、未定義です。")

    # expireの検証
    current_timestamp = int(time.time())
    if expire is None or int(expire) < current_timestamp:
        raise HTTPException(400, detail="クエリ文字列が未定義であるか、videoplayback の URL の有効期限が切れています。")
    
    # client ('c') の検証
    if client is None:
        raise HTTPException(400, detail="'c' クエリ文字列が未定義です。")

    # 不要なクエリパラメータを削除 (L76-L77)
    del query_params["host"]
    if "title" in query_params:
         del query_params["title"]

    # --- 3. Rangeヘッダーの処理 (L79-L90) ---
    range_header = request.headers.get("range")
    request_bytes = None
    first_byte = "0"
    last_byte = None
    
    if range_header:
        request_bytes = range_header.split("=")[1]
        
        # L83-L84
        if "-" in request_bytes:
            first_byte, last_byte = request_bytes.split("-")
        else:
            first_byte = request_bytes
            
        # L89-L90
        query_params["range"] = request_bytes

    # --- 4. ヘッダーの準備 (L92-L113) ---
    headers_to_send = {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-us,en;q=0.5",
        "origin": "https://www.youtube.com",
        "referer": "https://www.youtube.com",
        "user-agent": get_user_agent(client)
    }

    # 次回はリダイレクト追跡 (L115) からスタートします！


# Denoコードはここで前半が終わり、後半が始まります。
    
    # --- 5. リダイレクト追跡 (L115-L135) ---
    # Denoコードと同じく、ここで aiohttp.ClientSession を閉じます
    async with await get_fetch_client(config) as fetch_client:
        # L116: locationは前半のコードの末尾で既に定義されています。
        location = f"https://{host}/videoplayback?{urllib.parse.urlencode(query_params)}"
        head_response: aiohttp.ClientResponse = None
    
        # RFCの注記に従い、最大5回のリダイレクトを追跡 (L117)
        for i in range(5):
            # HEADリクエストを送信 (L121)
            # Denoコードは fetchClient(location, { method: "HEAD", ... }) を再現
            async with fetch_client.head(location, headers=headers_to_send, allow_redirects=False) as resp:
                
                # 403の場合、そのまま返す (L122-L126)
                if resp.status == 403:
                    # aiohttpのClientResponseからヘッダーとボディを取得し、FastAPIのResponseで返す
                    return Response(status_code=403, content=await resp.read(), headers=dict(resp.headers))
                
                # Locationヘッダーがある場合、リダイレクト先を追跡 (L127-L130)
                new_location = resp.headers.get("Location")
                if new_location:
                    location = new_location
                    continue
                else:
                    head_response = resp
                    break
        
        # リダイレクトが多すぎる場合の502エラー (L136-L143)
        if head_response is None:
            raise HTTPException(502, detail="Google headResponse redirected too many times")
        
        # --- 6. チャンク分割ストリーミング (L145-L177) ---
        # Denoの StreamingApi(writable, readable) の代わりとなる非同期ジェネレータ
        async def chunked_streaming_generator() -> AsyncGenerator[bytes, None]:
            
            # L149-L150: chunkSizeとtotalBytesの設定
            chunk_size = config["networking"]["videoplayback"]["video_fetch_chunk_size_mb"] * 1_000_000
            total_bytes = int(head_response.headers.get("Content-Length") or "0")
            
            # locationのURLオブジェクトを作成
            google_video_url = urllib.parse.urlparse(location)
            # クエリ無しのベースURL
            google_video_url_base = google_video_url._replace(query="").geturl()
            # 既存のクエリパラメータを辞書として取得
            existing_query = dict(urllib.parse.parse_qsl(google_video_url.query))

            # 全体のリクエスト範囲を決定 (L153-L154)
            whole_request_start_byte = int(first_byte or "0")
            whole_request_end_byte = whole_request_start_byte + total_bytes - 1

            # L155: チャンクごとのループを開始
            for start_byte in range(whole_request_start_byte, whole_request_end_byte, chunk_size):
                end_byte = start_byte + chunk_size - 1
                if end_byte > whole_request_end_byte:
                    end_byte = whole_request_end_byte
                
                # rangeクエリパラメータをセット (L158-L161)
                current_query = existing_query.copy() # ベースクエリをコピー
                current_query["range"] = f"{start_byte}-{end_byte}"
                post_url = f"{google_video_url_base}?{urllib.parse.urlencode(current_query)}"
                
                # POSTリクエストでチャンクを取得 (L164-L171)
                try:
                    # Deno L164: fetchClient(googleVideoUrl, { method: "POST", ... }) を再現
                    async with fetch_client.post(
                        post_url,
                        # protobuf: { 15: 0 } を再現 (L165)
                        data=b'\x78\x00', 
                        headers=headers_to_send,
                    ) as post_resp:
                        if post_resp.status != 200:
                            # L170: Non-200 response from google servers
                            raise Exception(f"Non-200 response ({post_resp.status}) from google servers")

                        # L171: await stream.pipe(postResponse.body) を再現
                        async for chunk in post_resp.content.iter_chunked(8192):
                            yield chunk
                except Exception as e:
                    # L176: chunk.catch(() => { stream.abort(); }) の代わり
                    print(f"[ERROR] チャンク処理中にエラーが発生しました: {e}")
                    raise 

        # --- 7. 最終レスポンスヘッダーの構築 (L180-L232) ---
        
        # ヘッダーの初期化 (L180-L188)
        # Denoコードは headResponse.headers.get("content-length") || "" を再現
        headers_for_response = {
            "content-length": head_response.headers.get("Content-Length", ""),
            "access-control-allow-origin": "*",
            "accept-ranges": head_response.headers.get("Accept-Ranges", ""),
            "content-type": head_response.headers.get("Content-Type", ""),
            "expires": head_response.headers.get("Expires", ""),
            "last-modified": head_response.headers.get("Last-Modified", ""),
        }

        # content-dispositionヘッダー (L190-L194)
        if title:
            # L192-L194: encodeURIComponent(title) と encodeRFC5987ValueChars(title) を再現
            encoded_title_rfc5987 = encode_rfc5987_value_chars(title)
            # urllib.parse.quote(title) は JS の encodeURIComponent の代替
            headers_for_response["content-disposition"] = (
                f'attachment; filename="{urllib.parse.quote(title)}"; filename*=UTF-8\'\'{encoded_title_rfc5987}'
            )

        # ステータスコードと Content-Range ヘッダーの処理 (L196-L230)
        response_status = head_response.status
        
        if request_bytes and response_status == 200:
            # 範囲ヘッダーがある場合の処理 (L198)
            
            if last_byte:
                # bytes=500-1000 の場合 (L208)
                response_status = 206
                headers_for_response["content-range"] = (
                    f"bytes {request_bytes}/{query_params.get('clen') or '*'}"
                )
            else:
                # bytes=500- の場合 (L213)
                bytes_received = headers_for_response["content-length"]
                total_content_length = int(first_byte) + int(bytes_received)
                last_byte_calc = total_content_length - 1
                
                # L222: i.e. "bytes=0-", "bytes=600-"
                if first_byte != "0":
                    # L226: 総コンテンツの一部のみが返されました、206
                    response_status = 206
                    
                # L228: 完全な Content-Range ヘッダーを構築
                headers_for_response["content-range"] = (
                    f"bytes {first_byte}-{last_byte_calc}/{total_content_length}"
                )
        
        # 最終レスポンス (L232-L236)
        return StreamingResponse(
            chunked_streaming_generator(),
            status_code=response_status,
            headers=headers_for_response,
            # Content-TypeはheadResponseから取得したものを使う
            media_type=head_response.headers.get("Content-Type", "application/octet-stream")
        )

# Denoコードはここで export default videoPlaybackProxy; でルーターをエクスポート
# Pythonでは FastAPIルーターを既に定義済みなので、これで完了です。


