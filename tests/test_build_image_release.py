import shutil
import subprocess
import os
from pathlib import Path


def test_build_image_release_uses_release_templates(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    output_rel = ".tmp-release-script-test"
    output_dir = repo_root / output_rel
    if output_dir.exists():
        shutil.rmtree(output_dir)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "cmd=\"$1\"\n"
        "shift || true\n"
        "case \"$cmd\" in\n"
        "  build)\n"
        "    exit 0\n"
        "    ;;\n"
        "  save)\n"
        "    printf 'fake-image-archive\\n'\n"
        "    ;;\n"
        "  *)\n"
        "    echo \"unsupported docker cmd: $cmd\" >&2\n"
        "    exit 1\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    try:
        subprocess.run(
            [
                "bash",
                "scripts/build-image-release.sh",
                "--skip-build",
                "--release-dir",
                output_rel,
            ],
            cwd=repo_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        assert (output_dir / "docker-compose.yml").read_text(encoding="utf-8") == (
            repo_root / "deployment/release/docker-compose.yml"
        ).read_text(encoding="utf-8")
        assert (output_dir / ".env.example").read_text(encoding="utf-8") == (
            repo_root / "deployment/release/.env.example"
        ).read_text(encoding="utf-8")
    finally:
        if output_dir.exists():
            shutil.rmtree(output_dir)
