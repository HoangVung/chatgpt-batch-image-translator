# ChatGPT Batch Translator v1.0.0 Release Checklist

Phase 7 validation items are checked from the confirmed release baseline because
Phase 8 made no functional or build changes. Packaging items are checked from
the final Phase 8 verification.

- [x] version confirmed
- [x] git status reviewed
- [x] production artifact verified
- [x] normal frozen launch PASS
- [x] `--tk` PASS
- [x] `--self-test` PASS
- [x] `--worker` isolated PASS
- [x] real 1-image batch PASS
- [x] folder picker PASS
- [x] Copy Log PASS
- [x] Export Log PASS
- [x] Open Output PASS
- [x] close/cleanup PASS
- [x] artifact hygiene PASS
- [x] release ZIP created
- [x] ZIP extraction verified
- [x] SHA-256 generated
- [x] README included
- [x] release notes included
- [x] license included if applicable

## Release notes

- Release version: `1.0.0`
- Package: `ChatGPT-Batch-Translator-v1.0.0-Windows-x64.zip`
- Target: Windows x64 portable
- Windows 11 validated; Windows 10 not fully validated
- Microsoft Edge WebView2 Runtime required
- Portable executable is not code-signed
