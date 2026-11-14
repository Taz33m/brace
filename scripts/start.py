"""Start everything Brace needs with one command, and stop it all with Ctrl-C.

    uv run python -m scripts.start

Three things run: the API, the web app on localhost (the Matterport key only works there), and a second
copy of the web app over HTTPS on the local network (phones only allow motion sensors, the camera and
the microphone on a secure page). Ports can be moved with BRACE_API_PORT, BRACE_WEB_PORT and BRACE_VR_PORT.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def port(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def in_use(number: int) -> bool:
    # The web app listens on "localhost", which on a Mac can mean the IPv6 address only, so try both.
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, number), timeout=0.3):
                return True
        except OSError:
            continue
    return False


def lan_address() -> str | None:
    """This computer's address on the local network, which is what a phone has to be pointed at."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this only picks the outbound interface
            return s.getsockname()[0]
    except OSError:
        return None


def wait_for(number: int, seconds: float, running: list[subprocess.Popen]) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if in_use(number):
            return True
        if any(p.poll() is not None for p in running):
            return False
        time.sleep(0.25)
    return False


def main() -> int:
    api, web, vr = port("BRACE_API_PORT", 8001), port("BRACE_WEB_PORT", 5174), port("BRACE_VR_PORT", 5175)
    taken = [n for n in (api, web, vr) if in_use(n)]
    if taken:
        print(f"Already in use: port {', '.join(map(str, taken))}. Stop what is running there, or choose other ports "
              "with BRACE_API_PORT, BRACE_WEB_PORT and BRACE_VR_PORT.")
        return 1
    if not (FRONTEND / "node_modules").exists():
        print("The web app's packages are not installed. Run: (cd frontend && npm install)")
        return 1
    photon = ROOT / "messaging" / "photon"
    config = {**dotenv_values(ROOT / ".env"), **os.environ}
    photon_enabled = config.get("BRACE_RECOVERY_ENABLED") == "1" and all(
        config.get(k) for k in ("PHOTON_PROJECT_ID", "PHOTON_PROJECT_SECRET", "BRACE_PHOTON_BRIDGE_SECRET"))
    if photon_enabled and not (photon / "node_modules" / "spectrum-ts").exists():
        print("Run npm --prefix messaging/photon ci to start iMessage with Brace.")
        photon_enabled = False

    env = {**os.environ, "BRACE_API_PORT": str(api), "BRACE_WEB_PORT": str(web), "BRACE_VR_PORT": str(vr)}
    quiet = {"stdout": subprocess.DEVNULL}   # errors still reach the terminal
    running = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.server:app", "--port", str(api), "--log-level", "warning"], cwd=ROOT, env=env),
        subprocess.Popen(["npx", "vite"], cwd=FRONTEND, env=env, **quiet),
        subprocess.Popen(["npx", "vite", "--config", "vite.vr.config.ts"], cwd=FRONTEND, env=env, **quiet),
    ]

    def stop(*_: object) -> None:
        for p in running:
            if p.poll() is None:
                p.terminate()
        for p in running:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    signal.signal(signal.SIGTERM, lambda *_: (stop(), sys.exit(0)))
    try:
        if not all(wait_for(n, 40, running) for n in (api, web, vr)):
            print("Something did not start. The error is above.")
            stop()
            return 1
        if photon_enabled:
            running.append(subprocess.Popen(
                ["node", "worker.mjs"], cwd=photon,
                env={**env, "BRACE_PHOTON_BRIDGE_URL": f"http://127.0.0.1:{api}"}))
            print("  iMessage           configured")
        address = lan_address()
        dotenv = ROOT / ".env"
        keyed = bool(os.environ.get("OPENAI_API_KEY")) or (dotenv.exists() and any(
            line.startswith("OPENAI_API_KEY=") and line.strip() != "OPENAI_API_KEY=" for line in dotenv.read_text().splitlines()))
        voice = "on" if keyed else "off (no OPENAI_API_KEY in .env)"
        print("\nBrace is running.\n")
        print(f"  On this computer   http://localhost:{web}")
        print(f"  For phones         https://{address or '<this computer>'}:{vr}   (accept the certificate warning once)")
        print(f"  Two-way voice      {voice}")
        print("\n  Open a building and press “Open in headset” for the code a phone scans.")
        print("  If a phone cannot load the page, the Wi-Fi is keeping devices apart: put this computer on the phone's hotspot.")
        print("\n  Ctrl-C stops everything.\n")
        while all(p.poll() is None for p in running):
            time.sleep(0.5)
        print("One of the servers stopped; stopping the rest.")
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        stop()


if __name__ == "__main__":
    sys.exit(main())
