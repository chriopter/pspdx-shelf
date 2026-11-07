# pspdx-shelf

pspdx-shelf serves a PSPDX-compatible catalog from a folder of disc images.

A private, LAN-only service that reads the PSP UMD images (`.iso`, `.cso`) in one
folder, shows what every disc says about itself, and publishes the folder as a
[PSPDX](https://chriopter.github.io/pspdx/) catalog so a PSP running PSPDX can list
and fetch the discs. Python 3.12 in a Docker container; Flask, pycdlib, jsonschema,
SQLite. Prototype, but tested: 191 tests, all run inside the container and on the host.

**For your LAN only.** No login, no rate limit, no hardening. Never expose port 8080
to the internet. It compresses nothing and changes no image; the one write into the
library folder is a rename you ask for, dry run first, and the folder is mounted
read-only unless you say otherwise.

**Plain HTTP.** PSPDX reads catalogs over HTTPS with TLS 1.3 only, so a reverse proxy
with a certificate the PSP trusts has to sit in front before the console can read
the catalog. The catalog is written with that proxy's `https://` address (`public_url`
in Settings); the service itself serves everything on one HTTP port.

```
umdlibrary/
  main.py        entry point: settings, database, jobs, watcher, one HTTP server
  settings.py    the JSON settings file and its rules
  logs.py        the service log, file and ring buffer
  tools/         the parsers, no web, no database, each a CLI too
    sfo.py       PARAM.SFO parser and writer
    cso.py       CSO reader as a file-like object, and a packer
    iso.py       one image: PARAM.SFO, UMD_DATA.BIN, volume id, media files
    lang.py      what languages a disc speaks
  library/       the folder and the database
    db.py        SQLite: images, hashes, renames
    scan.py      new, changed, gone
    hash.py      streamed SHA-256, cached by path, size, mtime
    media.py     ICON0/ICON1/PIC0/PIC1/SND0 into the data volume, ffmpeg to MP4
    rename.py    pattern, safe names, dry run, apply
    group.py     several discs of one game
    verify.py    match against a pspdb checkout
  catalog/       PSPDX
    manifest.py  the app entry, the .pspdx, the console's id
    build.py     catalog.json + apps/<id>/ media + pspdx/ into a temp dir, validate, swap
    validate.py  the vendored schemas with format checking
    schema/      catalog-v1.json, pspdx-v1.json
  jobs/          runner.py (one worker thread), watch.py (the watch folder)
  web/           app.py, routes/ one file per page, templates/, static/
tests/           mirrors the package: tools/, library/, catalog/, web/
```

## Run

```sh
UMD_LIBRARY=/path/to/isos UMD_HOST=192.168.1.10 docker compose up --build -d
open http://192.168.1.10:8080
```

| Variable | Default | |
|---|---|---|
| `UMD_LIBRARY` | `./isos` | the folder with the images, mounted read-only at `/isos` |
| `UMD_PORT` | `8080` | the host port |
| `UMD_HOST` | `localhost` | the name or IP this machine has on the LAN; in the served URLs |
| `UMD_PUBLIC_URL` | `https://<host>` | the `https://` base written into the catalog |
| `UMD_PSPDB` | `./pspdb` | a clone of [ryp/pspdb](https://github.com/ryp/pspdb), for Verify |

Put them in a `.env` next to `docker-compose.yml` to keep them. `./data` holds the
database, the extracted media, the log and `settings.json`; `./out/catalog` the
published catalog. To rename files, change the mount to `:rw` in the compose file.

Then, in the UI: **Scan**, **Hash**, **Catalog → Build and publish**. The catalog is
at `http://<host>:8080/catalog/catalog.json`; the PSP needs it at
`https://<public_url>/catalog/catalog.json`, so that is the proxy's job.

## Point PSPDX at it

The catalog entries name each image as `https://<public_url>/umd/<DISC-ID>.iso`
(or `.cso`), its manifest as `/umd/<DISC-ID>.pspdx`, its media under
`/catalog/apps/local.umd.<disc-id>/`. A reverse proxy at `public_url` with a
certificate the PSP trusts (PSPDX's localcat mechanism) forwards to port 8080; the
image downloads support HTTP ranges, so a 1 GB fetch can resume. The console derives
its own id for each disc from the host of `public_url` and the name, e.g.
`lan.psp.godofwarchainsofolympus`; the detail page shows it.

## The pages

Everything the service can do is a page or a button; nothing runs that is not on the
Jobs page.

- **Library**: one tile per game with the ICON0 (PIC1 behind it on hover) and a badge
  per version: region, disc id, languages, format, size, media, duplicate, hash,
  pspdb. Search, and filters by region, language, format, missing media, duplicates.
  The detail page has every SFO field, UMD_DATA.BIN, the media (PNG inline, PMF and
  AT3 as downloads, an MP4 of the film if ffmpeg made one), the versions of the game
  side by side, the `.pspdx` and the catalog entry as JSON, and the URLs.
- **Scan**: read new and changed images, forget gone ones, extract media. The watch
  folder toggle (off by default) queues a scan every N seconds.
- **Hash**: SHA-256 for images without one; per-file progress; cached by path, size
  and mtime.
- **Rename**: a pattern, default `{title} [{disc_id}].{ext}`, fields `title`,
  `disc_id`, `region`, `ext`, `format`, `name`, `disc_version`, `category`. Names
  become ASCII, without separators, control or reserved characters, at most 120
  characters, no trailing dot. The table is a dry run with conflicts marked; Apply
  renames the checked rows, never overwrites, never leaves the folder, logs every
  rename, and the database (hash included) follows the file.
- **Catalog**: what the next build would publish and why a disc is skipped (no hash
  yet, an older duplicate, unreadable); the published state; the URLs; the JSON;
  schema problems. A build writes into a temporary directory, validates against both
  vendored schemas, and swaps the directory in whole; a build that fails leaves the
  previous one.
- **Verify**: with a local clone of pspdb mounted and its path set, matches every
  hashed image's SHA-256 and size against `catalog/iso/*/*-ingest.json` and marks it
  a known dump (with the record's title and identifier) or unknown. No network.
- **Settings**: folders, host, port, public URL, rename pattern, watch interval,
  publisher per disc id (the catalog's `author`), languages per disc id, pspdb path.
  One JSON file; the page says where.
- **Jobs**: every job of this process with state, progress, times and log; cancel.
- **Logs**: the last N lines of the service log.
- **About**: versions, what it does not do, the license.

## What a disc yields

`UMD_DATA.BIN` is `<identifier>|<umd_uid>|<type_code>|<media_code>`, e.g.
`ULUS-10404|05FC10F031E498EA|0001|G`. The disc id used in URLs and file names is the
identifier in that form (`ULUS-10404`), from UMD_DATA.BIN, else from the SFO's
`DISC_ID` (which has no dash), else the ISO volume id, else `NOID-<hash>`. The region
comes from the prefix: ULES/UCES EU, ULUS/UCUS US, ULJS/UCJS/ULJM/NPJH JP, ULAS AS,
UCKS KR; anything else is `unknown`.

Languages are lowercase ISO 639-1 codes with an optional region tag. They come from
the SFO where it says anything (localized `TITLE_xx` keys, Sony's index: 00 ja, 01 en,
02 fr, 03 es, 04 de, ...; or a `LANGUAGE`-like key), otherwise from the region:
JP `ja`, US `en`, EU `en`, AS `en`, KR `ko`. An EU disc that speaks five languages is
`en` until you set an override in Settings, per disc id.

Two files with the same disc id are both listed and flagged; the newest by mtime is
the one the catalog and `/umd/<id>` serve. Several discs of one game (EU, US, JP,
a Platinum reissue) are grouped by the title, case-folded, with trailing region,
language, version and edition markers stripped.

## The catalog

Follows catalog-v1: `type: "iso"`, `category: "game"`, `name` from the SFO title cut
at 40 (with the disc id appended when the title has no ASCII letter or digit, as the
schema wants of a non-GitHub source), `source` `https://<public_url>/umd/<DISC-ID>`,
`id` `local.umd.<disc-id>` (the console ignores it and derives its own),
`author` from the publisher override, `summary` like `UMD ULES-01234, EU, 1.2 GB`,
`description` with the disc facts, `tags`, `languages`, `media` under
`apps/<id>/icon-<hash8>.png`, `picture-<hash8>.png`, `film-<hash8>.pmf`,
`sound-<hash8>.at3`, and one release: `tag` the DISC_VERSION, `published_at` the
file's mtime, `url`, `size`, `sha256`. Apps sorted by id, `generated_at` UTC, compact
JSON. Each disc also gets a `.pspdx` (pspdx-v1, with `release` pinned to the image).

`languages` is new in both schemas. This experiment adds it to the copies in
`../pspdx/schema/` (uncommitted, for review): optional, an array of up to 16 unique
strings matching `^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$`.

### The `umd` extension

catalog-v1 allows fields it does not name, so every app carries a flat `umd` object,
what this service knows beyond the schema. pspdx-v1 forbids unknown fields, so the
`.pspdx` does not have it.

| field | |
|---|---|
| `disc_id` | the SFO's `DISC_ID` as written, `ULUS10404` |
| `disc_key` | the id in URLs, `ULUS-10404` |
| `identifier`, `umd_uid`, `type_code`, `media_code` | the four parts of UMD_DATA.BIN, named as pspdb names them |
| `title` | the SFO `TITLE` |
| `disc_version` | `DISC_VERSION` |
| `psp_system_ver`, `required_firmware` | `PSP_SYSTEM_VER`, twice: the SFO's name and pspdb's |
| `region` | EU, US, JP, AS, KR or unknown |
| `languages`, `languages_from` | the codes, and whether they came from `sfo`, `region` or `override` |
| `parental_level`, `category` | `PARENTAL_LEVEL`, `CATEGORY` (UG for a game) |
| `format` | `iso` or `cso` |
| `file` | the file name in the library |
| `image_size`, `iso_size` | bytes on disk, and bytes of the ISO (equal for an .iso) |
| `has_media` | one flag per ICON0.PNG, ICON1.PMF, PIC0.PNG, PIC1.PNG, SND0.AT3 |
| `pspdb_status`, `pspdb_title` | `known`, `unknown` or null, and the title pspdb has |

## Tools on the command line

```sh
python -m umdlibrary.tools.sfo PARAM.SFO            # every field
python -m umdlibrary.tools.iso game.iso --media out/ # what the disc says, media copied
python -m umdlibrary.tools.cso game.cso --extract game.iso
```

## Tests

```sh
docker compose run --rm test        # inside the container (make test)
make venv && make test-host         # on the host, Python 3.12+
```

191 tests: the SFO parser against SFOs the tests write; the CSO reader against a
packer of its own, with random seeks, raw and compressed blocks, truncated and corrupt
files; disc reading from synthetic ISOs built with pycdlib (PARAM.SFO, a real PNG,
UMD_DATA.BIN), including a file that is no ISO, an ISO without PSP_GAME, a broken
SFO, a video UMD's UMD_DATA.BIN, a 4 GB sparse image, unicode titles and names; the
scanner (add, change, remove, duplicates newest first, unicode, cancel); hashing
(streamed, peak memory bounded, cached, follows a rename); rename (safe names,
patterns, dry-run statuses, apply, no overwrite even when a file appears in between,
a read-only folder, a pattern that tries to leave the folder); media and the ffmpeg
job; languages, grouping, the pspdb verifier with two fake records; the catalog
entry and `.pspdx` against both vendored schemas with format checking, the source
URL against the schema's host rules, a full build with the media layout and an
atomic swap that keeps the previous build when validation or writing fails, one game
in three language versions plus a multi-language disc; settings; jobs and the
watcher; every route, range requests, 404s, and the actions through the UI.

## Not done

- No HTTPS: PSPDX cannot read the catalog until a proxy provides it.
- The container runs as root; files it writes into `./data` and `./out` are root's
  on some hosts.
- The catalog lists one file per disc id (the newest); an older duplicate is only in
  the library.
- Publishers and multi-language EU discs are what you type; no disc says.
- The library is one folder, not a tree.

MIT, chriopter.
