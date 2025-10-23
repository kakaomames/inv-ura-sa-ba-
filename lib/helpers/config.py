# lib/helpers/config.py の修正
import json
import os
from typing import Dict, Any

def parse_config() -> Dict[str, Any]:
    """
    config.json ファイルを読み込み、Pythonの辞書として返す。
    """
    # Vercel環境に対応するため、カレントディレクトリ（/var/task）を基点にする
    # または、os.getcwd() を使ってプロジェクトのルートを取得する
    
    # 既存のロジック:
    # base_dir = os.path.dirname(os.path.abspath(__file__))
    # project_root = os.path.dirname(os.path.dirname(base_dir))
    # config_path = os.path.join(project_root, 'config.json')

    # 新しいロジック: 環境に依存せず、常にプロジェクトルート（カレントディレクトリ）の config.json を探す
    config_path = os.path.join(os.getcwd(), '/config.json')
    
    # os.getcwd()がVercelで信頼できない場合、最もシンプルな方法:
    config_path = 'config.json' 
    # Vercelはプロジェクトのルートにあるファイルをカレントディレクトリ(/var/task)に配置するため

    print(f"[INFO] 設定ファイル '{config_path}' を読み込みます。")

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        return config_data
    except FileNotFoundError:
        # Vercel環境でファイルが見つからない場合は、致命的エラーとして扱う
        print(f"[FATAL] エラー: '{config_path}' ファイルが見つかりません！")
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        print(f"[FATAL] エラー: '{config_path}' の形式が不正です。JSONパースエラー: {e}")
        raise SystemExit(1)
