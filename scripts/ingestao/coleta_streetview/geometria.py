"""
Geometria: a camada de calçadas do IPPUC e o traçado das ruas.

- Calçadas: a camada `passeio` (GeoPackage, SIRGAS 2000 / UTM 22S), lida só
  com a biblioteca padrão — GeoPackage é um SQLite e a geometria é WKB com um
  cabeçalho curto. Os panoramas do Street View vêm em lat/lon (WGS84);
  convertemos tudo para UTM e fazemos a geometria em metros (SIRGAS 2000 e
  WGS84 diferem em centímetros, o que é irrelevante aqui). A `LinhaCentral`
  de cada calçada é o que se divide em zonas.
- Ruas: nomes e traçados do OpenStreetMap, para achar a rua digitada e
  separar as calçadas dela das outras. Todas as vias de Curitiba são baixadas
  de uma vez (API Overpass) para data/raw/ruas_osm/, e a busca é local.
"""

import difflib
import gzip
import json
import math
import shutil
import sqlite3
import struct
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Iterator, Optional

import requests

from .config import CACHE_RUAS, CALCADAS_PATH, CALCADAS_ZIP, OVERPASS_URLS


# --------------------------------------------------------------------------- #
# Calçadas (IPPUC)
# --------------------------------------------------------------------------- #

# Projeção UTM 22S (série de Krüger, precisão sub-milimétrica).
_A = 6378137.0
_F = 1 / 298.257222101  # GRS80 (SIRGAS 2000)
_K0 = 0.9996
_LON0 = math.radians(-51.0)  # meridiano central da zona 22
_N0 = 10_000_000.0           # falso norte (hemisfério sul)
_E0 = 500_000.0

_n = _F / (2 - _F)
_AA = _A / (1 + _n) * (1 + _n**2 / 4 + _n**4 / 64)
_ALFA = [_n / 2 - 2 * _n**2 / 3 + 5 * _n**3 / 16, 13 * _n**2 / 48 - 3 * _n**3 / 5, 61 * _n**3 / 240]
_BETA = [_n / 2 - 2 * _n**2 / 3 + 37 * _n**3 / 96, _n**2 / 48 + _n**3 / 15, 17 * _n**3 / 480]
_DELTA = [2 * _n - 2 * _n**2 / 3 - 2 * _n**3, 7 * _n**2 / 3 - 8 * _n**3 / 5, 56 * _n**3 / 15]
_C = 2 * math.sqrt(_n) / (1 + _n)


def ll_para_utm(lat: float, lon: float) -> tuple[float, float]:
    """(lat, lon) WGS84 -> (leste, norte) em metros, UTM 22S."""
    phi, dl = math.radians(lat), math.radians(lon) - _LON0
    t = math.sinh(math.atanh(math.sin(phi)) - _C * math.atanh(_C * math.sin(phi)))
    xi_, eta_ = math.atan2(t, math.cos(dl)), math.atanh(math.sin(dl) / math.sqrt(1 + t * t))
    xi = xi_ + sum(a * math.sin(2 * j * xi_) * math.cosh(2 * j * eta_) for j, a in enumerate(_ALFA, 1))
    eta = eta_ + sum(a * math.cos(2 * j * xi_) * math.sinh(2 * j * eta_) for j, a in enumerate(_ALFA, 1))
    return _E0 + _K0 * _AA * eta, _N0 + _K0 * _AA * xi


def utm_para_ll(e: float, n: float) -> tuple[float, float]:
    """(leste, norte) UTM 22S -> (lat, lon) WGS84."""
    xi, eta = (n - _N0) / (_K0 * _AA), (e - _E0) / (_K0 * _AA)
    xi_ = xi - sum(b * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, b in enumerate(_BETA, 1))
    eta_ = eta - sum(b * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, b in enumerate(_BETA, 1))
    chi = math.asin(math.sin(xi_) / math.cosh(eta_))
    lat = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(_DELTA, 1))
    return math.degrees(lat), math.degrees(_LON0 + math.atan2(math.sinh(eta_), math.cos(xi_)))


def azimute(de_x: float, de_y: float, para_x: float, para_y: float) -> float:
    """Direção de um ponto a outro em graus, 0 = Norte, sentido horário.
    (Em UTM o norte da grade difere do verdadeiro em <1,5° em Curitiba.)"""
    return math.degrees(math.atan2(para_x - de_x, para_y - de_y)) % 360


# --------------------------------------------------------------------------- #
# Leitura do GeoPackage
# --------------------------------------------------------------------------- #

_TAM_ENVELOPE = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


def _envelope(blob: bytes) -> Optional[tuple]:
    """(xmin, xmax, ymin, ymax) do cabeçalho GPKG, sem decodificar o WKB."""
    tipo = (blob[3] >> 1) & 7
    if tipo == 0:
        return None
    ordem = "<" if blob[3] & 1 else ">"
    return struct.unpack(ordem + "4d", blob[8:40])


def _aneis_externos(blob: bytes) -> list[list[tuple[float, float]]]:
    """Decodifica o WKB (Multi)Polygon e devolve só os anéis externos."""
    wkb = blob[8 + _TAM_ENVELOPE[(blob[3] >> 1) & 7]:]
    pos = 0

    def ler(fmt: str, ordem: str):
        nonlocal pos
        valores = struct.unpack_from(ordem + fmt, wkb, pos)
        pos += struct.calcsize(fmt)
        return valores

    def poligono() -> list[tuple[float, float]]:
        ordem = "<" if ler("B", "<")[0] == 1 else ">"
        tipo = ler("I", ordem)[0] % 1000
        assert tipo == 3, f"esperava Polygon, veio tipo {tipo}"
        externo = []
        for i in range(ler("I", ordem)[0]):
            n = ler("I", ordem)[0]
            pontos = [ler("2d", ordem) for _ in range(n)]
            if i == 0:
                externo = pontos
        return externo

    ordem = "<" if ler("B", "<")[0] == 1 else ">"
    tipo = ler("I", ordem)[0] % 1000
    if tipo == 3:
        pos = 0
        return [poligono()]
    assert tipo == 6, f"geometria não suportada: tipo {tipo}"
    return [poligono() for _ in range(ler("I", ordem)[0])]


def garantir_calcadas(path: Path):
    """A camada fica zipada no repositório (data/raw/_Passeio_CWB.zip); na
    primeira vez, extrai o passeio.gpkg para `path`."""
    if path.exists():
        return
    if path != CALCADAS_PATH or not CALCADAS_ZIP.exists():
        raise SystemExit(f"Camada de calçadas não encontrada: {path}")
    print(f"Extraindo a camada de calçadas de {CALCADAS_ZIP.name}...")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(CALCADAS_ZIP) as z, z.open("passeio.gpkg") as origem, open(path, "wb") as destino:
        shutil.copyfileobj(origem, destino)


def ler_calcadas(path: Path, bbox_utm: Optional[tuple] = None) -> Iterator[dict]:
    """
    Itera sobre os polígonos da camada `passeio`: {"fid", "aneis"}. Se
    `bbox_utm` (emin, nmin, emax, nmax) for dado, pula — sem decodificar — os
    que estão fora dele.
    """
    garantir_calcadas(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for fid, blob in conn.execute("SELECT fid, geom FROM passeio"):
            if blob is None:
                continue
            env = _envelope(blob)
            if bbox_utm and env:
                xmin, xmax, ymin, ymax = env
                if xmax < bbox_utm[0] or xmin > bbox_utm[2] or ymax < bbox_utm[1] or ymin > bbox_utm[3]:
                    continue
            yield {"fid": fid, "aneis": _aneis_externos(blob)}
    finally:
        conn.close()


def comprimento_faixa(perimetro: float, area: float) -> float:
    """
    Calçada ≈ retângulo fino: P = 2(L + w), A = L·w. Resolve para L
    (a raiz maior). Se a forma não for de faixa, cai para P/2.
    """
    delta = perimetro * perimetro - 16 * area
    if delta < 0:
        return perimetro / 2
    return (perimetro + math.sqrt(delta)) / 4


def larguras(path: Path, fids: set) -> dict[int, float]:
    """Largura média (m) das calçadas pedidas: área / comprimento da faixa."""
    if not fids:
        return {}
    garantir_calcadas(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {fid: area / comprimento_faixa(perimetro, area)
                for fid, perimetro, area in conn.execute(
                    f"SELECT fid, Shape_Leng, Shape_Area FROM passeio "
                    f"WHERE fid IN ({','.join('?' * len(fids))})", list(fids))}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Linha central da calçada
# --------------------------------------------------------------------------- #

def _mais_proximo_nas_linhas(px: float, py: float, linhas: list) -> tuple[float, float, float]:
    """(distância, qx, qy) do ponto mais próximo de (px, py) sobre as polilinhas."""
    melhor = (math.inf, px, py)
    for linha in linhas:
        for (ax, ay), (bx, by) in zip(linha, linha[1:]):
            dx, dy = bx - ax, by - ay
            comp2 = dx * dx + dy * dy
            t = 0.0 if comp2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / comp2))
            qx, qy = ax + t * dx, ay + t * dy
            d = math.hypot(px - qx, py - qy)
            if d < melhor[0]:
                melhor = (d, qx, qy)
    return melhor


def _medir(caminho: list[tuple[float, float]]) -> list[float]:
    acumulado = [0.0]
    for (ax, ay), (bx, by) in zip(caminho, caminho[1:]):
        acumulado.append(acumulado[-1] + math.hypot(bx - ax, by - ay))
    return acumulado


def _ponto_em(caminho: list, acumulado: list[float], s: float) -> tuple[float, float]:
    for i in range(1, len(acumulado)):
        if acumulado[i] >= s:
            seg = acumulado[i] - acumulado[i - 1]
            t = 0.0 if seg == 0 else (s - acumulado[i - 1]) / seg
            (ax, ay), (bx, by) = caminho[i - 1], caminho[i]
            return ax + t * (bx - ax), ay + t * (by - ay)
    return caminho[-1]


class LinhaCentral:
    """
    Linha central de uma calçada, consultável em qualquer posição (em metros
    a partir de uma das pontas).

    A calçada é uma faixa fina (reta, em L ou em U, contornando a quadra).
    Cortamos o contorno nos dois vértices mais distantes entre si (as pontas
    da faixa), o que separa os dois lados compridos. Um ponto da linha central
    é marcado em um lado e puxado até o meio do caminho para o lado oposto.
    """

    def __init__(self, anel: list[tuple[float, float]]):
        pts = anel[:-1] if len(anel) > 1 and anel[0] == anel[-1] else anel[:]
        self._degenerada = len(pts) < 3
        if self._degenerada:
            self._pts, self.extensao = pts, 0.0
            return
        i, j = max(((a, b) for a in range(len(pts)) for b in range(a + 1, len(pts))),
                   key=lambda ab: math.dist(pts[ab[0]], pts[ab[1]]))
        self._lado_a = pts[i:j + 1]
        self._lado_b = pts[j:] + pts[:i + 1]
        self._acum_a = _medir(self._lado_a)
        self.extensao = (self._acum_a[-1] + _medir(self._lado_b)[-1]) / 2
        # posição na linha central (m) -> posição ao longo do lado A
        self._escala = self._acum_a[-1] / self.extensao if self.extensao else 0.0

    def ponto(self, posicao: float) -> tuple[float, float]:
        """Ponto da linha central a `posicao` metros da ponta (limitado à calçada)."""
        if self._degenerada:
            return self._pts[0]
        posicao = max(0.0, min(self.extensao, posicao))
        ax, ay = _ponto_em(self._lado_a, self._acum_a, posicao * self._escala)
        _, bx, by = _mais_proximo_nas_linhas(ax, ay, [self._lado_b])
        return (ax + bx) / 2, (ay + by) / 2

    def zonas(self, espacamento: float) -> list[tuple[float, float]]:
        """(início, fim) em m de trechos consecutivos de ~`espacamento` metros
        que cobrem a calçada inteira."""
        if self._degenerada:
            return [(0.0, 0.0)] if self._pts else []
        quantidade = max(1, round(self.extensao / espacamento))
        passo = self.extensao / quantidade
        return [(k * passo, (k + 1) * passo) for k in range(quantidade)]


# --------------------------------------------------------------------------- #
# Ruas (OpenStreetMap)
# --------------------------------------------------------------------------- #

class RuaNaoEncontrada(SystemExit):
    """Nenhuma rua de Curitiba casa com o nome. Fora do menu, encerra com a mensagem."""


class OverpassIndisponivel(SystemExit):
    """Nenhum servidor Overpass respondeu (vivem sobrecarregados). Fora do menu, encerra."""


class RuaAmbigua(SystemExit):
    """O nome não leva a uma rua só; `nomes` traz as candidatas e `titulo`
    explica por quê (várias casam, ou nenhuma casa e estas são parecidas)."""

    def __init__(self, nomes: list[str], titulo: str = "Mais de uma rua casa com esse nome:"):
        super().__init__(titulo + "\n  " + "\n  ".join(nomes))
        self.nomes, self.titulo = nomes, titulo


# Abreviações comuns no nome digitado. Tipos de via valem só na 1ª palavra,
# com ou sem ponto ("R. XV", "Av Batel"); títulos, só com ponto ("Des. Motta").
_TIPOS = {"r": "Rua", "av": "Avenida", "al": "Alameda", "tv": "Travessa", "trav": "Travessa",
          "pç": "Praça", "pca": "Praça", "pça": "Praça", "rod": "Rodovia", "lgo": "Largo"}
_TITULOS = {"dr": "Doutor", "dra": "Doutora", "prof": "Professor", "profa": "Professora",
            "des": "Desembargador", "cel": "Coronel", "gen": "General", "gal": "General",
            "com": "Comendador", "eng": "Engenheiro", "sen": "Senador", "dep": "Deputado",
            "pres": "Presidente", "mal": "Marechal", "ten": "Tenente", "cap": "Capitão",
            "pe": "Padre", "sta": "Santa", "sto": "Santo", "visc": "Visconde", "bar": "Barão"}
VIAS_CURITIBA = CACHE_RUAS / "_vias_curitiba.json.gz"  # todas as vias com nome, de uma vez


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _chave(nome: str) -> str:
    """Forma de comparar nomes: sem acento, minúsculas, espaços simples."""
    return " ".join(_sem_acento(nome).lower().split())


def normalizar_nome(nome: str) -> str:
    """O nome como alguém digitaria -> o mais perto do OSM: corta o que vem
    depois da vírgula (bairro, cidade) e expande as abreviações."""
    palavras = nome.split(",")[0].split()
    for k, palavra in enumerate(palavras):
        chave = palavra.rstrip(".").lower()
        if k == 0 and chave in _TIPOS:
            palavras[k] = _TIPOS[chave]
        elif palavra.endswith(".") and chave in _TITULOS:
            palavras[k] = _TITULOS[chave]
    return " ".join(palavras)


_vias: Optional[dict[str, list]] = None


def vias_de_curitiba() -> dict[str, list]:
    """
    {nome no OSM: trechos} de todas as vias com nome de Curitiba, cada trecho
    uma lista de [lat, lon]. Baixadas numa consulta só ao Overpass (~1 min,
    ~1 MB compactado) e guardadas em VIAS_CURITIBA: daí em diante, achar uma
    rua e o traçado dela é local e instantâneo. Consultar o Overpass rua a
    rua não serve — os servidores públicos vivem sobrecarregados e levam de
    30 s a minutos até para um nome exato, quando respondem. Apague o arquivo
    para baixar o OSM de novo.
    """
    global _vias
    if _vias is None and VIAS_CURITIBA.exists():
        _vias = json.loads(gzip.decompress(VIAS_CURITIBA.read_bytes()))["vias"]
    if _vias is not None:
        return _vias

    print("Baixando as ruas de Curitiba do OpenStreetMap (só na primeira vez, ~1 min)...", flush=True)
    query = ('[out:json][timeout:300]; area["name"="Curitiba"]["admin_level"="8"]->.cwb; '
             'way["highway"]["highway"!="platform"]["name"](area.cwb); out tags geom;')
    falhas = []
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query},
                                 headers={"User-Agent": "calcadas-curitiba/0.1"}, timeout=400)
            resp.raise_for_status()
            elementos = resp.json().get("elements", [])
        except (requests.exceptions.RequestException, ValueError) as exc:
            falhas.append(f"{url}: {exc}")
            continue
        if len(elementos) > 1000:  # menos que isso: resposta truncada no meio
            break
        falhas.append(f"{url}: resposta incompleta ({len(elementos)} vias)")
    else:
        raise OverpassIndisponivel("Nenhum servidor Overpass respondeu:\n  " + "\n  ".join(falhas))

    vias: dict[str, list] = {}
    for w in elementos:
        vias.setdefault(w["tags"]["name"], []).append([[round(p["lat"], 6), round(p["lon"], 6)]
                                                        for p in w["geometry"]])
    CACHE_RUAS.mkdir(parents=True, exist_ok=True)
    dados = {"fonte": "OpenStreetMap (ODbL), via Overpass", "obtido": time.strftime("%Y-%m-%d"), "vias": vias}
    VIAS_CURITIBA.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode()))
    _vias = vias
    return vias


def _grafia(grafias: list[str]) -> str:
    """A grafia de uma rua entre as variantes do OSM: a mais comum entre os
    trechos; no empate, a acentuada."""
    return max(set(grafias), key=lambda g: (grafias.count(g), g != _sem_acento(g), g))


def identificar_rua(nome: str) -> list[str]:
    """
    As grafias, no OSM, da rua que o nome digitado indica. O OSM às vezes
    grafa a mesma rua de dois jeitos em trechos diferentes ("Isaias" e
    "Isaías"): nomes iguais a menos de acento e maiúscula são uma rua só.
    Tenta o nome exato e depois "contém"; sem nada, sugere os parecidos.
    """
    nome = normalizar_nome(nome)
    chave = _chave(nome)
    ruas: dict[str, list[str]] = {}
    for n in vias_de_curitiba():
        ruas.setdefault(_chave(n), []).append(n)
    if chave in ruas:
        return ruas[chave]
    contem = [c for c in ruas if chave in c]
    if len(contem) == 1:
        return ruas[contem[0]]
    if contem:
        raise RuaAmbigua(sorted(_grafia(ruas[c]) for c in contem))
    parecidas = difflib.get_close_matches(chave, list(ruas), n=8, cutoff=0.75)
    if parecidas:
        raise RuaAmbigua([_grafia(ruas[c]) for c in parecidas],
                         f'Nenhuma rua de Curitiba se chama "{nome}". Você quis dizer:')
    raise RuaNaoEncontrada(f'Nenhuma rua encontrada em Curitiba com o nome "{nome}".')


def _cache_rua(nome: str) -> Path:
    return CACHE_RUAS / (_sem_acento(nome).lower().replace("/", "_") + ".json")


def buscar_rua(nome: str) -> tuple[str, list[list[tuple]]]:
    """
    (nome oficial no OSM, trechos), cada trecho uma lista de (lat, lon).

    Aceita o nome como se escreve: sem acento, em minúsculas, abreviado ("R.
    comendador araujo") e com bairro ou cidade depois da vírgula (veja
    `identificar_rua`). Sem rua: RuaNaoEncontrada; com várias candidatas:
    RuaAmbigua. O traçado sai de `vias_de_curitiba` e é congelado num JSON
    por rua: as zonas de uma rua já coletada não mudam se o OSM mudar.
    """
    cache = _cache_rua(normalizar_nome(nome))
    if cache.exists():
        dados = json.loads(cache.read_text(encoding="utf-8"))
        return dados["nome"], [[tuple(p) for p in t] for t in dados["trechos"]]

    vias = vias_de_curitiba()
    grafias = identificar_rua(nome)
    oficial = _grafia([g for g in grafias for _ in vias[g]])  # a grafia com mais trechos
    trechos = [[tuple(p) for p in t] for g in grafias for t in vias[g]]
    CACHE_RUAS.mkdir(parents=True, exist_ok=True)
    dados = json.dumps({"nome": oficial, "trechos": trechos}, ensure_ascii=False)
    # Também sob o nome oficial: as etapas seguintes buscam por ele.
    for arquivo in {cache, _cache_rua(oficial)}:
        arquivo.write_text(dados, encoding="utf-8")
    return oficial, trechos


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
