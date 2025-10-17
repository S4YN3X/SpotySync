import os
import time
import json
import redis
import spotipy
from huey import RedisHuey
from spotipy.oauth2 import SpotifyOAuth

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_conn = redis.from_url(REDIS_URL)

huey = RedisHuey('spotysync', url=os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))


def ensure_token(token_info):
    if token_info.get('expires_at', 0) - int(time.time()) < 60:
        auth = SpotifyOAuth(
            client_id=os.environ.get('SPOTIFY_CLIENT_ID'),
            client_secret=os.environ.get('SPOTIFY_CLIENT_SECRET'),
            redirect_uri=os.environ.get('SPOTIFY_REDIRECT_URI'),
            scope='playlist-modify-private playlist-modify-public user-read-private'
        )
        new_info = auth.refresh_access_token(token_info['refresh_token'])
        token_info.update(new_info)
    return token_info


@huey.task()
def search_candidates_task(token_info, queries, per_query_limit=4):
    """Ищет похожие треки и кэширует результаты."""
    r = redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379/0'))
    sp = spotipy.Spotify(auth=ensure_token(token_info)['access_token'])
    results_map = {}

    for q in queries:
        key = f"spotsearch:{q.lower()}"
        cached = r.get(key)
        if cached:
            results_map[q] = json.loads(cached)
            continue

        res = sp.search(q=q, type='track', limit=per_query_limit)
        items = res.get('tracks', {}).get('items', [])
        formatted = []
        for it in items:
            formatted.append({
                'id': it['id'],
                'name': it['name'],
                'artists': [a['name'] for a in it['artists']],
                'album': {
                    'name': it['album']['name'],
                    'images': it['album']['images']
                },
                'duration_ms': it['duration_ms'],
                'uri': it['uri']
            })
        results_map[q] = formatted
        r.setex(key, 3600 * 24, json.dumps(formatted))
        time.sleep(0.2)

    return results_map


def spotify_safe_parse(bytes_or_str):
    if isinstance(bytes_or_str, (bytes, bytearray)):
        bytes_or_str = bytes_or_str.decode('utf-8')
    return json.loads(bytes_or_str)


def cache_key_for_query(q):
    return f"spotsearch:{q.lower()}"


@huey.task()
def add_tracks_task(token_info, track_ids, create_new, new_playlist_name, existing_playlist_id):
    """
    Добавляет треки в существующий или новый плейлист партиями (до 100 за раз).
    """
    sp = spotipy.Spotify(auth=ensure_token(token_info)['access_token'])
    me = sp.current_user()
    user_id = me['id']

    # Создание или выбор существующего плейлиста

    playlist = sp.user_playlist_create(user_id, new_playlist_name or "SpotSync Imported", public=False)
    playlist_id = playlist['id']
    playlist_name = playlist['name']

    total = len(track_ids)
    added = 0

    # Разбиваем треки на группы по 100
    batch_size = 100
    for i in range(0, total, batch_size):
        batch = track_ids[i:i + batch_size]
        sp.playlist_add_items(playlist_id, batch)
        added += len(batch)

    return {'added': added, 'playlist_name': playlist_name}
