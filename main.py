"""
Simplified Multi-Speaker TTS Streamlit App with Supabase Authentication and Usage Limits
"""

import streamlit as st
import requests
import pathlib
import uuid
import os
import zipfile
from typing import List, Dict, Optional
from datetime import datetime
from supabase import create_client, Client

# Import your project modules
from core.config import settings
from services.elevenlabs import ElevenLabsManager

# Try importing pydub for audio merging
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

# ============================================================================
# CONFIGURATION
# ============================================================================

SAMPLES_DIR = pathlib.Path("data/voicesamples")
OUTPUTS_DIR = pathlib.Path("outputs/tts")
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# Usage limits
MAX_VOICES_PER_USER = 1
MAX_GENERATIONS_PER_USER = 5

st.set_page_config(page_title="Multi-Speaker TTS", layout="wide", initial_sidebar_state="expanded")

# ============================================================================
# SUPABASE SETUP
# ============================================================================

SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_KEY = settings.SUPABASE_ANON

def get_supabase_client() -> Optional[Client]:
    """Initialize and return Supabase client"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Failed to connect to Supabase: {e}")
        return None

# ============================================================================
# DATABASE FUNCTIONS FOR USER VOICES
# ============================================================================

def get_user_voice_count(user_id: str) -> int:
    """Get count of voices created by user"""
    supabase = get_supabase_client()
    if not supabase:
        return 0
    
    try:
        response = supabase.table("user_voices").select("id", count="exact").eq("user_id", user_id).execute()
        return response.count if response.count else 0
    except Exception as e:
        st.warning(f"Failed to get voice count: {e}")
        return 0

def save_user_voice(user_id: str, voice_id: str, voice_name: str) -> bool:
    """Save user's created voice to database"""
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    # Check if user has reached voice limit
    voice_count = get_user_voice_count(user_id)
    if voice_count >= MAX_VOICES_PER_USER:
        st.error(f"❌ You can only create {MAX_VOICES_PER_USER} voice. Delete your existing voice to create a new one.")
        return False
    
    try:
        data = {
            "user_id": user_id,
            "voice_id": voice_id,
            "voice_name": voice_name,
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table("user_voices").insert(data).execute()
        return True
    except Exception as e:
        st.warning(f"Failed to save voice to database: {e}")
        return False

def get_user_voices(user_id: str) -> List[Dict]:
    """Get all voices created by the user"""
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        response = supabase.table("user_voices").select("*").eq("user_id", user_id).execute()
        return response.data if response.data else []
    except Exception as e:
        st.warning(f"Failed to fetch user voices: {e}")
        return []

def delete_user_voice(user_id: str, voice_id: str) -> bool:
    """Delete a user's voice from database"""
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        supabase.table("user_voices").delete().eq("user_id", user_id).eq("voice_id", voice_id).execute()
        return True
    except Exception as e:
        st.warning(f"Failed to delete voice: {e}")
        return False

# ============================================================================
# DATABASE FUNCTIONS FOR TTS GENERATIONS
# ============================================================================

def get_user_generation_count(user_id: str) -> int:
    """Get count of TTS generations by user"""
    supabase = get_supabase_client()
    if not supabase:
        return 0
    
    try:
        response = supabase.table("tts_generations").select("id", count="exact").eq("user_id", user_id).execute()
        return response.count if response.count else 0
    except Exception as e:
        st.warning(f"Failed to get generation count: {e}")
        return 0

def save_tts_generation(user_id: str, text: str, voice_id: str, voice_name: str) -> bool:
    """Save TTS generation record to database"""
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        data = {
            "user_id": user_id,
            "text": text,
            "voice_id": voice_id,
            "voice_name": voice_name,
            "created_at": datetime.utcnow().isoformat()
        }
        supabase.table("tts_generations").insert(data).execute()
        return True
    except Exception as e:
        st.warning(f"Failed to save generation: {e}")
        return False

def get_user_generations(user_id: str) -> List[Dict]:
    """Get all TTS generations by user"""
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        response = supabase.table("tts_generations").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        st.warning(f"Failed to fetch generations: {e}")
        return []

# ============================================================================
# AUTHENTICATION FUNCTIONS
# ============================================================================

def login_user(email: str, password: str) -> bool:
    """Login user with email and password"""
    supabase = get_supabase_client()
    if not supabase:
        st.error("Database connection not configured")
        return False
    
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if response.user:
            st.session_state.user = {
                "id": response.user.id,
                "email": response.user.email,
                "access_token": response.session.access_token
            }
            st.session_state.authenticated = True
            return True
        else:
            st.error("Login failed: No user returned")
            return False
    except Exception as e:
        error_msg = str(e)
        
        # Provide helpful error messages
        if "Invalid login credentials" in error_msg:
            st.error("❌ Invalid email or password. Please check your credentials.")
            st.info("💡 Tip: If you just signed up, check your email for a confirmation link.")
        elif "Email not confirmed" in error_msg:
            st.error("❌ Please confirm your email before logging in.")
            st.info("Check your inbox for the confirmation email from Supabase.")
        else:
            st.error(f"Login failed: {error_msg}")
        
        return False

def signup_user(email: str, password: str, confirm_password: str) -> bool:
    """Register a new user"""
    if password != confirm_password:
        st.error("Passwords don't match")
        return False
    
    if len(password) < 6:
        st.error("Password must be at least 6 characters")
        return False
    
    supabase = get_supabase_client()
    if not supabase:
        st.error("Database connection not configured")
        return False
    
    try:
        response = supabase.auth.sign_up({
            "email": email,
            "password": password
        })
        
        if response.user:
            st.success("✓ Account created! Please check your email to verify your account.")
            return True
        return False
    except Exception as e:
        st.error(f"Signup failed: {str(e)}")
        return False

def logout_user():
    """Logout current user"""
    supabase = get_supabase_client()
    if supabase:
        try:
            supabase.auth.sign_out()
        except:
            pass
    
    st.session_state.authenticated = False
    st.session_state.user = None
    st.session_state.segments = [create_new_segment()]
    st.session_state.last_generated_files = []
    st.session_state.voices_cached = []

def check_authentication():
    """Check if user is authenticated, show login page if not"""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if not st.session_state.authenticated:
        show_login_page()
        st.stop()

def show_login_page():
    """Display login/signup page"""
    st.title("🎙️ Multi-Speaker TTS")
    st.markdown("### Welcome! Please login to continue")
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("⚠️ Supabase is not configured. Please add SUPABASE_URL and SUPABASE_KEY to your environment variables or settings.")
        st.info("You need to set up:")
        st.code("""
# In your .env file or environment:
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
        """)
        st.stop()
    
    tab1, tab2 = st.tabs(["Login", "Sign Up"])
    
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_password")
            submit = st.form_submit_button("Login", use_container_width=True)
            
            if submit:
                if not email or not password:
                    st.error("Please fill in all fields")
                else:
                    if login_user(email, password):
                        st.success("✓ Login successful!")
                        st.rerun()
    
    with tab2:
        with st.form("signup_form"):
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password", type="password", key="signup_password")
            confirm_password = st.text_input("Confirm Password", type="password", key="signup_confirm")
            submit = st.form_submit_button("Create Account", use_container_width=True)
            
            if submit:
                if not email or not password or not confirm_password:
                    st.error("Please fill in all fields")
                else:
                    signup_user(email, password, confirm_password)

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

def init_session_state():
    """Initialize all session state variables"""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "user" not in st.session_state:
        st.session_state.user = None
    if "segments" not in st.session_state:
        st.session_state.segments = [create_new_segment()]
    if "voices_cached" not in st.session_state:
        st.session_state.voices_cached = []
    if "last_generated_files" not in st.session_state:
        st.session_state.last_generated_files = []
    if "current_page" not in st.session_state:
        st.session_state.current_page = "editor"

def create_new_segment() -> Dict:
    """Create a new empty segment"""
    return {
        "id": uuid.uuid4().hex,
        "text": "",
        "voice_id": None,
        "voice_label": "Choose voice"
    }

# ============================================================================
# VOICE MANAGEMENT
# ============================================================================

def fetch_voices() -> List[Dict]:
    """Fetch available voices from ElevenLabs API"""
    try:
        response = requests.get(
            settings.ELEVENLABS_LIST_VOICES_URL,
            headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
            timeout=8
        )
        response.raise_for_status()
        voices = response.json().get("voices", [])
        st.session_state.voices_cached = voices
        return voices
    except Exception as e:
        st.warning(f"Failed to fetch voices: {e}")
        return st.session_state.voices_cached

def get_voice_options() -> List[tuple]:
    """Get voice options as (label, voice_id) tuples"""
    voices = st.session_state.voices_cached
    return [(v.get("name") or v.get("voice_id"), v.get("voice_id")) for v in voices]

def delete_voice_from_elevenlabs(voice_id: str) -> bool:
    """Delete a voice from ElevenLabs"""
    try:
        delete_url = f"{settings.ELEVENLABS_LIST_VOICES_URL}/{voice_id}"
        response = requests.delete(
            delete_url,
            headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
            timeout=8
        )
        response.raise_for_status()
        return True
    except Exception as e:
        st.error(f"Failed to delete voice from ElevenLabs: {e}")
        return False

# ============================================================================
# VOICE CLONING
# ============================================================================

def handle_voice_cloning(uploaded_file, voice_name: str):
    """Handle the voice cloning process"""
    user_id = st.session_state.user.get("id")
    
    # Check voice limit
    voice_count = get_user_voice_count(user_id)
    if voice_count >= MAX_VOICES_PER_USER:
        st.error(f"❌ You can only create {MAX_VOICES_PER_USER} voice. Delete your existing voice to create a new one.")
        return False
    
    # Save uploaded file
    try:
        filename = f"{uuid.uuid4().hex}_{uploaded_file.name}"
        file_path = str(SAMPLES_DIR / filename)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.read())
        st.success(f"✓ Saved: {filename}")
    except Exception as e:
        st.error(f"Failed to save file: {e}")
        return False

    # Create cloned voice
    voice_name = voice_name.strip() or f"cloned_{uuid.uuid4().hex[:6]}"
    
    with st.spinner("Creating cloned voice..."):
        try:
            new_voice_id = ElevenLabsManager.create_instant_voice_clone(
                input_voice_file_path=file_path,
                voice_name=voice_name
            )
            
            if new_voice_id and new_voice_id != "Failed to create voice":
                # Save to database
                if save_user_voice(user_id, new_voice_id, voice_name):
                    st.success(f"🎉 Voice created! ID: `{new_voice_id}`")
                    fetch_voices()  # Refresh voice list
                    return True
                else:
                    # If DB save fails, delete from ElevenLabs
                    delete_voice_from_elevenlabs(new_voice_id)
                    return False
            else:
                st.error("Failed to create voice")
                return False
        except Exception as e:
            st.error(f"Error: {e}")
            return False

# ============================================================================
# AUDIO GENERATION
# ============================================================================

def validate_segments() -> List[int]:
    """Validate segments and return indices of invalid ones"""
    invalid = []
    for i, seg in enumerate(st.session_state.segments):
        if not seg.get("text", "").strip() or not seg.get("voice_id"):
            invalid.append(i + 1)
    return invalid

def check_generation_limit(user_id: str, num_segments: int) -> bool:
    """Check if user has remaining generations"""
    current_count = get_user_generation_count(user_id)
    remaining = MAX_GENERATIONS_PER_USER - current_count
    
    if remaining <= 0:
        st.error(f"❌ You've reached your limit of {MAX_GENERATIONS_PER_USER} generations.")
        return False
    
    if num_segments > remaining:
        st.error(f"❌ You have {remaining} generation(s) remaining, but trying to generate {num_segments} segment(s).")
        return False
    
    return True

def generate_single_segment(segment: Dict, output_dir: str, user_id: str, voice_name: str) -> Optional[str]:
    """Generate audio for a single segment and save to database"""
    try:
        # Generate audio
        output_path = ElevenLabsManager.convert_and_save_text_to_speech(
            text=segment["text"],
            voice_id=segment["voice_id"],
            out_dir=output_dir
        )
        
        if output_path and os.path.exists(output_path):
            # Save generation record to database
            save_tts_generation(user_id, segment["text"], segment["voice_id"], voice_name)
            return output_path
        return None
    except Exception as e:
        raise e

def generate_all_segments() -> tuple[List[str], List[str]]:
    """Generate audio for all segments. Returns (successful_paths, errors)"""
    user_id = st.session_state.user.get("id")
    
    # Check generation limit
    if not check_generation_limit(user_id, len(st.session_state.segments)):
        return [], ["Generation limit exceeded"]
    
    generated = []
    errors = []
    
    for i, segment in enumerate(st.session_state.segments):
        try:
            # Get voice name for this segment
            voice_name = segment.get("voice_label", "Unknown")
            
            output_path = generate_single_segment(segment, str(OUTPUTS_DIR), user_id, voice_name)
            if output_path:
                generated.append(output_path)
            else:
                errors.append(f"Segment {i+1}: Generation failed")
        except Exception as e:
            errors.append(f"Segment {i+1}: {str(e)}")
    
    return generated, errors

def merge_audio_files(file_paths: List[str]) -> str:
    """Merge multiple audio files into one. Returns merged file path."""
    if not PYDUB_AVAILABLE:
        raise RuntimeError("pydub not available for merging")
    
    combined = None
    for path in file_paths:
        audio = AudioSegment.from_file(path, format="mp3")
        if combined is None:
            combined = audio
        else:
            combined += AudioSegment.silent(duration=300)  # 300ms gap
            combined += audio
    
    output_filename = f"merged_{uuid.uuid4().hex}.mp3"
    output_path = str(OUTPUTS_DIR / output_filename)
    combined.export(output_path, format="mp3")
    
    return output_path

def create_zip_archive(file_paths: List[str]) -> str:
    """Create ZIP archive of audio files. Returns ZIP file path."""
    zip_filename = f"segments_{uuid.uuid4().hex}.zip"
    zip_path = str(OUTPUTS_DIR / zip_filename)
    
    with zipfile.ZipFile(zip_path, "w") as z:
        for file_path in file_paths:
            z.write(file_path, arcname=os.path.basename(file_path))
    
    return zip_path

# ============================================================================
# UI COMPONENTS - NAVIGATION
# ============================================================================

def render_navigation():
    """Render navigation menu in sidebar"""
    with st.sidebar:
        st.markdown("### 📍 Navigation")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("✏️ Editor", use_container_width=True, 
                        type="primary" if st.session_state.current_page == "editor" else "secondary"):
                st.session_state.current_page = "editor"
                st.rerun()
        
        with col2:
            if st.button("🎤 Voices", use_container_width=True,
                        type="primary" if st.session_state.current_page == "all_voices" else "secondary"):
                st.session_state.current_page = "all_voices"
                st.rerun()
        
        st.divider()

def render_usage_info():
    """Display usage statistics in sidebar"""
    with st.sidebar:
        user_id = st.session_state.user.get("id")
        
        # Voice usage
        voice_count = get_user_voice_count(user_id)
        voice_remaining = MAX_VOICES_PER_USER - voice_count
        
        # Generation usage
        gen_count = get_user_generation_count(user_id)
        gen_remaining = MAX_GENERATIONS_PER_USER - gen_count
        
        st.markdown("### 📊 Usage")
        
        # Voice quota
        st.markdown(f"**Voices:** {voice_count} / {MAX_VOICES_PER_USER}")
        st.progress(voice_count / MAX_VOICES_PER_USER)
        if voice_remaining > 0:
            st.caption(f"✓ {voice_remaining} voice slot available")
        else:
            st.caption("⚠️ Voice limit reached")
        
        st.markdown("---")
        
        # Generation quota
        st.markdown(f"**Generations:** {gen_count} / {MAX_GENERATIONS_PER_USER}")
        st.progress(gen_count / MAX_GENERATIONS_PER_USER)
        if gen_remaining > 0:
            st.caption(f"✓ {gen_remaining} generation(s) remaining")
        else:
            st.caption("⚠️ Generation limit reached")
        
        st.divider()

def render_user_info():
    """Display user info and logout button in sidebar"""
    with st.sidebar:
        st.divider()
        user_email = st.session_state.user.get("email", "User")
        st.caption(f"👤 Logged in as:")
        st.text(user_email)
        
        if st.button("🚪 Logout", use_container_width=True):
            logout_user()
            st.rerun()

# ============================================================================
# UI COMPONENTS - VOICE LIBRARY PAGE
# ============================================================================

def render_all_voices_page():
    """Display all available voices - simplified view"""
    st.title("🎤 Voice Library")
    
    tab1, tab2 = st.tabs(["📚 All Voices", "👤 My Voices"])
    
    with tab1:
        render_all_voices_tab()
    
    with tab2:
        render_my_voices_tab()

def render_all_voices_tab():
    """Display all available voices from ElevenLabs"""
    st.caption("Browse all voices available in your ElevenLabs account")
    
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_all"):
            fetch_voices()
            st.rerun()
    
    st.divider()
    
    voices = st.session_state.voices_cached
    
    if not voices:
        st.info("No voices found. Click 'Refresh' to fetch from ElevenLabs.")
        return
    
    # Search
    search = st.text_input("🔍 Search voices", key="search_all")
    
    filtered_voices = voices
    if search:
        filtered_voices = [v for v in voices if search.lower() in v.get("name", "").lower()]
    
    st.markdown(f"**Showing {len(filtered_voices)} of {len(voices)} voices**")
    
    # Display as simple list
    for voice in filtered_voices:
        voice_name = voice.get("name", "Unnamed")
        voice_id = voice.get("voice_id", "")
        
        with st.expander(f"🎙️ {voice_name}"):
            st.caption(f"Voice ID: `{voice_id}`")
            
            # Preview audio if available
            preview_url = voice.get("preview_url")
            if preview_url:
                st.audio(preview_url)

def render_my_voices_tab():
    """Display voices created by the current user"""
    st.caption("Voices you have created")
    
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Refresh", use_container_width=True, key="refresh_my"):
            fetch_voices()
            st.rerun()
    
    st.divider()
    
    user_id = st.session_state.user.get("id")
    user_voices_db = get_user_voices(user_id)
    
    if not user_voices_db:
        st.info("You haven't created any voices yet. Go to the Editor to clone a voice!")
        return
    
    # Get full voice details
    all_voices = st.session_state.voices_cached
    user_voice_ids = {v["voice_id"] for v in user_voices_db}
    user_voices = [v for v in all_voices if v.get("voice_id") in user_voice_ids]
    
    st.markdown(f"**You have {len(user_voices)} cloned voice(s)**")
    
    for voice in user_voices:
        voice_name = voice.get("name", "Unnamed")
        voice_id = voice.get("voice_id", "")
        
        with st.expander(f"🎙️ {voice_name}", expanded=True):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.caption(f"Voice ID: `{voice_id}`")
                preview_url = voice.get("preview_url")
                if preview_url:
                    st.audio(preview_url)
            
            with col2:
                if st.button("🗑️ Delete", key=f"del_{voice_id}", use_container_width=True):
                    with st.spinner("Deleting..."):
                        if delete_voice_from_elevenlabs(voice_id):
                            delete_user_voice(user_id, voice_id)
                            st.success(f"✓ Deleted {voice_name}")
                            fetch_voices()
                            st.rerun()

# ============================================================================
# UI COMPONENTS - EDITOR PAGE
# ============================================================================

def render_sidebar_editor():
    """Render sidebar for editor page"""
    with st.sidebar:
        st.header("🎙️ Voice Cloning")
        
        user_id = st.session_state.user.get("id")
        voice_count = get_user_voice_count(user_id)
        
        if voice_count >= MAX_VOICES_PER_USER:
            st.warning(f"⚠️ You've reached the limit of {MAX_VOICES_PER_USER} voice. Delete your existing voice to create a new one.")
        else:
            st.caption("Upload ONE audio file (MP3/WAV)")
            
            uploaded_files = st.file_uploader(
                "Audio file",
                type=["mp3", "wav"],
                accept_multiple_files=True,
                key="voice_upload"
            )
            
            voice_name = st.text_input("Voice name (required)", key="voice_name")
            
            if st.button("Create Cloned Voice", use_container_width=True):
                if not voice_name or not voice_name.strip():
                    st.error("Please enter a voice name")
                elif not uploaded_files:
                    st.error("Please upload an audio file")
                elif len(uploaded_files) > 1:
                    st.error("❌ Only ONE file allowed")
                else:
                    if handle_voice_cloning(uploaded_files[0], voice_name):
                        st.rerun()
        
        st.divider()
        
        # Segment actions
        st.subheader("Segment Actions")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("➕ Add", use_container_width=True):
                st.session_state.segments.append(create_new_segment())
                st.rerun()
        with col2:
            if st.button("🗑️ Clear", use_container_width=True):
                st.session_state.segments = [create_new_segment()]
                st.rerun()

def render_segment(segment: Dict, index: int):
    """Render a single segment editor"""
    st.markdown(f"### Segment {index + 1}")
    
    col1, col2, col3 = st.columns([6, 2, 1])
    
    with col1:
        segment["text"] = st.text_area(
            f"Text",
            value=segment.get("text", ""),
            height=120,
            key=f"text_{segment['id']}",
            label_visibility="collapsed"
        )
    
    with col2:
        voice_options = get_voice_options()
        
        if voice_options:
            labels = [v[0] for v in voice_options]
            
            current_label = segment.get("voice_label", "Choose voice")
            try:
                selected_idx = labels.index(current_label) if current_label in labels else 0
            except:
                selected_idx = 0
            
            choice = st.selectbox(
                "Voice",
                options=labels,
                index=selected_idx,
                key=f"voice_{segment['id']}"
            )
            
            segment["voice_label"] = choice
            segment["voice_id"] = next((v[1] for v in voice_options if v[0] == choice), None)
            
            if segment.get("voice_id"):
                st.caption(f"ID: {segment['voice_id'][:8]}...")
        else:
            st.info("No voices available")
    
    with col3:
        if st.button("✕", key=f"remove_{segment['id']}", use_container_width=True):
            st.session_state.segments.pop(index)
            st.rerun()

def render_generation_controls():
    """Render audio generation buttons"""
    st.divider()
    st.markdown("## 🎵 Generate Audio")
    
    num_segments = len(st.session_state.segments)
    user_id = st.session_state.user.get("id")
    gen_remaining = MAX_GENERATIONS_PER_USER - get_user_generation_count(user_id)
    
    if gen_remaining <= 0:
        st.error(f"❌ You've used all {MAX_GENERATIONS_PER_USER} generations.")
        return
    
    st.info(f"💡 You have {gen_remaining} generation(s) remaining. Each segment counts as one generation.")
    
    col1, col2, col3 = st.columns(3)
    
    # Button 1: Generate individual segments
    with col1:
        btn1_disabled = num_segments < 1 or num_segments > gen_remaining
        if st.button("🎬 Generate Segments", use_container_width=True, disabled=btn1_disabled):
            invalid = validate_segments()
            if invalid:
                st.error(f"Invalid segments: {invalid}")
            else:
                with st.spinner("Generating..."):
                    generated, errors = generate_all_segments()
                    st.session_state.last_generated_files = generated
                    
                    if generated:
                        st.success(f"✓ Generated {len(generated)} file(s)")
                    for error in errors:
                        st.warning(error)
    
    # Button 2: Generate and merge
    with col2:
        btn2_disabled = num_segments < 2 or num_segments > gen_remaining
        if st.button("🔗 Generate & Merge", use_container_width=True, disabled=btn2_disabled):
            invalid = validate_segments()
            if invalid:
                st.error(f"Invalid segments: {invalid}")
            else:
                with st.spinner("Generating and merging..."):
                    generated, errors = generate_all_segments()
                    st.session_state.last_generated_files = generated
                    
                    for error in errors:
                        st.warning(error)
                    
                    if not generated:
                        st.error("No files to merge")
                    else:
                        merged_successfully = False
                        
                        if PYDUB_AVAILABLE:
                            try:
                                merged_path = merge_audio_files(generated)
                                st.success(f"✓ Merged: {os.path.basename(merged_path)}")
                                
                                st.audio(merged_path, format="audio/mp3")
                                with open(merged_path, "rb") as f:
                                    st.download_button(
                                        "⬇️ Download Merged MP3",
                                        data=f.read(),
                                        file_name=os.path.basename(merged_path),
                                        mime="audio/mpeg"
                                    )
                                merged_successfully = True
                            except Exception as e:
                                st.warning(f"Merge failed: {e}. Creating ZIP instead...")
                        
                        if not merged_successfully:
                            try:
                                zip_path = create_zip_archive(generated)
                                st.success(f"✓ Created ZIP: {os.path.basename(zip_path)}")
                                
                                with open(zip_path, "rb") as f:
                                    st.download_button(
                                        "⬇️ Download ZIP",
                                        data=f.read(),
                                        file_name=os.path.basename(zip_path),
                                        mime="application/zip"
                                    )
                            except Exception as e:
                                st.error(f"Failed to create ZIP: {e}")
    
    # Button 3: Preview
    with col3:
        if st.button("▶️ Preview All", use_container_width=True):
            files = st.session_state.last_generated_files
            if not files:
                st.info("Generate segments first")
            else:
                st.write("**Generated files:**")
                for file_path in files:
                    st.markdown(f"🔊 {os.path.basename(file_path)}")
                    st.audio(file_path, format="audio/mp3")

def render_editor_page():
    """Render the main editor page"""
    st.title("✏️ Script Editor")
    
    # Sidebar for editor
    render_sidebar_editor()
    
    # Main content
    st.markdown("## 📝 Script Segments")
    st.caption("Each segment = text + voice")
    
    for idx, segment in enumerate(st.session_state.segments):
        render_segment(segment, idx)
    
    # Generation controls
    render_generation_controls()

# ============================================================================
# MAIN APP
# ============================================================================

def main():
    """Main application entry point"""
    # Initialize session state
    init_session_state()
    
    # Check authentication
    check_authentication()
    
    # Fetch voices if not cached
    if not st.session_state.voices_cached:
        fetch_voices()
    
    # Navigation
    render_navigation()
    
    # Usage info
    render_usage_info()
    
    # Route to appropriate page
    if st.session_state.current_page == "editor":
        render_editor_page()
    elif st.session_state.current_page == "all_voices":
        render_all_voices_page()
    
    # User info at bottom
    render_user_info()

if __name__ == "__main__":
    main()