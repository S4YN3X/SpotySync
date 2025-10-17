import os
import time
import json
from datetime import datetime
from flask import Flask, redirect, request, session, url_for, render_template, jsonify, flash
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import redis
from rq import Queue
from tasks import huey, search_candidates_task, add_tracks_task

from tasks import huey

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET") or os.urandom(24)

# Spotify config
CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI")
SCOPE = "user-read-private playlist-modify-public playlist-modify-private"

if not (CLIENT_ID and CLIENT_SECRET and REDIRECT_URI):
    raise RuntimeError("Set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI in .env")


def sp_oauth():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=None,
        show_dialog=True
    )


# Redis & RQ
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
redis_conn = redis.from_url(REDIS_URL)


# queue = Queue("spot_sync", connection=redis_conn)


# Token helpers (store token_info in session)
def save_token_info(token_info: dict):
    session['token_info'] = token_info


def get_token_info():
    return session.get('token_info')


def clear_token_info():
    session.pop('token_info', None)
    session.clear()


def get_spotify_client_from_token(token_info):
    # returns spotipy.Spotify (no refresh here; tasks will refresh if needed)
    return spotipy.Spotify(auth=token_info['access_token'])


# ---- Routes ----
@app.route('/')
def index():
    token_info = get_token_info()
    if token_info:
        sp = get_spotify_client()
        if sp:
            me = sp.current_user()
            if me.get('display_name'):
                return render_template('index.html', username=me.get('display_name') or me.get('id'), target="/add")
    return render_template('index.html', target="/login")


@app.route('/login')
def login():
    return redirect(sp_oauth().get_authorize_url())


@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return "Authorization failed", 400
    auth = sp_oauth()
    token_info = auth.get_access_token(code, check_cache=False)
    # some spotipy versions: token_info = auth.get_cached_token()
    if not token_info or 'access_token' not in token_info:
        token_info = auth.get_cached_token()
    if not token_info:
        return "Failed to obtain token.", 400
    save_token_info(token_info)
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    clear_token_info()
    flash("Вы успешно вышли.", "info")
    return redirect(url_for('index'))


@app.route('/add', methods=['GET'])
def add_page():
    # page with AJAX UI
    token_info = get_token_info()
    if not token_info:
        return redirect(url_for('login'))
    sp = get_spotify_client()
    me = sp.current_user()
    # fetch playlists (first 50)
    return render_template('add_tracks_ajax.html', username=me.get('display_name') or me.get('id'))


# ---- API: start search job ----
@app.route('/api/search', methods=['POST'])
def api_search():
    token_info = session.get('token_info')
    if not token_info:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.get_json()
    queries = [line.strip() for line in data.get('tracks_text', '').splitlines() if line.strip()]
    job = search_candidates_task(token_info, queries)
    return jsonify({'job_id': str(job.id)}), 202


# ---- API: check job status / get results ----
@app.route('/api/job/<job_id>')
def api_job(job_id):
    try:
        result = huey.result(job_id, preserve=True)
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

    if result is None:
        # Задача ещё в очереди или выполняется
        task = huey.storage.peek_data(job_id)
        return jsonify({'status': 'queued' if task else 'running', 'progress': 0})

    # Если результат есть — это успех
    if isinstance(result, dict):
        return jsonify({'status': 'finished', 'result': result})
    else:
        # На случай если результат строка/JSON
        try:
            return jsonify({'status': 'finished', 'result': json.loads(result)})
        except Exception:
            return jsonify({'status': 'finished', 'result': result})


# ---- API: enqueue add-to-playlist job ----
@app.route('/api/add', methods=['POST'])
def api_add():
    token_info = session.get('token_info')
    if not token_info:
        return jsonify({'error': 'Not logged in'}), 401
    data = request.get_json()
    job = add_tracks_task(
        token_info,
        data['track_ids'],
        data['create_new'],
        data.get('new_playlist_name'),
        data.get('existing_playlist')
    )
    return jsonify({'job_id': str(job.id)}), 202


# Utility to provide Spotify client with refresh if needed (for server routes)
def get_spotify_client():
    token_info = get_token_info()
    if not token_info:
        return None
    # refresh if expiring
    if token_info.get('expires_at', 0) - int(time.time()) < 60:
        auth = sp_oauth()
        refreshed = auth.refresh_access_token(token_info.get('refresh_token'))
        token_info.update(refreshed)
        save_token_info(token_info)
    return spotipy.Spotify(auth=token_info['access_token'])


if __name__ == '__main__':
    app.run(debug=True)
