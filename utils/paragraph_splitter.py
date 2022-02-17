import pysbd
from sentence_splitter import split_text_into_sentences
from indicnlp.tokenize.sentence_tokenize import sentence_split


def paragraph_tokenizer(text, language="en"):
    """Replace sentences with their indexes, and store indexes of newlines
    Args:
        text (str): Text to be indexed

    Returns:
        sentences (list): List of sentences
        breaks (list): List of indexes of sentences and newlines
    """

    languages_splitter = ["ca", "cs", "da", "de", "el", "en", "es", "fi", "fr", "hu", "is", "it",
                          "lt", "lv", "nl", "no", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "tr"]
    languages_indic = ["as", "bn", "gu", "hi", "kK", "kn", "ml", "mr", "ne", "or", "pa", "sa",
                       "sd", "si", "ta", "te"]
    languages_pysbd = ["en", "hi", "mr", "zh", "es", "am", "ar", "hy", "bg", "ur", "ru", "pl",
                       "fa", "nl", "da", "fr", "my", "el", "it", "ja", "de", "kk", "sk"]

    languages = languages_splitter + languages_indic + languages_pysbd
    language = language if language in languages else "en"

    text = text.strip()
    paragraphs = text.splitlines(True)

    breaks = []
    sentences = []

    for paragraph in paragraphs:
        if paragraph == "\n":
            breaks.append("\n")
        else:
            if language in languages_pysbd:
                segmenter = pysbd.Segmenter(language=language, clean=True)
                paragraph_sentences = segmenter.segment(paragraph)
            elif language in languages_splitter:
                paragraph_sentences = split_text_into_sentences(paragraph, language)
            elif language in languages_indic:
                paragraph_sentences = sentence_split(paragraph, language)


            breaks.extend(
                list(range(len(sentences), +len(sentences) + len(paragraph_sentences)))
            )
            breaks.append("\n")
            sentences.extend(paragraph_sentences)

    # Remove the last newline
    breaks = breaks[:-1]

    return sentences, breaks


def paragraph_detokenizer(sentences, breaks):
    """Restore original paragraph format from indexes of sentences and newlines

    Args:
        sentences (list): List of sentences
        breaks (list): List of indexes of sentences and newlines

    Returns:
        text (str): Text with original format
    """
    output = []

    for br in breaks:
        if br == "\n":
            output.append("\n")
        else:
            output.append(sentences[br] + " ")

    text = "".join(output)
    return text
