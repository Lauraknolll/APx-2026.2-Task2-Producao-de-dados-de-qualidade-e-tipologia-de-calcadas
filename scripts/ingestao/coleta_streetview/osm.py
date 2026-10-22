"""
Traçado das ruas, do OpenStreetMap (API Overpass).

Serve só para separar as calçadas de uma rua das outras: uma zona é "da rua"
se o centro dela fica a até DISTANCIA_RUA m do eixo. Os traçados consultados
ficam em cache em data/raw/ruas_osm/, para não depender do Overpass estar no ar.
"""

import json
import math
import sys

import requests

from .config import CACHE_RUAS, OVERPASS_URLS


def buscar_rua(nome: str) -> tuple[str, list[list[tuple]]]:
    """
    (nome oficial no OSM, trechos), cada trecho uma lista de (lat, lon).

    Tenta o nome exato (sem diferenciar maiúsculas); se não achar, busca por
    "contém" — e, se isso casar com mais de uma rua, pede para ser mais
    específico. O nome é o do OSM, por extenso ("Avenida", não "Av.").
    """
    cache = CACHE_RUAS / (nome.strip().lower().replace("/", "_") + ".json")
    if cache.exists():
        dados = json.loads(cache.read_text(encoding="utf-8"))
        return dados["nome"], [[tuple(p) for p in t] for t in dados["trechos"]]

    def consultar(filtro: str) -> list[dict]:
        query = f"""[out:json][timeout:60];
            area["name"="Curitiba"]["admin_level"="8"]->.cwb;
            way["highway"]["name"~"{filtro}",i](area.cwb);
            out geom;"""
        falhas = []
        for url in OVERPASS_URLS:
            try:
                resp = requests.post(url, data={"data": query},
                                     headers={"User-Agent": "calcadas-curitiba/0.1"}, timeout=90)
                resp.raise_for_status()
                return resp.json().get("elements", [])
            except (requests.exceptions.RequestException, ValueError) as exc:
                falhas.append(f"{url}: {exc}")
        sys.exit("Nenhum servidor Overpass respondeu:\n  " + "\n  ".join(falhas))

    escapado = "".join(f"\\\\{c}" if c in r'\.^$|?*+()[]{}"' else c for c in nome.strip())
    ways = consultar(f"^{escapado}$") or consultar(escapado)
    if not ways:
        sys.exit(f'Nenhuma rua encontrada em Curitiba com o nome "{nome}".')

    nomes = sorted({w["tags"]["name"] for w in ways})
    if len(nomes) > 1:
        sys.exit("Mais de uma rua casou com esse nome, use o nome completo:\n  "
                 + "\n  ".join(nomes))

    trechos = [[(p["lat"], p["lon"]) for p in w["geometry"]] for w in ways]
    CACHE_RUAS.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"nome": nomes[0], "trechos": trechos}, ensure_ascii=False),
                     encoding="utf-8")
    return nomes[0], trechos


def _para_metros(lat: float, lon: float, lat_ref: float) -> tuple[float, float]:
    """Projeção equirretangular local — precisão de sobra para dezenas de metros."""
    return (lon * 111_320 * math.cos(math.radians(lat_ref)), lat * 111_320)


def distancia_rua(lat: float, lon: float, trechos: list[list[tuple]]) -> float:
    """Menor distância (m) de um ponto até a polilinha da rua."""
    px, py = _para_metros(lat, lon, lat)
    melhor = math.inf
    for trecho in trechos:
        pontos = [_para_metros(a, b, lat) for a, b in trecho]
        for (ax, ay), (bx, by) in zip(pontos, pontos[1:]):
            dx, dy = bx - ax, by - ay
            comp2 = dx * dx + dy * dy
            t = 0.0 if comp2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / comp2))
            melhor = min(melhor, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return melhor


def bbox_rua(trechos: list[list[tuple]], margem_m: float) -> tuple:
    """(lon_min, lat_min, lon_max, lat_max) da rua, com uma margem em metros."""
    lats = [p[0] for t in trechos for p in t]
    lons = [p[1] for t in trechos for p in t]
    m_lat = margem_m / 111_320
    m_lon = margem_m / (111_320 * math.cos(math.radians(sum(lats) / len(lats))))
    return (min(lons) - m_lon, min(lats) - m_lat, max(lons) + m_lon, max(lats) + m_lat)
