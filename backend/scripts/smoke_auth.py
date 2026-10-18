r"""Смоук-тест auth v2: register → refresh (ідемпотентний) → me → logout.

Запуск: python scripts\smoke_auth.py
"""
import random

from fastapi.testclient import TestClient

from app.main import app

with TestClient(app) as c:
    u = 'smoke' + str(random.randint(10000, 99999))
    r = c.post('/api/auth/register', json={'username': u,
                                           'password': 'password123',
                                           'email': u + '@example.com'})
    print('register', r.status_code, r.json().get('ok'))
    d = r.json()['data']
    tok = d['refresh_token']
    print('same_token', d['access_token'] == d['refresh_token'])

    r2 = c.post('/api/auth/refresh', json={'refresh_token': tok})
    print('refresh', r2.status_code, r2.json().get('ok'))
    # повторний refresh тим самим токеном (гонка вкладок) — має бути 200
    r3 = c.post('/api/auth/refresh', json={'refresh_token': tok})
    print('parallel_refresh', r3.status_code)

    h = {'Authorization': 'Bearer ' + tok}
    r4 = c.get('/api/auth/me', headers=h)
    print('me', r4.status_code, r4.json().get('ok'))
    r5 = c.get('/api/auth/sessions?current=' + tok, headers=h)
    print('sessions', r5.status_code, len(r5.json()['data']))

    r6 = c.post('/api/auth/logout', json={'refresh_token': tok})
    print('logout', r6.status_code)
    r7 = c.get('/api/auth/me', headers=h)
    print('me_after_logout', r7.status_code)
    r8 = c.post('/api/auth/refresh', json={'refresh_token': tok})
    print('refresh_after_logout', r8.status_code)