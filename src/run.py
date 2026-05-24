# -*- coding: utf-8 -*-
"""Runner: starts WebUI + Telegram bot."""
import threading

from webui import app as webui_app


def start_webui():
    webui_app.run(host="0.0.0.0", port=9099, debug=False, use_reloader=False)


if __name__ == "__main__":
    t = threading.Thread(target=start_webui, daemon=True)
    t.start()
    from bot import main
    main()
