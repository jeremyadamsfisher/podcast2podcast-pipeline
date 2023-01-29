import json
import re
from typing import Callable, Optional

import openai
from loguru import logger

from podcast2podcast.config import settings
from podcast2podcast.utils import retry

SUMMARIZE = """\
Please summarize the following podcast description as a JSON. Only include \
information about the content of the episode. For example, ignore links \
to the podcast's website and social media accounts.

Description: {}

"""

REWRITE = """\
Please write dialog for a talk show where the host, "JeremyBot," discusses and \
summarizes a podcast. There are no guests on this show. Respond with JSON and \
make sure to end with the tagline: "That's all for today. Join us next time \
for another exciting summary."

For example, consider the following summary.

Summary: This week on the Slate Gabfest, David Plotz, Emily Bazelon, and John \
Dickerson discuss the House GOP's "Weaponization of Government" subcommittee, \
the insurrection in Brazil, Prince Harry's book "Spare", and the status of \
"return to office". They also provide references and chatters from John, Emily, \
David, and a listener.

For that summary, you could write the following:

{{"dialog": "Welcome! Today we are summarizing The Slate Political Gabfest. On \
this episode, David Plotz, Emily Bazelon, and John Dickerson discuss the House \
GOP's 'Weaponization of Government' subcommittee, the insurrection in Brazil, \
Prince Harry's book 'Spare', and the status of 'return to office'. They also \
provide references and chatters from John, Emily, David, and a listener. \
That's all for today. Join us next time for another exciting summary."}}

In this case, summarize {}:

Summary: {}

"""

FIRST_LINE = """\
Welcome back. I'm JeremyBot, an artificial intelligence that summarizes \
podcasts. Today we are summarizing {}: {}.\
"""


def new_dialog(podcast_title, episode_title, description) -> str:
    """Create a new dialog transcript from a podcast transcript.

    Args:
        podcast_title (str): The podcast title.
        episode_title (str): The episode title.
        description (str): The episode description.

    Returns:
        str: The new dialog transcript.

    """
    openai.api_key = settings.openai_token

    logger.info("Description: {}", description)

    summary = generate_summary(description)
    dialog = generate_dialog(summary, podcast_title, episode_title)

    return dialog


class CompletionError(Exception):
    pass


def generate_summary(description: str) -> str:
    """Summarize a podcast description.

    Args:
        description (str): The podcast description.

    Returns:
        str: The summary.

    """
    description = re.sub(r"\n*", " ", description)
    summary = json_complete(
        prompt=SUMMARIZE.format(description), key="summary", max_tokens=512
    )
    logger.info("Summary: {}", summary)
    return summary


def generate_dialog(summary: str, podcast_title: str, episode_title: str) -> str:
    """Generate dialog from a podcast summary.

    Args:
        summary (str): The podcast summary.
        podcast_title (str): The podcast title.
        episode_title (str): The episode title.

    Returns:
        str: The dialog.

    """
    summary = re.sub(r"\n*", " ", summary)
    if not (
        podcast_title.lower().startswith("the") or podcast_title.lower().startswith("a")
    ):
        podcast_title = "the " + podcast_title
    dialog = json_complete(
        prompt=REWRITE.format(podcast_title.title(), summary),
        output_prefix=FIRST_LINE.format(podcast_title.title(), episode_title.title()),
        key="dialog",
        attempt_fix=attempt_to_salvage_dialog_that_is_slightly_too_long,
        max_tokens=600,
    )
    logger.info("Dialog: {}", dialog)
    return dialog


def attempt_to_salvage_dialog_that_is_slightly_too_long(dialog):
    pat = r"(that'?s all for today.*$)"
    if re.findall(pat, dialog, flags=re.IGNORECASE):
        return re.sub(
            pat,
            "That's all for today. Join us next time for another exciting summary.\"}",
            dialog,
            flags=re.IGNORECASE,
        )
    else:
        raise ValueError(f"Can't salvage dialog that is too long: `{dialog}`")


def text_complete(
    prompt: str,
    model="text-davinci-003",
    max_tokens=256,
    output_prefix="",
) -> str:
    """Complete text using OpenAI API.

    Args:
        prompt (str): Prompt to complete.
        model (str, optional): Model to use. Defaults to "text-davinci-003".
        max_tokens (int, optional): Maximum number of tokens to generate. Defaults to 256.
        output_prefix (str, optional): Prefix to add to the output. Defaults to "".

    Returns:
        str: Completed text, not including the prompt.

    """
    try:
        response = openai.Completion.create(
            prompt=prompt + output_prefix,
            model=model,
            max_tokens=max_tokens,
            temperature=0.7,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
        )
        return output_prefix + response.choices[0]["text"].strip()
    except Exception as e:
        raise CompletionError(f"Error completing text: {e}")


def extract_from_curly_brackets(s: str) -> str:
    """Extract text from curly brackets.

    Args:
        s (str): String to extract from.

    Raises:
        ValueError: If there is not exactly one match.

    Returns:
        str: Extracted text.

    """
    try:
        (extraction,) = re.findall(r"({.*})", s, re.DOTALL)
    except ValueError:
        raise ValueError(f"None or too many curly brackets : {s}")
    return extraction


@retry(n=5, delay=2)
def json_complete(
    key: str,
    prompt: str,
    model="text-davinci-003",
    max_tokens=256,
    output_prefix="",
    attempt_fix: Optional[Callable] = None,
) -> str:
    """Complete text using OpenAI API, evoking JSON outputs from the model to
    know what part of the output is relevant.

    Args:
        key (str): Key to extract from JSON from GPT3.
        *args, **kwargs: Arguments to pass to text_complete.
        attempt_fix (Callable, optional): Function to attempt to fix the JSON if it is invalid. Defaults to None.

    Returns:
        str: Completed text, not including the prompt.

    """
    json_start = f'{{"{key}": "'  # e.g., '{"summary": "'
    if output_prefix:
        json_start += " " + output_prefix
    completion = text_complete(
        prompt,
        model,
        max_tokens,
        output_prefix=json_start,
    )
    try:
        completion = extract_from_curly_brackets(completion)
    except ValueError as e:
        if attempt_fix is None:
            raise e
        logger.warning(f"Invalid JSON: {completion}. Attempting to fix...")
        completion = attempt_fix(completion)
        completion = extract_from_curly_brackets(completion)
    try:
        completion = json.loads(completion.replace("\n", r"\n"))[key]
    except (json.JSONDecodeError, TypeError):
        raise ValueError(f"Invalid JSON: {completion}")
    return completion
