from pathlib import Path


def test_local_nginx_allows_larger_upload_bodies():
    repo_root = Path(__file__).resolve().parents[1]
    config = (repo_root / "deployment/local-nginx/default.conf").read_text(
        encoding="utf-8"
    )

    assert "client_max_body_size 32m;" in config


def test_local_nginx_exposes_agentplayground_routes():
    repo_root = Path(__file__).resolve().parents[1]
    config = (repo_root / "deployment/local-nginx/default.conf").read_text(
        encoding="utf-8"
    )

    assert "location = /agentplayground {" in config
    assert "return 301 $scheme://$http_host/agentplayground/;" in config
    assert "location /agentplayground/api/ {" in config
    assert "location /agentplayground/ {" in config


def test_local_nginx_preserves_shell_prefixes_for_backend_middleware():
    repo_root = Path(__file__).resolve().parents[1]
    config = (repo_root / "deployment/local-nginx/default.conf").read_text(
        encoding="utf-8"
    )

    assert "rewrite ^/assistant/" not in config
    assert "location /assistant/ {" in config
    assert "proxy_pass http://webui:18780;" in config
