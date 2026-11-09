# pspdx-shelf

pspdx-shelf serves a PSPDX-compatible catalog from a folder of disc images.

Point it at a folder of `.iso` and `.cso` files, add its address as a source in
[PSPDX](https://github.com/chriopter/pspdx-app), and the discs show up on your PSP.
For your own discs, on your own network.

## Run

1. Save this as `docker-compose.yml`, with your folder:

   ```yaml
   services:
     pspdx-shelf:
       image: ghcr.io/chriopter/pspdx-shelf:latest
       ports:
         - "8080:8080"
       volumes:
         - /path/to/your/isos:/discs:ro
         - ./data:/data
       # environment:
       #   SHELF_PASSWORD: change-me
       restart: unless-stopped
   ```

2. `docker compose up -d`, then open `http://192.168.1.10:8080` in a browser.
3. In PSPDX: **Sources** → add `http://192.168.1.10:8080/`.

- No address to set: the downloads in the catalog point back the way it was
  fetched, so the shelf works at home, through a VPN or behind a reverse proxy
  (which sends `X-Forwarded-Host` and `-Proto`) at once, as the same apps in PSPDX.
- `SHELF_PASSWORD` asks for a password everywhere, as HTTP Basic with any user
  name: the page in the browser, and the catalog and downloads in PSPDX, which
  asks for it when the source is added. Plain `http://` sends it in the clear.
- `SHELF_INTERVAL`: how often the folder is checked for changes, in seconds; once a
  day by default, so a sleeping disk stays asleep. **Rebuild** on the page reads it at once.

## Details

- **Rebuilt when the folder changed:** at start, on **Rebuild** and at every check;
  a file that did not change is not read again.
- **Each disc says what it is:** id and title from `UMD_DATA.BIN` and `PARAM.SFO`,
  icon, picture, film and sound from `PSP_GAME/`.
- **Every entry is checked** against the [catalog schema](https://chriopter.github.io/pspdx/#catalog-v1);
  a disc that fails is left out, with the reason on the page.
- **Genres:** each disc carries its genre as a tag (Sports, Racing, Role-playing
  (RPG), ...), looked up by its disc id in libretro-database's list, which is
  checked in and pinned. A disc the list does not know has none.
- **Two files of one disc:** the highest version is listed, a release before a beta or demo.
- **Downloads can resume:** the images are served with HTTP ranges.
- **Read-only:** the folder is mounted `:ro`; `./data` holds `catalog.json`, the
  media and the SHA-256 cache.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest
docker build -t pspdx-shelf .
```

`tools/update-genres.py` pins the genre list to a newer libretro-database commit.

A tag `v*` builds the image for amd64 and arm64 and publishes it to
`ghcr.io/chriopter/pspdx-shelf`.

## Credits

The genres are from [libretro-database](https://github.com/libretro/libretro-database)
by its contributors, licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); see
[`shelf/genres/`](shelf/genres/).
