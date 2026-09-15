# ChatGPT Batch Translator v1.0.0

## Highlights

- Liquid Glass / pywebview Windows interface
- CustomTkinter fallback interface
- ChatGPT and Google Gemini batch image workflow
- Real-time progress and logging
- Account/profile management
- Stop, retry, and manual-intervention support
- Portable Windows package

## Validation

- Frozen real batch: PASS
- WebView2 shell: PASS
- Tk fallback: PASS
- Worker and self-test: PASS
- Unicode and path handling: PASS
- Full test suite: 82 PASS, 2 expected skips

## Packaging

- Production artifact size: 594.48 MiB
- Chromium headful bundled
- Chromium headless shell excluded
- System Microsoft Edge WebView2 Runtime used

## Known notes

- Windows 11 64-bit validated
- Windows 10 64-bit may work with WebView2 but is not fully validated
- Microsoft Edge WebView2 Runtime required
- Executable is not code-signed
