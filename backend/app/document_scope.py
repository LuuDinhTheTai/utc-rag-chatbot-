"""Interpret explicit multi-year document titles without using incidental body dates."""
import re
import unicodedata


def document_years(title, admission_year):
    text = ''.join(c for c in unicodedata.normalize('NFD', title.casefold())
                   if unicodedata.category(c) != 'Mn').replace('đ', 'd')
    years = {int(value) for value in re.findall(r'\b20\d{2}\b', text)}
    if len(years) < 2:
        return [admission_year]
    # A range and a list both declare coverage; a date mentioned in the body does not.
    for start, end in re.findall(r'\b(20\d{2})\s*(?:den|toi|[-–—])\s*(20\d{2})\b', text):
        if 0 < int(end) - int(start) <= 20:
            years.update(range(int(start), int(end) + 1))
    return sorted(years)
