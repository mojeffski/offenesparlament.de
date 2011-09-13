# -*- coding: UTF-8 -*-
import logging
import re, sys
import urllib2, urllib
import cookielib
import time
from threading import Lock 
from lxml import etree
from itertools import count
from urlparse import urlparse, urljoin, parse_qs
from StringIO import StringIO

from webstore.client import URL as WebStore

from offenesparlament.extract.util import threaded

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.NOTSET)

MAKE_SESSION_URL = "http://dipbt.bundestag.de/dip21.web/bt"
BASE_URL = "http://dipbt.bundestag.de/dip21.web/searchProcedures/simple_search.do?method=Suchen&offset=%s&anzahl=100"
ABLAUF_URL = "http://dipbt.bundestag.de/dip21.web/searchProcedures/simple_search_list.do?selId=%s&method=select&offset=100&anzahl=100&sort=3&direction=desc"
DETAIL_VP_URL = "http://dipbt.bundestag.de/dip21.web/searchProcedures/simple_search_detail_vp.do?vorgangId=%s"    

FACTION_MAPS = {
        u"BÜNDNIS 90/DIE GRÜNEN": u"B90/Die Grünen",
        u"DIE LINKE.": u"Die LINKE.",
        u"Bündnis 90/Die Grünen": u"B90/Die Grünen",
        u"Die Linke": "Die LINKE."
        }

DIP_GREMIUM_TO_KEY = {
    u"Ausschuss für Bildung, Forschung und Technikfolgenabschätzung": "a18",
    u"Ausschuss für Ernährung, Landwirtschaft und Verbraucherschutz": "a10",
    u"Ausschuss für Tourismus": "a20",
    u"Ausschuss für Umwelt, Naturschutz und Reaktorsicherheit": "a16",
    u"Ausschuss für Verkehr, Bau und Stadtentwicklung": "a15",
    u"Ausschuss für Arbeit und Soziales": "a11",
    u"Ausschuss für Familie, Senioren, Frauen und Jugend": "a13",
    u"Ausschuss für Wirtschaft und Technologie": "a09",
    u"Finanzausschuss": "a07",
    u"Haushaltsausschuss": "a08",
    u"Ausschuss für die Angelegenheiten der Europäischen Union": "a21",
    u"Ausschuss für Agrarpolitik und Verbraucherschutz": "a10",
    u"Ausschuss für Innere Angelegenheiten": "a04",
    u"Wirtschaftsausschuss": "a09",
    u"Ausschuss für Gesundheit": "a14",
    u"Ausschuss für Wahlprüfung, Immunität und Geschäftsordnung": "a01",
    u"Rechtsausschuss": "a06",
    u"Ausschuss für Fragen der Europäischen Union": "a21",
    u"Ausschuss für Kulturfragen": "a22",
    u"Gesundheitsausschuss": "a14",
    u"Ausschuss für Menschenrechte und humanitäre Hilfe": "a17",
    u"Ausschuss für wirtschaftliche Zusammenarbeit und Entwicklung": "a19",
    u"Ausschuss für Auswärtige Angelegenheiten": "a03",
    u"Ausschuss für Kultur und Medien": "a22",
    u"Sportausschuss": "a05",
    u"Auswärtiger Ausschuss": "a03",
    u"Ausschuss für Arbeit und Sozialpolitik": "a11",
    u"Ausschuss für Frauen und Jugend": "a13",
    u"Ausschuss für Städtebau, Wohnungswesen und Raumordnung": "a15",
    u"Innenausschuss": "a04",
    u"Verkehrsausschuss": "a15",
    u"Verteidigungsausschuss": "a12",
    u"Ausschuss für Familie und Senioren": "a13",
    u"Petitionsausschuss": "a02",
    u"Ausschuss für Verteidigung": "a12",
    u"Ältestenrat": "002"
    }


DIP_ABLAUF_STATES_FINISHED = { 
    u'Beantwortet': True,
    u'Abgeschlossen': True,
    u'Abgelehnt': True,
    u'In der Beratung (Einzelheiten siehe Vorgangsablauf)': False,
    u'Verkündet': True,
    u'Angenommen': True,
    u'Keine parlamentarische Behandlung': False,
    u'Überwiesen': False,
    u'Beschlussempfehlung liegt vor': False,
    u'Noch nicht beraten': False,
    u'Für erledigt erklärt': True,
    u'Noch nicht beantwortet': False,
    u'Zurückgezogen': True,
    u'Dem Bundestag zugeleitet - Noch nicht beraten': False,
    u'Nicht beantwortet wegen Nichtanwesenheit des Fragestellers': True,
    u'Zustimmung erteilt': True,
    u'Keine parlamentarische Behandlung': True,
    u'Aufhebung nicht verlangt': False,
    u'Den Ausschüssen zugewiesen': False,
    u'Zusammengeführt mit... (siehe Vorgangsablauf)': True,
    u'Dem Bundesrat zugeleitet - Noch nicht beraten': False,
    u'Zustimmung (mit Änderungen) erteilt': True,
    u'Bundesrat hat Vermittlungsausschuss nicht angerufen': False,
    u'Bundesrat hat zugestimmt': False,
    u'1. Durchgang im Bundesrat abgeschlossen': False,
    u'Einbringung abgelehnt': True,
    u'Verabschiedet': True,
    u'Entlastung erteilt': True,
    u'Abschlussbericht liegt vor': True,
    u'Erledigt durch Ende der Wahlperiode (§ 125 GOBT)': True,
    u'Zuleitung beschlossen': False,
    u'Zuleitung in geänderter Fassung beschlossen': False,
    u'Für gegenstandslos erklärt': False,
    u'Nicht ausgefertigt wegen Zustimmungsverweigerung des Bundespräsidenten': False,
    u'Im Vermittlungsverfahren': False,
    u'Zustimmung versagt': True,
    u'Einbringung in geänderter Fassung beschlossen': False,
    u'Bundesrat hat keinen Einspruch eingelegt': False,
    u'Bundesrat hat Einspruch eingelegt': False,
    u'Zuleitung in Neufassung beschlossen': True,
    u'Untersuchungsausschuss eingesetzt': False
}

jar = None
lock = Lock()

inline_re = re.compile(r"<!--(.*?)-->", re.M + re.S)
inline_comments_re = re.compile(r"<-.*->", re.M + re.S)

def inline_xml_from_page(page):
    for comment in inline_re.findall(page):
        comment = comment.strip()
        if comment.startswith("<?xml"):
            comment = inline_comments_re.sub('', comment)
            return etree.parse(StringIO(comment))

def get_dip_with_cookie(url, method='GET', data={}):
    class _Request(urllib2.Request):
        def get_method(self): 
            return method

    for i in range(3):
        lock.acquire()
        try:
            def _req(url, jar, data={}):
                _data = urllib.urlencode(data) 
                req = _Request(url, _data)
                jar.add_cookie_header(req)
                fp = urllib2.urlopen(req)
                jar.extract_cookies(fp, req)
                return fp
            global jar
            if jar is None:
                jar = cookielib.CookieJar()
                fp = _req(MAKE_SESSION_URL, jar)
                fp.read()
                fp.close()
            return _req(url, jar, data=data)
        except urllib2.HTTPError, he:
            log.exception(he)
            time.sleep(2)
        finally:
            lock.release()


def _get_dokument(hrsg, typ, nummer, link=None):
    nummer = nummer.lstrip("0")
    return {'link': link, 'hrsg': hrsg, 
            'typ': typ, 'nummer': nummer}

def dokument_by_id(hrsg, typ, nummer, link=None):
    if '/' in nummer:
        section, nummer = nummer.split("/", 1)
        nummer = nummer.lstrip("0")
        nummer = section + "/" + nummer
    return _get_dokument(hrsg, typ, nummer, link=link)

def dokument_by_url(url):
    if url is None or not url:
        return
    if '#' in url:
        url, fragment = url.split('#', 1)
    name, file_ext = url.rsplit('.', 1)
    base = name.split('/', 4)[-1].split("/")
    hrsg, typ = {"btd": ("BT", "drs"),
                 "btp": ("BT", "plpr"),
                 "brd": ("BR", "drs"),
                 "brp": ("BR", "plpr")
                }.get(base[0])
    if hrsg == 'BR' and typ == 'plpr': 
        nummer = base[1]
    elif hrsg == 'BR' and typ == 'drs':
        nummer = "/".join(base[-1].split("-"))
    elif hrsg == 'BT':
        s = base[1]
        nummer = base[-1][len(s):].lstrip("0")
        nummer = s + "/" + nummer
    return _get_dokument(hrsg, typ, nummer, link=url)


END_ID = re.compile("[,\n]")
def dokument_by_name(name):
    if name is None or not name:
        return
    if ' - ' in name:
        date, name = name.split(" - ", 1)
    else:
        log.warn("NO DATE: %s" % name)
    if ',' in name or '\n' in name:
        name, remainder = END_ID.split(name, 1)
    typ, nummer = name.strip().split(" ", 1)
    hrsg, typ = {
            "BT-Plenarprotokoll": ("BT", "plpr"), 
            "BT-Drucksache": ("BT", "drs"), 
            "BR-Plenarprotokoll": ("BR", "plpr"),
            "BR-Drucksache": ("BR", "drs")
            }.get(typ, ('BT', 'drs'))
    if hrsg == 'BT' and typ == 'drs':
        f, s = nummer.split("/", 1)
        s = s.split(" ")[0]
        s = s.zfill(5)
        link = "http://dipbt.bundestag.de:80/dip21/btd/%s/%s/%s%s.pdf" % (f, s[:3], f, s)
    return _get_dokument(hrsg, typ, nummer, link=link)


# EU Links
COM_LINK = re.compile('.*Kom.\s\((\d{1,4})\)\s(\d{1,6}).*')
SEC_LINK = re.compile('.*Sek.\s\((\d{1,4})\)\s(\d{1,6}).*')
RAT_LINK = re.compile('.*Ratsdok.\s*([\d\/]*).*')
EUR_LEX_RECH = "http://eur-lex.europa.eu/Result.do?T1=%s&T2=%s&T3=%s&RechType=RECH_naturel"
LEX_URI = "http://eur-lex.europa.eu/LexUriServ/LexUriServ.do?uri=%s:%s:%s:FIN:DE:%s"
CONS = "http://register.consilium.europa.eu/servlet/driver?lang=DE&typ=Advanced&cmsid=639&ff_COTE_DOCUMENT=%s&fc=REGAISDE&md=100&rc=1&nr=1&page=Detail"
def expand_dok_nr(ablauf):
    if ablauf['eu_dok_nr']:
        com_match = COM_LINK.match(ablauf['eu_dok_nr'])
        if com_match:
            year, process = com_match.groups()
            ablauf['eur_lex_url'] = EUR_LEX_RECH % ("V5", year, process)
            ablauf['eur_lex_pdf'] = LEX_URI % ("COM", year, process.zfill(4), "PDF")
        sec_match = SEC_LINK.match(ablauf['eu_dok_nr'])
        if sec_match:
            year, process = sec_match.groups()
            ablauf['eur_lex_url'] = EUR_LEX_RECH % ("V7", year, process)
            ablauf['eur_lex_pdf'] = LEX_URI % ("SEC", year, process.zfill(4), "PDF")
        rat_match = RAT_LINK.match(ablauf['eu_dok_nr'])
        if rat_match:
            id, = rat_match.groups()
            ablauf['consilium_url'] = CONS % urllib.quote(id)
    return ablauf


def scrape_activities(ablauf, db):
    urlfp = get_dip_with_cookie(DETAIL_VP_URL % ablauf['key'])
    if urlfp is None:
        return
    xml = inline_xml_from_page(urlfp.read())
    urlfp.close()
    if xml is not None: 
        for elem in xml.findall(".//VORGANGSPOSITION"):
            scrape_activity(ablauf, elem, db)

def scrape_activity(ablauf, elem, db):
    urheber = elem.findtext("URHEBER")
    fundstelle = elem.findtext("FUNDSTELLE")
    Position = db['position']
    p = Position.find_one(urheber=urheber, 
                          fundstelle=fundstelle, 
                          ablauf_source_url=ablauf['source_url'])
    if p is not None:
        return 
    p = {'ablauf_source_url': ablauf['source_url'], 
         'urheber': urheber,
         'fundstelle': fundstelle}
    pos_keys = p.copy()
    p['zuordnung'] = elem.findtext("ZUORDNUNG")
    p['fundstelle_url'] = elem.findtext("FUNDSTELLE_LINK")
    
    for zelem in elem.findall("ZUWEISUNG"):
        z = pos_keys.copy()
        z['text'] = zelem.findtext("AUSSCHUSS_KLARTEXT")
        z['federfuehrung'] = zelem.find("FEDERFUEHRUNG") is not None
        z['gremium_key'] = DIP_GREMIUM_TO_KEY.get(z['text'])
        db['zuweisung'].writerow(z)
        
    Beschluss = db['beschluss']
    for belem in elem.findall("BESCHLUSS"):
        b = pos_keys.copy()
        b['seite'] = belem.findtext("BESCHLUSSSEITE")
        b['dokument_text'] = belem.findtext("BEZUGSDOKUMENT")
        b['tenor'] = belem.findtext("BESCHLUSSTENOR")
        Beschluss.writerow(b)

    try:
        dokument = dokument_by_url(p['fundstelle_url']) or \
            dokument_by_name(p['fundstelle'])
        dokument.update(pos_keys)
        dokument['ablauf_key'] = ablauf['key']
        dokument['wahlperiode'] = ablauf['wahlperiode']
        db['referenz'].writerow(dokument, unique_columns=[
                'link', 'wahlperiode', 'ablauf_key', 'seiten'
                ])
    except Exception, e:
        log.exception(e)

    Position.writerow(p)
    Person = db['person']
    Beitrag = db['beitrag']
    for belem in elem.findall("PERSOENLICHER_URHEBER"):
        b = pos_keys.copy()
        b['vorname'] = belem.findtext("VORNAME")
        b['nachname'] = belem.findtext("NACHNAME")
        b['funktion'] = belem.findtext("FUNKTION")
        b['ort'] = belem.findtext('WAHLKREISZUSATZ')
        p = Person.find_one(vorname=b['vorname'],
                nachname=b['nachname'],
                ort=b['ort'])
        if p is not None:
            b['person_source_url'] = p['source_url']
        #q = Rolle.query.filter_by(funktion=funktion)
        #r = q.filter_by(person_id=p.id).first()
        #if r is None:
        #    r = Rolle()
        #    r.funktion = funktion
        b['ressort'] = belem.findtext("RESSORT")
        b['land'] = belem.findtext("BUNDESLAND")
        b['fraktion'] = FACTION_MAPS.get(belem.findtext("FRAKTION"), 
            belem.findtext("FRAKTION"))
        #    r.person = ps
        #    db.session.add(r)

        b['seite'] = belem.findtext("SEITE")
        b['art'] = belem.findtext("AKTIVITAETSART")
        Beitrag.writerow(b)

def scrape_ablauf(url, db):
    Ablauf = db['ablauf']
    a = Ablauf.find_one(source_url=url)
    if a is not None and a['abgeschlossen'] == 'True':
        log.info("Skipping: %s" % a['titel'])
        return
    if a is None:
        a = {}
    a['key'] = key = parse_qs(urlparse(url).query).get('selId')[0]
    urlfp = get_dip_with_cookie(url)
    if urlfp is None:
        return
    doc = inline_xml_from_page(urlfp.read())
    urlfp.close()
    if doc is None: 
        log.warn("Could not find embedded XML in Ablauf: %s", a['key'])
        return
    a['wahlperiode'] = wp = doc.findtext("WAHLPERIODE")
    a['typ'] = doc.findtext("VORGANGSTYP")
    a['titel'] = doc.findtext("TITEL")

    if not a['titel'] or not len(a['titel'].strip()):
        return

    if '\n' in a['titel']:
        t, k = a['titel'].rsplit('\n', 1)
        k = k.strip()
        if k.startswith('KOM') or k.startswith('SEK'):
            a['titel'] = t
    a['initiative'] = doc.findtext("INITIATIVE")
    a['stand'] = doc.findtext("AKTUELLER_STAND")
    a['signatur'] = doc.findtext("SIGNATUR")
    a['gesta_id'] = doc.findtext("GESTA_ORDNUNGSNUMMER")
    a['eu_dok_nr'] = doc.findtext("EU_DOK_NR")
    a['abstrakt'] = doc.findtext("ABSTRAKT")
    a['sachgebiet'] = doc.findtext("SACHGEBIET")
    a['zustimmungsbeduerftig'] = doc.findtext("ZUSTIMMUNGSBEDUERFTIGKEIT")
    a['source_url'] = url
    #a.schlagworte = []
    for sw in doc.findall("SCHLAGWORT"):
        wort = {'wort': sw.text, 'key': key, 'wahlperiode': wp}
        db['schlagwort'].writerow(wort, unique_columns=wort.keys())
    log.info("Ablauf %s: %s" % (key, a['titel']))
    a['titel'] = a['titel'].strip().lstrip('.').strip()
    a = expand_dok_nr(a)
    a['abgeschlossen'] = DIP_ABLAUF_STATES_FINISHED.get(a['stand'], False)
    if 'Originaltext der Frage(n):' in a['abstrakt']:
        _, a['abstrakt'] = a['abstrakt'].split('Originaltext der Frage(n):', 1)

    for elem in doc.findall("WICHTIGE_DRUCKSACHE"):
        link = elem.findtext("DRS_LINK")
        hash = None
        if link is not None and '#' in link:
            link, hash = link.rsplit('#', 1)
        dokument = dokument_by_id(elem.findtext("DRS_HERAUSGEBER"), 
                'drs', elem.findtext("DRS_NUMMER"), link=link)
        dokument['text'] = elem.findtext("DRS_TYP")
        dokument['seiten'] = hash
        dokument['wahlperiode'] = wp
        dokument['ablauf_key'] = key
        db['referenz'].writerow(dokument, unique_columns=[
            'link', 'wahlperiode', 'ablauf_key', 'seiten'
            ])

    for elem in doc.findall("PLENUM"):
        link = elem.findtext("PLPR_LINK")
        if link is not None and '#' in link:
            link, hash = link.rsplit('#', 1)
        dokument = dokument_by_id(elem.findtext("PLPR_HERAUSGEBER"), 
                'plpr', elem.findtext("PLPR_NUMMER"), link=link)
        dokument['text'] = elem.findtext("PLPR_KLARTEXT")
        dokument['seiten'] = elem.findtext("PLPR_SEITEN")
        dokument['wahlperiode'] = wp
        dokument['ablauf_key'] = key
        db['referenz'].writerow(dokument, unique_columns=[
            'link', 'wahlperiode', 'ablauf_key', 'seiten'
            ])

    Ablauf.writerow(a, unique_columns=['key', 'wahlperiode'])
    scrape_activities(a, db)


def load_dip(db):
    for url in load_dip_index():
        scrape_ablauf(url, db)
    #def bound_scrape(url):
    #    scrape_ablauf(url, db)
    #threaded(load_dip_index(), bound_scrape)

def load_dip_index():
    for offset in count():
        urlfp = get_dip_with_cookie(BASE_URL % (offset*100))
        if urlfp is None:
            return
        root = etree.parse(urlfp, etree.HTMLParser())
        urlfp.close()
        table = root.find(".//table[@summary='Ergebnisliste']")
        if table is None: return
        for result in table.findall(".//a[@class='linkIntern']"):
            yield urljoin(BASE_URL, result.get('href'))

if __name__ == '__main__':
    assert len(sys.argv)==2, "Need argument: webstore-url!"
    db, _ = WebStore(sys.argv[1])
    print "DESTINATION", db
    load_dip(db)

