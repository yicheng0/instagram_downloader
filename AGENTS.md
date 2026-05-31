# Agent Instructions

## Project Overview

Instaloader is a Python 3.9+ package and command-line tool for downloading
Instagram media, captions, comments, geotags, stories, saved media, and related
metadata. The public CLI entrypoint is `instaloader=instaloader.__main__:main`,
and the top-level `instaloader.py` script delegates to that entrypoint.

## Repository Layout

- `instaloader/`: Core package.
  - `__main__.py`: CLI argument parsing and command orchestration.
  - `instaloader.py`: Main downloader class and high-level download behavior.
  - `instaloadercontext.py`: HTTP/session handling, logging, rate control, and
    request behavior.
  - `structures.py`: Public data model objects such as `Profile`, `Post`,
    `StoryItem`, `Hashtag`, and serialization helpers.
  - `nodeiterator.py` and `sectioniterator.py`: Pagination and resumable
    iteration helpers.
  - `lateststamps.py`: Latest-stamps persistence.
  - `exceptions.py`: Project exception hierarchy.
- `test/`: `unittest`-based integration tests. These tests contact Instagram
  and some require an existing login session.
- `docs/`: Sphinx documentation sources.
- `deploy/`: Packaging and release helper scripts.

## Development Commands

Install development dependencies:

```sh
python -m pip install pipenv==2025.0.4
pipenv --python <3.x> sync --dev
```

Run the CLI locally:

```sh
pipenv run python -m instaloader --help
```

Run lint and type checks:

```sh
pipenv run pylint instaloader
pipenv run mypy -m instaloader
```

Build documentation with warnings treated as errors:

```sh
pipenv run make -C docs html SPHINXOPTS="-W -n"
```

Run the test suite:

```sh
pipenv run python -m unittest test.instaloader_unittests
```

The tests are network-dependent, can be affected by Instagram behavior and rate
limits, and some logged-in tests require a reusable session for the configured
account.

## Coding Guidelines

- Preserve Python 3.9+ compatibility. CI checks Python 3.9 through 3.14.
- Keep changes small and consistent with the current code style. The Pylint
  configuration allows lines up to 120 characters.
- Prefer typed public interfaces and maintain existing type-checking behavior.
- Avoid changing public CLI or library API behavior unless that is the explicit
  goal of the task.
- When changing CLI syntax or visible usage text, update duplicated references
  in `README.rst` and relevant files under `docs/`.
- Treat Instagram-facing behavior carefully: retries, rate control, session
  handling, and resumable downloads are user-visible and regression-prone.
- Do not commit generated files or local caches such as `__pycache__/` or
  `docs/_build/`.

## Verification Expectations

For code changes, run the narrowest relevant checks first, then broaden when the
change affects shared CLI, downloader, context, iterator, or public model
behavior. For documentation-only changes, building docs is sufficient when the
edited files participate in the Sphinx build.
