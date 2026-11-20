"""Build the release and run browser acceptance against disposable servers/data."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.request import urlopen

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"
WEB = ROOT / "apps" / "web"
NODE = shutil.which("node") or "node"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_url(url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Local service exited before responding at {url}")
        try:
            with urlopen(url, timeout=2):
                return
        except (OSError, URLError):
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}")


@contextmanager
def server(command: list[str], cwd: Path, env: dict, url: str, log_path: Path):
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log)
        try:
            wait_for_url(url, process)
            yield
        finally:
            if process.poll() is None and os.name == "nt":
                subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            elif process.poll() is None:
                process.terminate()
            try:
                process.wait(8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def prepare_project(temp: Path, env: dict, log_path: Path, *, build: bool) -> Path:
    web_copy = temp / "web"
    web_copy.mkdir()
    shutil.copytree(WEB / "src", web_copy / "src")
    if (WEB / "public").exists():
        shutil.copytree(WEB / "public", web_copy / "public")
    for pattern in ("*.json", "*.ts", "*.mjs"):
        for source in WEB.glob(pattern):
            if source.is_file():
                shutil.copy2(source, web_copy / source.name)
    def link_or_copy(source: str, destination: str):
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)

    shutil.copytree(
        WEB / "node_modules", web_copy / "node_modules",
        copy_function=link_or_copy, ignore=shutil.ignore_patterns(".cache"),
    )
    if not build:
        return web_copy
    print("Building Next.js production bundle", flush=True)
    with log_path.open("wb") as log:
        result = subprocess.run(
            [NODE, "node_modules/next/dist/bin/next", "build"],
            cwd=web_copy,
            env=env,
            stdout=log,
            stderr=log,
        )
    if result.returncode:
        raise RuntimeError(f"Production build failed. See {log_path}")
    return web_copy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playwright-module", type=Path, help="Absolute path to the Playwright package")
    parser.add_argument("--chromium-executable", type=Path, help="Use an already installed Chromium executable")
    parser.add_argument("--evidence", type=Path, default=ROOT / "qa" / "evidence")
    parser.add_argument("--dev", action="store_true", help="Skip the build for a local acceptance iteration")
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    api_port, web_port = free_port(), free_port()
    while web_port == api_port:
        web_port = free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    web_url = f"http://127.0.0.1:{web_port}"
    with TemporaryDirectory(prefix=".gizioptima-e2e-", dir=WEB.parent) as directory:
        temp = Path(directory)
        env = dict(os.environ)
        for key in list(env):
            if key.startswith("GIZIOPTIMA_") or key in {
                "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "NEXT_PUBLIC_API_BASE_URL",
            }:
                del env[key]
        env.update(
            GIZIOPTIMA_DATABASE_URL=f"sqlite:///{(temp / 'qa.db').as_posix()}",
            GIZIOPTIMA_QC_STORAGE_DIR=str(temp / "qc-images"),
            GIZIOPTIMA_SEED_DEMO_ACCOUNTS="true",
            GIZIOPTIMA_DEMO_PASSWORD=secrets.token_urlsafe(20),
            GIZIOPTIMA_ENV="development",
            GIZIOPTIMA_COOKIE_SECURE="false",
            BACKEND_INTERNAL_URL=api_url,
            NEXT_TELEMETRY_DISABLED="1",
            PYTHONUNBUFFERED="1",
            QA_WEB_URL=web_url,
            QA_ARTIFACTS=str(evidence),
            QA_FIXTURES=str(temp),
        )
        if args.playwright_module:
            env["QA_PLAYWRIGHT_MODULE"] = str(args.playwright_module.resolve())
        if args.chromium_executable:
            env["QA_CHROMIUM_EXECUTABLE"] = str(args.chromium_executable.resolve())

        from tests.test_sprint2a_persistence_and_api import _make_valid_csv_bundle

        for filename, data, _ in _make_valid_csv_bundle().values():
            (temp / filename).write_bytes(data)
        Image.new("RGB", (640, 480), (231, 217, 185)).save(temp / "upload-test.jpg", "JPEG")
        web_project = prepare_project(temp, env, evidence / "production-build.log", build=not args.dev)
        web_cmd = [
            NODE, "node_modules/next/dist/bin/next", "dev" if args.dev else "start",
            "--hostname", "127.0.0.1", "--port", str(web_port),
        ]
        api_cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)]
        health_url = api_url + "/api/v1/health"

        def run_browser(mode: str) -> None:
            command = [NODE, str(ROOT / "qa" / "sprint3a5.cjs"), mode]
            with (evidence / f"browser-{mode}.log").open("w", encoding="utf-8") as log:
                with subprocess.Popen(
                    command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    encoding="utf-8", errors="replace",
                ) as browser_run:
                    assert browser_run.stdout is not None
                    for line in browser_run.stdout:
                        log.write(line)
                        log.flush()
                        print(line, end="", flush=True)
                    if browser_run.wait():
                        raise subprocess.CalledProcessError(browser_run.returncode, command)

        with server(web_cmd, web_project, env, web_url + "/login", evidence / "next.log"):
            with server(api_cmd, API, env, health_url, evidence / "api-unconfigured.log"):
                run_browser("unconfigured")
            test_env = dict(env, GIZIOPTIMA_VISION_PROVIDER="deterministic_test")
            with server(api_cmd, API, test_env, health_url, evidence / "api-test.log"):
                run_browser("workflow")
            with server(api_cmd, API, env, health_url, evidence / "api-after-restart.log"):
                run_browser("persistence")


if __name__ == "__main__":
    sys.path.insert(0, str(API))
    main()
