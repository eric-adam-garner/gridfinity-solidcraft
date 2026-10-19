# gridfinity-solidcraft

Gridfinity bins, baseplates, connection clips and collections, as made by
[gridfinitygenerator.com](https://gridfinitygenerator.com/en), built in SolidCraft.

```sh
uv sync
uv run gridfinity box --units 2 1 --height 3 --out box.stl
uv run gridfinity box --units 2 1 --live          # build in the running app
uv run gridfinity --help
uv run pytest -q                                  # needs solidcraft-cli on PATH for the build tests
```

What each part is made of, the settings and dimensions, how the geometry is built and how to
extend it: [docs/gridfinity.html](docs/gridfinity.html).
