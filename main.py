# app.py — Full Streamlit app (fixed duplicate keys, single-file IVC upload, multi-segment TTS)
import streamlit as st
import requests
import pathlib
import uuid
import os
import zipfile
from typing import List, Dict, Optional

# Update these imports to match your project structure
from core.config import settings
from services.elevenlabs import ElevenLabsManager  # <-- ensure this path is correct

# Directories
SAMPLES_DIR = pathlib.Path("data/voicesamples")
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR = pathlib.Path("outputs/tts")
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Multi-Speaker TTS + Single-file IVC", layout="wide")
st.title("Multi-Speaker TTS ")

# Try to import pydub for merging; fallback to ZIP if unavailable
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except Exception:
    PYDUB_AVAILABLE = False

# ---------------- Helpers ----------------
def fetch_voices() -> List[Dict]:
    """Fetch voices from ElevenLabs and cache in session state."""
    try:
        resp = requests.get(settings.ELEVENLABS_LIST_VOICES_URL, headers={"xi-api-key": settings.ELEVENLABS_API_KEY}, timeout=8)
        resp.raise_for_status()
        voices = resp.json().get("voices", [])
        st.session_state["voices_cached"] = voices
        return voices
    except Exception as e:
        st.warning(f"Failed to fetch voices: {e}")
        return st.session_state.get("voices_cached", [])

def safe_filename(orig_name: str) -> str:
    return f"{uuid.uuid4().hex}_{orig_name}"

def new_segment_template():
    return {"id": uuid.uuid4().hex, "text": "", "voice_id": None, "voice_label": "Choose voice"}

def ensure_segments():
    if "segments" not in st.session_state:
        st.session_state["segments"] = [ new_segment_template() ]

# initialize segments and caches
ensure_segments()
voices = st.session_state.get("voices_cached") or fetch_voices()
voice_map = [((v.get("name") or v.get("voice_id")), v.get("voice_id")) for v in (voices or [])]

# ---------------- Sidebar: Upload voice (single file only) + quick actions ----------------
with st.sidebar:
    st.header("Actions & Single-file IVC Upload")

    if st.button("Refresh voices", key="refresh_voices"):
        st.session_state.pop("voices_cached", None)
        fetch_voices()
        st.rerun()

    st.markdown("---")
    st.subheader("Upload ONE sample → Create cloned voice")
    st.markdown("Upload **exactly one** MP3/WAV file. If you upload more than one, the app will show an error.")

    # file_uploader can't force single-file, so we accept multiple and validate
    uploaded_files = st.file_uploader(
        "Upload a single sample (mp3/wav)",
        type=["mp3", "wav"],
        accept_multiple_files=True,
        key="upload_ivc_single"
    )

    # Unique key for the text input (fixes duplicate key error)
    ivc_voice_name = st.text_input("Voice name (optional)", value="", key="ivc_voice_name_single")

    if st.button("Create cloned voice (single file)", key="create_cloned_voice_single"):
        # Validation: exactly one file
        if not uploaded_files:
            st.error("Please upload one audio file.")
            st.stop()

        if len(uploaded_files) > 1:
            st.error("❌ Only ONE file is allowed. Remove additional files and try again.")
            st.stop()

        up = uploaded_files[0]
        try:
            orig_name = up.name or "sample"
            fname = safe_filename(orig_name)
            saved_path = str(SAMPLES_DIR / fname)
            with open(saved_path, "wb") as out_f:
                out_f.write(up.read())
            st.success(f"Saved sample: `{saved_path}`")
        except Exception as e:
            st.error(f"Failed to save uploaded file: {e}")
            st.stop()

        # Create IVC using single saved file
        voice_name = ivc_voice_name.strip() or f"user_voice_{uuid.uuid4().hex[:6]}"
        st.info("Creating cloned voice (this may take a moment)...")
        try:
            new_vid = ElevenLabsManager.create_instant_voice_clone(
                input_voice_file_path=saved_path,  # single file path
                voice_name=voice_name
            )
            if new_vid and new_vid != "Failed to create voice":
                st.success(f"🎉 Voice created! Voice ID: `{new_vid}`")
                # Refresh voice list and rerun to show new voice in selectors
                st.session_state.pop("voices_cached", None)
                fetch_voices()
                st.rerun()
            else:
                st.error(f"Failed to create voice. Returned: {new_vid}")
        except Exception as e:
            st.error(f"Error creating voice: {e}")

    st.markdown("---")
    st.subheader("Quick segment actions")
    if st.button("Add segment", key="add_segment"):
        st.session_state["segments"].append(new_segment_template())
        st.rerun()
    if st.button("Clear segments", key="clear_segments"):
        st.session_state["segments"] = [ new_segment_template() ]
        st.rerun()

# ---------------- Main: multi-segment editor ----------------
st.markdown("## Script segments (each segment = text + voice)")

segments = st.session_state["segments"]

# Render editable segments
for idx, seg in enumerate(list(segments)):  # list() to avoid iteration issues when removing
    st.markdown(f"### Segment {idx+1}")
    cols = st.columns([6,2,1])
    with cols[0]:
        seg_text = st.text_area(f"Text (segment {idx+1})", value=seg.get("text",""), key=f"text_{seg['id']}", height=120)
    with cols[1]:
        if voice_map:
            labels = [v[0] for v in voice_map]
            try:
                selected_index = labels.index(seg.get("voice_label")) if seg.get("voice_label") in labels else 0
            except Exception:
                selected_index = 0
            choice = st.selectbox(f"Voice (segment {idx+1})", options=labels, index=selected_index, key=f"voice_{seg['id']}")
            seg["voice_label"] = choice
            seg["voice_id"] = next((v[1] for v in voice_map if v[0]==choice), None)
            if seg.get("voice_id"):
                st.caption(f"voice_id: {seg.get('voice_id')}")
        else:
            st.info("No voices available. Click 'Refresh voices' in the sidebar.")
    with cols[2]:
        if st.button("Remove", key=f"remove_{seg['id']}"):
            st.session_state["segments"].pop(idx)
            st.rerun()
    seg["text"] = seg_text

st.markdown("---")

# ---------------- Generation controls ----------------
st.markdown("## Generate audio for script")
gen_cols = st.columns([1,1,1,1])

num_segments = len(st.session_state["segments"])

# ---------------- BUTTON 1: Generate Segments ----------------
with gen_cols[0]:
    if num_segments < 1:
        st.warning("No segments to generate.")
    else:
        if st.button("Generate segments (save each)", key="generate_segments"):
            missing = [i+1 for i,s in enumerate(segments) if not s.get("text","").strip() or not s.get("voice_id")]
            if missing:
                st.error(f"Segments missing text/voice: {missing}")
            else:
                st.info("Generating each segment...")
                generated = []
                errors = []
                for i, s in enumerate(segments):
                    try:
                        out_path = ElevenLabsManager.convert_and_save_text_to_speech(
                            text=s["text"],
                            voice_id=s["voice_id"],
                            out_dir=str(OUTPUTS_DIR)
                        )
                        if out_path and os.path.exists(out_path):
                            generated.append(out_path)
                        else:
                            errors.append(f"Segment {i+1} generation failed.")
                    except Exception as e:
                        errors.append(f"Segment {i+1} error: {e}")

                st.session_state["last_generated_files"] = generated

                if generated:
                    st.success(f"Generated {len(generated)} file(s).")
                if errors:
                    for e in errors:
                        st.warning(e)

# ---------------- BUTTON 2: Generate & Merge ----------------
with gen_cols[1]:
    if num_segments < 2:
        st.button("Generate & Merge into one MP3", disabled=True, key="generate_merge_disabled")
        st.caption("Add 2 or more segments to enable merging.")
    else:
        if st.button("Generate & Merge into one MP3", key="generate_merge"):
            missing = [i+1 for i,s in enumerate(segments) if not s.get("text","").strip() or not s.get("voice_id")]
            if missing:
                st.error(f"Segments missing text/voice: {missing}")
            else:
                st.info("Generating and merging segments...")
                generated = []
                errors = []
                for i, s in enumerate(segments):
                    try:
                        out_path = ElevenLabsManager.convert_and_save_text_to_speech(
                            text=s["text"],
                            voice_id=s["voice_id"],
                            out_dir=str(OUTPUTS_DIR)
                        )
                        if out_path and os.path.exists(out_path):
                            generated.append(out_path)
                        else:
                            errors.append(f"Segment {i+1} generation failed.")
                    except Exception as e:
                        errors.append(f"Segment {i+1} error: {e}")

                st.session_state["last_generated_files"] = generated

                if errors:
                    for e in errors:
                        st.warning(e)

                if not generated:
                    st.error("No generated files to merge.")
                else:
                    merged_path = ""
                    if PYDUB_AVAILABLE:
                        try:
                            combined = None
                            for fpath in generated:
                                seg_audio = AudioSegment.from_file(fpath, format="mp3")
                                if combined is None:
                                    combined = seg_audio
                                else:
                                    combined += AudioSegment.silent(duration=300)
                                    combined += seg_audio
                            merged_filename = f"merged_{uuid.uuid4().hex}.mp3"
                            merged_path = str(OUTPUTS_DIR / merged_filename)
                            combined.export(merged_path, format="mp3")
                            st.success(f"Merged saved to: {merged_path}")
                            st.session_state["last_merged"] = merged_path
                        except Exception as e:
                            st.warning(f"Merging failed (pydub/ffmpeg issue): {e}")
                            merged_path = ""
                    else:
                        st.info("pydub not available — creating ZIP of individual MP3s instead.")
                        merged_path = ""

                    if merged_path and os.path.exists(merged_path):
                        st.audio(merged_path, format="audio/mp3")
                        with open(merged_path, "rb") as f:
                            st.download_button("Download merged MP3", data=f.read(), file_name=os.path.basename(merged_path), mime="audio/mpeg", key=f"download_merged_{uuid.uuid4().hex}")
                    else:
                        # ZIP fallback
                        zip_name = f"segments_{uuid.uuid4().hex}.zip"
                        zip_path = str(OUTPUTS_DIR / zip_name)
                        try:
                            with zipfile.ZipFile(zip_path, "w") as z:
                                for f in generated:
                                    z.write(f, arcname=os.path.basename(f))
                            st.success(f"Created ZIP: {zip_path}")
                            with open(zip_path, "rb") as f:
                                st.download_button("Download ZIP of segments", data=f.read(), file_name=os.path.basename(zip_path), mime="application/zip", key=f"download_zip_{uuid.uuid4().hex}")
                            st.session_state["last_zip"] = zip_path
                        except Exception as e:
                            st.error(f"Failed to create ZIP: {e}")

# ---------------- BUTTON 3: Play preview ----------------
with gen_cols[2]:
    if st.button("Play generated segments sequentially", key="play_generated"):
        files = st.session_state.get("last_generated_files", [])
        if not files:
            st.info("No generated files found. Click 'Generate segments' first.")
        else:
            st.write("Playing segments one by one:")
            for f in files:
                st.markdown(f"**{os.path.basename(f)}**")
                try:
                    st.audio(f, format="audio/mp3")
                except Exception:
                    st.write("Preview not available in this environment.")

with gen_cols[3]:
    if st.button("Show last generated files", key="show_last_generated"):
        files = st.session_state.get("last_generated_files", [])
        if not files:
            st.info("No generated files yet.")
        else:
            st.write("Last generated files:")
            for f in files:
                st.write(f"- {f}")

st.markdown("---")

