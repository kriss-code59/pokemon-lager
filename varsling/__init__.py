"""Varsling: VAPID-nokler, varseltekst og utsending.

Ligger som egen pakke pa rotnivaa fordi to helt ulike prosesser trenger den:
API-et (api/push.py, for testvarsel og abonnement) og cron-senderen
(overvak/varsler.py). La den i api/ ville tvunget senderen til a importere
FastAPI og apne en tilkoblingspool den ikke trenger.
"""
