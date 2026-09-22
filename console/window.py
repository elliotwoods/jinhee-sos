"""pywebview wiring. `webview` is imported lazily so console/app.py imports without a runtime."""
import paths  # noqa: F401
import threading

WEB = paths.CONSOLE / 'web'


def run_native(hub, api, debug=False, title='NCT Console'):
    import webview

    window = webview.create_window(title, str(WEB / 'index.html'), js_api=api, width=1440, height=900,
                                   min_size=(1100, 700), text_select=True)
    refusing = threading.Event()

    def on_closing():
        try:
            hub.call(hub.shutdown).result(timeout=20)
        except ValueError as exc:
            refusing.set()
            try:
                window.evaluate_js(f'window.nct && window.nct.notify({str(exc)!r}, "bad")')
            except Exception:
                pass
            return False
        except Exception:
            pass
        return True

    window.events.closing += on_closing

    def wake():
        try:
            window.run_js('window.nct && window.nct.wake && window.nct.wake()')
        except Exception:
            pass

    hub.on_wake = _throttled(wake, hub.clock)
    webview.start(debug=debug, http_server=True, private_mode=False)


def _throttled(fn, clock, interval=0.15):
    last = [0.0]
    lock = threading.Lock()

    def call():
        now = clock()
        with lock:
            if now - last[0] < interval:
                return
            last[0] = now
        fn()

    return call
