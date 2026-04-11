from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from core._1_ytdlp import download_video_ytdlp
from core.utils import use_config_path

ROOT_DIR = Path(__file__).resolve().parents[2]
TASKS_ROOT = ROOT_DIR / "task"
WORKSPACE_OUTPUT_DIR = ROOT_DIR / "output"
GLOBAL_CONFIG_PATH = ROOT_DIR / "config.yaml"
TASK_CONFIG_NAME = "config.yaml"
TASK_META_NAME = "meta.json"
STAGE1_SUBTITLE_NAME = "source_subtitles.srt"
STAGE1_CLEANED_CHUNKS = Path("output/log/cleaned_chunks.xlsx")
STAGE2_REQUIRED_FILES = (Path("output/src.srt"), Path("output/trans.srt"))
MEDIA_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".flv",
    ".wmv",
    ".webm",
    ".wav",
    ".mp3",
    ".flac",
    ".m4a",
}
GENERATED_MEDIA_NAMES = {
    "output_sub.mp4",
    "output_dub.mp4",
    "black_screen.mp4",
    "dub.mp3",
    "normalized_dub.wav",
}


@dataclass
class TaskStatus:
    stage1: str
    stage2: str
    media_path: Path | None
    created_at: str = ""
    last_error: str = ""


@dataclass
class TaskSummary:
    task_dir: Path
    name: str
    created_at: str
    created_at_display: str
    media_name: str
    stage1: str
    stage2: str
    status_label: str
    last_error: str
    can_retry_stage1: bool
    can_retry_stage2: bool


def sanitize_media_name(filename: str) -> str:
    raw_name = filename.replace(" ", "_")
    stem = Path(raw_name).stem
    ext = Path(raw_name).suffix.lower()
    clean_stem = re.sub(r"[^\w\-.]", "", stem).strip("._") or "media"
    return f"{clean_stem}{ext}"


def build_task_name(filename: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    stem = Path(sanitize_media_name(filename)).stem[:40] or "task"
    return f"{now:%Y%m%d}_{stem}"


def _build_available_task_dir(tasks_root: Path, filename: str) -> Path:
    base_name = build_task_name(filename)
    task_dir = tasks_root / base_name
    suffix = 2
    while task_dir.exists():
        task_dir = tasks_root / f"{base_name}_{suffix}"
        suffix += 1
    return task_dir


def _write_task_meta(task_dir: Path, payload: dict):
    (task_dir / TASK_META_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _default_stage_meta() -> dict:
    return {
        "status": "pending",
        "updated_at": "",
        "error_msg": "",
    }


def _default_meta_payload() -> dict:
    return {
        "created_at": "",
        "source_type": "upload",
        "original_filename": "",
        "stored_filename": "",
        "stage1": _default_stage_meta(),
        "stage2": _default_stage_meta(),
        "audio": _default_stage_meta(),
    }


def _merge_meta(defaults: dict, payload: dict) -> dict:
    merged = defaults.copy()
    for key, value in payload.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _merge_meta(merged[key], value)
        else:
            merged[key] = value
    return merged


def read_task_meta(task_dir: Path) -> dict:
    defaults = _default_meta_payload()
    meta_path = task_dir / TASK_META_NAME
    if not meta_path.exists():
        return defaults

    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return _merge_meta(defaults, payload)


def write_task_meta(task_dir: Path, payload: dict):
    _write_task_meta(task_dir, _merge_meta(_default_meta_payload(), payload))


def create_task_from_upload(
    filename: str,
    data: bytes,
    tasks_root: Path = TASKS_ROOT,
    config_path: Path = GLOBAL_CONFIG_PATH,
) -> Path:
    tasks_root.mkdir(parents=True, exist_ok=True)
    task_dir = _build_available_task_dir(tasks_root, filename)
    output_dir = task_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_media_name(filename)
    (output_dir / safe_name).write_bytes(bytes(data))
    shutil.copy2(config_path, task_dir / TASK_CONFIG_NAME)
    _write_task_meta(
        task_dir,
        _merge_meta(
            _default_meta_payload(),
            {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_type": "upload",
            "original_filename": filename,
            "stored_filename": safe_name,
            },
        ),
    )
    return task_dir


def create_task_from_youtube(
    url: str,
    resolution: str,
    tasks_root: Path = TASKS_ROOT,
    config_path: Path = GLOBAL_CONFIG_PATH,
) -> Path:
    tasks_root.mkdir(parents=True, exist_ok=True)
    task_dir = _build_available_task_dir(tasks_root, "youtube_task.mp4")
    output_dir = task_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(config_path, task_dir / TASK_CONFIG_NAME)
    _write_task_meta(
        task_dir,
        _merge_meta(
            _default_meta_payload(),
            {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_type": "youtube",
            "url": url,
            "resolution": resolution,
            },
        ),
    )
    download_video_ytdlp(url, save_path=str(output_dir), resolution=resolution)
    return task_dir


def list_tasks(tasks_root: Path = TASKS_ROOT) -> list[Path]:
    if not tasks_root.exists():
        return []
    return sorted([path for path in tasks_root.iterdir() if path.is_dir()], reverse=True)


def get_task_output_dir(task_dir: Path) -> Path:
    return task_dir / "output"


def get_task_config_path(task_dir: Path) -> Path:
    return task_dir / TASK_CONFIG_NAME


def find_task_media_file(task_dir: Path) -> Path | None:
    output_dir = get_task_output_dir(task_dir)
    if not output_dir.exists():
        return None

    fallback_media = None
    for file_path in sorted(output_dir.iterdir()):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        if file_path.name in GENERATED_MEDIA_NAMES:
            if file_path.name == "black_screen.mp4":
                fallback_media = file_path
            continue
        return file_path
    return fallback_media


def detect_task_status(task_dir: Path) -> TaskStatus:
    output_dir = get_task_output_dir(task_dir)
    meta = read_task_meta(task_dir)
    stage1_ready = (
        (output_dir / "log" / "cleaned_chunks.xlsx").exists()
        and (output_dir / STAGE1_SUBTITLE_NAME).exists()
    )
    stage2_ready = all((output_dir / rel_path.name).exists() for rel_path in STAGE2_REQUIRED_FILES)
    stage1 = "completed" if stage1_ready else meta["stage1"]["status"]
    stage2 = "completed" if stage2_ready else meta["stage2"]["status"]
    last_error = meta["stage2"]["error_msg"] or meta["stage1"]["error_msg"] or ""
    return TaskStatus(
        stage1=stage1,
        stage2=stage2,
        media_path=find_task_media_file(task_dir),
        created_at=meta.get("created_at", ""),
        last_error=last_error,
    )


def _replace_directory(src: Path, dst: Path):
    if dst.exists() or dst.is_symlink():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()

    if src.exists():
        shutil.copytree(src, dst)
    else:
        dst.mkdir(parents=True, exist_ok=True)


def sync_task_to_workspace(
    task_dir: Path,
    workspace_output: Path = WORKSPACE_OUTPUT_DIR,
):
    _replace_directory(get_task_output_dir(task_dir), workspace_output)


def sync_workspace_to_task(
    task_dir: Path,
    workspace_output: Path = WORKSPACE_OUTPUT_DIR,
):
    _replace_directory(workspace_output, get_task_output_dir(task_dir))


def _safe_remove(path: Path):
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def mark_task_stage(
    task_dir: Path,
    stage: str,
    status: str,
    error_msg: str = "",
):
    meta = read_task_meta(task_dir)
    meta[stage]["status"] = status
    meta[stage]["updated_at"] = datetime.now().isoformat(timespec="seconds")
    meta[stage]["error_msg"] = error_msg
    if status == "completed":
        meta[stage]["error_msg"] = ""
    write_task_meta(task_dir, meta)


def _reset_stage_meta(meta: dict, stage: str):
    meta[stage] = _default_stage_meta()


def prepare_stage_retry(task_dir: Path, stage: str):
    output_dir = get_task_output_dir(task_dir)

    if stage == "stage1":
        media_path = find_task_media_file(task_dir)
        keep_names = {media_path.name} if media_path else set()
        for item in list(output_dir.iterdir()):
            if item.name in keep_names:
                continue
            _safe_remove(item)
    elif stage == "stage2":
        removable = [
            output_dir / "src.srt",
            output_dir / "trans.srt",
            output_dir / "src_trans.srt",
            output_dir / "trans_src.srt",
            output_dir / "output_sub.mp4",
            output_dir / "gpt_log",
            output_dir / "dub.srt",
            output_dir / "output_dub.mp4",
        ]
        for path in removable:
            _safe_remove(path)
    else:
        raise ValueError(f"Unsupported stage: {stage}")

    meta = read_task_meta(task_dir)
    _reset_stage_meta(meta, stage)
    if stage == "stage1":
        _reset_stage_meta(meta, "stage2")
        _reset_stage_meta(meta, "audio")
    write_task_meta(task_dir, meta)


def delete_task(task_dir: Path):
    shutil.rmtree(task_dir, ignore_errors=True)


def _parse_created_at(created_at: str, fallback_name: str) -> datetime | None:
    if created_at:
        try:
            return datetime.fromisoformat(created_at)
        except ValueError:
            pass
    try:
        return datetime.strptime(fallback_name[:15], "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _format_created_at(created_at: str, fallback_name: str) -> str:
    parsed = _parse_created_at(created_at, fallback_name)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else "-"


def _get_status_label(stage1: str, stage2: str) -> str:
    if stage2 == "completed":
        return "Stage 2 completed"
    if stage2 == "failed":
        return "Stage 2 failed"
    if stage2 == "stopped":
        return "Stage 2 stopped"
    if stage2 == "running":
        return "Stage 2 running"
    if stage1 == "completed":
        return "Stage 1 completed"
    if stage1 == "failed":
        return "Stage 1 failed"
    if stage1 == "stopped":
        return "Stage 1 stopped"
    if stage1 == "running":
        return "Stage 1 running"
    return "Pending"


def build_task_summary(task_dir: Path) -> TaskSummary:
    meta = read_task_meta(task_dir)
    status = detect_task_status(task_dir)
    media_path = status.media_path
    return TaskSummary(
        task_dir=task_dir,
        name=task_dir.name,
        created_at=meta.get("created_at", ""),
        created_at_display=_format_created_at(meta.get("created_at", ""), task_dir.name),
        media_name=media_path.name if media_path else meta.get("stored_filename", ""),
        stage1=status.stage1,
        stage2=status.stage2,
        status_label=_get_status_label(status.stage1, status.stage2),
        last_error=status.last_error,
        can_retry_stage1=status.stage1 in ("failed", "stopped"),
        can_retry_stage2=status.stage2 in ("failed", "stopped"),
    )


def list_task_summaries(tasks_root: Path = TASKS_ROOT) -> list[TaskSummary]:
    return [build_task_summary(task_dir) for task_dir in list_tasks(tasks_root)]


def open_task_directory(task_dir: Path):
    if platform.system() == "Darwin":
        subprocess.run(["open", str(task_dir)], check=True)
    elif platform.system() == "Windows":
        os.startfile(str(task_dir))  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", str(task_dir)], check=True)


def format_srt_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole_seconds = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))

    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    if whole_seconds == 60:
        minutes += 1
        whole_seconds = 0
    if minutes == 60:
        hours += 1
        minutes = 0

    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def export_stage1_source_subtitles(output_dir: Path = WORKSPACE_OUTPUT_DIR) -> Path:
    cleaned_chunks_path = output_dir / "log" / "cleaned_chunks.xlsx"
    subtitle_path = output_dir / STAGE1_SUBTITLE_NAME
    df = pd.read_excel(cleaned_chunks_path)

    entries = []
    for index, row in df.iterrows():
        text = str(row["text"]).strip().strip('"').strip()
        if not text:
            continue
        start = format_srt_timestamp(float(row["start"]))
        end = format_srt_timestamp(float(row["end"]))
        entries.append(f"{len(entries) + 1}\n{start} --> {end}\n{text}\n")

    subtitle_path.write_text("\n".join(entries).strip() + "\n", encoding="utf-8")
    return subtitle_path


def bind_task_step(task_dir: Path, func: Callable) -> Callable:
    def wrapped():
        with use_config_path(get_task_config_path(task_dir)):
            func()

    return wrapped


def bind_task_steps(task_dir: Path, steps: list[tuple[str, Callable]]) -> list[tuple[str, Callable]]:
    return [(label, bind_task_step(task_dir, func)) for label, func in steps]
