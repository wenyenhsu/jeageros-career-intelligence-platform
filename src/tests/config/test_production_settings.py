import os
import subprocess
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[2]


def _production_check(**overrides):
    environment = os.environ.copy()
    environment.update(
        {
            "SECRET_KEY": (
                "production-check-key-7gK9vQ2xM4pR8sT1wY6zN3cF5hJ0dL2bV9kS4mP7"
            ),
            "ALLOWED_HOSTS": "jobs.example.com",
            "CSRF_TRUSTED_ORIGINS": "https://jobs.example.com",
            "DB_PASSWORD": "production-check-database-password",
            "USE_SQLITE": "0",
            "CELERY_BROKER_URL": ("redis://:production-check-password@redis:6379/0"),
            "CELERY_RESULT_BACKEND": (
                "redis://:production-check-password@redis:6379/0"
            ),
        }
    )
    environment.update(overrides)
    return subprocess.run(
        [
            sys.executable,
            "manage.py",
            "check",
            "--deploy",
            "--settings=config.settings.prod",
        ],
        cwd=SRC_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_production_deploy_check_has_no_security_warnings():
    result = _production_check()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "System check identified no issues" in result.stdout + result.stderr


def test_production_settings_reject_weak_secret_key():
    result = _production_check(SECRET_KEY="short")

    assert result.returncode != 0
    assert "SECRET_KEY must be at least 50 characters" in result.stderr
