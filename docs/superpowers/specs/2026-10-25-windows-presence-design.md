# H.4 optional Windows presence

Continue the approved H plan directly on main. Add two independent, default-off desktop options: keep the app running in the notification area when its window closes, and open the installed app at Windows sign-in. Sign-in launches remain disconnected; no credential restoration, automatic broker connection, entry enablement or Discord delivery is added.

Use a small presence controller separate from Tk and execution. Persist only the tray preference as atomic nonsecret JSON. Derive startup status from the current user's Run registration, writing only Crier's named value when the user explicitly opts in. Startup is available for a frozen Windows executable, not an unstable source checkout. The installer removes only a registration matching its own executable on uninstall and never registers startup by default.

Use pystray's Windows backend with a generated Pillow icon. Native callbacks enqueue fixed actions; the existing Tk refresh loop drains them on the UI thread. Actions are Show Crier, Pause new entries, and Quit. There is no tray action to enable entries. Closing hides only after the tray reports ready; startup or runtime tray failure keeps/restores the window. Disabling tray mode restores the window. Quit uses the existing disconnect/in-flight shutdown flow and removes the icon after successful disconnect.

Prefer a supported tray library to Win32 window-procedure hooks or a new Windows service. Keep a visible window as the fallback instead of allowing an invisible worker. Do not change existing price/sizing policies, process locks or OAuth-return handling. Tests use fake registry/tray boundaries and hidden Tk windows; actual packaged tray startup/shutdown is checked on the ephemeral Windows CI runner, without broker or Discord calls. Physical Explorer/taskbar interaction remains deferred.

Windows packages also carry the exact installed tray library's Python source, upstream source-build files and GPL/LGPL license texts. Pillow/six notices and installed dependency versions accompany them. The source bundler refuses a mismatched tray version or missing source/license data. This preserves dependency terms without changing Crier's application license.

Tray lifecycle reference: [pystray usage](https://pystray.readthedocs.io/en/latest/usage.html), inspected 2026-10-25. Windows permits its event loop on a worker thread; callbacks must not touch Tk directly.
