"""Local test launcher: runs Shiftbase on 127.0.0.1 with its own SQLite database and demo data.

Works both from source (python launcher/shiftbase_launcher.py) and when frozen with PyInstaller.
Not for production use: DEBUG is on and the server only listens on the loopback interface.
"""
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
HERE = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
BUNDLE = Path(getattr(sys, "_MEIPASS", HERE))  # where PyInstaller unpacked bundled files
ROOT = HERE if FROZEN else HERE.parent
DATA = HERE / "data"  # database + secret key live next to the exe, never on C:
SEED_VERSION = "3"  # bump when the demo data changes; older demo databases are rebuilt


def free_port(start=8000):
    for port in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free port found between 8000 and 8049.")


def main():
    DATA.mkdir(exist_ok=True)
    key_file = DATA / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(64))
    dist = BUNDLE / "frontend_dist" if FROZEN else ROOT / "frontend" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit(f"Frontend build not found at {dist}. Run `npm run build` in frontend/ first.")
    os.environ.update({
        "SECRET_KEY": key_file.read_text(),
        "DEBUG": "true",
        "SECURE_SSL_REDIRECT": "false",
        "DATABASE_URL": "sqlite:///" + (DATA / "shiftbase.sqlite3").as_posix(),
        "FRONTEND_DIST": str(dist),
        "DJANGO_SETTINGS_MODULE": "config.settings",
    })
    if not FROZEN:
        sys.path.insert(0, str(ROOT / "backend"))

    import django
    from django.core.management import call_command

    db, marker = DATA / "shiftbase.sqlite3", DATA / "seed.version"
    if db.exists() and (not marker.exists() or marker.read_text() != SEED_VERSION):
        print("Demo data changed in this version - rebuilding the local test database…")
        db.unlink()

    django.setup()
    print("Preparing database…")
    call_command("migrate", verbosity=0)
    from core.models import Organization

    if not Organization.objects.exists():
        call_command("seed_demo")
    marker.write_text(SEED_VERSION)

    from django.core.wsgi import get_wsgi_application
    from waitress import serve

    port = free_port()
    url = f"http://localhost:{port}/"
    print(f"\nShiftbase is running at {url}")
    print("Demo logins (password: demo-password-123): manager@demo.test, owner@demo.test,")
    print("  or any employee: employee1@demo.test ... employee10@demo.test")
    print(f"Data folder: {DATA}  (delete it to reset to fresh demo data)")
    print("Close this window or press Ctrl+C to stop.\n")
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    serve(get_wsgi_application(), host="127.0.0.1", port=port, threads=8, ident="shiftbase")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except BaseException as exc:  # keep the window open so the error can be read
        if not isinstance(exc, SystemExit) or exc.code not in (0, None):
            print(f"\nShiftbase failed to start: {exc}")
            input("Press Enter to close…")
        raise
