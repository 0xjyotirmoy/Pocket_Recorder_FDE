#!/usr/bin/env python3
"""Fieldnotes management CLI (Windows, macOS, Linux). Run with any Python 3.10+:

    python manage.py setup              create backend/.venv, install packages, move old data, make samples
    python manage.py set-key gsk_xxx    save the Groq key once (in ~/.fieldnotes/config.env, outside the project)
    python manage.py check              self-test: config, key, speech-to-text, LLM
    python manage.py start [--port N]   run API + dashboard on http://localhost:8000
    python manage.py test               run the test suite (offline, fake providers)
    python manage.py eval               ask the golden questions against the running server
    python manage.py config             show where config and data live
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
VENV = BACKEND / ".venv"
HOME = Path(os.environ.get("FIELDNOTES_HOME") or (Path.home() / ".fieldnotes"))
USER_CONFIG = HOME / "config.env"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def say(msg: str) -> None:
    print(f"  {msg}", flush=True)


def run(cmd: list, **kw) -> int:
    return subprocess.call([str(c) for c in cmd], **kw)


def vpy_works() -> bool:
    if not VPY.exists():
        return False
    try:
        return subprocess.call(
            [str(VPY), "-c", "import sys"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) == 0
    except OSError:
        return False


def need_venv() -> None:
    if not vpy_works():
        sys.exit("  Virtual environment is missing or incompatible. Run:  python manage.py setup")


def read_config() -> dict[str, str]:
    out = {}
    if USER_CONFIG.exists():
        for line in USER_CONFIG.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def write_config(updates: dict[str, str]) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    cfg = {**read_config(), **updates}
    body = "# Fieldnotes user config (outside the project, survives updates)\n" + "".join(f"{k}={v}\n" for k, v in cfg.items())
    USER_CONFIG.write_text(body, encoding="utf-8")
    try:
        os.chmod(USER_CONFIG, 0o600)
    except OSError:
        pass


def project_env_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("GROQ_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# ---- commands ----------------------------------------------------------------------------------
def cmd_setup(_):
    print("\n=== Fieldnotes setup ===")
    if sys.version_info < (3, 10):
        sys.exit("  Python 3.10+ is required.")
    if VENV.exists() and not vpy_works():
        say("Existing environment is broken or incompatible; recreating it")
        shutil.rmtree(VENV, ignore_errors=True)
    if not VPY.exists():
        say("Creating Python environment (backend/.venv)")
        if run([sys.executable, "-m", "venv", VENV]) != 0:
            sys.exit("  Could not create the virtual environment.")
    say("Installing packages")
    run([VPY, "-m", "pip", "install", "--upgrade", "pip", "-q"])
    if run([VPY, "-m", "pip", "install", "-r", BACKEND / "requirements.txt", "-q"]) != 0:
        sys.exit("  Package installation failed (see above).")

    # one-time moves: key from project .env, data from ./data -> ~/.fieldnotes
    key = project_env_key()
    if key and not read_config().get("GROQ_API_KEY"):
        write_config({"GROQ_API_KEY": key})
        say(f"Saved your Groq key to {USER_CONFIG} (no need to enter it again)")
    old, new = ROOT / "data", HOME / "data"
    if (old / "app.db").exists() and not (new / "app.db").exists():
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(old, new, dirs_exist_ok=True)
        say(f"Moved your existing recordings to {new}")

    samples = ROOT / "sample-recordings"
    if not (samples / "manifest.json").exists() and os.name == "nt":
        say("Creating two spoken sample meetings (Windows text-to-speech)")
        run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ROOT / "scripts" / "make_samples.ps1"])

    print()
    if not read_config().get("GROQ_API_KEY") and not key:
        say("Next: python manage.py set-key gsk_your_key   then   python manage.py check")
    else:
        say("Done. Next: python manage.py check   then   python manage.py start")


def cmd_set_key(a):
    key = a.key.strip().strip('"').strip("'")
    if not key.startswith("gsk_") or " " in key:
        sys.exit("  That doesn't look like a Groq key (it should start with gsk_ and have no spaces).")
    write_config({"GROQ_API_KEY": key})
    say(f"Saved to {USER_CONFIG}. Every copy of the project on this computer will use it.")
    env = ROOT / ".env"
    if env.exists() and project_env_key() and project_env_key() != key:
        say("Note: the project .env also has a GROQ_API_KEY and takes priority. Remove that line to use this one.")


def cmd_config(_):
    cfg = read_config()
    k = cfg.get("GROQ_API_KEY") or project_env_key()
    say(f"user config : {USER_CONFIG} ({'exists' if USER_CONFIG.exists() else 'missing'})")
    say(f"project .env: {ROOT / '.env'} ({'exists' if (ROOT / '.env').exists() else 'not used'})")
    say(f"Groq key    : {'gsk_...' + k[-4:] if k else 'NOT SET'}")
    say(f"data        : {os.environ.get('DATA_DIR') or cfg.get('DATA_DIR') or HOME / 'data'}")


def cmd_check(_):
    need_venv()
    sys.exit(run([VPY, "-m", "app.doctor"], cwd=BACKEND))


def cmd_start(a):
    need_venv()
    url = f"http://localhost:{a.port}"
    print(f"\n  Dashboard : {url}\n  Recorder  : http://<this-computer-ip>:{a.port}/upload\n  Stop      : Ctrl+C\n")
    if not a.no_browser:
        threading.Thread(target=lambda: (time.sleep(3), webbrowser.open(url + "/app/")), daemon=True).start()
    try:
        sys.exit(run([VPY, "-m", "uvicorn", "app.main:app", "--host", a.host, "--port", str(a.port)], cwd=BACKEND))
    except KeyboardInterrupt:
        pass


def cmd_test(_):
    need_venv()
    sys.exit(run([VPY, "-m", "pytest", "-q"], cwd=BACKEND))


def cmd_eval(a):
    need_venv()
    sys.exit(run([VPY, ROOT / "scripts" / "eval_qa.py", "--server", a.server]))


def main():
    p = argparse.ArgumentParser(prog="manage.py", description="Fieldnotes management")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup").set_defaults(fn=cmd_setup)
    k = sub.add_parser("set-key")
    k.add_argument("key")
    k.set_defaults(fn=cmd_set_key)
    sub.add_parser("config").set_defaults(fn=cmd_config)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    s = sub.add_parser("start")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_start)
    sub.add_parser("test").set_defaults(fn=cmd_test)
    e = sub.add_parser("eval")
    e.add_argument("--server", default="http://localhost:8000")
    e.set_defaults(fn=cmd_eval)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
