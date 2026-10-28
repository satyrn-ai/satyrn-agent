# satyrn-agent

🚧 *This repo is under active development.*

The downstream agent from the ds4-py design: a customisation of ds4-py that
runs against a patched [ds4](https://dwarfstar.sh/) engine (dense qwen35 on Metal, DFlash speculative
decode).

## Development status

Current status: repo bootstrap.

The ds4 patch series and its tooling land next; the
governing design is `docs/specs/2026-10-24-ds4-patch-series-design.md` on
branch `docs/ds4-patch-series` until that slice merges.

## Layout

- `docs/specs/` — design documents (the patch-series design is on branch
  `docs/ds4-patch-series` for now).
- `docs/plans/` — implementation plans, when they exist.
- `patches/` — the ds4 patch series against `antirez/ds4` (next slice).
- `tools/` — patch and build scripts (next slice).
- `.ds4/` — gitignored scratch trees materialized from the patch series.

## Develop

devenv provides the toolchain (C, Python + uv from Nix). After cloning:

```
direnv allow    # or: devenv shell
```
