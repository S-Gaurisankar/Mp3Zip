import os
import sys
import asyncio
import unittest
import tempfile
import subprocess
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.system_check import run_system_diagnostics
from backend.metadata import parse_track_input, parse_track_batch, clean_text_noise
from backend.tagger import embed_id3_tags
from backend.transcoder import transcode_to_mp3
from mutagen.mp3 import MP3

class TestMusicExtractionEngine(unittest.TestCase):
    def test_01_system_diagnostics(self):
        diag = run_system_diagnostics()
        self.assertTrue(diag["ready"], f"System dependencies failed: {diag.get('troubleshooting')}")
        self.assertTrue(diag["ffmpeg"]["available"])
        self.assertTrue(diag["ffprobe"]["available"])
        self.assertTrue(diag["libmp3lame"]["available"])

    def test_02_metadata_parsing_and_noise_cleaning(self):
        # Test basic format
        t1 = parse_track_input("Daft Punk - Get Lucky [Official Video 4K]")
        self.assertEqual(t1.artist, "Daft Punk")
        self.assertEqual(t1.title, "Get Lucky")
        self.assertIn("ytsearch1:Daft Punk - Get Lucky official audio", t1.get_search_query())

        # Test noise stripping
        noisy = "Pink Floyd - Time (Official Audio 2024 Remastered) [HQ]"
        t2 = parse_track_input(noisy)
        self.assertEqual(t2.artist, "Pink Floyd")
        self.assertEqual(t2.title, "Time")

        # Test CSV parsing
        csv_line = "Miles Davis, So What, Kind of Blue"
        t3 = parse_track_input(csv_line)
        self.assertEqual(t3.artist, "Miles Davis")
        self.assertEqual(t3.title, "So What")
        self.assertEqual(t3.album, "Kind of Blue")

        # Test batch parsing
        batch_text = """
        # Comment line
        Daft Punk - One More Time
        Queen - Bohemian Rhapsody (A Night at the Opera)
        https://music.youtube.com/watch?v=12345
        """
        batch = parse_track_batch(batch_text)
        self.assertEqual(len(batch), 3)
        self.assertEqual(batch[0].artist, "Daft Punk")
        self.assertEqual(batch[1].artist, "Queen")
        self.assertTrue(batch[2].is_direct_url)

    def test_03_transcoding_and_tagging(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            synth_wav = tmppath / "synth_test.wav"
            target_mp3 = tmppath / "output_test.mp3"

            # Generate 1-second sine wave using ffmpeg
            gen_cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "sine=frequency=440:duration=1",
                str(synth_wav)
            ]
            subprocess.run(gen_cmd, check=True, capture_output=True)
            self.assertTrue(synth_wav.exists())

            # Test async transcode
            success = asyncio.run(transcode_to_mp3(synth_wav, target_mp3))
            self.assertTrue(success)
            self.assertTrue(target_mp3.exists())
            self.assertGreater(target_mp3.stat().st_size, 0)

            # Test ID3 Tagging
            # 1x1 png image bytes for test album art
            tiny_png = (
                b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
                b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00'
                b'\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4'
                b'\x00\x00\x00\x00IEND\xaeB`\x82'
            )

            tag_success = embed_id3_tags(
                mp3_file_path=target_mp3,
                title="Synthetic Tone",
                artist="Test Studio",
                album="Audio Tests",
                image_bytes=tiny_png
            )
            self.assertTrue(tag_success)

            # Verify Mutagen read back
            audio = MP3(str(target_mp3))
            self.assertEqual(str(audio.tags["TIT2"]), "Synthetic Tone")
            self.assertEqual(str(audio.tags["TPE1"]), "Test Studio")
            self.assertEqual(str(audio.tags["TALB"]), "Audio Tests")
            self.assertTrue("APIC:Cover" in audio.tags or any(k.startswith("APIC") for k in audio.tags))

    def test_04_spotify_playlist_parsing(self):
        from backend.spotify import is_spotify_url, parse_spotify_url
        from unittest.mock import patch, MagicMock
        
        url = "https://open.spotify.com/playlist/5XPxtJ61Rfp9NFT0vzEgb5"
        self.assertTrue(is_spotify_url(url))

        mock_html = '''
        <html>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "state": {
                "data": {
                  "entity": {
                    "title": "Tamil Hits",
                    "trackList": [
                      {"title": "Kannukulla", "subtitle": "Sai Abhyankkar, Jonita Gandhi"},
                      {"title": "Pookkal Pookkum", "subtitle": "G. V. Prakash"}
                    ]
                  }
                }
              }
            }
          }
        }
        </script>
        </html>
        '''

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html

        with patch("requests.get", return_value=mock_resp):
            tracks = parse_track_batch(url)
            self.assertEqual(len(tracks), 2)
            self.assertEqual(tracks[0].title, "Kannukulla")
            self.assertEqual(tracks[0].artist, "Sai Abhyankkar, Jonita Gandhi")
            self.assertEqual(tracks[0].album, "Tamil Hits")

if __name__ == "__main__":
    unittest.main()
