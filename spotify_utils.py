import spotipy
from spotipy.oauth2 import SpotifyOAuth


def get_valid_sp_for_user(user_id):
    """Возвращает клиент Spotipy по токену пользователя"""
    # тут можно хранить токен в session или БД
    from flask import session
    token_info = session.get('token_info')
    if not token_info:
        raise Exception("Пользователь не авторизован")
    return spotipy.Spotify(auth=token_info['access_token'])
