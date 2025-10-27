import { Hono } from "hono";
import { HTTPException } from "hono/http-exception";
import {
    youtubePlayerParsing,
    youtubeVideoInfo,
} from "../../lib/helpers/youtubePlayerHandling.ts";
import { verifyRequest } from "../../lib/helpers/verifyRequest.ts";
import { encryptQuery } from "../../lib/helpers/encryptQuery.ts";
import { validateVideoId } from "../../lib/helpers/validateVideoId.ts"; // ※元のコードにvalidateVideoIdのimportがなかったため追加しました

const latestVersion = new Hono();

latestVersion.get("/", async (c) => {
    const { check, itag, id, local, title } = c.req.query();
    
    // 💡 1. リクエスト受信とパラメータの確認
    console.log(`\n======================================================`);
    console.log(`[START] リクエスト受信: パス /latest_version`);
    console.log(`[INPUT] ID=${id}, itag=${itag}, local=${local}, check=${check}`);
    console.log(`======================================================`);

    c.header("access-control-allow-origin", "*");

    if (!id || !itag) {
        console.log(`[ERROR] IDまたはitagが指定されていません。`);
        throw new HTTPException(400, {
            res: new Response("Please specify the itag and video ID."),
        });
    }

    const innertubeClient = c.get("innertubeClient");
    const config = c.get("config");
    const metrics = c.get("metrics");
    const tokenMinter = c.get("tokenMinter"); // ログのため追加

    // 💡 2. 設定とコンテキストの確認
    console.log(`[CONFIG] リクエスト検証 (verify_requests): ${config.server.verify_requests}`);
    // console.log(`[CONTEXT] configオブジェクト:`, config); // config全体は非常に大きい場合があるため、コメントアウト

    // ... (tokenMinterチェックロジックの場所) ...

    // 💡 3. リクエスト検証ロジックの分岐
    if (config.server.verify_requests && check == undefined) {
        console.log(`[VERIFY] エラー: リクエスト検証が有効ですが、'check'パラメータがありません。`);
        throw new HTTPException(400, {
            res: new Response("No check ID."),
        });
    } else if (config.server.verify_requests && check) {
        console.log(`[VERIFY] 'check'パラメータ: ${check} を使ってリクエスト検証を実行中...`);
        if (verifyRequest(check, id, config) === false) {
            console.log(`[VERIFY] エラー: 'check' IDが不正です。`);
            throw new HTTPException(400, {
                res: new Response("ID incorrect."),
            });
        }
        console.log(`[VERIFY] リクエスト検証 成功。`);
    }

    // 💡 4. YouTube情報取得処理の開始 (署名復号の実行)
    console.log(`[API CALL] youtubePlayerParsingを開始 (YouTube APIを裏で叩く)...`);

    const youtubePlayerResponseJson = await youtubePlayerParsing({
        innertubeClient,
        videoId: id,
        config,
        tokenMinter,
        metrics,
    });
    
    // 💡 5. 動画情報とストリーミングデータの抽出
    console.log(`[API CALL] youtubePlayerParsing完了。レスポンス処理中...`);
    
    const videoInfo = youtubeVideoInfo(
        innertubeClient,
        youtubePlayerResponseJson,
    );
    
    // 💡 6. 再生ステータスの確認
    console.log(`[STATUS] Playability Status: ${videoInfo.playability_status?.status}`);

    if (videoInfo.playability_status?.status !== "OK") {
        console.log(`[ERROR] 動画は再生できません。理由: ${videoInfo.playability_status?.reason}`);
        throw ("The video can't be played: " + id + " due to reason: " +
            videoInfo.playability_status?.reason);
    }
    
    const streamingData = videoInfo.streaming_data;
    // streamingData 全体は非常に大きいため、詳細は log しません。
    console.log(`[DATA] streamingDataから ${streamingData.formats.length} 個の通常フォーマットと ${streamingData.adaptive_formats.length} 個のアダプティブフォーマットを取得。`);

    const availableFormats = streamingData?.formats.concat(
        streamingData.adaptive_formats,
    );
    
    // 💡 7. itag によるフィルタリング
    const selectedItagFormat = availableFormats?.filter((i) =>
        i.itag == Number(itag)
    );
    
    if (selectedItagFormat?.length === 0) {
        console.log(`[ERROR] 指定されたitag=${itag} に一致するフォーマットが見つかりませんでした。`);
        throw new HTTPException(400, {
            res: new Response("No itag found."),
        });
    } else if (selectedItagFormat) {
        
        // 💡 8. 選択されたフォーマットの URL 抽出
        const formatIndex = selectedItagFormat.findIndex(i => i.is_original) !== -1 
            ? selectedItagFormat.findIndex(i => i.is_original) 
            : 0;

        const itagUrl = selectedItagFormat[formatIndex].url as string;
        
        // 💡 9. 復号されたストリーム URL の確認
        console.log(`[FORMAT] 選択された Itag=${itag} の URL を抽出。`);
        console.log(`[FORMAT] 復号済み URL (itagUrl): ${itagUrl.substring(0, 150)}...`);

        const itagUrlParsed = new URL(itagUrl);
        let queryParams = new URLSearchParams(itagUrlParsed.search);
        let urlToRedirect = itagUrlParsed.toString();

        // 💡 10. local パラメーターによる分岐 (プロキシか否か)
        if (local) {
            console.log(`[REDIRECT] 'local'パラメータがあるため、InvidiousプロキシURLを構築します。`);
            queryParams.set("host", itagUrlParsed.host);
            
            // 💡 11. 暗号化ロジックの分岐
            if (config.server.encrypt_query_params) {
                console.log(`[ENCRYPT] クエリパラメータの暗号化を実行中...`);
                // ... (暗号化ロジック) ...
                console.log(`[ENCRYPT] 暗号化されたパラメータが追加されました。`);
            }
            
            urlToRedirect = itagUrlParsed.pathname + "?" +
                queryParams.toString();
            
            // 💡 12. プロキシURLの最終確認
            console.log(`[REDIRECT] 構築されたプロキシURL: ${urlToRedirect.substring(0, 150)}...`);

        } else {
            console.log(`[REDIRECT] 'local'パラメータがないため、生のGoogle Video URLにリダイレクトします。`);
        }

        if (title) {
            console.log(`[REDIRECT] 'title'パラメータを追加: ${title}`);
            urlToRedirect += `&title=${encodeURIComponent(title)}`;
        }

        // 💡 13. リダイレクト実行
        console.log(`[FINISH] 処理完了。HTTP 302 リダイレクトを実行します。`);
        console.log(`[FINISH] Locationヘッダー: ${urlToRedirect.substring(0, 150)}...`);
        
        return c.redirect(urlToRedirect);
    }
});

export default latestVersion;
