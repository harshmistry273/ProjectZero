# app.py — Simple TTS app: refresh page after IVC creation (no polling)
import streamlit as st
import requests
import pathlib
import uuid
import os
from typing import List, Dict

# Adjust imports to your project
from core.config import settings
from services.elevenlabs import ElevenLabsManager  # <-- change to your module

# Directories
SAMPLES_DIR = pathlib.Path("data/voicesamples")
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR = pathlib.Path("outputs/tts")
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="TTS App", layout="centered")
st.title("TTS App")

# ------------------ Helpers ------------------
def fetch_voices_from_api(timeout: int = 8) -> List[Dict]:
    resp = requests.get(settings.ELEVENLABS_LIST_VOICES_URL, headers={"xi-api-key": settings.ELEVENLABS_API_KEY}, timeout=timeout)
    resp.raise_for_status()
    return resp.json().get("voices", [])

def fetch_voices(force: bool = False) -> List[Dict]:
    if not force and st.session_state.get("voices_cached"):
        return st.session_state["voices_cached"]
    try:
        voices = fetch_voices_from_api()
        st.session_state["voices_cached"] = voices
        return voices
    except Exception as e:
        st.session_state["voices_cached"] = []
        st.warning(f"Failed to fetch voices: {e}")
        return []

def safe_filename(orig_name: str) -> str:
    return f"{uuid.uuid4().hex}_{orig_name}"

# ------------------ SIDEBAR ------------------
with st.sidebar:
    st.header("Voice Picker")

    # manual refresh button
    if st.button("Refresh voices"):
        st.session_state.pop("voices_cached", None)
        fetch_voices(force=True)
        st.rerun()

    # load voices (cached unless forced)
    voices = fetch_voices(force=False)

    if voices:
        voice_map = { (v.get("name") or v.get("voice_id")): v.get("voice_id") for v in voices }
        selected_name = st.selectbox("Choose voice", options=list(voice_map.keys()))
        st.session_state["voice_id"] = voice_map[selected_name]
        st.caption(f"Selected ID: {st.session_state['voice_id']}")
    else:
        st.info("No voices found. Check API key.")
        st.session_state["voice_id"] = None

    # Core expander (upload/create voice)
    with st.expander("Core — Add Voice (upload sample)"):
        st.markdown("Upload an MP3 voice sample and create an instant voice clone (IVC). After creation the page will refresh.")
        uploaded = st.file_uploader("Upload MP3 (voice sample)", type=["mp3"], accept_multiple_files=False, key="ivc_uploader")
        voice_name_input = st.text_input("Voice name (optional)", value="", key="ivc_name")

        if st.button("Create Voice from Sample"):
            if not uploaded:
                st.error("Please upload an MP3 file first.")
            else:
                try:
                    orig_name = uploaded.name or "sample.mp3"
                    filename = safe_filename(orig_name)
                    saved_path = str(SAMPLES_DIR / filename)

                    # Save uploaded file
                    with open(saved_path, "wb") as out_f:
                        out_f.write(uploaded.read())

                    st.success(f"Saved sample to `{saved_path}`")

                    # Create voice
                    voice_name = voice_name_input.strip() or f"user_voice_{uuid.uuid4().hex[:6]}"
                    st.info("Creating instant voice clone...")

                    new_voice_id = ElevenLabsManager.create_instant_voice_clone(input_voice_file_path=saved_path, voice_name=voice_name)

                    if new_voice_id and new_voice_id != "Failed to create voice":
                        st.success(f"Voice created! Voice ID: `{new_voice_id}`")

                        # Force refresh voices cache and reload the page so the new voice appears
                        st.session_state.pop("voices_cached", None)
                        try:
                            # Try one immediate refresh (may or may not show up depending on ElevenLabs indexing)
                            fetch_voices(force=True)
                        except Exception:
                            # ignore; we'll rerun anyway
                            pass

                        # Rerun the app to rebuild sidebar and selectbox with fresh voices
                        st.rerun()
                    else:
                        st.error(f"Failed to create voice. Manager returned: {new_voice_id}")

                except Exception as e:
                    st.error(f"Failed to save or create voice: {e}")

# ------------------ MAIN (Convert & Save only) ------------------
st.markdown("## Text → Speech (Save + Preview + Download)")
text = st.text_area("Enter text to convert", height=160, placeholder="Type something to convert to speech...")

if st.button("Convert & Save"):
    voice_id = st.session_state.get("voice_id")
    if not voice_id:
        st.error("Please select a voice from the sidebar.")
    elif not text or not text.strip():
        st.error("Please enter some text.")
    else:
        st.info("Generating and saving MP3 (using convert_and_save_text_to_speech)...")
        try:
            saved_path = ElevenLabsManager.convert_and_save_text_to_speech(text=text, voice_id=voice_id)
        except Exception as e:
            saved_path = ""
            st.error(f"Error during TTS generation: {e}")

        if saved_path and saved_path.endswith(".mp3") and os.path.exists(saved_path):
            st.success("Audio generated and saved!")

            # Preview
            try:
                st.audio(saved_path, format="audio/mp3")
            except Exception:
                st.write("Preview not available in this environment.")

            # Download saved file
            try:
                with open(saved_path, "rb") as f:
                    bytes_data = f.read()
                filename = os.path.basename(saved_path)
                st.download_button(
                    label="Download MP3 (saved file)",
                    data=bytes_data,
                    file_name=filename,
                    mime="audio/mpeg",
                )
            except Exception as e:
                st.error(f"Could not create download button: {e}")
        else:
            st.error("Failed to generate or save audio. Check logs for errors.")

# ------------------ Footer ------------------
st.markdown("---")
