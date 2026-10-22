"""
O resultado: downloads-ruas/<rua>/, a coleta mais recente de cada rua.

Para cada rua coletada, a pasta tem só os quadrados limpos da vista escolhida
de cada zona aprovada (<zona>_<tentativa>_<quadrado>.jpg) e um indice.csv que
liga cada foto à zona, às coordenadas e ao panorama de origem — para
georreferenciar e auditar. A pasta é sincronizada com o banco a cada rodada:
o que deixou de valer (zona reavaliada, foto recusada, quadrado que deixou de
passar) sai, o que é novo entra.
"""

import csv
import json
import shutil
import sqlite3
import unicodedata
from pathlib import Path

from .config import OBSTRUCAO_NA_FRENTE, PASTA_IMAGENS, PASTA_RUAS, RAIZ

CAMPOS_INDICE = ["arquivo", "zona", "quadrado", "captura", "lat", "lon", "endereco", "piso",
                 "obstrucao", "pano_id"]


def pasta_da_rua(rua: str) -> Path:
    """downloads-ruas/<nome da rua sem acentos, minúsculo, com hífens>/"""
    sem_acento = unicodedata.normalize("NFKD", rua).encode("ascii", "ignore").decode()
    return PASTA_RUAS / "-".join("".join(c if c.isalnum() else " " for c in sem_acento.lower()).split())


def exportar_ruas(conn: sqlite3.Connection) -> dict[str, int]:
    """Sincroniza downloads-ruas/<rua>/ de todas as ruas; retorna quadrados por rua."""
    contagem = {}
    for (rua,) in conn.execute("SELECT DISTINCT rua FROM pontos_rua").fetchall():
        pasta = pasta_da_rua(rua)
        pasta.mkdir(parents=True, exist_ok=True)
        desejados, linhas = {}, []
        for pid, tentativa, limpos, endereco, data, pano, alat, alon, quadrados in conn.execute("""
                SELECT p.id, p.tentativa, p.quadrados, p.endereco, t.data, t.pano_id, t.alvo_lat,
                       t.alvo_lon, t.quadrados
                FROM pontos p JOIN pontos_rua r ON r.ponto_id = p.id
                JOIN tentativas t ON t.ponto_id = p.id AND t.posicao = p.tentativa
                WHERE r.rua = ? AND p.status = 'aprovada' AND p.quadrados IS NOT NULL
                ORDER BY p.id""", (rua,)):
            medidas = json.loads(quadrados) if quadrados else []
            for k in map(int, limpos.split(",")):
                nome = f"{pid}_{tentativa}_{k}.jpg"
                desejados[nome] = PASTA_IMAGENS / "quadrados" / nome
                m = medidas[k - 1] if k <= len(medidas) else {"piso": None, "obstrucao": {}}
                linhas.append({"arquivo": nome, "zona": pid, "quadrado": k, "captura": data,
                               "lat": round(alat, 7), "lon": round(alon, 7), "endereco": endereco or "",
                               "piso": m["piso"],
                               "obstrucao": round(sum(m["obstrucao"].get(t, 0) for t in OBSTRUCAO_NA_FRENTE), 3),
                               "pano_id": pano})
        for arquivo in pasta.glob("*.jpg"):
            if arquivo.name not in desejados:
                arquivo.unlink()
        for nome, origem in desejados.items():
            if not (pasta / nome).exists() and origem.exists():
                shutil.copy2(origem, pasta / nome)
        with open(pasta / "indice.csv", "w", newline="", encoding="utf-8") as f:
            escritor = csv.DictWriter(f, fieldnames=CAMPOS_INDICE)
            escritor.writeheader()
            escritor.writerows(linhas)
        contagem[rua] = len(desejados)
    return contagem


def resumo_exportacao(contagem: dict[str, int]) -> str:
    """Uma linha com quantos quadrados cada rua tem em downloads-ruas/."""
    if not contagem:
        return ""
    return "Quadrados de calçada por rua: " + "; ".join(
        f"{n} em {pasta_da_rua(rua).relative_to(RAIZ)}" for rua, n in contagem.items())
