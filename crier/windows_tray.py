"""Windows-only tray backend. Callbacks enqueue actions and never call Tk."""
import sys
import threading


class WindowsTray:
    def __init__(self, send):
        if sys.platform != 'win32':
            raise ValueError('Tray mode is available in the Windows app.')
        import pystray
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (64,64), '#121b2b')
        draw = ImageDraw.Draw(image)
        draw.ellipse((10,10,54,54), outline='#72dfba', width=6)
        draw.line((34,18,22,32,34,46), fill='#ffffff', width=5)
        menu = pystray.Menu(
            pystray.MenuItem('Show Crier', lambda: send('show'), default=True),
            pystray.MenuItem('Pause new entries', lambda: send('pause')),
            pystray.MenuItem('Quit Crier', lambda: send('quit')))
        self.icon = pystray.Icon('SentinelCrier', image,
                                 'Sentinel Crier — open for actual connection and order status', menu)
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, name='Crier notification area', daemon=True)

    def _run(self):
        def setup(icon):
            if self.stopping.is_set():
                icon.stop()
                return
            icon.visible = True
            if self.stopping.is_set():
                icon.stop()
                return
            self.ready.set()
        try:
            self.icon.run(setup=setup)
        except Exception:
            # The presence controller detects a stopped thread and restores Tk.
            pass

    @property
    def alive(self):
        return self.thread.is_alive()

    def start(self):
        self.thread.start()
        return self.ready.wait(2) and not self.stopping.is_set() and self.alive

    def stop(self):
        self.stopping.set()
        self.icon.stop()
        if self.thread.ident is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
