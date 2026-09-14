# pywebview UI POC

Disposable proof of concept for a local pywebview + HTML/CSS/vanilla JavaScript desktop shell. It does not import or call the application worker.

## Run

From this directory:

```powershell
python -m pip install -r requirements.txt
python main.py --self-test
python main.py
```

The interactive smoke test should confirm:

- `Bridge ready` is visible.
- JS → Python echo returns the entered text.
- Python → JS updates the pushed-event panel.
- Choose Folder opens the native OS folder dialog.
- Platform and renderer values are populated.
- System, Light, and Dark selections work.
- The native titlebar remains visible and the window resizes down to its minimum size.
- Network inspection shows only the loopback-hosted local HTML/CSS/JS assets.

## Package on Windows

```powershell
python -m PyInstaller --noconfirm --clean --onedir --windowed --name "Pywebview UI POC" --add-data "ui;ui" main.py
```

Run `dist\Pywebview UI POC\Pywebview UI POC.exe`. The Windows machine needs the Microsoft Edge WebView2 Runtime. This is independent from the Playwright Chromium used by the main application's worker.

## Package on macOS

```bash
python3 -m PyInstaller --noconfirm --clean --onedir --windowed --name "Pywebview UI POC" --add-data "ui:ui" main.py
```

Run `dist/Pywebview UI POC.app`. Verify WKWebView, native titlebar, resize, system appearance, and vibrancy on a real Mac before accepting macOS packaging.
