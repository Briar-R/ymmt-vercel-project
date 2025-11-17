import os
import psycopg2
from googleapiclient.discovery import build
import json
import base64
from datetime import date
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS

# Vercelは環境変数を自動で読み込みます
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
NEON_CONNECTION_STRING = os.environ.get("NEON_CONNECTION_STRING")

# Flaskアプリの初期化
app = Flask(__name__)
# CORS(app) # すべてのルートでCORSを許可
# Vercelでは vercel.json で制御するため、FlaskのCORSは不要な場合がありますが、
# 念のため有効にしておきます。
CORS(app)


# --- データベース/API接続関数 ---

def get_db_connection():
    print(f"DEBUG: Connecting with string length: {len(NEON_CONNECTION_STRING) if NEON_CONNECTION_STRING else 0}")
    conn = psycopg2.connect(NEON_CONNECTION_STRING)
    return conn

def get_youtube_service():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# --- メタデータ取得/登録関数 ---
# (get_channel_metadata, get_video_metadata, register_channel, register_video関数は以前のコードと同じため省略)
def get_channel_metadata(channel_id, youtube):
    try:
        request = youtube.channels().list(part="snippet", id=channel_id)
        response = request.execute()
        if not response.get('items'):
            return None
        item = response['items'][0]
        return {'channel_id': item['id'], 'title': item['snippet']['title']}
    except Exception as e:
        print(f"チャンネル情報取得エラー: {e}")
        return None

def get_video_metadata(video_id, youtube):
    try:
        request = youtube.videos().list(part="snippet", id=video_id)
        response = request.execute()
        if not response.get('items'):
            return None
        item = response['items'][0]
        return {'video_id': item['id'], 'channel_id': item['snippet']['channelId'], 'title': item['snippet']['title'], 'published_at': item['snippet']['publishedAt']}
    except Exception as e:
        print(f"動画情報取得エラー: {e}")
        return None

def register_channel(channel_id, char_tags):
    conn = get_db_connection()
    cursor = conn.cursor()
    youtube = get_youtube_service()
    if "youtube.com/channel/" in channel_id:
        channel_id = channel_id.split('/')[-1]
    metadata = get_channel_metadata(channel_id, youtube)
    if not metadata:
        conn.close()
        return False
    try:
        cursor.execute(
            "INSERT INTO channels (channel_id, title, char_tags) VALUES (%s, %s, %s) "
            "ON CONFLICT (channel_id) DO UPDATE SET title = EXCLUDED.title, char_tags = %s;",
            (metadata['channel_id'], metadata['title'], char_tags, char_tags)
        )
        conn.commit()
        print(f"チャンネル {metadata['title']} を登録しました。")
        return True
    except Exception as e:
        conn.rollback()
        print(f"データベース登録エラー: {e}")
        return False
    finally:
        conn.close()

def register_video(video_id, char_tags):
    conn = get_db_connection()
    cursor = conn.cursor()
    youtube = get_youtube_service()
    metadata = get_video_metadata(video_id, youtube)
    if not metadata:
        conn.close()
        return False
    try:
        cursor.execute(
            "INSERT INTO videos (video_id, channel_id, title, published_at, char_tags) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (video_id) DO UPDATE SET title = EXCLUDED.title, channel_id = EXCLUDED.channel_id, published_at = EXCLUDED.published_at, char_tags = %s;",
            (metadata['video_id'], metadata['channel_id'], metadata['title'], metadata['published_at'], char_tags, char_tags)
        )
        conn.commit()
        print(f"動画 {metadata['title']} を登録しました。")
        return True
    except Exception as e:
        conn.rollback()
        print(f"データベース登録エラー: {e}")
        return False
    finally:
        conn.close()

# --- 総再生数/日次更新関数 ---
# (update_video_stats_daily_views関数は以前のコードと同じため省略)
def update_video_stats_daily_views():
    print("--- DAILY VIEWS UPDATE START ---")
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        youtube = get_youtube_service()
        cursor.execute("SELECT video_id, total_views, daily_views_last_30_days FROM video_stats;")
        existing_stats = {row[0]: {'total': row[1], 'daily_array': row[2] if row[2] else []} for row in cursor.fetchall()}
        cursor.execute("SELECT video_id FROM videos;")
        video_ids = [row[0] for row in cursor.fetchall()]
        if not video_ids:
            print("DBに登録された動画が見つかりません。")
            return True
        batch_size = 50
        success_count = 0
        for i in range(0, len(video_ids), batch_size):
            batch_ids = video_ids[i:i + batch_size]
            id_string = ','.join(batch_ids)
            request = youtube.videos().list(part="statistics", id=id_string)
            response = request.execute()
            for item in response.get('items', []):
                video_id = item['id']
                current_total_views = int(item['statistics'].get('viewCount', 0))
                stats = existing_stats.get(video_id)
                previous_total_views = int(stats['total']) if stats and stats['total'] is not None else 0
                daily_increase = max(0, current_total_views - previous_total_views)
                daily_array = stats['daily_array'] if stats else []
                new_daily_array = [daily_increase] + daily_array
                if len(new_daily_array) > 30:
                    new_daily_array = new_daily_array[:30]
                cursor.execute(
                    """
                    INSERT INTO video_stats (video_id, total_views, daily_views_last_30_days, last_updated)
                    VALUES (%s, %s, %s, CURRENT_DATE)
                    ON CONFLICT (video_id) DO UPDATE SET 
                        total_views = EXCLUDED.total_views, 
                        daily_views_last_30_days = EXCLUDED.daily_views_last_30_days, 
                        last_updated = CURRENT_DATE;
                    """,
                    (video_id, current_total_views, new_daily_array)
                )
                success_count += 1
        conn.commit()
        print(f"--- DAILY UPDATE SUCCESS. Updated {success_count} videos. ---")
        return True
    except Exception as e:
        if conn: conn.rollback()
        print(f"FATAL ERROR: Daily Update Failed: {e}")
        return False
    finally:
        if conn: conn.close()


# --- APIエンドポイント (GET - ウェブサイト用) ---

@app.route("/channels", methods=['GET'])
def get_channels_api():
    conn = None
    print("--- GET /channels START ---")
    try:
        conn = get_db_connection()
        print("--- /channels: DB Connection Established ---")
        cursor = conn.cursor()
        cursor.execute("SELECT channel_id, title, char_tags FROM channels;")
        channels = [{'channel_id': row[0], 'title': row[1], 'char_tags': row[2]} for row in cursor.fetchall()]
        print(f"DEBUG: Retrieved {len(channels)} channels.")
        return jsonify({'data': channels}) # Flaskのjsonifyを使用
    except Exception as e:
        print(f"FATAL ERROR: /channels DB Access Failed: {e}")
        return make_response(jsonify({'data': [], 'message': f'DB Error: {str(e)}'}), 500)
    finally:
        if conn and not conn.closed:
            conn.close()

@app.route("/videos", methods=['GET'])
def get_videos_api():
    conn = None
    print("--- GET /videos START ---")
    try:
        conn = get_db_connection()
        print("--- /videos: DB Connection Established ---")
        cursor = conn.cursor()
        cursor.execute("SELECT v.video_id, v.title, v.char_tags, c.title AS channel_title FROM videos v JOIN channels c ON v.channel_id = c.channel_id WHERE array_length(v.char_tags, 1) > 0;")
        videos = [{'video_id': row[0], 'title': row[1], 'char_tags': row[2], 'channel_title': row[3]} for row in cursor.fetchall()]
        print(f"DEBUG: Retrieved {len(videos)} videos.")
        return jsonify({'data': videos})
    except Exception as e:
        print(f"FATAL ERROR: /videos DB Access Failed: {e}")
        return make_response(jsonify({'data': [], 'message': f'DB Error: {str(e)}'}), 500)
    finally:
        if conn and not conn.closed:
            conn.close()

@app.route("/stats", methods=['GET'])
def get_stats_api():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                v.video_id,
                v.title,
                vs.total_views,
                vs.daily_views_last_30_days 
            FROM videos v
            LEFT JOIN video_stats vs ON v.video_id = vs.video_id
            ORDER BY vs.total_views DESC;
        """)
        stats_data = []
        for row in cursor.fetchall():
            daily_array = row[3] if row[3] else []
            views_last_30_days = sum(daily_array) 
            stats_data.append({
                'video_id': row[0],
                'video_title': row[1],
                'total_views': int(row[2]) if row[2] is not None else 0,
                'views_last_30_days': views_last_30_days
            })
        print(f"DEBUG DATA (STATS): {json.dumps(stats_data)}")
        return jsonify({'data': stats_data})
    except Exception as e:
        print(f"GET Stats DB Error: {e}")
        return make_response(jsonify({'data': [], 'message': f'DB Error on GET: {str(e)}'}), 500)
    finally:
        if conn:
            conn.close()

# --- APIエンドポイント (POST - スプレッドシート用) ---

@app.route("/register/channels", methods=['POST'])
def register_channels_api():
    try:
        data = request.json # Flaskが自動でJSONをパース
        items = data.get('items')
    except Exception as e:
        print(f"JSON Processing Error: {str(e)}")
        return make_response(jsonify({'success': False, 'message': f'Invalid request processing: {str(e)}'}), 400)

    if not items:
        return make_response(jsonify({'success': False, 'message': 'データが指定されていません。'}), 400)
    
    success_count = 0
    total_count = len(items)
    
    for item in items:
        channel_id = item[0].strip()
        tags_string = item[1] if len(item) > 1 else ''
        char_tags = [tag.strip() for tag in tags_string.split(',') if tag.strip()]
        
        if register_channel(channel_id, char_tags):
            success_count += 1
            
    if success_count == total_count:
        return jsonify({'success': True, 'message': 'すべてのチャンネルの登録が完了しました。'})
    else:
        return make_response(jsonify({'success': False, 'message': f'登録中にエラーが発生しました。{total_count}件中{success_count}件のみ完了しました。'}), 500)

@app.route("/register/videos", methods=['POST'])
def register_videos_api():
    try:
        data = request.json
        items = data.get('items')
    except Exception as e:
        print(f"JSON Processing Error: {str(e)}")
        return make_response(jsonify({'success': False, 'message': f'Invalid request processing: {str(e)}'}), 400)

    if not items:
        return make_response(jsonify({'success': False, 'message': 'データが指定されていません。'}), 400)

    success_count = 0
    total_count = len(items)

    for item in items:
        video_id = item[0].strip()
        tags_string = item[1] if len(item) > 1 else ''
        char_tags = [tag.strip() for tag in tags_string.split(',') if tag.strip()]

        if register_video(video_id, char_tags):
            success_count += 1
            
    if success_count == total_count:
        return jsonify({'success': True, 'message': 'すべての動画の登録が完了しました。'})
    else:
        return make_response(jsonify({'success': False, 'message': f'登録中にエラーが発生しました。{total_count}件中{success_count}件のみ完了しました。'}), 500)

# --- APIエンドポイント (GET - Cronジョブ用) ---

@app.route("/update/dailyviews", methods=['GET'])
def daily_update_endpoint():
    print("Received request for daily update.")
    success = update_video_stats_daily_views()
    if success:
        return jsonify({'success': True, 'message': 'Daily views update attempted.'})
    else:
        return make_response(jsonify({'success': False, 'message': 'Daily views update failed.'}), 500)