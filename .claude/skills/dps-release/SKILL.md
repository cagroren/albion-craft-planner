---
name: dps-release
description: Build, smoke-test and publish a new AlbionDPSMeter.exe as GitHub release dps-vN for this repo. Use when the owner asks to release, publish or "yayınla" the DPS Meter / exe, or after changing dps-meter/albion_dps.py and the owner approved the release.
---

# DPS Meter release (dps-vN)

Only run the publishing steps (push, `gh release create`) after the owner explicitly approved them in this turn ("Evet, push et ve exe'yi dps-vN olarak yayınla"). Before that, stop after step 4 and ask "Canlıya alayım mı?".

## 1. Version
- `gh release list -L 1` → latest `dps-vN`. The new version is N+1.
- Set `VERSION = N+1` in `dps-meter/albion_dps.py`. It must equal the release number, or the self-updater will offer the update forever or never.

## 2. Syntax check
`py -3 -c "import ast;ast.parse(open('dps-meter/albion_dps.py',encoding='utf-8').read())"`

## 3. Smoke test in the scratchpad (never touch the owner's running collector)
- Build to the scratchpad:
  `py -3 -m PyInstaller --noconfirm --onefile --noconsole --name AlbionDPSMeter --collect-submodules scapy.layers --hidden-import pystray._win32 --distpath <scratch>\dist --workpath <scratch>\work --specpath <scratch> dps-meter\albion_dps.py`
- Run it with `ALBION_DPS_PORT=47713`, `ALBION_NO_BROWSER=1` and `ALBION_NO_DATA_CLIENT=1`, plus the argument `--updated` so no browser opens.
- Check that `http://127.0.0.1:47713/status` reports the new `version`.
- Stop only processes whose path is in the scratchpad.
- Running the exe re-registers `albiondps://` to the scratch path. Point it back:
  - Set `HKCU:\Software\Classes\albiondps\shell\open\command` (default) to `"<owner exe>" "%1"`.
  - Set `DefaultIcon` (default) to `"<owner exe>",0`.
  - The owner's exe is the newest `AlbionDPSMeter*.exe` in `%USERPROFILE%\Downloads`.

## 4. Release build and commit
- From `dps-meter/`:
  `py -3 -m PyInstaller --noconfirm --onefile --noconsole --name AlbionDPSMeter --collect-submodules scapy.layers --hidden-import pystray._win32 --distpath ..\dist --workpath ..\build albion_dps.py`
- Do not run this exe; running it re-registers the protocol.
- Commit with a Turkish message via `git commit -F <file>`, ending with the Co-Authored-By line.
- Ask the owner: "Push edip exe'yi dps-v{N+1} olarak yayınlayayım mı?"

## 5. Publish (after approval)
- `git push origin main`
- Write short Turkish release notes to a scratch file: what changed, and "v9+ kullananlar DPS Meter sayfasındaki Güncelle düğmesiyle otomatik güncellenir".
- `gh release create dps-v{N+1} ..\dist\AlbionDPSMeter.exe --title "DPS Meter v{N+1}" --notes-file <file> --target main --latest`
- Verify that `gh release list -L 2` shows the new release as Latest, and `gh release view dps-v{N+1} --json assets` lists `AlbionDPSMeter.exe`.

## Notes
- Users on v9+ see a "Güncelle" button on the DPS Meter page within one app start.
- The site's download links use `releases/latest/download/AlbionDPSMeter.exe`, so they follow automatically.
