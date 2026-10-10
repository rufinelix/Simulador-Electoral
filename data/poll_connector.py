"""
Conector de encuestas y sondeos electorales.
Incluye sondeos de referencia (CIS, 40dB, GAD3, ElectoPanel, Oficial 23J),
soporte para URLs de APIs JSON y cargador en vivo con caché local.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import urllib.request
import ssl
import re

CACHE_FILE = Path(__file__).parent / "polls_cache.json"

# Catálogo verificado de encuestas y sondeos de referencia en España (actualizado a octubre de 2026)
BENCHMARK_POLLS: Dict[str, Dict[str, Any]] = {
    "Oficial 23J 2023 (Congreso de los Diputados)": {
        "source": "Ministerio del Interior / BOE",
        "date": "23 de julio de 2023",
        "turnout": 66.59,
        "sample": "24.7M votos (escrutinio definitivo oficial JEC / BOE: 66,59% participación)",
        "poll": {
            "PP": 33.05,
            "PSOE": 31.70,
            "Vox": 12.39,
            "Sumar": 12.31,
            "Podemos": 0.0,
            "ERC": 1.89,
            "Junts": 1.60,
            "EH Bildu": 1.36,
            "PNV": 1.12,
            "BNG": 0.62,
            "CC": 0.46,
            "UPN": 0.21,
            "Adelante Andalucía": 0.04,
        }
    },
    "40dB / El País - Cadena SER": {
        "source": "40dB. para El País y Cadena SER (Flash Convocatoria 29N)",
        "date": "9 de octubre de 2026",
        "turnout": 68.0,
        "sample": "800 entrevistas online (campo 7-8 oct, sondeo post-convocatoria 29N)",
        "poll": {
            "PP": 31.9,
            "PSOE": 28.1,
            "Vox": 18.9,
            "Sumar": 5.3,
            "Podemos": 2.3,
            "SALF": 1.8,
            "ERC": 1.8,
            "Junts": 1.5,
            "EH Bildu": 1.4,
            "PNV": 1.1,
            "BNG": 0.8,
            "CC": 0.5,
            "Adelante Andalucía": 0.4,
            "UPN": 0.2,
        }
    },
    "ElectoPanel / Electomanía": {
        "source": "ElectoPanel (EM-Analytics / Electomanía)",
        "date": "9 de octubre de 2026",
        "turnout": 68.2,
        "sample": "4.125 respuestas online (campo 5-9 oct, panel continuo 29N)",
        "poll": {
            "PP": 31.5,
            "PSOE": 26.9,
            "Vox": 19.1,
            "Sumar": 6.0,
            "Podemos": 3.4,
            "SALF": 1.7,
            "ERC": 2.0,
            "Junts": 1.1,
            "EH Bildu": 1.4,
            "PNV": 1.1,
            "BNG": 1.0,
            "Adelante Andalucía": 1.1,
            "CC": 0.3,
            "UPN": 0.2,
        }
    },
    "Target Point / El Debate": {
        "source": "Target Point para El Debate",
        "date": "9 de octubre de 2026",
        "turnout": 67.6,
        "sample": "1.002 entrevistas (campo 6-9 oct)",
        "poll": {
            "PP": 32.0,
            "PSOE": 25.9,
            "Vox": 18.7,
            "Sumar": 6.9,
            "Podemos": 3.4,
            "SALF": 1.3,
            "ERC": 1.8,
            "Junts": 1.4,
            "EH Bildu": 1.3,
            "PNV": 1.0,
            "BNG": 0.8,
            "CC": 0.4,
            "Adelante Andalucía": 0.4,
            "UPN": 0.2,
        }
    },
    "Hamalgama Métrica / Vozpópuli": {
        "source": "Hamalgama Métrica para Vozpópuli",
        "date": "9 de octubre de 2026",
        "turnout": 67.5,
        "sample": "1.000 entrevistas (campo 5-8 oct)",
        "poll": {
            "PP": 33.4,
            "PSOE": 25.3,
            "Vox": 19.6,
            "Sumar": 5.4,
            "Podemos": 3.3,
            "SALF": 1.8,
            "ERC": 1.9,
            "Junts": 1.7,
            "EH Bildu": 1.3,
            "PNV": 0.9,
            "BNG": 0.8,
            "CC": 0.5,
            "Adelante Andalucía": 0.4,
            "UPN": 0.2,
        }
    },
    "IMOP Insights / El Confidencial": {
        "source": "IMOP Insights para El Confidencial",
        "date": "8 de octubre de 2026",
        "turnout": 68.4,
        "sample": "900 entrevistas (campo 5-7 oct)",
        "poll": {
            "PP": 30.4,
            "PSOE": 26.5,
            "Vox": 19.0,
            "Sumar": 7.6,
            "Podemos": 2.3,
            "SALF": 1.9,
            "ERC": 2.2,
            "Junts": 1.1,
            "EH Bildu": 1.3,
            "PNV": 0.9,
            "BNG": 1.1,
            "CC": 0.6,
            "Adelante Andalucía": 1.0,
            "UPN": 0.2,
        }
    },
    "NC Report / La Razón": {
        "source": "NC Report para La Razón",
        "date": "7 de octubre de 2026",
        "turnout": 63.1,
        "sample": "1.000 entrevistas (campo 1-6 oct)",
        "poll": {
            "PP": 34.1,
            "PSOE": 25.0,
            "Vox": 18.2,
            "Sumar": 5.3,
            "Podemos": 3.9,
            "SALF": 1.9,
            "Junts": 2.9,
            "ERC": 1.8,
            "EH Bildu": 1.4,
            "PNV": 0.9,
            "BNG": 0.7,
            "CC": 0.4,
            "Adelante Andalucía": 0.4,
            "UPN": 0.2,
        }
    },
    "SocioMétrica / El Español": {
        "source": "SocioMétrica para El Español",
        "date": "4 de octubre de 2026",
        "turnout": 67.9,
        "sample": "1.000 entrevistas (campo 1-3 oct)",
        "poll": {
            "PP": 33.4,
            "PSOE": 26.5,
            "Vox": 18.1,
            "Sumar": 5.3,
            "Podemos": 3.1,
            "SALF": 2.2,
            "ERC": 2.2,
            "Junts": 1.2,
            "EH Bildu": 1.3,
            "PNV": 1.0,
            "BNG": 0.9,
            "CC": 0.6,
            "Adelante Andalucía": 0.4,
            "UPN": 0.2,
        }
    },
    "Data10 / Okdiario": {
        "source": "Data10 para Okdiario",
        "date": "3 de octubre de 2026",
        "turnout": 68.0,
        "sample": "1.000 entrevistas (campo 2 oct)",
        "poll": {
            "PP": 34.0,
            "PSOE": 26.1,
            "Vox": 18.6,
            "Sumar": 5.2,
            "Podemos": 4.3,
            "SALF": 1.4,
            "ERC": 1.9,
            "Junts": 1.5,
            "EH Bildu": 1.4,
            "PNV": 0.8,
            "BNG": 1.0,
            "CC": 0.3,
            "Adelante Andalucía": 0.5,
            "UPN": 0.2,
        }
    },
    "Sigma Dos / El Mundo": {
        "source": "Sigma Dos para El Mundo",
        "date": "2 de octubre de 2026",
        "turnout": 67.8,
        "sample": "2.116 entrevistas (campo 22 sep - 1 oct)",
        "poll": {
            "PP": 32.6,
            "PSOE": 25.6,
            "Vox": 18.3,
            "Sumar": 6.6,
            "Podemos": 3.3,
            "SALF": 2.1,
            "ERC": 2.5,
            "Junts": 1.1,
            "EH Bildu": 1.3,
            "PNV": 1.0,
            "BNG": 0.9,
            "CC": 0.5,
            "Adelante Andalucía": 0.8,
            "UPN": 0.2,
        }
    },
    "CIS (Barómetro de Intención de Voto)": {
        "source": "Centro de Investigaciones Sociológicas (CIS)",
        "date": "14 de septiembre de 2026",
        "turnout": 68.5,
        "sample": "4.000 entrevistas (Estudio 3577)",
        "poll": {
            "PSOE": 31.0,
            "PP": 25.5,
            "Vox": 16.6,
            "Sumar": 5.7,
            "Podemos": 3.7,
            "SALF": 2.4,
            "ERC": 1.8,
            "Junts": 1.5,
            "EH Bildu": 1.3,
            "PNV": 1.1,
            "BNG": 0.8,
            "CC": 0.5,
            "Adelante Andalucía": 0.5,
            "UPN": 0.2,
        }
    },
    "GAD3 / ABC": {
        "source": "GAD3 para ABC",
        "date": "4 de septiembre de 2026",
        "turnout": 69.0,
        "sample": "1.000 entrevistas telefónicas (campo 1-3 sep)",
        "poll": {
            "PP": 31.1,
            "PSOE": 26.1,
            "Vox": 19.2,
            "Sumar": 7.0,
            "Podemos": 3.1,
            "SALF": 2.2,
            "ERC": 1.7,
            "Junts": 1.6,
            "EH Bildu": 1.3,
            "PNV": 1.1,
            "BNG": 0.7,
            "CC": 0.5,
            "Adelante Andalucía": 0.4,
            "UPN": 0.2,
        }
    },
}


class PollConnector:
    def __init__(self):
        self.cached_polls = dict(BENCHMARK_POLLS)
        self._load_cache()

    def _load_cache(self):
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    extra = json.load(f)
                    self.cached_polls.update(extra)
            except Exception:
                pass

    def _save_cache(self):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cached_polls, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_available_poll_names(self) -> List[str]:
        return list(self.cached_polls.keys())

    def get_poll(self, name: str) -> Optional[Dict[str, Any]]:
        return self.cached_polls.get(name)

    def get_poll_date(self, name: str) -> str:
        poll_info = self.get_poll(name)
        if poll_info and "date" in poll_info:
            return str(poll_info["date"])
        return "Fecha no especificada"

    def fetch_from_custom_api(self, url: str) -> Tuple[bool, str, Optional[Dict[str, float]]]:
        """
        Descarga una encuesta desde un endpoint JSON público.
        Espera un formato: {"PP": 34.0, "PSOE": 29.0, ...} o {"poll": {...}}
        """
        try:
            ctx = ssl._create_unverified_context()
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SimuladorElectoralBot/1.0 (contact@portfolio.es)"}
            )
            with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                
                # Extraer el diccionario de porcentajes
                poll_dict = data.get("poll", data)
                clean_poll = {}
                for k, v in poll_dict.items():
                    try:
                        clean_poll[str(k)] = float(v)
                    except (ValueError, TypeError):
                        pass

                if not clean_poll:
                    return False, "La respuesta JSON no contiene un diccionario de partidos y porcentajes válido.", None

                # Guardar en caché con el nombre de la URL
                poll_name = f"API Personalizada ({url[:30]}...)"
                self.cached_polls[poll_name] = {
                    "source": url,
                    "date": "En vivo",
                    "turnout": 68.0,
                    "sample": "API Externa",
                    "poll": clean_poll,
                }
                self._save_cache()

                return True, f"Encuesta cargada correctamente desde API: {len(clean_poll)} candidaturas.", clean_poll

        except Exception as e:
            return False, f"Error al conectar con la API: {str(e)}", None
