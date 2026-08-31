# Docker manage.py

This app runs in Docker. Database host is `DB_HOST=db`.

Run Django commands inside the web container, for example:

`docker compose exec web python manage.py migrate`

Do not run `python manage.py` on the host. Host Python cannot reach `db` and will fail or hit the wrong database.
