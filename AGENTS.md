# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Repository purpose
VideoLingo is a Python-based Streamlit application for video translation, subtitle generation, and dubbing. It also includes a separate Next.js/Nextra documentation site under `docs/`.

## Key commands
- `python install.py` — recommended install path; installs Python dependencies, GPU-aware PyTorch, demucs, and checks ffmpeg.
- `python launch.py` — pre-flight check and launch helper that validates installed packages and starts Streamlit.
- `streamlit run st.py` — run the main application UI.
- `python -m pip install -r requirements.txt` — install Python dependencies manually if needed.
- `python -m pip install -e .` — install the package in editable mode for development.
- `python setup_env.py` — helper script for uv-based environment setup as described in README.
- `python setup.py install` — install the package via setuptools.
- `docker build -t videolingo .` — build the Docker image using the repository's `Dockerfile`.

### Docs site commands
- `cd docs && npm install` — install documentation dependencies.
- `cd docs && npm run dev` — run the docs site locally.
- `cd docs && npm run build` — build the docs site.
- `cd docs && npm run start` — start the built docs site.

## Architecture overview
- `st.py` is the main Streamlit entrypoint. It assembles the UI, sidebar settings, and pipeline control flow.
- `core/` contains the application logic for video processing and audio/translation workflows.
  - `core/_1_ytdlp.py` through `core/_12_dub_to_vid.py` are the sequential pipeline stages used by the app.
  - `core/asr_backend/` contains ASR engine integrations (`whisperX`, `302.ai`, local WhisperX, etc.).
  - `core/tts_backend/` contains TTS and voice synthesis integrations (Azure, OpenAI, fish-tts, GPT-SoVITS, Edge-TTS, custom TTS, etc.).
  - `core/st_utils/` contains Streamlit UI helpers, page layout, task runner, and download sections.
  - `core/utils/` contains helper utilities for configuration, model selection, error handling, and cleanup.
- `translations/` contains localized UI strings used by the app.
- `batch/` contains batch-mode helper files and documentation for scripted usage.
- `docs/` is the documentation website built with Next.js and Nextra.

## Development notes
- The repo does not appear to include a dedicated test suite or lint configuration; prioritize manual verification of app behavior.
- The main runtime is Streamlit, so changes should be validated by running `streamlit run st.py` and exercising the UI flow.
- The `install.py` installer is the repository's primary supported dependency setup path and handles GPU-specific PyTorch wheel selection.
- Use `launch.py` when diagnosing startup/package issues before editing the app.

## File conventions
- Pipeline step modules are named by stage prefix: `_1_...`, `_2_...`, etc.
- UI behavior is centralized in `st.py`; data processing is delegated to `core/` modules.
- Docs are isolated in `docs/`, so work there should generally stay separate from the Python app.

## Useful paths
- `st.py` — main application entrypoint.
- `core/` — pipeline and backend integration logic.
- `core/asr_backend/` — speech recognition backends.
- `core/tts_backend/` — text-to-speech backends.
- `docs/` — static documentation website.
- `requirements.txt`/`setup.py` — Python dependency/package configuration.
- `install.py` — installer and environment-health checks.
