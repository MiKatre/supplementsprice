"""Turn shop titles, option labels and label text into comparable facts.

Everything here is pure and conservative: when a fact can't be read with confidence it stays None,
and the offer is either dropped (no size) or shown without the derived number (no protein).
"""

import html
import re
import unicodedata

CREATINE = re.compile(r"cr[eé]atin", re.I)
# Creatine products that aren't plain powder, or blends where creatine isn't the point.
CREATINE_EXCLUDE = re.compile(
    r"gumm|gominol|chewable|mastic|c[aá]psul|caps\b|g[eé]lules?|tabs?\b|tablet|comprim|pastill|"
    r"complex|pre[- ]?work|pre[- ]?entreno|pre[- ]?training|gainer|ganador|\bhcl\b|kre[- ]?alk|alcalin|"
    r"evokalyn|nitrate|malate|citrate|orotat|magnapower|creatin[ae]? ?\+|\+ ?cr[eé]atin|"
    r"amino|eaa|bcaa|electrolyt|electrolit|[eé]lectrolyt|hydration|hydratation|hidrataci|isotonic|recovery|recuper|shot|gel\b|bar\b|barrit|pack\b|duo\b|bundle|"
    r"lote|kit\b|sachet|sobre|stick|monodos|caja\b|box\b|\bx\s?\d+\s*(?:sobres|sticks)|"
    r"whey|prot[eé][ií]?n|soja|gainer|carb|maltodex|beta[- ]?alan|glutamin|taurin|caf[eé]ine|cafe[ií]na|"
    r"\shmb|vitamin|coenzim|q10|drink|malato|creamag|magnes|\s\+\s|gratis|free\b|offert",
    re.I,
)
WHEY = re.compile(r"whey|suero|lactos[eé]rum|isolat|aislad|\bwpi\b|\bwpc\b|prot[eé]ine? de lait|protimuscle", re.I)
# Whey-adjacent products that would distort a €/kg comparison.
WHEY_EXCLUDE = re.compile(
    r"no ?whey|syntha|secuencial|sequential|multi[- ]?phase|"
    r"gainer|ganador|mass\b|ca[sz][eé]in|micell|recovery|recupera|r[eé]cup|\boat|avoine|avena|"
    r"collag|col[aá]geno|"
    r"\bbar\b|bars\b|barre|barrit|cookie|galleta|cr[eè]me de riz|crema de arroz|rice cream|pancake|porridge|"
    r"brownie|cake|crepe|cr[eê]pe|mug|pudding|snack|chips|crisp|wafer|spread|cr[eè]me|crema|"
    r"vegan|v[eé]g[eé]tal|pea\b|guisante|pois\b|riz\b|arroz|rice|soja|soy|egg|huevo|oeuf|[oœ]uf|beef|vacuno|"
    r"hemp|c[aá]{1,2}?ñamo|chanvre|insect|blend de prot|mezcla de prot|multi[- ]?prot|evopro|"
    r"shaker|sample|muestra|[eé]chantillon|monodos|sachet|sobre|stick|dose unique|single serv|"
    r"rtd|ready to drink|bebida|boisson|drink|batido listo|pack\b|duo\b|bundle|lote|kit\b|box\b|caja\b|"
    r"coffret|gift|regalo|cadeau|creatin|cr[eé]atin|pre[- ]?work|glutamin|bcaa|eaa\b|amino|"
    r"lactase|diet|keto|slim|meal|repas|comida|bake|cuisine|cocina|baking|chocolate negro|"
    r"protein water|clear protein water|ice ?cream|helado|glace|yogur|yaourt|pizza|pasta|"
    r"caf[eé]\b|coffee|kaffee|espresso|latte|all[- ]in[- ]one|todo en uno|tout[- ]en[- ]un|"
    r"advent|calendar|calendario|calendrier|thanos|marvel|edici[oó]n limitada|limited edition",
    re.I,
)

FLAVOURLESS = re.compile(r"neutr|nature|natural|sin sabor|sans ar[oô]me|unflavou?r|plain|sin aroma|non aromat", re.I)
SWEETENER_FREE = re.compile(r"sin edulcorant|sans [eé]dulcorant|unsweetened|no sweetener|sin az[uú]car ni edulc", re.I)
TESTED = re.compile(r"informed[- ]?(?:sport|choice)|k[oö]lner liste|cologne list", re.I)

_UNIT = r"(kg|kilos?|g|gr|grs|gramos|grammes?|lbs?|libras?)"
_WEIGHT = re.compile(rf"(?<![\d.,])(\d{{1,4}}(?:[.,]\d{{1,3}})?)\s*{_UNIT}\b", re.I)
_PACK = re.compile(r"(\d{1,2})\s*[x×]\s*(\d{1,4}(?:[.,]\d+)?)\s*(kg|g)\b", re.I)
_NOT_NET_WEIGHT = re.compile(
    r"^\s*(?:de |of |d['’])?(?:prot|protein|creat|par |per |por |cada|each|"
    r"/\s*(?:dose|serv|raci|toma|portion|scoop|jour|d[ií]a|day))",
    re.I,
)


def clean(text: str | None) -> str:
    """HTML → collapsed plain text."""
    if not text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</(p|div|li|tr|td|th|h\d)>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = text.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def classify(title: str, extra: str = "") -> str | None:
    """'creatine', 'whey' or None, from the product title (plus product type/tags when given)."""
    t = title or ""
    if CREATINE.search(t):
        return None if CREATINE_EXCLUDE.search(t) else "creatine"
    if WHEY.search(t) or (WHEY.search(extra) and re.search(r"prot", t, re.I)):
        return None if WHEY_EXCLUDE.search(t) else "whey"
    return None


def _grams(value: str, unit: str) -> float:
    q = float(value.replace(",", "."))
    u = unit.lower()
    if u.startswith("k"):
        return q * 1000
    if u.startswith("l"):
        return round(q * 453.592, 1)
    return q


def parse_grams(*texts: str | None) -> float | None:
    """Net weight in grams from option labels or titles, first text that has one wins.

    Ignores per-serving amounts ("22 g de protéines"), sizes below 100 g and above 10 kg.
    "2 x 1 kg" packs become 2000 g.
    """
    for text in texts:
        if not text:
            continue
        pack = _PACK.search(text)
        if pack:
            g = int(pack.group(1)) * _grams(pack.group(2), pack.group(3))
            if 100 <= g <= 10000:
                return g
        for m in _WEIGHT.finditer(text):
            if _NOT_NET_WEIGHT.match(text[m.end():]):
                continue
            g = _grams(m.group(1), m.group(2))
            if 100 <= g <= 10000:
                return g
    return None


_SAMPLE = re.compile(
    r"sobre|sachet|monodos|unidos|muestra|sample|[eé]chantillon|stick|caja|box\b|bo[iî]te de \d+ |dosis individual|"
    r"single serv|serving pack|\bx ?\d+ ?(?:sobres|sachets|sticks|doses)",
    re.I,
)


def is_sample(label: str | None) -> bool:
    """A variant that is a sachet, a box of single doses or a sample, not a tub."""
    if not label:
        return False
    m = _WEIGHT.search(label)
    if m:  # "Sachet de 1 kg" is a bag; "Sobre de 5 g" is a sample
        return _grams(m.group(1), m.group(2)) < 100
    return bool(_SAMPLE.search(label))


def whey_type(title: str) -> str:
    t = title.lower()
    if re.search(r"hydro|hidroli|optipep|peptopro", t):
        return "hydrolysed"
    has_iso = re.search(r"isolat|aislad|\biso\b|\biso[- ]|\bwpi\b|clear", t)
    has_conc = re.search(r"concentr|\bwpc\b|blend|mezcla|mix\b|\+", t)
    if has_iso and has_conc:
        return "blend"
    return "isolate" if has_iso else "concentrate"


def is_creapure(*texts: str | None) -> bool:
    return any(t and re.search(r"creapure", t, re.I) for t in texts)


def is_native(title: str) -> bool:
    return bool(re.search(r"\bnati(ve|va|f)\b|protimuscle|native whey", title, re.I))


# Protein per 100 g of powder, as sold. Nutrition tables first (they're the regulated part of the label),
# marketing percentages only as a fallback, and never "dry matter" figures.
_NUM = r"(\d{1,2}(?:[.,]\d{1,2})?)"
_PROT_ROW = re.compile(
    r"prot[eé][ií]?n[ea]?s?\b[^\d\n]{0,60}?(\d{1,2}(?:[.,]\d{1,2})?)\s*g\b"
    r"(?:[^\d\n]{0,12}?(\d{1,2}(?:[.,]\d{1,2})?)\s*g\b)?",
    re.I,
)
_H100 = re.compile(r"(?:pour|por|per|par|/|in|je)?\s*100\s*g\b", re.I)
_HSERV = re.compile(
    r"(?:portion|dose|dosis|serving|raci[oó]n|toma|scoop|cacito|cacillo|cazo|porci[oó]n|serv)\w*"
    r"[^\d\n]{0,14}\(?\s*(\d{2}(?:[.,]\d)?)\s*g\b",
    re.I,
)
_PCT = [
    re.compile(rf"{_NUM}\s*%\s*(?:de\s+)?prot[eé][ií]?n[ea]?s?", re.I),
    re.compile(rf"prot[eé][ií]?n[ea]?s?\s*(?:\(?[^)\n]{{0,12}}\)?)?\s*[:=]?\s*{_NUM}\s*%", re.I),
]
_SERV_SENTENCE = re.compile(
    r"(\d{1,2}(?:[.,]\d)?)\s*g\s+(?:de\s+|of\s+)?prot[eé][ií]?n[ea]?s?\s+(?:per|por|pour|par|en|in|dans|cada)\s+"
    r"(?:une?\s+|a\s+|each\s+)?(?:\w+\s+){0,2}?(?:de\s+)?\(?(\d{2})\s*g",
    re.I,
)
_DRY = re.compile(r"seca|s[eè]che|dry|sur sec|ms\b|materia seca|mati[eè]re s[eè]che|trockenmasse", re.I)


def _f(x: str) -> float:
    return float(x.replace(",", "."))


def protein_per_100g(text: str | None) -> float | None:
    """Protein grams per 100 g of powder, read from label text. None when unsure."""
    if not text:
        return None
    text = clean(text) if "<" in text else text
    text = re.sub(r"\s+", " ", text)
    plausible = lambda v: 50 <= v <= 97  # noqa: E731 - whey powders live in this range
    for row in _PROT_ROW.finditer(text):
        before = text[max(0, row.start() - 700): row.start()]
        if _DRY.search(text[row.start(): row.end() + 15]):
            continue
        a = _f(row.group(1))
        b = _f(row.group(2)) if row.group(2) else None
        after = re.match(r"\s*g\b\s*(?:per|por|pour|par|/)\s*(?:une?\s+|a\s+)?\(?(\d{2})\s*g\b", text[row.end(1):])
        if after and 15 <= _f(after.group(1)) <= 80:
            v = round(a * 100 / _f(after.group(1)), 1)
            if plausible(v):
                return v
        if re.match(r"\s*/\s*100\s*g", text[row.end(1) + 1: row.end(1) + 12]):
            if plausible(a):
                return a
            continue
        serv = [m for m in _HSERV.finditer(before)]
        h100 = [m for m in _H100.finditer(before)]
        size = _f(serv[-1].group(1)) if serv else None
        if size and not 15 <= size <= 80:
            size = None
        if b is not None:
            hi, lo = max(a, b), min(a, b)
            if size and abs(lo * 100 / size - hi) <= max(2.0, hi * 0.04) and plausible(hi):
                return hi
            if h100 and plausible(hi) and lo < hi:
                return hi
            continue
        if size and (not h100 or serv[-1].start() > h100[-1].start()) and a < size:
            v = round(a * 100 / size, 1)
            if plausible(v):
                return v
        if h100 and plausible(a):
            return a
        if size and a < size:
            v = round(a * 100 / size, 1)
            if plausible(v):
                return v
    m = _SERV_SENTENCE.search(text)
    if m:
        v = round(_f(m.group(1)) * 100 / _f(m.group(2)), 1)
        if plausible(v):
            return v
    for rx in _PCT:
        for m in rx.finditer(text):
            if _DRY.search(text[max(0, m.start() - 40): m.end() + 40]):
                continue
            v = _f(m.group(1))
            if plausible(v):
                return v
    return None


_NET = re.compile(
    r"(?:pot|sachet|bote|bolsa|bo[iî]te|doypack|tarro|envase|bidon|contenance|contenu net|poids net|peso neto|"
    r"net weight|net wt|contenido neto|formato)\s*(?:de|:|=)?\s*(\d{1,4}(?:[.,]\d{1,3})?)\s*(kg|g)\b",
    re.I,
)


def net_weight(text: str | None) -> float | None:
    """'Sachet de 180 g', 'Poids net : 1 kg' → grams. For pages whose variants don't state a size."""
    if not text:
        return None
    for m in _NET.finditer(text):
        g = _grams(m.group(1), m.group(2))
        if 100 <= g <= 10000:
            return g
    return None


def flavour_of(*labels: str | None) -> str:
    return " / ".join(x for x in labels if x and x.lower() not in {"default title", "-"})
