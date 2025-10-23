# lib/helpers/rfc5987.py
import urllib.parse
import re

# RFC 5987でエンコードが不要な文字を定義
_re_unacceptable = re.compile(r"[\x00-\x1f\x7f-\xff%\\/]")

def encode_rfc5987_value_chars(input_str: str) -> str:
    """
    RFC 5987で定義された 'value-chars' のルールに従って文字列をエンコードする。
    Content-Dispositionヘッダーの 'filename*' パラメータに使用される。
    """
    if not isinstance(input_str, str):
        input_str = str(input_str)

    # UTF-8にエンコード
    utf8_bytes = input_str.encode('utf-8')
    
    encoded_parts = []
    
    # バイト列をチェックし、エンコードが必要な場合は %XX 形式に変換
    for byte in utf8_bytes:
        char = chr(byte)
        if _re_unacceptable.search(char):
            # エンコードが必要な文字 (%XX)
            encoded_parts.append(f"%{byte:02X}")
        else:
            # エンコードが不要な文字
            encoded_parts.append(char)
            
    # エンコードされた文字列を結合して返す
    return "".join(encoded_parts)
