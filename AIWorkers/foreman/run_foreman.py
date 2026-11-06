import logging
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from foreman import Foreman
from foreman_app import create_app

ROOT = Path(__file__).resolve().parent.parent  # E:\AIWorkers
PORT = 8720  # the Warden is 8710; the Foreman lives next door


def main() -> None:
    # What the shift decided and when, so "it said nothing to do" can be read afterwards rather than guessed at
    handler = logging.FileHandler(ROOT / "data" / "logs" / "foreman.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logging.getLogger("foreman").addHandler(handler)
    logging.getLogger("foreman").setLevel(logging.INFO)
    foreman = Foreman(ROOT)
    link = f"http://127.0.0.1:{PORT}/login?token={foreman.token}"
    (ROOT / "data" / "foreman_login.txt").write_text(link + "\n", encoding="utf-8")
    print(f"\nForeman is up. Open: {link}\n", flush=True)
    if "--open" in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=(link,)).start()
    foreman.shift.start()
    try:
        uvicorn.run(create_app(foreman), host="127.0.0.1", port=PORT, log_level="warning")
    finally:
        foreman.run.stop()  # closing the Foreman sends the worker home too


if __name__ == "__main__":
    main()
