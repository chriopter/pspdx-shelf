# Genres

`Sony - PlayStation Portable.dat` is the PSP genre list of
[libretro-database](https://github.com/libretro/libretro-database)
(`metadat/genre/`), unchanged, at the commit in `pin.json`. It is licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) by the
libretro-database contributors; the rest of pspdx-shelf is MIT.

`tools/update-genres.py [commit]` pins another commit: it downloads the list,
checks that it parses, and writes it with its SHA-256 into `pin.json`.
