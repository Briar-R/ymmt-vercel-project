// ★ 警告: このAPIエンドポイントURLをあなたのAPI GatewayのURLに置き換えてください。
const API_ENDPOINT = 'https://4ge666g877.execute-api.ap-southeast-2.amazonaws.com/prod'; 

async function fetchData(endpoint) {
    try {
        const url = `${API_ENDPOINT}/api/${endpoint}`;
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`データの取得に失敗しました: HTTP ${response.status}`);
        }
        
        // 1. 応答本文全体を生のテキストとして取得する
        const responseText = await response.text();
        
        // 2. 外部のLambda応答構造全体をJSONとしてパース
        const outerResponse = JSON.parse(responseText); 
        
        // 3. 'body' キーの内容（JSON文字列）を取り出し、再度パースしてデータオブジェクトを取得
        if (outerResponse.statusCode === 200 && outerResponse.body) {
            // bodyの内容をデコードせずに直接パース
            const innerData = JSON.parse(outerResponse.body);
            return innerData; // {data: [...]} の形式を返す
        } else {
            // Lambdaでエラーが発生した場合の処理
            const errorBody = outerResponse.body ? outerResponse.body : 'No response body.';
            throw new Error(`Lambdaエラー: ${outerResponse.statusCode} - ${errorBody}`);
        }
        
    } catch (error) {
        // デバッグ情報としてコンソールに出力
        console.error(`[${endpoint}] Fetch error:`, error);
        return { data: [] }; // データが取得できなかった場合は空の配列を返す
    }
}

// チャンネル一覧と動画一覧を表示する関数
async function renderItems() {
    // statsのデータ取得を追加
    const [channelsData, videosData, statsData] = await Promise.all([
        fetchData('channels'),
        fetchData('videos'),
        fetchData('stats')
    ]);

    // --- チャンネル一覧のレンダリング ---
    const channelsList = document.getElementById('channels-list');
    channelsList.innerHTML = '';
    channelsData.data.forEach(channel => {
        const div = document.createElement('div');
        div.className = 'item';
        div.innerHTML = `
            <h3><a href="https://www.youtube.com/channel/${channel.channel_id}" target="_blank">${channel.title}</a></h3>
            <p>タグ: ${channel.char_tags.join(', ')}</p>
        `;
        channelsList.appendChild(div);
    });

    // --- 動画一覧のレンダリング ---
    const videosList = document.getElementById('videos-list');
    videosList.innerHTML = '';
    videosData.data.forEach(video => {
        const div = document.createElement('div');
        div.className = 'item';
        div.innerHTML = `
            <h3><a href="https://www.youtube.com/watch?v=${video.video_id}" target="_blank">${video.title}</a></h3>
            <p>チャンネル: ${video.channel_title}</p>
            <p>タグ: ${video.char_tags.join(', ')}</p>
        `;
        videosList.appendChild(div);
    });

    // --- 再生数ランキングのレンダリング ---
    const statsList = document.getElementById('stats-list');
    statsList.innerHTML = '';
    statsData.data.forEach(stat => {
        const div = document.createElement('div');
        div.className = 'item';
        div.innerHTML = `
            <h3><a href="https://www.youtube.com/watch?v=${stat.video_id}" target="_blank">${stat.video_title}</a></h3>
            <p>総再生数: ${stat.total_views.toLocaleString()}</p>
            <p>過去30日間の再生数: ${stat.views_last_30_days.toLocaleString()}</p>
        `;
        statsList.appendChild(div);
    });
}

// ページ読み込み時に実行
document.addEventListener('DOMContentLoaded', renderItems);