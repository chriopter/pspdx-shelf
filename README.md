# pspdx-shelf

pspdx-shelf serves a PSPDX-compatible catalog from a folder of disc images.

Point it at a folder of `.iso` and `.cso` files, add its address as a source in
[PSPDX](https://github.com/chriopter/pspdx-app), and the discs show up on your PSP.
For your own discs, on your own network.

## Run

1. Save this as `docker-compose.yml`, with your folder and this machine's address:

   ```yaml
   services:
     pspdx-shelf:
       image: ghcr.io/chriopter/pspdx-shelf:latest
       ports:
         - "8080:8080"
       volumes:
         - /path/to/your/isos:/discs:ro
         - ./data:/data
       environment:
         SHELF_URL: http://192.168.1.10:8080
         # SHELF_PASSWORD: change-me
       restart: unless-stopped
   ```

2. `docker compose up -d`, then open `http://192.168.1.10:8080` in a browser.
3. In PSPDX: **Sources** → add `http://192.168.1.10:8080/`.

- `SHELF_URL` is the address PSPDX reaches the shelf at: `http://` on your own
  network, or `https://` with a reverse proxy in front.
- `SHELF_PASSWORD` puts everything under `/<password>/`: the page, the catalog
  and the downloads. Add `http://192.168.1.10:8080/<password>/` in PSPDX then;
  every other address answers 404.
- `SHELF_INTERVAL`: how often the folder is checked for changes, in seconds; once a
  day by default, so a sleeping disk stays asleep. **Rebuild** on the page reads it at once.

## Details

- **Rebuilt when the folder changed:** at start, on **Rebuild** and at every check;
  a file that did not change is not read again.
- **Each disc says what it is:** id and title from `UMD_DATA.BIN` and `PARAM.SFO`,
  icon, picture, film and sound from `PSP_GAME/`.
- **Every entry is checked** against the [catalog schema](https://chriopter.github.io/pspdx/#catalog-v1);
  a disc that fails is left out, with the reason on the page.
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

A tag `v*` builds the image for amd64 and arm64 and publishes it to
`ghcr.io/chriopter/pspdx-shelf`.
