from nltk import sent_tokenize


def paragraph_tokenizer(text):
    """ Replace sentences with their indexes, and store indexes of newlines
    Args:
        text (str): Text to be indexed

    Returns:
        sentences (list): List of sentences
        breaks (list): List of indexes of sentences and newlines
    """
    text = text.strip()
    paragraphs = text.splitlines(True)

    breaks = []
    sentences = []

    for paragraph in paragraphs:
        if paragraph == "\n":
            breaks.append("\n")
        else:
            paragraph_sentences = sent_tokenize(paragraph)
            breaks.extend(list(range(len(sentences),  + len(sentences)+len(paragraph_sentences))))
            breaks.append("\n")
            sentences.extend(paragraph_sentences)

    # Remove the last newline
    breaks = breaks[:-1]

    return sentences, breaks


def paragraph_detokenizer(sentences, breaks):
    """Restore the original pharagraph format from the indexes of sentences and newlines

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
