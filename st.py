import streamlit as st
import os, sys, time
from core.st_utils.imports_and_utils import *
from core.st_utils.download_video_section import get_selected_task_dir
from core.st_utils.task_runner import TaskRunner
from core.st_utils.task_manager import (
    STAGE1_SUBTITLE_NAME,
    bind_task_steps,
    detect_task_status,
    export_stage1_source_subtitles,
    mark_task_stage,
    prepare_stage_retry,
    sync_task_to_workspace,
    sync_workspace_to_task,
)
from core import *

# SET PATH
current_dir = os.path.dirname(os.path.abspath(__file__))
os.environ["PATH"] += os.pathsep + current_dir
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

st.set_page_config(page_title="VideoLingo", page_icon="docs/logo.svg")

SUB_VIDEO = "output/output_sub.mp4"
DUB_VIDEO = "output/output_dub.mp4"
STAGE1_SOURCE_SUBTITLE = os.path.join("output", STAGE1_SUBTITLE_NAME)


# ─── Task control UI (auto-refreshes every 1s while task is active) ───


@st.fragment(run_every=1)
def _task_control_panel(runner_key: str):
    """Renders progress bar + pause/stop buttons. Auto-refreshes every 1s."""
    runner = TaskRunner.get(st.session_state, runner_key)

    if runner.state == "idle":
        return

    # Progress
    step_text = (
        f"({runner.current_step + 1}/{runner.total_steps}) {runner.current_label}"
        if runner.current_step >= 0
        else ""
    )

    if runner.is_active:
        if runner.state == "paused":
            st.warning(f"⏸️ {t('Paused')} {step_text}")
        else:
            st.info(f"⏳ {t('Running...')} {step_text}")
        st.progress(runner.progress)

        # Control buttons
        col1, col2 = st.columns(2)
        with col1:
            if runner.state == "paused":
                if st.button(
                    f"▶️ {t('Resume')}",
                    key=f"{runner_key}_resume",
                    use_container_width=True,
                ):
                    runner.resume()
                    st.rerun()
            else:
                if st.button(
                    f"⏸️ {t('Pause')}",
                    key=f"{runner_key}_pause",
                    use_container_width=True,
                ):
                    runner.pause()
                    st.rerun()
        with col2:
            if st.button(
                f"⏹️ {t('Stop')}",
                key=f"{runner_key}_stop",
                use_container_width=True,
                type="primary",
            ):
                runner.stop()
                st.rerun()

    elif runner.state == "completed":
        st.success(t("Task completed!"))
        st.progress(1.0)
        runner.reset()
        time.sleep(0.5)
        st.rerun(scope="app")

    elif runner.state == "stopped":
        st.warning(f"⏹️ {t('Task stopped')} {step_text}")
        if st.button(t("OK"), key=f"{runner_key}_ack_stop", use_container_width=True):
            runner.reset()
            st.rerun(scope="app")

    elif runner.state == "error":
        st.error(f"❌ {t('Task error')}: {runner.error_msg}")
        if st.button(t("OK"), key=f"{runner_key}_ack_error", use_container_width=True):
            runner.reset()
            st.rerun(scope="app")


# ─── Text processing ───


def _get_text_steps():
    """Return the subtitle processing steps as (label, callable) list."""
    steps = [
        (t("WhisperX word-level transcription"), _2_asr.transcribe),
        (
            t("Sentence segmentation using NLP and LLM"),
            lambda: (
                _3_1_split_nlp.split_by_spacy(),
                _3_2_split_meaning.split_sentences_by_meaning(),
            ),
        ),
        (
            t("Summarization and multi-step translation"),
            lambda: (_4_1_summarize.get_summary(), _4_2_translate.translate_all()),
        ),
        (
            t("Cutting and aligning long subtitles"),
            lambda: (
                _5_split_sub.split_for_sub_main(),
                _6_gen_sub.align_timestamp_main(),
            ),
        ),
        (
            t("Merging subtitles into the video"),
            _7_sub_into_vid.merge_subtitles_to_video,
        ),
    ]
    return steps


def _get_stage1_steps():
    return [
        (t("WhisperX word-level transcription"), _2_asr.transcribe),
        ("Export source subtitles", lambda: export_stage1_source_subtitles()),
    ]


def _get_stage2_steps():
    return [
        (
            t("Sentence segmentation using NLP and LLM"),
            lambda: (
                _3_1_split_nlp.split_by_spacy(),
                _3_2_split_meaning.split_sentences_by_meaning(),
            ),
        ),
        (
            t("Summarization and multi-step translation"),
            lambda: (_4_1_summarize.get_summary(), _4_2_translate.translate_all()),
        ),
        (
            t("Cutting and aligning long subtitles"),
            lambda: (
                _5_split_sub.split_for_sub_main(),
                _6_gen_sub.align_timestamp_main(),
            ),
        ),
        (
            t("Merging subtitles into the video"),
            _7_sub_into_vid.merge_subtitles_to_video,
        ),
    ]


def _start_task_runner(runner_key: str, task_dir: str, stage_name: str, steps):
    runner = TaskRunner.get(st.session_state, runner_key)
    runner.start(
        bind_task_steps(task_dir, steps),
        before_run=lambda: (
            mark_task_stage(task_dir, stage_name, "running"),
            sync_task_to_workspace(task_dir),
        ),
        cleanup_run=lambda: sync_workspace_to_task(task_dir),
        on_success=lambda: mark_task_stage(task_dir, stage_name, "completed"),
        on_error=lambda exc: mark_task_stage(
            task_dir, stage_name, "failed", error_msg=str(exc)
        ),
        on_stopped=lambda: mark_task_stage(task_dir, stage_name, "stopped"),
    )


def text_processing_section():
    st.header("b. Subtitle Workflow")
    task_dir = get_selected_task_dir()

    if not task_dir:
        st.info("Create or select a task first.")
        return False

    status = detect_task_status(task_dir)
    stage1_runner = TaskRunner.get(st.session_state, "_stage1_runner")
    stage2_runner = TaskRunner.get(st.session_state, "_stage2_runner")

    with st.container(border=True):
        st.subheader("Stage 1: ASR and source subtitles")
        st.markdown(
            """
        1. Extract audio from the current task media
        2. Run WhisperX transcription
        3. Export a source subtitle file for handoff
        """
        )

        if status.stage1 == "completed":
            st.success("Stage 1 completed. The task is ready for Stage 2 on this or another machine.")
            if os.path.exists(STAGE1_SOURCE_SUBTITLE):
                with open(STAGE1_SOURCE_SUBTITLE, "rb") as subtitle_file:
                    st.download_button(
                        "Download Stage 1 subtitles",
                        data=subtitle_file.read(),
                        file_name=STAGE1_SUBTITLE_NAME,
                        mime="application/x-subrip",
                    )
        elif stage1_runner.is_active or stage1_runner.is_done:
            _task_control_panel("_stage1_runner")
        else:
            stage1_label = "Retry Stage 1" if status.stage1 in ("failed", "stopped") else "Start Stage 1"
            if st.button(stage1_label, key="stage1_processing_button"):
                if status.stage1 in ("failed", "stopped"):
                    prepare_stage_retry(task_dir, "stage1")
                _start_task_runner("_stage1_runner", task_dir, "stage1", _get_stage1_steps())
                st.rerun()

        st.divider()
        st.subheader("Stage 2: AI refinement and final subtitles")
        st.markdown(
            f"""
        1. {t("Sentence segmentation using NLP and LLM")}
        2. {t("Summarization and multi-step translation")}
        3. {t("Cutting and aligning long subtitles")}
        4. {t("Merging subtitles into the video")}
        """
        )

        if status.stage1 != "completed":
            st.info("Stage 2 will unlock after Stage 1 produces the source subtitle files.")
        elif status.stage2 == "completed":
            st.success("Stage 2 completed.")
            if os.path.exists(SUB_VIDEO):
                st.video(SUB_VIDEO)
            download_subtitle_zip_button(text=t("Download All Srt Files"))
        elif stage2_runner.is_active or stage2_runner.is_done:
            _task_control_panel("_stage2_runner")
        else:
            stage2_label = "Retry Stage 2" if status.stage2 in ("failed", "stopped") else "Start Stage 2"
            if st.button(stage2_label, key="stage2_processing_button"):
                if status.stage2 in ("failed", "stopped"):
                    prepare_stage_retry(task_dir, "stage2")
                _start_task_runner("_stage2_runner", task_dir, "stage2", _get_stage2_steps())
                st.rerun()
        return True


# ─── Audio processing ───


def _get_audio_steps():
    """Return the audio/dubbing processing steps as (label, callable) list."""
    steps = [
        (
            t("Generate audio tasks and chunks"),
            lambda: (
                _8_1_audio_task.gen_audio_task_main(),
                _8_2_dub_chunks.gen_dub_chunks(),
            ),
        ),
        (t("Extract reference audio"), _9_refer_audio.extract_refer_audio_main),
        (t("Generate and merge audio files"), _10_gen_audio.gen_audio),
        (t("Merge full audio"), _11_merge_audio.merge_full_audio),
        (t("Merge final audio into video"), _12_dub_to_vid.merge_video_audio),
    ]
    return steps


def audio_processing_section():
    st.header(t("c. Dubbing"))
    task_dir = get_selected_task_dir()
    runner = TaskRunner.get(st.session_state, "_audio_runner")

    if not task_dir:
        st.info("Create or select a task first.")
        return

    with st.container(border=True):
        st.markdown(
            f"""
        <p style='font-size: 20px;'>
        {t("This stage includes the following steps:")}
        <p style='font-size: 20px;'>
            1. {t("Generate audio tasks and chunks")}<br>
            2. {t("Extract reference audio")}<br>
            3. {t("Generate and merge audio files")}<br>
            4. {t("Merge final audio into video")}
        """,
            unsafe_allow_html=True,
        )

        if not os.path.exists(DUB_VIDEO):
            if runner.is_active:
                _task_control_panel("_audio_runner")
            elif runner.is_done:
                _task_control_panel("_audio_runner")
            else:
                if st.button(
                    t("Start Audio Processing"), key="audio_processing_button"
                ):
                    steps = _get_audio_steps()
                    _start_task_runner("_audio_runner", task_dir, "audio", steps)
                    st.rerun()
        else:
            st.success(
                t(
                    "Audio processing is complete! You can check the audio files in the `output` folder."
                )
            )
            if load_key("burn_subtitles"):
                st.video(DUB_VIDEO)
            if st.button(t("Delete dubbing files"), key="delete_dubbing_files"):
                delete_dubbing_files()
                st.rerun()
            if st.button(t("Archive to 'history'"), key="cleanup_in_audio_processing"):
                cleanup()
                st.rerun()


# ─── Main ───


def main():
    logo_col, _ = st.columns([1, 1])
    with logo_col:
        st.image("docs/logo.png", width="stretch")
    st.markdown(button_style, unsafe_allow_html=True)
    welcome_text = t(
        'Hello, welcome to VideoLingo. If you encounter any issues, feel free to get instant answers with our Free QA Agent <a href="https://share.fastgpt.in/chat/share?shareId=066w11n3r9aq6879r4z0v9rh" target="_blank">here</a>! You can also try out our SaaS website at <a href="https://videolingo.io" target="_blank">videolingo.io</a> for free!'
    )
    st.markdown(
        f"<p style='font-size: 20px; color: #808080;'>{welcome_text}</p>",
        unsafe_allow_html=True,
    )
    # add settings
    with st.sidebar:
        page_setting()
        st.markdown(give_star_button, unsafe_allow_html=True)
    download_video_section()
    text_processing_section()
    audio_processing_section()


if __name__ == "__main__":
    main()
