import os
import re
import subprocess
from pathlib import Path
from time import sleep

import streamlit as st
from core.utils import *
from core.st_utils.task_manager import (
    build_task_summary,
    create_task_from_upload,
    create_task_from_youtube,
    delete_task,
    detect_task_status,
    find_task_media_file,
    list_tasks,
    list_task_summaries,
    open_task_directory,
    sanitize_media_name,
    sync_task_to_workspace,
)
from translations.translations import translate as t

OUTPUT_DIR = "output"


def get_selected_task_dir() -> Path | None:
    task_dir = st.session_state.get("selected_task_dir")
    if not task_dir:
        return None
    path = Path(task_dir)
    return path if path.exists() else None


def set_selected_task(task_dir: Path):
    sync_task_to_workspace(task_dir)
    st.session_state["selected_task_dir"] = str(task_dir)


def download_video_section():
    st.header("a. Create or Select Task")
    with st.container(border=True):
        task_paths = list_tasks()
        task_map = {task_dir.name: task_dir for task_dir in task_paths}
        current_task = get_selected_task_dir()
        current_name = current_task.name if current_task else ""
        options = [""] + list(task_map.keys())
        selected_name = st.selectbox(
            "Task",
            options=options,
            index=options.index(current_name) if current_name in options else 0,
            format_func=lambda value: "Select a task" if not value else value,
        )

        if selected_name != current_name:
            if selected_name:
                set_selected_task(task_map[selected_name])
            else:
                st.session_state.pop("selected_task_dir", None)
            sleep(0.2)
            st.rerun()

        current_task = get_selected_task_dir()
        if current_task:
            summary = build_task_summary(current_task)
            status = detect_task_status(current_task)
            st.caption(f"Task: `{current_task.name}`")
            st.caption(
                f"Status: `{summary.status_label}` | Created: `{summary.created_at_display}`"
            )
            st.caption(f"Stage 1: `{status.stage1}` | Stage 2: `{status.stage2}`")
            if summary.last_error:
                st.caption(f"Last error: `{summary.last_error}`")

            media_path = status.media_path or find_task_media_file(current_task)
            if media_path:
                st.video(str(media_path))

            if st.button("Reload task files", key="reload_task_files"):
                set_selected_task(current_task)
                st.rerun()

        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            url = st.text_input(t("Enter YouTube link:"))
        with col2:
            res_dict = {"360p": "360", "1080p": "1080", "Best": "best"}
            target_res = load_key("ytb_resolution")
            res_options = list(res_dict.keys())
            default_idx = (
                list(res_dict.values()).index(target_res)
                if target_res in res_dict.values()
                else 0
            )
            res_display = st.selectbox(
                t("Resolution"), options=res_options, index=default_idx
            )
            res = res_dict[res_display]

        if st.button("Create task from YouTube", key="download_button", use_container_width=True):
            if url:
                with st.spinner("Downloading video into task workspace..."):
                    task_dir = create_task_from_youtube(url, resolution=res)
                set_selected_task(task_dir)
                st.rerun()
        uploaded_file = st.file_uploader(
            t("Or upload video"),
            type=load_key("allowed_video_formats") + load_key("allowed_audio_formats"),
        )
        if uploaded_file and st.button(
            "Create task from upload",
            key="upload_task_button",
            use_container_width=True,
        ):
            task_dir = create_task_from_upload(uploaded_file.name, uploaded_file.getbuffer())
            media_path = task_dir / "output" / sanitize_media_name(uploaded_file.name)

            if media_path.suffix.lower() in load_key("allowed_audio_formats"):
                convert_audio_to_video(str(media_path), output_dir=str(task_dir / "output"))

            set_selected_task(task_dir)
            st.rerun()

        task_summaries = list_task_summaries()
        if task_summaries:
            st.divider()
            st.subheader("Existing Tasks")
            for summary in task_summaries:
                with st.container(border=True):
                    st.markdown(f"**{summary.name}**")
                    st.caption(
                        f"Status: `{summary.status_label}` | Created: `{summary.created_at_display}`"
                    )
                    if summary.media_name:
                        st.caption(f"Media: `{summary.media_name}`")
                    if summary.last_error:
                        st.caption(f"Last error: `{summary.last_error}`")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button(
                            "Use Task",
                            key=f"use_task_{summary.name}",
                            use_container_width=True,
                        ):
                            set_selected_task(summary.task_dir)
                            st.rerun()
                    with col2:
                        if st.button(
                            "Open Folder",
                            key=f"open_task_{summary.name}",
                            use_container_width=True,
                        ):
                            try:
                                open_task_directory(summary.task_dir)
                                st.toast("Task folder opened.", icon="📂")
                            except Exception as exc:
                                st.error(f"Failed to open task folder: {exc}")
                    with col3:
                        if st.button(
                            "Delete Task",
                            key=f"delete_task_{summary.name}",
                            use_container_width=True,
                            type="primary",
                        ):
                            delete_task(summary.task_dir)
                            if (
                                st.session_state.get("selected_task_dir")
                                == str(summary.task_dir)
                            ):
                                st.session_state.pop("selected_task_dir", None)
                            st.rerun()

        return current_task is not None


def convert_audio_to_video(audio_file: str, output_dir: str = OUTPUT_DIR) -> str:
    output_video = os.path.join(output_dir, 'black_screen.mp4')
    if not os.path.exists(output_video):
        print(f"🎵➡️🎬 Converting audio to video with FFmpeg ......")
        ffmpeg_cmd = ['ffmpeg', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=640x360', '-i', audio_file, '-shortest', '-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p', output_video]
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"🎵➡️🎬 Converted <{audio_file}> to <{output_video}> with FFmpeg\n")
        # delete audio file
        os.remove(audio_file)
    return output_video
