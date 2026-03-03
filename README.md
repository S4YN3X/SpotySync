# SpotySync

**SpotySync** — веб-сервис для мгновенного переноса плейлистов из Яндекс.Музыки в Spotify.  
Просто введите логин Яндекса → выберите плейлист → получите готовый плейлист в Spotify.

**Сайт:** [spotysync.ru](https://spotysync.ru)

---

## Возможности

- Поиск **публичных** плейлистов Яндекс.Музыки по логину
- Перенос плейлиста **«Мне нравится»** (все лайкнутые треки)
- Прогресс-бар в реальном времени (SSE)
- Очередь задач — пользователи обрабатываются по одному
- Глобальный счётчик перенесённых треков
- История переносов в браузере (localStorage)
- Восстановление результата после перезагрузки страницы

---

## Стек технологий

| Компонент | Технология |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Spotify API | Spotipy |
| Yandex Music | Internal API + yandex-music (token) |
| Frontend | HTML / CSS / Vanilla JS |
| Стриминг | SSE (Server-Sent Events) |
| Деплой | Docker, docker-compose |

---

## Быстрый старт

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/S4YN3X/spotysync.git
cd spotysync
```

### 2. Создайте файл `.env`

```env
SPOTIFY_CLIENT_ID=client_id
SPOTIFY_CLIENT_SECRET=client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8000/callback
YANDEX_TOKEN=токен_яндекса
```

> `YANDEX_TOKEN` нужен для загрузки плейлиста «Мне нравится» и получения полных данных о треках.

### 3. Подготовьте папку данных

```bash
mkdir -p data
echo '{"total_tracks_synced": 0, "total_playlists": 0}' > data/stats.json
```

### 4. Запустите через Docker

```bash
docker-compose up --build -d
```

Откройте в браузере: **http://localhost:8000**

---

## Как пользоваться

1. **Откройте сайт** — [spotysync.ru](https://spotysync.ru) (или `localhost:8000` локально)
2. **Введите логин** от Яндекс.Музыки (например, `ivan.ivanov`)
3. **Выберите плейлист** — появится список всех открытых плейлистов + «Мне нравится»
4. **Дождитесь переноса** — прогресс отображается в реальном времени
5. **Откройте в Spotify** — нажмите кнопку и сохраните плейлист в свою библиотеку

> ⚠️ Приватные плейлисты не будут найдены. Сделайте их **открытыми** в настройках Яндекс.Музыки.

---

## Структура проекта

```
app/
├── main.py              # FastAPI backend
├── Dockerfile
├── docker-compose.yml
├── .env                 # Переменные окружения
├── data/
│   └── stats.json       # Глобальная статистика
└── static/
    ├── index.html        # Главная страница
    ├── app.js            # Frontend логика
    └── style.css       # Стили
```

---

## Конфигурация

### Очередь

Количество одновременных переносов настраивается в `main.py`:

```python
MAX_CONCURRENT_JOBS = 1
```

### Статистика

Файл статистики хранится в `data/stats.json` и монтируется через Docker volume:

```yaml
volumes:
  - ./data:/app/data
```


---


## Roadmap

- [ ] Rate limiting по IP (защита от DDoS)
- [ ] Кэширование результатов поиска Spotify
- [ ] SQLite для серверной истории переносов
- [ ] Админ-панель со статистикой

---

## Лицензия

MIT License — см. [LICENSE](LICENSE)

---

<p align="center">
  Сделано с ❤️ by <a href="https://github.com/S4YN3X">S4YN3X</a>
</p>
