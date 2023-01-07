from typing import Literal

from podcast2podcast.summarize import summarize_pipeline as summarize
from podcast2podcast.transcribe import FIVE_MINUTES
from podcast2podcast.transcribe import transcribe_pipeline as transcribe
from podcast2podcast.tts.google import text2speech_pipeline as google_tts
from podcast2podcast.tts.tortoise import text2speech_pipeline as tortoise_tts
from podcast2podcast.utils import yap


def pipeline(
    url,
    podcast,
    episode_name,
    duration=FIVE_MINUTES,
    tts_method: Literal["google", "tortoise"] = "google",
    fp_out=None,
):
    """Run the entire pipeline (transcription to spoken output).

    Args:
        url (str): URL to audio file.
        podcast (str): Podcast name.
        episode_name (str): Episode name.
        duration (int, optional): Duration in seconds. Defaults to the first 5 minutes of the episode.
        fp_out (str, optional): Path to output audio file. Defaults to "./podcast.mp3".

    Returns:
        str: Path to output audio file.
    """

    with yap(about="transcribing"):
        transcript_original = transcribe(url, duration)
    with yap(about="creating new dialog"):
        transcript_generated = summarize(transcript_original, podcast, episode_name)
    with yap(about="generating audio"):
        tts = {"google": google_tts, "tortoise": tortoise_tts}[tts_method]
        audio = tts(transcript_generated)

    if fp_out is None:
        fp_out = f"./{podcast}_{episode_name}_summary.mp3"
    audio.export(fp_out, format="mp3")

    return fp_out
