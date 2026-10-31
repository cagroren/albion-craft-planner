# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working with the owner

- The owner writes Turkish; answer in Turkish. UI text, code comments and commit messages are Turkish too.
- Flow for every change: implement → test locally → commit locally → ask **"Canlıya alayım mı?"**. Push (and publish a DPS release) only after an explicit yes in that turn. Vercel deploys `main` automatically on push.
- Commit with `git commit -F <file>` (PowerShell breaks multi-line `-m`).
- **Update notes:** every change users can see gets a plain-Turkish bullet in `data/changelog.json` (newest entry first; add to today's entry or create `{date,title,items}`), committed with the change. No technical jargon, no internal/dev-only changes. Users see new notes once as a popup (`auth.js` `notesPopup`) and on `yenilikler.html`; `nav.js` shows an unread dot (`aoNotesLatest` vs `aoNotesSeen`).
- `index.html`, `destiny.html`, `builds.html`, `admin.html` are large: Grep first, then Read with offset/limit. For multi-line edits a small Python replace script (`assert s.count(old)==1`) written to the scratchpad is more reliable than shell heredocs.

## What this is

Static site (no build step, no framework, no test suite) for the Albion Online guild **Kal Vas Flam (KVF)**, hosted on Vercel (`albion-craft-planner-lovat.vercel.app`) with Supabase (project `aulscfeqndppxbtypezs`) for auth and data, plus a Windows packet-sniffing collector (`dps-meter/`).

## Local testing

- Serve the repo: `py -3 -m http.server 5517 --bind 127.0.0.1` and open `http://localhost:5517/...` in the built-in browser. Opening files via `file://` breaks localStorage.
- On `localhost`/`127.0.0.1` the guild gate in `auth.js` is disabled (`GATE=false`); serve on `127.0.0.2` to see the gate.
- The browser caches `auth.js`/`nav.js`/pages aggressively (and `sw.js` exists): `await fetch(path,{cache:"reload"})` then reload.
- Page scripts are mostly wrapped in closures; to test internals, copy the page to a temporary `_test_*.html` that exposes functions on `window`, then delete it.
- `api/*.js` can be tested with Node by mocking `globalThis.fetch` and importing the handler (`GET`/`POST` take a `Request`-like object).

## Architecture

### Pages and shared scripts
- `index.html` hosts many tools selected by URL hash: Alchemy (default), `#food`, `#craft`, `#enchant`, `#farm`, `#refine`, `#bm`, `#db`. The tool is chosen at load, so switching tabs reloads the page.
- `builds.html`, `destiny.html`, `dps.html`, `maps.html`, `depo.html`, `admin.html` are separate pages.
- `nav.js`: shared grouped top menu, remembers the last tab, hides tabs closed from the panel (`window.aoNav.set(off, isAdmin)`, cached in `localStorage.aoTabsOff`).
- `auth.js` (loaded on every page except `admin.html`):
  - Discord login via Supabase (`window.aoSb`), the guild gate overlay, feedback bubble, Data Client / DPS Meter info popups, page-view tracking.
  - Cloud sync: hooks `Storage.prototype.setItem` and pushes the `KEYS` list to `user_data`. On load it compares the cloud value with a snapshot taken when the page opened, so a page that rewrites its own data on load does not trigger a reload loop.
- `dspec.js` (index.html only): `window.aoSpec` reads Destiny Board levels (collector > `destiny_boards` > `aodestiny1` manual) and fills Craft/Cooking/Alchemy/Farming/Refining spec fields once per load or character change; fields stay editable.
- `config.js`: Supabase URL and publishable key (public by design; security is RLS).

### Guild access (Discord role gate)
- `api/access.js`: called by `auth.js` on every page load and every 2 minutes. Verifies the Supabase JWT, then asks the Discord bot whether the user has the exact role `DISCORD_MIN_ROLE` ("Üye") in `DISCORD_GUILD_ID`.
  - A definite "no" deletes the auth user; everything cascades from `auth.users`.
  - Errors never delete. Admins (`profiles.is_admin`) are always allowed.
- `api/sweep.js`: same rule for all users.
  - Called every minute by Supabase `pg_cron` job `kvf-sweep` (header `x-sweep-key`, secret generated in `app_secrets`) and daily by Vercel Cron (`CRON_SECRET`).
  - `?dry=1` lists who would be removed without deleting.
  - Writes `app_status` and `removals`.
  - **Before changing the access rule, pause the cron job, deploy, run a dry run, then resume.**
- `api/admin.js`: admin-only Discord member info and manual delete.
- `api/_guild.js`: shared helpers.
- Vercel env vars: `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_MIN_ROLE`, `SUPABASE_SERVICE_ROLE_KEY`, `CRON_SECRET`. The owner enters secrets; never type tokens yourself.

### Supabase
- `supabase/schema.sql` is the source of truth. Sections are appended over time; each "(yeni eklendi)" block is idempotent.
- Run SQL through the Supabase MCP if authorized. Otherwise use the browser SQL editor: `monaco.editor.getModels()[0].setValue(sql)` → Run → confirm the "destructive operations" dialog. The owner must be logged in to Supabase in the built-in browser.
- Run SQL **before** pushing code that depends on new columns. Example: `admin.html` selects `is_owner`.
- Key RLS helpers: `is_member()`, `is_admin()`, `is_owner()` (feedback is owner-only, not admins).
- Admin actions are logged by triggers into `admin_log`.

### Discord share previews
- `vercel.json` rewrites `/b/:id` and `/g/:id` to `api/share.js` (edge); its OG image comes from `api/og.js` (Node runtime; `@vercel/og` returns empty images on edge).
- `api/_build.js` reads builds with the service key (builds are member-only under RLS) and game data from `data/builds.json`.
- Build gear slots: `w o h a s c b m f p`. Swaps are `x xh xa xs xp`, mapped by `SWP`/`BASE` in both `builds.html` and `api/_build.js`.

### Destiny Board
- `data/destiny.json` is generated by `py -3 tools/gen_destiny.py` from ao-bin-dumps. Node ids are indexes in achievements.xml order, which the collector sends.
- Respec math in `destiny.html`:
  - credit = fame × `lpmultiplier` × `respecmodifier`, only for `rs==="combat"`.
  - silver = elite credit × 0.38147.
  - For combat nodes, levels above 100 are credit-only (not counted as fame).
- The plan syncs to the `destiny_plans` table; boards sync to `destiny_boards`.

### Depo (`depo.html`, `stock.js`)
- Personal storage: bank tabs and island/house chests. Stored in `localStorage.aostock1` (cloud-synced via `auth.js` KEYS): `{stores:{key:{name,zone,kind:"bank"|"chest"|"manual",t,on,items:{id:qty}}},hidden:{key:deletedAt},set:{...}}`.
- Collector `/storage` (v15+) returns bank tabs (`BankVaultInfo` event: 1 = `"guid@zone"`, 2 = tab guids, 3 = tab names; a tab's content is the `AttachItemContainer` whose param 2 equals the tab guid) and non-corpse chests opened via `ContainerOpen`. Keys: `b:<tabguid>`, `c:<containerguid>`. Island chests (zone contains `ISLAND`) are added automatically; other chests are offered with an "add" button.
- `stock.js` (`window.aoStock`): `total()` sums stores with `on`, `tag(id,need)` renders "depoda X · Y alınacak". Used by the Craft/Cooking/Alchemy shopping list (Depoda/Alınacak columns), Refining plan and Farming seed/baby cells.
- "Ne craftlayabilirim" builds recipes from items.json (gear, meals, potions, refined materials; farming = seeds/babies in stock), counts how many can be made from the stock (optional return rate) and sorts by total profit at the chosen city's sell prices.
- `data/zones.json` (cluster id -> display name) is written by `tools/gen_maps.py`.

### Avalon Maps (`maps.html`)
- `data/maps.json` is generated by `py -3 tools/gen_maps.py` from ao-bin-dumps `cluster/world*.xml` (+ `_patch.xml`), `cluster/TNL-*.cluster.xml` and templates. Downloads are cached in `%TEMP%/ao-bin-cache` (`--fresh` to refetch).
- Terrain: `data/maps/<cluster>.json` is a 5-unit grid (run-length rows, north first) rasterised from template tiles. Default is void; only `type="Ground"` tiles are walkable. Compoundtiles (e.g. the winding `_ROADS_MIST_OFFROAD_*` paths) are expanded into their member tiles from `tiles.xml`, which gives the real path shapes. `*NOCLICK*` = void (painted first, ground drawn over it), `AVA_GROUND_*`/`AVA_PORTAL_GROUND` = Avalon stone floor, water/river. The page smooths the grid with SVG blur+threshold filters. Main roads are `_ROADS_MIST_ROAD_*` compoundtiles (sparse pieces), stored as `rd` segments joining axis-aligned neighbours. The page draws it rotated 45° (verified against an albionmaps image: screen right = (dx+dz)/√2).
- Only `cluster/world.xml` is used: `world_europe.xml`/`world_asia.xml` in the dump stopped updating in 2024/2023 and are stale (owner confirmed Hebitos-Atontum is T6 in game, as in world.xml). `S` rows end with the enabled flag; `L` holds layouts by cluster file.
- Resource counts come from the game's own `distribution` in world.xml; chest/boss/dungeon positions from active template layers. Road chest colour follows the chest type (`lootchests.xml` minimap marker): solo = green, group (veteran) = blue, raid (elite) = gold. The T4/T6/T8 in chest tile names is not the colour.
- albionmaps.com.br has no API or reuse terms; do not copy its data or images.

### DPS Meter collector (`dps-meter/albion_dps.py`)
- Passive Photon packet sniffer (scapy + Npcap, ported from AlbionOnline-StatisticsAnalysis). HTTP API on `127.0.0.1:47700` (`/status`, `/fights`, `/destiny`, `/loot`, `/storage`, `/end`, `/pause`, `/resume`, `/update`); only the site origin and localhost may call it.
- Windowed tray app (pystray):
  - Registers the `albiondps://` protocol in HKCU so pages can launch it.
  - Runs a single instance (`SO_EXCLUSIVEADDRUSE`).
  - Starts `albiondata-client` hidden (downloads it next to the exe).
  - Self-updates from the newest GitHub release `dps-vN` via a batch file that waits for both PyInstaller processes.
  - Starts the new exe with `PYINSTALLER_RESET_ENVIRONMENT=1`.
- `VERSION` in the script must equal the release number N.
- Build:
  `py -3 -m PyInstaller --noconfirm --onefile --noconsole --name AlbionDPSMeter --collect-submodules scapy.layers --hidden-import pystray._win32 --distpath ..\dist --workpath ..\build albion_dps.py` (run from `dps-meter/`)
- Release: `gh release create dps-vN ..\dist\AlbionDPSMeter.exe --title "DPS Meter vN" --notes-file <file> --target main --latest`
- Testing the exe overwrites the `albiondps://` registry entry with the test path. Use `ALBION_DPS_PORT`, `ALBION_NO_BROWSER=1` and `ALBION_NO_DATA_CLIENT=1` for test runs. Afterwards point `HKCU\Software\Classes\albiondps\shell\open\command` back to the owner's exe.
- Never kill the owner's own collector processes; only ones started from the scratchpad.

### Prices
Albion Data Project API (`{europe,west,east}.albion-online-data.com`); item metadata from ao-data/ao-bin-dumps.
