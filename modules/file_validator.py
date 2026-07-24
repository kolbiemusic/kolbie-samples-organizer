import os
import hashlib
import json
import logging
from pathlib import Path
from mutagen.wave import WAVE
from mutagen.aiff import AIFF
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
import soundfile as sf

logger = logging.getLogger(__name__)

class FileValidator:
    AUDIO_FORMATS = {'.wav', '.aif', '.aiff', '.flac', '.mp3'}

    def __init__(self):
        self.md5_cache = {}
        self.invalid_files = []
        self.duplicates = {}

    def is_valid_audio(self, filepath):
        """Check if file is valid and readable audio"""
        try:
            ext = Path(filepath).suffix.lower()
            if ext not in self.AUDIO_FORMATS:
                return False

            if ext in {'.wav'}:
                WAVE(filepath)
            elif ext in {'.aif', '.aiff'}:
                AIFF(filepath)
            elif ext in {'.flac'}:
                FLAC(filepath)
            elif ext in {'.mp3'}:
                MP3(filepath)

            return True
        except Exception as e:
            # mutagen parses the WAV/AIFF's embedded ID3 chunk for tags, and
            # some real, perfectly playable files (e.g. 24-bit WAVs from
            # certain sample-pack tools) carry a malformed/truncated ID3
            # sub-chunk that isn't the actual audio data — mutagen rejects
            # the whole file for that. soundfile reads the PCM data directly
            # and ignores tag chunks, so it's the real arbiter of whether the
            # audio itself is usable before giving up on the file entirely.
            if ext in {'.wav', '.aif', '.aiff'} and self._soundfile_readable(filepath):
                return True
            logger.warning(f"Invalid audio file {filepath}: {e}")
            self.invalid_files.append(str(filepath))
            return False

    def _soundfile_readable(self, filepath):
        try:
            sf.info(filepath)
            return True
        except Exception:
            return False

    def get_file_hash(self, filepath):
        """Calculate MD5 hash of file"""
        if filepath in self.md5_cache:
            return self.md5_cache[filepath]

        try:
            hash_md5 = hashlib.md5()
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            file_hash = hash_md5.hexdigest()
            self.md5_cache[filepath] = file_hash
            return file_hash
        except Exception as e:
            logger.error(f"Error hashing file {filepath}: {e}")
            return None

    def find_duplicates(self, file_list):
        """Find duplicate files by MD5 hash"""
        hash_map = {}
        duplicates = {}

        for filepath in file_list:
            file_hash = self.get_file_hash(filepath)
            if file_hash:
                if file_hash in hash_map:
                    if file_hash not in duplicates:
                        duplicates[file_hash] = [hash_map[file_hash]]
                    duplicates[file_hash].append(filepath)
                else:
                    hash_map[file_hash] = filepath

        self.duplicates = duplicates
        return duplicates

    def extract_existing_metadata(self, filepath):
        """Extract metadata from audio tags if present"""
        metadata = {
            'bpm': None,
            'key': None,
            'genre': None,
            'artist': None,
            'title': None
        }

        try:
            ext = Path(filepath).suffix.lower()

            if ext in {'.wav'}:
                audio = WAVE(filepath)
            elif ext in {'.aif', '.aiff'}:
                audio = AIFF(filepath)
            elif ext in {'.flac'}:
                audio = FLAC(filepath)
            elif ext in {'.mp3'}:
                audio = MP3(filepath)
            else:
                return metadata

            if audio.tags:
                # Standard tags
                if 'TIT2' in audio.tags:  # ID3 Title
                    metadata['title'] = str(audio.tags['TIT2'])
                elif 'TITLE' in audio.tags:
                    metadata['title'] = str(audio.tags['TITLE'])

                if 'TPE1' in audio.tags:  # ID3 Artist
                    metadata['artist'] = str(audio.tags['TPE1'])
                elif 'ARTIST' in audio.tags:
                    metadata['artist'] = str(audio.tags['ARTIST'])

                if 'TCON' in audio.tags:  # ID3 Genre
                    metadata['genre'] = str(audio.tags['TCON'])
                elif 'GENRE' in audio.tags:
                    metadata['genre'] = str(audio.tags['GENRE'])

                # BPM tags
                if 'TBPM' in audio.tags:
                    try:
                        metadata['bpm'] = int(str(audio.tags['TBPM']))
                    except:
                        pass
                elif 'BPM' in audio.tags:
                    try:
                        metadata['bpm'] = int(str(audio.tags['BPM']))
                    except:
                        pass

                # Key tags
                if 'TKEY' in audio.tags:
                    metadata['key'] = str(audio.tags['TKEY'])
                elif 'KEY' in audio.tags:
                    metadata['key'] = str(audio.tags['KEY'])

        except Exception as e:
            logger.debug(f"Could not extract metadata from {filepath}: {e}")

        return metadata

    def get_audio_duration(self, filepath):
        """Get audio file duration in seconds"""
        try:
            ext = Path(filepath).suffix.lower()

            if ext in {'.wav'}:
                audio = WAVE(filepath)
            elif ext in {'.aif', '.aiff'}:
                audio = AIFF(filepath)
            elif ext in {'.flac'}:
                audio = FLAC(filepath)
            elif ext in {'.mp3'}:
                audio = MP3(filepath)
            else:
                return None

            return audio.info.length
        except Exception as e:
            # Same malformed-tag-chunk case as is_valid_audio — fall back to
            # soundfile, which reads the PCM header directly.
            if ext in {'.wav', '.aif', '.aiff'}:
                try:
                    info = sf.info(filepath)
                    return info.duration
                except Exception:
                    pass
            logger.warning(f"Could not get duration for {filepath}: {e}")
            return None
