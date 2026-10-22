"""
Leitura da camada de calçadas do IPPUC (passeio.gpkg) e geometria em metros.

A camada está em SIRGAS 2000 / UTM 22S (EPSG:31982). Os panoramas do Street
View vêm em lat/lon (WGS84); convertemos tudo para UTM e fazemos a geometria
em metros. SIRGAS 2000 e WGS84 diferem em centímetros, o que é irrelevante
aqui.

Só usa a biblioteca padrão: GeoPackage é um SQLite, e a geometria é WKB com
um cabeçalho curto.
"""

import math
import shutil
import sqlite3
import struct
import zipfile
from pathlib import Path
from typing import Iterator, Optional

from .config import CALCADAS_PATH, CALCADAS_ZIP

# --------------------------------------------------------------------------- #
# Projeção UTM 22S (série de Krüger, precisão sub-milimétrica)
# --------------------------------------------------------------------------- #

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
