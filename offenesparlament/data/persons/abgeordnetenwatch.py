#coding: utf-8
from lxml import etree

import sqlaload as sl

from offenesparlament.core import etl_engine
from offenesparlament.data.lib.reference import resolve_person, \
    BadReference

FEED_URL = "http://www.abgeordnetenwatch.de/koop/feeds/index.php?account=60e4a1f4fac1801c6486e85f8ed78a06&feed=3f39181c64fa435556f3ce86c24cd118"

PARTEI_MAPPING = {
    'CDU': 'CDU/CSU',
    'CSU': 'CDU/CSU',
    u'GRÜNE': u'B90/DIE GRÜNEN',
    'DIE LINKE': 'DIE LINKE.'
    }

def load_profiles(engine):
    doc = etree.parse(FEED_URL)
    Person = sl.get_table(engine, 'person')
    for profile in doc.findall('//PROFIL'):
        name = profile.findtext('.//VORNAME')
        if name is None:
            continue
        name += ' ' + profile.findtext('.//NACHNAME')
        partei = profile.findtext('.//PARTEI')
        name += ' ' + PARTEI_MAPPING.get(partei, partei)
        try:
            fp = resolve_person(name)
            sl.upsert(engine, Person,
                      {'awatch_url': profile.get('url'),
                       'fingerprint': fp},
                    unique=['fingerprint'])
        except BadReference: pass

