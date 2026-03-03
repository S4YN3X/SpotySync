#!/usr/bin/env python3
"""
SpotySync — Перенос плейлистов Яндекс.Музыки в Spotify
FastAPI веб-приложение с real-time прогрессом через SSE
"""

import os
import re
import sys
import time
import uuid
import json
import logging
import asyncio
import requests
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from yandex_music import Client as YMClient
except ImportError:
    sys.exit("pip install yandex-music")

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    sys.exit("pip install spotipy")

# ─── Статистика и Очередь ───────────────────────────────────────────────────
STATS_FILE = "data/stats.json"

# Важно: больше нет глобальной переменной global_stats = load_stats() !

def update_stats(found_tracks: int, playlists: int = 1):
    """Считывает свежий файл, прибавляет числа и сохраняет"""
    # 1. Читаем самые свежие данные прямо перед обновлением
    current_stats = {"total_tracks_synced": 0, "total_playlists": 0}
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                current_stats = json.load(f)
        except Exception:
            pass

    # 2. Прибавляем
    current_stats["total_tracks_synced"] += found_tracks
    current_stats["total_playlists"] += playlists

    # 3. Сохраняем обратно в файл
    try:
        # Создаем папку, если ее вдруг нет
        os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
        with open(STATS_FILE, "w") as f:
            json.dump(current_stats, f)
    except Exception as e:
        logger.error(f"Не удалось сохранить статистику: {e}")

def get_current_stats():
    """Просто отдает текущие цифры для фронтенда"""
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_tracks_synced": 0, "total_playlists": 0}

# Семафор оставляем как было
MAX_CONCURRENT_JOBS = 1
job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
active_jobs_count = 0


# Ограничиваем количество одновременных задач (например, 3)
MAX_CONCURRENT_JOBS = 1
job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
active_jobs_count = 0

# ─── Конфигурация ───────────────────────────────────────────────────────────

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")
SPOTIFY_SCOPE = "playlist-modify-public playlist-modify-private"
YANDEX_TOKEN = os.getenv("YANDEX_TOKEN", None)

SPOTIPY_CACHE_PATH = os.getenv("SPOTIPY_CACHE_PATH", ".cache")

SEARCH_DELAY = 0.12
BATCH_SIZE = 100
MAX_RETRIES = 3
MAX_WORKERS = 4

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SpotySync")

# ─── Хранилище задач (in-memory) ────────────────────────────────────────────

@dataclass
class Job:
    id: str
    status: str = "pending"
    progress: int = 0
    total: int = 0
    found: int = 0
    not_found_tracks: List[str] = field(default_factory=list)
    playlist_title: str = ""
    spotify_url: str = ""
    error: str = ""
    elapsed: float = 0.0
    queue_position: int = 0  # <--- Добавили
    owner: str = ""


jobs: Dict[str, Job] = {}
job_events: Dict[str, asyncio.Queue] = {}

app = FastAPI(title="SpotySync", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def emit_event(job_id: str, data: dict):
    if job_id in job_events:
        try:
            job_events[job_id].put_nowait(data)
        except asyncio.QueueFull:
            pass

@app.get("/api/stats")
async def get_stats():
    return get_current_stats()


# ─── Роут: Получение плейлистов ──────────────────────────────────────────────

@app.get("/api/playlists")
async def get_playlists(username: str):
    username = username.strip().split('@')[0]
    if not username:
        return JSONResponse({"error": "Введите логин"}, status_code=400)
        
    try:
        url = f"https://music.yandex.ru/handlers/playlists.jsx?owner={username}"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers)
        
        if r.status_code == 404:
            return JSONResponse({"error": f"Пользователь '{username}' не найден"}, status_code=404)
        
        r.raise_for_status()
        data = r.json()
        
        yandex_playlists = data.get('playlists', [])
        result_playlists = []
        
        # Если настроен токен, получаем реальное количество лайков
        if YANDEX_TOKEN:
            likes_count = "Все"
            try:
                # Подключаемся по токену, чтобы узнать количество
                ym = YMClient(token=YANDEX_TOKEN).init()
                # Берем только метаданные треков (без загрузки всего списка)
                likes_tracks = ym.users_likes_tracks()
                if likes_tracks:
                    likes_count = len(likes_tracks)
            except Exception as e:
                logger.warning(f"Не удалось получить количество лайков: {e}")

            result_playlists.append({
                "id": "likes",
                "title": "❤️ Мне нравится",
                "trackCount": likes_count,
                "kind": "likes",
                "owner": username
            })
             
        for p in yandex_playlists:
            if p.get('visibility') != 'public':
                continue
            result_playlists.append({
                "id": f"{username}_{p['kind']}",
                "title": p.get('title', 'Без названия'),
                "trackCount": p.get('trackCount', 0),
                "kind": p['kind'],
                "owner": username
            })
            
        if not result_playlists:
             return JSONResponse({"error": "У пользователя нет публичных плейлистов"}, status_code=404)
             
        return {"playlists": result_playlists}
        
    except requests.exceptions.RequestException as e:
        # Если Яндекс недоступен (502, 503)
        logger.warning(f"Ошибка сети при обращении к Яндексу для {username}: {e}")
        return JSONResponse({"error": "Ошибка связи с Яндекс Музыкой"}, status_code=502)
    except Exception as e:
        logger.exception("Внутренняя ошибка получения плейлистов")
        return JSONResponse({"error": "Не удалось загрузить плейлисты профиля"}, status_code=500)




# ─── Ядро импорта ────────────────────────────────────────────────────────────

async def run_import(job_id: str, owner: str, kind: str):
    global active_jobs_count, global_stats
    job = jobs[job_id]
    job.owner = owner
    
    # Увеличиваем счетчик всех пришедших задач
    active_jobs_count += 1
    
    # Если задач больше, чем может обработать семафор (в нашем случае 1), значит мы в очереди
    if active_jobs_count > MAX_CONCURRENT_JOBS:
        job.status = "queued"
        queue_pos = active_jobs_count - MAX_CONCURRENT_JOBS
        # Отправляем сообщение на фронт
        emit_event(job_id, {"status": "queued", "message": f"Ожидание в очереди... Перед вами: {queue_pos}"})
    
    try:
        # Семафор "заморозит" код здесь, если уже идет перенос у другого человека
        async with job_semaphore:
            job.status = "fetching"
            start = time.time()
            emit_event(job_id, {"status": "fetching", "message": "Подождите немного. Загрузка треков..."})
            
            tracks = []
            
            # 1. Загрузка треков напрямую через API Яндекса
            if kind == "likes":
                job.playlist_title = "Мне нравится (SpotySync)"
                url = f"https://music.yandex.ru/handlers/playlist.jsx?owner={owner}&kinds=3"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                
                # Запускаем requests в отдельном потоке, чтобы не блокировать asyncio цикл
                r = await asyncio.to_thread(requests.get, url, headers=headers)
                r.raise_for_status()
                
                data = r.json()
                raw_tracks = data.get('playlist', {}).get('tracks', [])
                
                job.total = len(raw_tracks)
                emit_event(job_id, {"status": "fetching_done", "playlist_title": job.playlist_title, "total": job.total, "message": f"Анализ {job.total} треков..."})
                
                for t in raw_tracks:
                    title = t.get("title", "Неизвестный трек")
                    artists = [a.get("name", "") for a in t.get("artists", []) if a.get("name")]
                    tracks.append({"title": title, "artists": artists})
                    
            else:
                url = f"https://music.yandex.ru/handlers/playlist.jsx?owner={owner}&kinds={kind}"
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                
                r = await asyncio.to_thread(requests.get, url, headers=headers)
                r.raise_for_status()
                
                data = r.json()
                pl_info = data.get('playlist', {})
                job.playlist_title = pl_info.get('title', 'SpotySync Playlist')
                raw_tracks = pl_info.get('tracks', [])
                
                job.total = len(raw_tracks)
                emit_event(job_id, {"status": "fetching_done", "playlist_title": job.playlist_title, "total": job.total, "message": f"Анализ {job.total} треков..."})
                
                for t in raw_tracks:
                    title = t.get("title", "Неизвестный трек")
                    artists = [a.get("name", "") for a in t.get("artists", []) if a.get("name")]
                    tracks.append({"title": title, "artists": artists})

            job.total = len(tracks)
            emit_event(job_id, {
                "status": "fetching_done",
                "playlist_title": job.playlist_title,
                "total": job.total,
                "message": f"Плейлист «{job.playlist_title}» — {job.total} треков"
            })

            if not tracks:
                raise ValueError("Плейлист пуст или скрыт настройками приватности!")

            # 2. Подключаемся к Spotify
            job.status = "searching"
            emit_event(job_id, {"status": "searching", "message": "Поиск треков в Spotify..."})

            auth_manager = SpotifyOAuth(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET,
                redirect_uri=SPOTIFY_REDIRECT_URI,
                scope=SPOTIFY_SCOPE,
                open_browser=False,
                cache_path=SPOTIPY_CACHE_PATH,
            )
            sp = spotipy.Spotify(auth_manager=auth_manager, retries=MAX_RETRIES)
            sp_user_id = sp.current_user()["id"]

            # 3. Ищем треки
            found_uris = []
            not_found = []

            def search_track(t):
                artist = t["artists"][0] if t["artists"] else ""
                title = t["title"]
                for attempt in range(MAX_RETRIES):
                    try:
                        res = sp.search(q=f"track:{title} artist:{artist}", type="track", limit=1)
                        items = res.get("tracks", {}).get("items", [])
                        if items: return items[0]["uri"]
                        
                        res = sp.search(q=f"{artist} {title}", type="track", limit=1)
                        items = res.get("tracks", {}).get("items", [])
                        if items: return items[0]["uri"]
                        return None
                    except spotipy.exceptions.SpotifyException as e:
                        if e.http_status == 429: time.sleep(int(e.headers.get("Retry-After", 5)))
                        else: time.sleep(2 ** attempt)
                    except Exception:
                        time.sleep(2 ** attempt)
                return None

            def process_one(idx_track):
                idx, t = idx_track
                time.sleep(SEARCH_DELAY * (idx % MAX_WORKERS))
                uri = search_track(t)
                return (t, uri)

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = []
                for i, t in enumerate(tracks):
                    if i > 0 and i % MAX_WORKERS == 0: time.sleep(SEARCH_DELAY)
                    futures.append(executor.submit(process_one, (i, t)))

                for future in futures:
                    t, uri = future.result()
                    job.progress += 1
                    if uri:
                        found_uris.append(uri)
                        job.found += 1
                    else:
                        label = f"{', '.join(t['artists'])} — {t['title']}"
                        not_found.append(label)
                        job.not_found_tracks.append(label)

                    if job.progress % 2 == 0 or job.progress == job.total:
                        emit_event(job_id, {
                            "status": "searching",
                            "progress": job.progress,
                            "total": job.total,
                            "found": job.found,
                            "message": f"Поиск: {job.progress}/{job.total} (найдено {job.found})"
                        })

            # 4. Создаём плейлист в Spotify
            if not found_uris:
                raise ValueError("Ни один трек не найден в Spotify!")

            job.status = "creating"
            emit_event(job_id, {"status": "creating", "message": "Создание плейлиста в Spotify..."})

            desc = f"Импорт из Яндекс.Музыки: {job.playlist_title} ({job.found}/{job.total} треков) • SpotySync"
            playlist_resp = sp.user_playlist_create(
                user=sp_user_id, 
                name=job.playlist_title, 
                public=True,
                collaborative=False, 
                description=desc
            )
            playlist_id = playlist_resp["id"]

            for i in range(0, len(found_uris), BATCH_SIZE):
                batch = found_uris[i:i + BATCH_SIZE]
                sp.playlist_add_items(playlist_id, batch)

            # 5. Готово!
            job.spotify_url = f"https://open.spotify.com/playlist/{playlist_id}"
            job.elapsed = time.time() - start
            job.status = "done"
            
            # Обновляем статистику
            update_stats(found_tracks=job.found, playlists=1)
            
            emit_event(job_id, {
                "status": "done",
                "spotify_url": job.spotify_url,
                "found": job.found,
                "total": job.total,
                "owner": job.owner,
                "not_found": job.not_found_tracks[:50],
                "elapsed": round(job.elapsed, 1),
                "playlist_title": job.playlist_title,
                "message": "Готово!"
            })

    except Exception as e:
        job.status = "error"
        job.error = str(e)
        emit_event(job_id, {"status": "error", "error": str(e)})
        logger.exception(f"Job {job_id} failed")
    finally:
        # Задача завершилась (с ошибкой или успешно), освобождаем счетчик
        active_jobs_count -= 1




# ─── Роуты ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/import")
async def start_import(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    owner = body.get("owner", "").strip()
    kind = body.get("kind", "").strip()

    if not owner or not kind:
        return JSONResponse({"error": "Отсутствуют данные плейлиста"}, status_code=400)

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return JSONResponse({"error": "Spotify API не настроен"}, status_code=500)

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = Job(id=job_id)
    job_events[job_id] = asyncio.Queue(maxsize=200)

    background_tasks.add_task(run_import, job_id, owner, kind)
    return {"job_id": job_id}

@app.get("/api/stream/{job_id}")
async def stream_events(job_id: str):
    if job_id not in jobs:
         return JSONResponse({"error": "Job not found"}, status_code=404)
    # [Тот же самый код генератора SSE из вашего оригинала...]
    async def event_generator():
        queue = job_events.get(job_id)
        if not queue: return
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=120)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if data.get("status") in ("done", "error"): break
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'status': 'ping'})}\n\n"
            except Exception: break
        if job_id in job_events: del job_events[job_id]

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        return JSONResponse({"error": "Задача не найдена"}, status_code=404)
        
    job = jobs[job_id]
    return {
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
        "found": job.found,
        "playlist_title": job.playlist_title,
        "owner": job.owner,
        "error": job.error,
        "spotify_url": job.spotify_url,
        "elapsed": round(job.elapsed, 1),
        "not_found": job.not_found_tracks[:50]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
