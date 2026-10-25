"""Optional desktop presence. No broker credentials or execution authorization."""
import json
import os
from pathlib import Path
import queue
import sys
import tempfile

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE = 'SentinelCrierDesktop'


class RunRegistry:
    def get(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, kind = winreg.QueryValueEx(key, RUN_VALUE)
                return value if kind == winreg.REG_SZ else '<unsupported registration>'
        except FileNotFoundError:
            return None

    def set(self, value):
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, value)

    def delete(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            pass


class StartupRegistration:
    def __init__(self, executable=None, *, frozen=None, platform=None, registry=None):
        executable = Path(executable or sys.executable)
        self.available = bool((sys.platform if platform is None else platform) == 'win32'
                              and (getattr(sys, 'frozen', False) if frozen is None else frozen)
                              and executable.is_absolute() and executable.is_file()
                              and executable.suffix.lower() == '.exe')
        self.command = f'"{executable}" --startup'
        self.registry = registry or RunRegistry()

    @property
    def enabled(self):
        return self.available and self.registry.get() == self.command

    def set_enabled(self, enabled):
        if not self.available:
            raise ValueError('Windows sign-in startup requires the packaged Windows app.')
        if type(enabled) is not bool:
            raise ValueError('Choose whether to open at sign-in.')
        existing = self.registry.get()
        if existing is not None and existing != self.command:
            raise ValueError('A different Crier startup registration exists. Inspect Windows Startup apps first.')
        if enabled:
            self.registry.set(self.command)
        elif existing is not None:
            self.registry.delete()


class Presence:
    def __init__(self, folder, *, startup=None, tray_factory=None):
        self.path = Path(folder)/'desktop-presence.json'
        self.startup = startup or StartupRegistration()
        self.tray_factory = tray_factory
        self.tray_enabled = False
        self.tray_ready = False
        self.tray = None
        self.error = ''
        self.events = queue.SimpleQueue()
        try:
            if self.path.exists():
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(value, dict) or set(value) != {'tray'} or type(value['tray']) is not bool:
                    raise ValueError('Invalid preference')
                self.tray_enabled = value['tray']
        except (OSError, ValueError, UnicodeError):
            self.error = 'Cannot read desktop preferences. Tray mode is off; preserve the file for recovery.'

    def _start_tray(self):
        if self.tray_ready:
            return
        try:
            factory = self.tray_factory
            if factory is None:
                from .windows_tray import WindowsTray
                factory = WindowsTray
            self.tray = factory(self.events.put)
            if not self.tray.start():
                raise ValueError('Tray unavailable')
            self.tray_ready = True
        except Exception:
            self.stop()
            self.error = 'Cannot start the tray. Crier will keep its window visible.'
            raise ValueError(self.error) from None

    def start(self):
        if self.tray_enabled:
            try:
                self._start_tray()
            except ValueError:
                pass

    def set_tray(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Choose whether to keep running in the tray.')
        old = self.tray_enabled
        if enabled:
            self._start_tray()
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.path.parent, delete=False) as file:
                temporary = Path(file.name)
                json.dump({'tray':enabled}, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except OSError:
            if enabled and not old:
                self.stop()
            raise ValueError('Cannot save desktop preferences. The prior choice remains active.') from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.tray_enabled = enabled
        self.error = ''
        if not enabled:
            self.stop()

    def poll(self):
        actions = []
        while True:
            try:
                action = self.events.get_nowait()
            except queue.Empty:
                break
            if action in ('show','pause','quit'):
                actions.append(action)
        if self.tray_ready and not self.tray.alive:
            self.stop()
            self.error = 'Tray stopped. Crier restored its window; inspect desktop settings.'
            actions.append('show')
        return actions

    def stop(self):
        self.tray_ready = False
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                self.error = 'Tray cleanup failed. Crier keeps its window available; Quit still stops the worker.'

