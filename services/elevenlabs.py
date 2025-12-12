import os
from core.config import settings
from core.logger import logger

from io import BytesIO
import uuid

from elevenlabs import ElevenLabs, VoiceSettings
from elevenlabs.play import play


class ElevenLabsManager:
    client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)

    # SIMPLE TTS
    @classmethod
    def convert_text_to_speech(cls, text: str, voice_id: str = "ZF6FPAbjXT4488VcRRnw"):
        try:
            logger.info(f"Converting text to speech for text: {text}")
            audio = cls.client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=settings.ELEVENLABS_MODEL,
                output_format="mp3_44100_128",
                voice_settings=VoiceSettings(
                    stability=0.0,
                    similarity_boost=1.0,
                    style=0.0,
                    use_speaker_boost=True,
                    speed=1.0,
                )
            )
            
            logger.info(f"Playing audio.")
        except Exception as e:
            logger.error(str(e))

        try:
            # 
            audio_bytes = b"".join(chunk for chunk in audio if chunk)
            return audio_bytes
        except Exception as e:
            logger.error(str(e))
            print("Failed to play audio. Ensure ffmpeg/ffplay is installed on your system.")

    # SAVE IN DIR
    @classmethod
    def convert_and_save_text_to_speech(cls, text: str, out_dir:str, voice_id: str = "ZF6FPAbjXT4488VcRRnw") -> str:
        try:
            logger.info(f"Converting text to speech for text: {text}")
            audio = cls.client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=settings.ELEVENLABS_MODEL,
                output_format="mp3_44100_128",
                voice_settings=VoiceSettings(
                    stability=0.0,
                    similarity_boost=1.0,
                    style=0.0,
                    use_speaker_boost=True,
                    speed=1.0,
                )
            )

        except Exception as e:
            logger.error(str(e))

        try:
            logger.info("Creating file name")
            # os.makedirs("outputs/ivc", exist_ok=True)
            file_path = f"{out_dir}/{uuid.uuid4()}.mp3"
            
            with open(file_path, "wb") as f:
                for chunk in audio:
                    if chunk:
                        f.write(chunk)
            logger.info(f"File saved at {file_path}")
            
            return file_path
        
        except Exception as e:
            logger.error(str(e))
            return "Failed to save file"

    # CREATE IVC
    @classmethod
    def create_instant_voice_clone(cls, input_voice_file_path: str, voice_name: str = str(uuid.uuid4())) -> str: 
        try:
            logger.info(f"Creating voice {voice_name}")
            voice = cls.client.voices.ivc.create(
                name=voice_name,
                files=[BytesIO(open(input_voice_file_path, "rb").read())]
            )
            logger.info(f"Created voice {voice} with voice id {voice.voice_id}")
            
            return voice.voice_id
    
        except Exception as e:
            logger.error(str(e))
            return "Failed to create voice"
