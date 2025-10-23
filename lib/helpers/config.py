# lib/helpers/config.py
import json
import os
from typing import Dict, Any

# ❗ 注意: Denoコードは 'await parseConfig()' でしたが、
# PythonでシンプルなJSON読み込みは通常同期で行います。

def parse_config() -> Dict[str, Any]:
    """
    config.json ファイルを読み込み、Pythonの辞書として返す。
    """
    # スクリプトがある場所（lib/helpers）から相対的にプロジェクトルートを特定
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # プロジェクトルートに移動: .../lib/helpers/config.py -> .../lib/helpers -> .../lib -> .../inv
    project_root = os.path.dirname(os.path.dirname(base_dir))
    config_path = os.path.join(project_root, 'config.json')

    print(f"[INFO] 設定ファイル '{config_path}' を読み込みます。")

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        return config_data
    except FileNotFoundError:
        print("[FATAL] エラー: 'config.json' ファイルが見つかりません！")
        print("プロジェクトのルートディレクトリに設定ファイルがあるか確認してください。")
        # 実行を停止
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        print(f"[FATAL] エラー: 'config.json' の形式が不正です。JSONパースエラー: {e}")
        raise SystemExit(1)
