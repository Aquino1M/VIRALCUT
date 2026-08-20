from pathlib import Path

from app.config import parse_worker_origins


def test_worker_cors_allowlist_rejects_wildcards_and_normalizes_origins():
    assert parse_worker_origins('https://viral.example, http://localhost:3000/, *, file:///tmp') == [
        'https://viral.example', 'http://localhost:3000'
    ]


def test_worker_cors_is_explicitly_configurable_without_wildcard_credentials():
    main = Path('app/main.py').read_text(encoding='utf-8')
    env = Path('.env.example').read_text(encoding='utf-8')
    assert 'CORSMiddleware' in main
    assert 'WORKER_ALLOWED_ORIGINS' in main
    assert 'allow_origins=WORKER_ALLOWED_ORIGINS' in main
    assert 'WORKER_ALLOWED_ORIGINS=' in env
    assert 'allow_origins=["*"]' not in main
