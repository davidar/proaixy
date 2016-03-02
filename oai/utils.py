# -*- encoding: utf-8 -*-
from __future__ import unicode_literals

from unidecode import unidecode
from django.utils.timezone import make_naive, UTC
import datetime
import re
import hashlib
import unicode_tex
from unidecode import unidecode
from lxml.html.clean import Cleaner
from lxml.html import fromstring, _transform_result
from lxml import etree
from io import StringIO

filter_punctuation_alphanum_regex = re.compile(r'\w')
def filter_punctuation(lst):
    return filter(lambda x: filter_punctuation_alphanum_regex.findall(x) != [], lst)

def nocomma(lst):
    """
    Join fields using ',' ensuring that it does not appear in the fields
    """
    lst = map(lambda x: str(x).replace(',','').replace('\n',''), lst)
    lst = [x if x else ' ' for x in lst]
    return ','.join(lst)

split_re = re.compile(r'[ .,-]*')
def split_words(string):
    return filter(lambda x: x != '', split_re.split(string))

def ulower(s):
    return unicode(s).lower()

def isupper(s):
    if type(s) == type(u''):
        return unicode.isupper(s)
    else:
        return str.isupper(s)

def nstr(s):
    if s:
        return s
    return ''

def nstrip(s):
    if s:
        return s.strip()
    return None


class KeyValuePair(object):
    def __init__(self, key, val):
        self.key = key
        self.val = val

def to_kv_pairs(dct):
    for k in dct:
        yield KeyValuePair(k, dct[k])

def isupper(s):
    if type(s) == type(u''):
        return unicode.isupper(s)
    else:
        return str.isupper(s)

def remove_diacritics(s):
    if type(s) == type(u''):
        return unidecode(s)
    else:
        return s

def iunaccent(s):
    return remove_diacritics(s).lower()


def ndt(d):
    if d:
        return make_naive(d, UTC()).isoformat()
    return ''

class OaiRequestError(Exception):
    def __init__(self, code, reason):
        self.code = code
        self.reason = reason
    def __str__(self):
        return self.reason

from oai.name import *
# Utils taken from Dissemin

## HTML sanitizing for the title

overescaped_re = re.compile(r'&amp;#(\d+);')
unicode4_re = re.compile(r'(\\u[0-9A-Z]{4})(?![0-9A-Z])')
whitespace_re = re.compile(r'\s+')

html_cleaner = Cleaner()
html_cleaner.allow_tags = ['sub','sup','b','span']
html_cleaner.remove_unknown_tags = False

html_killer = Cleaner()
html_killer.allow_tags = ['div']
html_killer.remove_unknown_tags = False

latexmath_re = re.compile(r'\$(\S[^$]*\S|\S)\$')
def remove_latex_math_dollars(string):
    return latexmath_re.sub(r'\1', string)

latex_command_re = re.compile(r'(\\([a-zA-Z]+|[.=\'"])({[^}]*})*)')
def unescape_latex(s):
    def conditional_replace(fragment):
        rep = unicode_tex.tex_to_unicode_map.get(fragment.group(0))
        return rep if rep is not None else fragment.group(0)

    return latex_command_re.sub(conditional_replace, s)

latex_one_character_braces_re = re.compile(r'(^|(^|[^\\])\b(\w+)){(.)}', re.UNICODE)
latex_full_line_braces_re = re.compile(r'^{(.*)}$')
latex_word_braces_re = re.compile(r'(^|\s){(\w+)}($|\s)', re.UNICODE)
def remove_latex_braces(s):
    """
    Removes spurious braces such as in "Th{é}odore" or "a {CADE} conference"
    This should be run *after* unescape_latex
    """
    s = latex_full_line_braces_re.sub(r'\1', s)
    s = latex_word_braces_re.sub(r'\1\2\3', s)
    s = latex_one_character_braces_re.sub(r'\1\4', s)
    s = latex_one_character_braces_re.sub(r'\1\4', s)
    s = latex_one_character_braces_re.sub(r'\1\4', s)
    return s

def sanitize_html(s):
    s = overescaped_re.sub(r'&#\1;', s)
    s = unicode4_re.sub(lambda x: x.group(1).decode('unicode-escape'), s)
    s = whitespace_re.sub(r' ', s)
    s = unescape_latex(s)
    orig = html_cleaner.clean_html('<span>'+s+'</span>')
    return orig[6:-7]

def kill_html(s):
    """
    Removes every tag except <div> (but there are no
    <div> in titles as sanitize_html removes them)
    """
    orig = html_killer.clean_html('<div>'+s+'</div>')
    return orig[5:-6]


##### Paper fingerprinting

stripped_chars = re.compile(r'[^- a-z0-9]')
def create_paper_plain_fingerprint(title, authors, year):
    title = kill_html(title)
    title = remove_diacritics(title).lower()
    title = stripped_chars.sub('',title)
    title = title.strip()
    title = re.sub('[ -]+', '-', title)
    buf = title

    # If the title is long enough, we return the fingerprint as is
    if len(buf) > 50:
        return buf
    
    # If the title is just one word, we add the year (for "Preface", "Introduction" cases)
    if len(title) < 16:
        buf += '-'+str(year)

    author_names_list = []
    for author in authors:
        if not author:
            continue
        author = (remove_diacritics(author[0]),remove_diacritics(author[1]))
        # Initials of the given names are not used anymore in the fingerprints
        # initials = map(lambda x: x[0].lower(), split_words(author[0]))

        # Last name, without the small words such as "van", "der", "de"…
        last_name_words, last_name_separators = split_name_words(author[1])
        last_words = []
        for i in range(len(last_name_words)):
            if (last_name_words[i][0].isupper() or
                (i > 0 and last_name_separators[i-1] == '-')):
                last_words.append(last_name_words[i])
             
        # If no word was uppercased, fall back on all the words
        if not last_words:
            last_words = last_name_words

        # Lowercase
        last_words = map(ulower, last_words)
        fp = '-'.join(last_words)
        author_names_list.append(fp)

    author_names_list.sort()
    for fp in author_names_list:
        buf += '/'+fp

    return buf

def create_paper_fingerprint(title, authors, year):
    m = hashlib.md5()
    m.update(create_paper_plain_fingerprint(title, authors, year))
    return m.hexdigest()

### Partial date representation

def parse_int(val, default):
    try:
        return int(val)
    except ValueError:
        return default
    except TypeError:
        return default

def date_from_dateparts(dateparts):
    year = 1970 if len(dateparts) < 1 else parse_int(dateparts[0], 1970)
    month = 01 if len(dateparts) < 2 else parse_int(dateparts[1], 01)
    day = 01 if len(dateparts) < 3 else parse_int(dateparts[2], 01)
    return datetime.date(year=year, month=month, day=day)

def tolerant_datestamp_to_datetime(datestamp):
    """A datestamp to datetime that's more tolerant of diverse inputs.
    Taken from pyoai.

    Not used inside pyoai itself right now, but can be used when defining
    your own metadata schema if that has a broader variety of datetimes
    in there.
    """
    splitted = datestamp.split('T')
    if len(splitted) == 2:
        d, t = splitted
        # if no Z is present, raise error
        if t[-1] != 'Z':
            raise DatestampError(datestamp)
        # split off Z at the end
        t = t[:-1]
    else:
        d = splitted[0]
        t = '00:00:00'
    d_splitted = d.split('-')
    if len(d_splitted) == 3:
        YYYY, MM, DD = d_splitted
    elif len(d_splitted) == 2:
        YYYY, MM = d_splitted
        DD = '01'
    elif len(d_splitted) == 1:
        YYYY = d_splitted[0]
        MM = '01'
        DD = '01'   
    else:
        raise ValueError("Invalid datestamp: "+str(datestamp))
    
    t_splitted = t.split(':')
    if len(t_splitted) == 3:
        hh, mm, ss = t_splitted
    else:
        raise ValueError("Invalid datestamp: "+str(datestamp))
    return datetime.datetime(
        int(YYYY), int(MM), int(DD), int(hh), int(mm), int(ss))


#### Crossref utilities

def convert_to_name_pair(dct):
    if 'family' in dct and 'given' in dct:
        return (dct['given'],dct['family'])
    elif 'family' in dct:
        return ('',dct['family'])
    elif 'literal' in dct:
        return parse_comma_name(dct['literal'])

def parse_crossref_date(date):
    ret = None
    if 'date-parts' in date:
        try:
            for date in date['date-parts']:
                ret = date_from_dateparts(date)
                if ret is not None:
                    return ret
        except ValueError:
            pass
    if 'raw' in date:
        ret = tolerant_datestamp_to_datetime(date['raw']).date()
    return ret

def get_fingerprint_from_citeproc(citeproc):
    try:
        title = citeproc.get('title')
        authors = map(convert_to_name_pair, citeproc.get('author', []))
        pubdate = parse_crossref_date(citeproc.get('issued'))
        if not title or not pubdate or not authors:
            return
        if type(title) == list:
            title = title[0]
        return create_paper_fingerprint(title, authors, pubdate.year)
    except (ValueError, AttributeError, TypeError):
        return



