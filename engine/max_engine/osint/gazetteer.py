"""Country gazetteer — map free text / GDELT country names to ISO-A3 codes.

ISO-A3 is the canonical key everywhere downstream; the desktop map joins its
atlas polygons to these codes. GDELT reports a country *name* per article and RSS
items carry none at all, so we normalize both through one alias table. Coverage
is the newsworthy set, not every micro-state — unmatched items are simply dropped
from the per-country heat (best-effort, as flagged in the UI).

Aliases are lowercase and include common short names, GDELT spellings, and the
demonyms most likely to appear in a headline (e.g. "ukrainian" -> UKR).
"""

from __future__ import annotations

import re

# iso_a3 -> (display name, [aliases])
_COUNTRIES: dict[str, tuple[str, list[str]]] = {
    "USA": ("United States", ["united states", "u.s.", "usa", "america", "american", "washington"]),
    "GBR": (
        "United Kingdom",
        ["united kingdom", "uk", "britain", "british", "england", "scotland", "wales", "london"],
    ),
    "UKR": ("Ukraine", ["ukraine", "ukrainian", "kyiv", "kiev"]),
    "RUS": ("Russia", ["russia", "russian", "moscow", "kremlin"]),
    "CHN": ("China", ["china", "chinese", "beijing"]),
    "TWN": ("Taiwan", ["taiwan", "taiwanese", "taipei"]),
    "JPN": ("Japan", ["japan", "japanese", "tokyo"]),
    "KOR": ("South Korea", ["south korea", "korea, south", "south korean", "seoul"]),
    "PRK": ("North Korea", ["north korea", "korea, north", "north korean", "pyongyang"]),
    "IND": ("India", ["india", "indian", "new delhi", "delhi"]),
    "PAK": ("Pakistan", ["pakistan", "pakistani", "islamabad"]),
    "AFG": ("Afghanistan", ["afghanistan", "afghan", "kabul", "taliban"]),
    "IRN": ("Iran", ["iran", "iranian", "tehran"]),
    "IRQ": ("Iraq", ["iraq", "iraqi", "baghdad"]),
    "ISR": ("Israel", ["israel", "israeli", "jerusalem", "tel aviv"]),
    "PSE": ("Palestine", ["palestine", "palestinian", "gaza", "west bank", "hamas"]),
    "SYR": ("Syria", ["syria", "syrian", "damascus"]),
    "LBN": ("Lebanon", ["lebanon", "lebanese", "beirut", "hezbollah"]),
    "SAU": ("Saudi Arabia", ["saudi arabia", "saudi", "riyadh"]),
    "ARE": (
        "United Arab Emirates",
        ["united arab emirates", "uae", "dubai", "abu dhabi"],
    ),
    "QAT": ("Qatar", ["qatar", "qatari", "doha"]),
    "YEM": ("Yemen", ["yemen", "yemeni", "sanaa", "houthi"]),
    "TUR": ("Turkey", ["turkey", "turkish", "ankara", "istanbul", "turkiye"]),
    "EGY": ("Egypt", ["egypt", "egyptian", "cairo"]),
    "LBY": ("Libya", ["libya", "libyan", "tripoli"]),
    "TUN": ("Tunisia", ["tunisia", "tunisian", "tunis"]),
    "DZA": ("Algeria", ["algeria", "algerian", "algiers"]),
    "MAR": ("Morocco", ["morocco", "moroccan", "rabat"]),
    "NGA": ("Nigeria", ["nigeria", "nigerian", "abuja", "lagos"]),
    "ETH": ("Ethiopia", ["ethiopia", "ethiopian", "addis ababa"]),
    "KEN": ("Kenya", ["kenya", "kenyan", "nairobi"]),
    "ZAF": (
        "South Africa",
        ["south africa", "south african", "johannesburg", "pretoria", "cape town"],
    ),
    "SDN": ("Sudan", ["sudan", "sudanese", "khartoum"]),
    "SSD": ("South Sudan", ["south sudan", "s. sudan", "juba"]),
    "SOM": ("Somalia", ["somalia", "somali", "mogadishu"]),
    "COD": (
        "DR Congo",
        ["democratic republic of the congo", "dr congo", "dem. rep. congo", "drc", "kinshasa"],
    ),
    "MLI": ("Mali", ["mali", "malian", "bamako"]),
    "GHA": ("Ghana", ["ghana", "ghanaian", "accra"]),
    "CMR": ("Cameroon", ["cameroon", "cameroonian", "yaounde"]),
    "FRA": ("France", ["france", "french", "paris"]),
    "DEU": ("Germany", ["germany", "german", "berlin"]),
    "ITA": ("Italy", ["italy", "italian", "rome"]),
    "ESP": ("Spain", ["spain", "spanish", "madrid"]),
    "PRT": ("Portugal", ["portugal", "portuguese", "lisbon"]),
    "NLD": ("Netherlands", ["netherlands", "dutch", "amsterdam", "the hague"]),
    "BEL": ("Belgium", ["belgium", "belgian", "brussels"]),
    "CHE": ("Switzerland", ["switzerland", "swiss", "geneva", "zurich", "bern"]),
    "AUT": ("Austria", ["austria", "austrian", "vienna"]),
    "POL": ("Poland", ["poland", "polish", "warsaw"]),
    "SWE": ("Sweden", ["sweden", "swedish", "stockholm"]),
    "NOR": ("Norway", ["norway", "norwegian", "oslo"]),
    "FIN": ("Finland", ["finland", "finnish", "helsinki"]),
    "DNK": ("Denmark", ["denmark", "danish", "copenhagen"]),
    "IRL": ("Ireland", ["ireland", "irish", "dublin"]),
    "GRC": ("Greece", ["greece", "greek", "athens"]),
    "CZE": ("Czechia", ["czechia", "czech republic", "czech", "prague"]),
    "HUN": ("Hungary", ["hungary", "hungarian", "budapest"]),
    "ROU": ("Romania", ["romania", "romanian", "bucharest"]),
    "BGR": ("Bulgaria", ["bulgaria", "bulgarian", "sofia"]),
    "SRB": ("Serbia", ["serbia", "serbian", "belgrade"]),
    "HRV": ("Croatia", ["croatia", "croatian", "zagreb"]),
    "BIH": (
        "Bosnia and Herzegovina",
        ["bosnia and herzegovina", "bosnia", "bosnia and herz.", "sarajevo"],
    ),
    "BLR": ("Belarus", ["belarus", "belarusian", "minsk"]),
    "GEO": ("Georgia", ["georgia", "georgian", "tbilisi"]),
    "ARM": ("Armenia", ["armenia", "armenian", "yerevan"]),
    "AZE": ("Azerbaijan", ["azerbaijan", "azerbaijani", "baku"]),
    "KAZ": ("Kazakhstan", ["kazakhstan", "kazakh", "astana"]),
    "UZB": ("Uzbekistan", ["uzbekistan", "uzbek", "tashkent"]),
    "CAN": ("Canada", ["canada", "canadian", "ottawa", "toronto"]),
    "MEX": ("Mexico", ["mexico", "mexican", "mexico city"]),
    "BRA": ("Brazil", ["brazil", "brazilian", "brasilia", "sao paulo"]),
    "ARG": ("Argentina", ["argentina", "argentine", "argentinian", "buenos aires"]),
    "CHL": ("Chile", ["chile", "chilean", "santiago"]),
    "COL": ("Colombia", ["colombia", "colombian", "bogota"]),
    "VEN": ("Venezuela", ["venezuela", "venezuelan", "caracas"]),
    "PER": ("Peru", ["peru", "peruvian", "lima"]),
    "ECU": ("Ecuador", ["ecuador", "ecuadorian", "quito"]),
    "BOL": ("Bolivia", ["bolivia", "bolivian", "la paz"]),
    "CUB": ("Cuba", ["cuba", "cuban", "havana"]),
    "HTI": ("Haiti", ["haiti", "haitian", "port-au-prince"]),
    "AUS": ("Australia", ["australia", "australian", "canberra", "sydney"]),
    "NZL": ("New Zealand", ["new zealand", "wellington", "auckland"]),
    "IDN": ("Indonesia", ["indonesia", "indonesian", "jakarta"]),
    "MYS": ("Malaysia", ["malaysia", "malaysian", "kuala lumpur"]),
    "SGP": ("Singapore", ["singapore", "singaporean"]),
    "THA": ("Thailand", ["thailand", "thai", "bangkok"]),
    "VNM": ("Vietnam", ["vietnam", "vietnamese", "hanoi"]),
    "PHL": ("Philippines", ["philippines", "filipino", "philippine", "manila"]),
    "MMR": ("Myanmar", ["myanmar", "burma", "burmese", "naypyidaw", "yangon"]),
    "BGD": ("Bangladesh", ["bangladesh", "bangladeshi", "dhaka"]),
    "LKA": ("Sri Lanka", ["sri lanka", "sri lankan", "colombo"]),
    "NPL": ("Nepal", ["nepal", "nepali", "kathmandu"]),
}

# alias -> iso, longest aliases first so "south korea" wins over "korea".
_ALIAS_TO_ISO: dict[str, str] = {}
for _iso, (_name, _aliases) in _COUNTRIES.items():
    _ALIAS_TO_ISO[_name.lower()] = _iso
    for _a in _aliases:
        _ALIAS_TO_ISO.setdefault(_a, _iso)

_ALIASES_BY_LEN: list[tuple[str, str]] = sorted(
    _ALIAS_TO_ISO.items(), key=lambda kv: len(kv[0]), reverse=True
)


def name_for(iso: str) -> str | None:
    entry = _COUNTRIES.get(iso)
    return entry[0] if entry else None


def iso_for_name(name: str | None) -> str | None:
    """Resolve a country *name* (e.g. GDELT's ``sourcecountry``) to ISO-A3."""
    if not name:
        return None
    return _ALIAS_TO_ISO.get(name.strip().lower())


def find_iso_in_text(text: str | None) -> str | None:
    """Best-effort: find the first country an RSS headline/summary is about.

    Scans longest aliases first and matches on word boundaries so "us" doesn't
    fire inside "thus". Returns ``None`` when nothing recognizable is present.
    """
    if not text:
        return None
    low = text.lower()
    for alias, iso in _ALIASES_BY_LEN:
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return iso
    return None


def all_countries() -> dict[str, str]:
    """iso -> display name, for the whole gazetteer."""
    return {iso: name for iso, (name, _) in _COUNTRIES.items()}
