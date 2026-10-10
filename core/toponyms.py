"""
Módulo de normalización toponímica para las circunscripciones de España.
Resuelve de forma exhaustiva y bidireccional los nombres de provincias y circunscripciones
escritos en castellano, lenguas cooficiales (catalán, valenciano, euskera, gallego, asturiano),
denominaciones oficiales compuestas (BOE), formatos administrativos invertidos del INE
("Palmas, Las", "Coruña, La", "Rioja, La", "Baleares, Islas") y variantes sin tildes o con puntuación.
"""

from typing import Dict, List, Optional, Any
import unicodedata
import functools


def _clean_str(text: str) -> str:
    """Elimina tildes, signos de puntuación extra y pasa a minúsculas para coincidencia robusta."""
    if not text:
        return ""
    s = str(text).strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    for ch in ["-", "/", ",", "(", ")", ".", ";", ":", "_"]:
        s = s.replace(ch, " ")
    return " ".join(s.split())


# Catálogo toponímico exhaustivo de las 52 circunscripciones
PROVINCES_DATA: Dict[str, Dict[str, Any]] = {
    "Araba/Álava": {
        "canonical": "Araba/Álava",
        "name_es": "Álava",
        "name_coofficial": "Araba",
        "official_boe": "Araba/Álava",
        "community": "PVA",
        "display": "Araba/Álava (Álava)",
        "aliases": [
            "Araba/Álava", "Álava/Araba", "Araba / Álava", "Álava / Araba",
            "Álava", "Alava", "Araba", "Araba/Alava", "Alava/Araba", "Araba / Alava",
            "Vitoria", "Gasteiz", "Vitoria-Gasteiz", "Vitoria / Gasteiz"
        ],
    },
    "Albacete": {
        "canonical": "Albacete",
        "name_es": "Albacete",
        "name_coofficial": None,
        "official_boe": "Albacete",
        "community": "CLM",
        "display": "Albacete",
        "aliases": ["Albacete"],
    },
    "Alicante/Alacant": {
        "canonical": "Alicante/Alacant",
        "name_es": "Alicante",
        "name_coofficial": "Alacant",
        "official_boe": "Alicante/Alacant",
        "community": "CVA",
        "display": "Alicante / Alacant",
        "aliases": [
            "Alicante/Alacant", "Alacant/Alicante", "Alicante / Alacant", "Alacant / Alicante",
            "Alicante", "Alacant"
        ],
    },
    "Almería": {
        "canonical": "Almería",
        "name_es": "Almería",
        "name_coofficial": None,
        "official_boe": "Almería",
        "community": "AND",
        "display": "Almería",
        "aliases": ["Almería", "Almeria"],
    },
    "Asturias": {
        "canonical": "Asturias",
        "name_es": "Asturias",
        "name_coofficial": "Asturies",
        "official_boe": "Principado de Asturias",
        "community": "AST",
        "display": "Asturias (Asturies)",
        "aliases": [
            "Asturias", "Asturies", "Principado de Asturias", "Asturias / Asturies",
            "Oviedo", "Gijón", "Gijon"
        ],
    },
    "Ávila": {
        "canonical": "Ávila",
        "name_es": "Ávila",
        "name_coofficial": None,
        "official_boe": "Ávila",
        "community": "CYL",
        "display": "Ávila",
        "aliases": ["Ávila", "Avila"],
    },
    "Badajoz": {
        "canonical": "Badajoz",
        "name_es": "Badajoz",
        "name_coofficial": None,
        "official_boe": "Badajoz",
        "community": "EXT",
        "display": "Badajoz",
        "aliases": ["Badajoz"],
    },
    "Illes Balears": {
        "canonical": "Illes Balears",
        "name_es": "Islas Baleares",
        "name_coofficial": "Illes Balears",
        "official_boe": "Illes Balears",
        "community": "BAL",
        "display": "Illes Balears / Islas Baleares",
        "aliases": [
            "Illes Balears", "Islas Baleares", "Baleares", "Baleares, Islas",
            "Balears (Illes)", "Balears", "Illes Balears / Islas Baleares",
            "Islas Baleares / Illes Balears", "Mallorca", "Palma", "Palma de Mallorca",
            "Menorca", "Ibiza", "Eivissa", "Formentera"
        ],
    },
    "Barcelona": {
        "canonical": "Barcelona",
        "name_es": "Barcelona",
        "name_coofficial": "Barcelona",
        "official_boe": "Barcelona",
        "community": "CAT",
        "display": "Barcelona",
        "aliases": ["Barcelona", "Barna"],
    },
    "Burgos": {
        "canonical": "Burgos",
        "name_es": "Burgos",
        "name_coofficial": None,
        "official_boe": "Burgos",
        "community": "CYL",
        "display": "Burgos",
        "aliases": ["Burgos"],
    },
    "Cáceres": {
        "canonical": "Cáceres",
        "name_es": "Cáceres",
        "name_coofficial": None,
        "official_boe": "Cáceres",
        "community": "EXT",
        "display": "Cáceres",
        "aliases": ["Cáceres", "Caceres"],
    },
    "Cádiz": {
        "canonical": "Cádiz",
        "name_es": "Cádiz",
        "name_coofficial": None,
        "official_boe": "Cádiz",
        "community": "AND",
        "display": "Cádiz",
        "aliases": ["Cádiz", "Cadiz"],
    },
    "Cantabria": {
        "canonical": "Cantabria",
        "name_es": "Cantabria",
        "name_coofficial": None,
        "official_boe": "Cantabria",
        "community": "CAN",
        "display": "Cantabria",
        "aliases": ["Cantabria", "Santander"],
    },
    "Castellón/Castelló": {
        "canonical": "Castellón/Castelló",
        "name_es": "Castellón",
        "name_coofficial": "Castelló",
        "official_boe": "Castellón/Castelló",
        "community": "CVA",
        "display": "Castellón / Castelló",
        "aliases": [
            "Castellón/Castelló", "Castelló/Castellón", "Castellón / Castelló", "Castelló / Castellón",
            "Castellón", "Castelló", "Castellon", "Castello",
            "Castellón de la Plana", "Castelló de la Plana", "Castellon de la Plana"
        ],
    },
    "Ceuta": {
        "canonical": "Ceuta",
        "name_es": "Ceuta",
        "name_coofficial": None,
        "official_boe": "Ceuta",
        "community": "CEU",
        "display": "Ceuta",
        "aliases": ["Ceuta"],
    },
    "Ciudad Real": {
        "canonical": "Ciudad Real",
        "name_es": "Ciudad Real",
        "name_coofficial": None,
        "official_boe": "Ciudad Real",
        "community": "CLM",
        "display": "Ciudad Real",
        "aliases": ["Ciudad Real", "Ciudadreal"],
    },
    "Córdoba": {
        "canonical": "Córdoba",
        "name_es": "Córdoba",
        "name_coofficial": None,
        "official_boe": "Córdoba",
        "community": "AND",
        "display": "Córdoba",
        "aliases": ["Córdoba", "Cordoba"],
    },
    "A Coruña": {
        "canonical": "A Coruña",
        "name_es": "La Coruña",
        "name_coofficial": "A Coruña",
        "official_boe": "A Coruña",
        "community": "GAL",
        "display": "A Coruña / La Coruña",
        "aliases": [
            "A Coruña", "La Coruña", "Coruña, La", "Coruña", "Coruna, La", "Coruna",
            "A Coruna", "La Coruna", "A Coruña / La Coruña", "La Coruña / A Coruña",
            "A Coruna / La Coruna"
        ],
    },
    "Cuenca": {
        "canonical": "Cuenca",
        "name_es": "Cuenca",
        "name_coofficial": None,
        "official_boe": "Cuenca",
        "community": "CLM",
        "display": "Cuenca",
        "aliases": ["Cuenca"],
    },
    "Gipuzkoa": {
        "canonical": "Gipuzkoa",
        "name_es": "Guipúzcoa",
        "name_coofficial": "Gipuzkoa",
        "official_boe": "Gipuzkoa",
        "community": "PVA",
        "display": "Gipuzkoa / Guipúzcoa",
        "aliases": [
            "Gipuzkoa", "Guipúzcoa", "Guipuzcoa", "Gipuzkoa / Guipúzcoa", "Guipúzcoa / Gipuzkoa",
            "Gipuzkoa / Guipuzcoa", "Guipuzcoa / Gipuzkoa", "San Sebastián", "San Sebastian",
            "Donostia", "Donostia-San Sebastián", "Donostia / San Sebastián"
        ],
    },
    "Girona": {
        "canonical": "Girona",
        "name_es": "Gerona",
        "name_coofficial": "Girona",
        "official_boe": "Girona",
        "community": "CAT",
        "display": "Girona / Gerona",
        "aliases": [
            "Girona", "Gerona", "Girona / Gerona", "Gerona / Girona", "Girona/Gerona", "Gerona/Girona"
        ],
    },
    "Granada": {
        "canonical": "Granada",
        "name_es": "Granada",
        "name_coofficial": None,
        "official_boe": "Granada",
        "community": "AND",
        "display": "Granada",
        "aliases": ["Granada"],
    },
    "Guadalajara": {
        "canonical": "Guadalajara",
        "name_es": "Guadalajara",
        "name_coofficial": None,
        "official_boe": "Guadalajara",
        "community": "CLM",
        "display": "Guadalajara",
        "aliases": ["Guadalajara"],
    },
    "Huelva": {
        "canonical": "Huelva",
        "name_es": "Huelva",
        "name_coofficial": None,
        "official_boe": "Huelva",
        "community": "AND",
        "display": "Huelva",
        "aliases": ["Huelva"],
    },
    "Huesca": {
        "canonical": "Huesca",
        "name_es": "Huesca",
        "name_coofficial": "Uesca",
        "official_boe": "Huesca",
        "community": "ARA",
        "display": "Huesca (Uesca)",
        "aliases": ["Huesca", "Uesca", "Huesca / Uesca"],
    },
    "Jaén": {
        "canonical": "Jaén",
        "name_es": "Jaén",
        "name_coofficial": None,
        "official_boe": "Jaén",
        "community": "AND",
        "display": "Jaén",
        "aliases": ["Jaén", "Jaen"],
    },
    "León": {
        "canonical": "León",
        "name_es": "León",
        "name_coofficial": "Llión",
        "official_boe": "León",
        "community": "CYL",
        "display": "León",
        "aliases": ["León", "Leon", "Llión", "Llion"],
    },
    "Lleida": {
        "canonical": "Lleida",
        "name_es": "Lérida",
        "name_coofficial": "Lleida",
        "official_boe": "Lleida",
        "community": "CAT",
        "display": "Lleida / Lérida",
        "aliases": [
            "Lleida", "Lérida", "Lerida", "Lleida / Lérida", "Lérida / Lleida",
            "Lleida / Lerida", "Lerida / Lleida", "Lleida/Lérida", "Lérida/Lleida"
        ],
    },
    "Lugo": {
        "canonical": "Lugo",
        "name_es": "Lugo",
        "name_coofficial": "Lugo",
        "official_boe": "Lugo",
        "community": "GAL",
        "display": "Lugo",
        "aliases": ["Lugo"],
    },
    "Madrid": {
        "canonical": "Madrid",
        "name_es": "Madrid",
        "name_coofficial": None,
        "official_boe": "Madrid",
        "community": "MAD",
        "display": "Madrid",
        "aliases": ["Madrid", "Comunidad de Madrid"],
    },
    "Málaga": {
        "canonical": "Málaga",
        "name_es": "Málaga",
        "name_coofficial": None,
        "official_boe": "Málaga",
        "community": "AND",
        "display": "Málaga",
        "aliases": ["Málaga", "Malaga"],
    },
    "Melilla": {
        "canonical": "Melilla",
        "name_es": "Melilla",
        "name_coofficial": None,
        "official_boe": "Melilla",
        "community": "MEL",
        "display": "Melilla",
        "aliases": ["Melilla"],
    },
    "Murcia": {
        "canonical": "Murcia",
        "name_es": "Murcia",
        "name_coofficial": None,
        "official_boe": "Murcia",
        "community": "MUR",
        "display": "Murcia",
        "aliases": ["Murcia", "Región de Murcia", "Region de Murcia"],
    },
    "Navarra": {
        "canonical": "Navarra",
        "name_es": "Navarra",
        "name_coofficial": "Nafarroa",
        "official_boe": "Comunidad Foral de Navarra",
        "community": "NAV",
        "display": "Navarra / Nafarroa",
        "aliases": [
            "Navarra", "Nafarroa", "Navarra / Nafarroa", "Nafarroa / Navarra",
            "Comunidad Foral de Navarra", "Nafarroako Foru Komunitatea",
            "Pamplona", "Iruña", "Iruna"
        ],
    },
    "Ourense": {
        "canonical": "Ourense",
        "name_es": "Orense",
        "name_coofficial": "Ourense",
        "official_boe": "Ourense",
        "community": "GAL",
        "display": "Ourense / Orense",
        "aliases": [
            "Ourense", "Orense", "Ourense / Orense", "Orense / Ourense",
            "Ourense/Orense", "Orense/Ourense"
        ],
    },
    "Palencia": {
        "canonical": "Palencia",
        "name_es": "Palencia",
        "name_coofficial": None,
        "official_boe": "Palencia",
        "community": "CYL",
        "display": "Palencia",
        "aliases": ["Palencia"],
    },
    "Las Palmas": {
        "canonical": "Las Palmas",
        "name_es": "Las Palmas",
        "name_coofficial": None,
        "official_boe": "Las Palmas",
        "community": "CNR",
        "display": "Las Palmas",
        "aliases": [
            "Las Palmas", "Palmas, Las", "Palmas", "Las Palmas de Gran Canaria",
            "Gran Canaria", "Fuerteventura", "Lanzarote"
        ],
    },
    "Pontevedra": {
        "canonical": "Pontevedra",
        "name_es": "Pontevedra",
        "name_coofficial": "Pontevedra",
        "official_boe": "Pontevedra",
        "community": "GAL",
        "display": "Pontevedra",
        "aliases": ["Pontevedra", "Vigo"],
    },
    "La Rioja": {
        "canonical": "La Rioja",
        "name_es": "La Rioja",
        "name_coofficial": None,
        "official_boe": "La Rioja",
        "community": "RIO",
        "display": "La Rioja",
        "aliases": ["La Rioja", "Rioja, La", "Rioja", "Logroño", "Logrono"],
    },
    "Salamanca": {
        "canonical": "Salamanca",
        "name_es": "Salamanca",
        "name_coofficial": None,
        "official_boe": "Salamanca",
        "community": "CYL",
        "display": "Salamanca",
        "aliases": ["Salamanca"],
    },
    "Santa Cruz de Tenerife": {
        "canonical": "Santa Cruz de Tenerife",
        "name_es": "Santa Cruz de Tenerife",
        "name_coofficial": None,
        "official_boe": "Santa Cruz de Tenerife",
        "community": "CNR",
        "display": "Santa Cruz de Tenerife",
        "aliases": [
            "Santa Cruz de Tenerife", "Tenerife", "S.C. Tenerife", "SC Tenerife",
            "La Palma", "La Gomera", "El Hierro"
        ],
    },
    "Segovia": {
        "canonical": "Segovia",
        "name_es": "Segovia",
        "name_coofficial": None,
        "official_boe": "Segovia",
        "community": "CYL",
        "display": "Segovia",
        "aliases": ["Segovia"],
    },
    "Sevilla": {
        "canonical": "Sevilla",
        "name_es": "Sevilla",
        "name_coofficial": None,
        "official_boe": "Sevilla",
        "community": "AND",
        "display": "Sevilla",
        "aliases": ["Sevilla"],
    },
    "Soria": {
        "canonical": "Soria",
        "name_es": "Soria",
        "name_coofficial": None,
        "official_boe": "Soria",
        "community": "CYL",
        "display": "Soria",
        "aliases": ["Soria"],
    },
    "Tarragona": {
        "canonical": "Tarragona",
        "name_es": "Tarragona",
        "name_coofficial": "Tarragona",
        "official_boe": "Tarragona",
        "community": "CAT",
        "display": "Tarragona",
        "aliases": ["Tarragona"],
    },
    "Teruel": {
        "canonical": "Teruel",
        "name_es": "Teruel",
        "name_coofficial": None,
        "official_boe": "Teruel",
        "community": "ARA",
        "display": "Teruel",
        "aliases": ["Teruel"],
    },
    "Toledo": {
        "canonical": "Toledo",
        "name_es": "Toledo",
        "name_coofficial": None,
        "official_boe": "Toledo",
        "community": "CLM",
        "display": "Toledo",
        "aliases": ["Toledo"],
    },
    "Valencia/València": {
        "canonical": "Valencia/València",
        "name_es": "Valencia",
        "name_coofficial": "València",
        "official_boe": "València/Valencia",
        "community": "CVA",
        "display": "Valencia / València",
        "aliases": [
            "Valencia/València", "València/Valencia", "Valencia / València", "València / Valencia",
            "Valencia", "València", "Valencia/Valencia", "Valencia / Valencia"
        ],
    },
    "Valladolid": {
        "canonical": "Valladolid",
        "name_es": "Valladolid",
        "name_coofficial": None,
        "official_boe": "Valladolid",
        "community": "CYL",
        "display": "Valladolid",
        "aliases": ["Valladolid"],
    },
    "Bizkaia": {
        "canonical": "Bizkaia",
        "name_es": "Vizcaya",
        "name_coofficial": "Bizkaia",
        "official_boe": "Bizkaia",
        "community": "PVA",
        "display": "Bizkaia / Vizcaya",
        "aliases": [
            "Bizkaia", "Vizcaya", "Bizkaia / Vizcaya", "Vizcaya / Bizkaia",
            "Bizkaia/Vizcaya", "Vizcaya/Bizkaia", "Bilbao"
        ],
    },
    "Zamora": {
        "canonical": "Zamora",
        "name_es": "Zamora",
        "name_coofficial": None,
        "official_boe": "Zamora",
        "community": "CYL",
        "display": "Zamora",
        "aliases": ["Zamora"],
    },
    "Zaragoza": {
        "canonical": "Zaragoza",
        "name_es": "Zaragoza",
        "name_coofficial": "Zaragoza",
        "official_boe": "Zaragoza",
        "community": "ARA",
        "display": "Zaragoza",
        "aliases": ["Zaragoza", "Saragossa"],
    },
}

# Lista canónica de las 52 circunscripciones
CANONICAL_PROVINCES: List[str] = list(PROVINCES_DATA.keys())

# Provincias andaluzas canónicas
ANDALUSIAN_CANONICAL: List[str] = [
    "Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"
]

# Mapeo canónico de las 19 Comunidades y Ciudades Autónomas a sus circunscripciones
CCAA_PROVINCES: Dict[str, List[str]] = {
    "Andalucía": ["Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"],
    "Aragón": ["Huesca", "Teruel", "Zaragoza"],
    "Asturias": ["Asturias"],
    "Illes Balears": ["Illes Balears"],
    "Canarias": ["Las Palmas", "Santa Cruz de Tenerife"],
    "Cantabria": ["Cantabria"],
    "Castilla y León": ["Ávila", "Burgos", "León", "Palencia", "Salamanca", "Segovia", "Soria", "Valladolid", "Zamora"],
    "Castilla-La Mancha": ["Albacete", "Ciudad Real", "Cuenca", "Guadalajara", "Toledo"],
    "Cataluña": ["Barcelona", "Girona", "Lleida", "Tarragona"],
    "Ceuta": ["Ceuta"],
    "Comunidad de Madrid": ["Madrid"],
    "Comunitat Valenciana": ["Alicante/Alacant", "Castellón/Castelló", "Valencia/València"],
    "Extremadura": ["Badajoz", "Cáceres"],
    "Galicia": ["A Coruña", "Lugo", "Ourense", "Pontevedra"],
    "La Rioja": ["La Rioja"],
    "Melilla": ["Melilla"],
    "Navarra": ["Navarra"],
    "País Vasco": ["Araba/Álava", "Bizkaia", "Gipuzkoa"],
    "Región de Murcia": ["Murcia"],
}

# Construcción de tablas hash de búsqueda directa y limpia
EXACT_ALIAS_MAP: Dict[str, str] = {}
CLEAN_ALIAS_MAP: Dict[str, str] = {}

for canonical, meta in PROVINCES_DATA.items():
    # Asociar la propia canónica
    EXACT_ALIAS_MAP[canonical] = canonical
    CLEAN_ALIAS_MAP[_clean_str(canonical)] = canonical
    
    # Asociar español, cooficial y oficial
    for prop in ["name_es", "name_coofficial", "official_boe", "display"]:
        val = meta.get(prop)
        if val:
            EXACT_ALIAS_MAP[val] = canonical
            CLEAN_ALIAS_MAP[_clean_str(val)] = canonical

    # Asociar todos los alias
    for alias in meta.get("aliases", []):
        EXACT_ALIAS_MAP[alias] = canonical
        CLEAN_ALIAS_MAP[_clean_str(alias)] = canonical


@functools.lru_cache(maxsize=1024)
def normalize_province_name(name: str) -> str:
    """
    Normaliza cualquier variante toponímica de una provincia española a su nombre canónico.
    
    Ejemplos:
        normalize_province_name("Gerona") -> "Girona"
        normalize_province_name("Girona") -> "Girona"
        normalize_province_name("Vizcaya") -> "Bizkaia"
        normalize_province_name("Bizkaia") -> "Bizkaia"
        normalize_province_name("Valencia") -> "Valencia/València"
        normalize_province_name("València") -> "Valencia/València"
        normalize_province_name("Coruña, La") -> "A Coruña"
        normalize_province_name("La Coruña") -> "A Coruña"
        normalize_province_name("Baleares, Islas") -> "Illes Balears"
        normalize_province_name("Palmas, Las") -> "Las Palmas"
        normalize_province_name("Rioja, La") -> "La Rioja"
    """
    if not name:
        return ""
    name_str = str(name).strip()
    
    # 1. Búsqueda directa exacta
    if name_str in EXACT_ALIAS_MAP:
        return EXACT_ALIAS_MAP[name_str]
        
    # 2. Búsqueda limpia (sin tildes, minúsculas, sin separadores)
    cleaned = _clean_str(name_str)
    if cleaned in CLEAN_ALIAS_MAP:
        return CLEAN_ALIAS_MAP[cleaned]
        
    # 3. Búsqueda descartando prefijos administrativos comunes
    for prefix in [
        "provincia de ", "provincia d ", "provincia del ", "provincia de la ", "provincia de las ", "provincia de los ",
        "circunscripcion de ", "circunscripcion d ", "circunscripcion de la ", "circunscripcion de las ",
        "comunidad de ", "comunidad foral de ", "principado de "
    ]:
        if cleaned.startswith(prefix):
            sub = cleaned[len(prefix):].strip()
            if sub in CLEAN_ALIAS_MAP:
                return CLEAN_ALIAS_MAP[sub]
                
    # 4. Coincidencia parcial si contiene el nombre de la capital o provincia
    for clean_alias, can in CLEAN_ALIAS_MAP.items():
        if len(clean_alias) > 3 and clean_alias in cleaned:
            return can

    # Si no se reconoce, devolver el texto original limpio de espacios
    return name_str


def are_same_province(name1: str, name2: str) -> bool:
    """Comprueba si dos nombres de provincia se refieren a la misma circunscripción."""
    if not name1 or not name2:
        return False
    return normalize_province_name(name1) == normalize_province_name(name2)


def get_province_display_name(name: str) -> str:
    """Devuelve la denominación bilingüe o formateada idónea para selectores y leyendas."""
    canon = normalize_province_name(name)
    if canon in PROVINCES_DATA:
        return PROVINCES_DATA[canon]["display"]
    return name


def get_province_metadata(name: str) -> Optional[Dict[str, Any]]:
    """Devuelve el registro toponímico completo de la provincia."""
    canon = normalize_province_name(name)
    return PROVINCES_DATA.get(canon)


def is_andalusian_province(name: str) -> bool:
    """Verifica si la provincia pertenece a Andalucía considerando cualquier toponimia."""
    return normalize_province_name(name) in ANDALUSIAN_CANONICAL


class ToponymDict(dict):
    """
    Diccionario inteligente para circunscripciones electorales.
    Permite acceder a los elementos usando indistintamente cualquier toponimia
    (castellano, catalán, euskera, gallego, formato INE invertido, etc.).
    """
    def __getitem__(self, key: Any) -> Any:
        if super().__contains__(key):
            return super().__getitem__(key)
        norm_key = normalize_province_name(str(key))
        for k in self.keys():
            if normalize_province_name(str(k)) == norm_key:
                return super().__getitem__(k)
        raise KeyError(key)

    def __contains__(self, key: Any) -> bool:
        if super().__contains__(key):
            return True
        norm_key = normalize_province_name(str(key))
        return any(normalize_province_name(str(k)) == norm_key for k in self.keys())

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default
