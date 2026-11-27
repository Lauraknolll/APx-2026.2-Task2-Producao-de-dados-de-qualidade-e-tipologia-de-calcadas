"""
Etapa 4 da coleta: a avaliação automática da qualidade de cada quadrado.

Lê do banco os quadrados limpos da vista escolhida de cada zona aprovada,
classifica os que ainda não têm avaliação e grava em `avaliacoes` com
origem = "modelo", o nome do modelo em `autor` e a probabilidade em
`confianca`. É o que colore as ruas no mapa — sem ninguém avaliar à mão.

Uma avaliação manual nunca é sobrescrita: ela é a correção de uma pessoa e
vale mais que o modelo. Com --refazer, as avaliações do próprio modelo são
refeitas (por exemplo, depois de trocar o .joblib).

    python -m scripts.ingestao.coleta_streetview avaliar               # tudo que falta
    python -m scripts.ingestao.coleta_streetview avaliar --rua "Rua X"
    python -m scripts.ingestao.coleta_streetview avaliar --refazer     # refaz as do modelo
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional

from scripts.ingestao.coleta_streetview import config
from scripts.ingestao.coleta_streetview.banco import filtro_zonas, registrar_avaliacao


def quadrados_a_avaliar(conn: sqlite3.Connection, filtro: str = "", params: Optional[list] = None,
                        refazer: bool = False) -> list[tuple[int, int, int]]:
    """(zona, vista, quadrado) dos quadrados limpos sem avaliação (ou, com
    `refazer`, sem avaliação manual)."""
    linhas = conn.execute(f"""
        SELECT p.id, p.tentativa, p.quadrados FROM pontos p
        WHERE p.status = 'aprovada' AND p.quadrados IS NOT NULL {filtro}
        ORDER BY p.id""", params or []).fetchall()
    avaliados = {(pid, pos, q): origem for pid, pos, q, origem in
                 conn.execute("SELECT ponto_id, posicao, quadrado, origem FROM avaliacoes")}
    saida = []
    for pid, tentativa, limpos in linhas:
        for k in map(int, limpos.split(",")):
            origem = avaliados.get((pid, tentativa, k))
            if origem is None or (refazer and origem == "modelo"):
                saida.append((pid, tentativa, k))
    return saida


def contar_sem_avaliacao(conn: sqlite3.Connection, rua: str) -> int:
    """Quantos quadrados da rua (nome oficial) ainda não têm avaliação."""
    return len(quadrados_a_avaliar(conn, " AND p.id IN (SELECT ponto_id FROM pontos_rua WHERE rua = ?)", [rua]))


def carregar_classificador(caminho: Optional[Path] = None, confianca_min: Optional[float] = None):
    """O classificador de produção, ou None (com o motivo impresso) se não houver."""
    from .classificador import ClassificadorQualidade

    caminho = Path(caminho or config.MODELO_QUALIDADE)
    if not caminho.is_file():
        print(f"  Sem modelo de qualidade em {caminho.relative_to(config.RAIZ) if caminho.is_relative_to(config.RAIZ) else caminho}:"
              " a avaliação automática foi pulada.\n"
              "  Gere com `python -m scripts.inferencia.treinar` (ou copie o .joblib do Cenário 4 para lá).")
        return None
    return ClassificadorQualidade.carregar(
        caminho, config.BACKBONE_QUALIDADE,
        config.CONFIANCA_MIN if confianca_min is None else confianca_min, config.LOTE_QUALIDADE)


def cmd_avaliar(args, conn: sqlite3.Connection) -> int:
    """Avalia os quadrados que faltam; retorna quantos foram avaliados."""
    filtro, params = filtro_zonas(args)
    pendentes = quadrados_a_avaliar(conn, filtro, params, refazer=getattr(args, "refazer", False))
    if not pendentes:
        print("  Nenhum quadrado sem avaliação.")
        return 0
    clf = carregar_classificador(getattr(args, "modelo", None), getattr(args, "confianca_min", None))
    if clf is None:
        return 0

    pasta = config.PASTA_IMAGENS / "quadrados"
    print(f"  {len(pendentes)} quadrados para avaliar com o modelo \"{clf.nome}\" ({clf.backbone})", flush=True)
    t0, contagem, feitos = time.time(), {}, 0
    print(f"  [0/{len(pendentes)}] quadrados avaliados", flush=True)
    for i in range(0, len(pendentes), clf.lote):
        lote = [q for q in pendentes[i:i + clf.lote] if (pasta / f"{q[0]}_{q[1]}_{q[2]}.jpg").is_file()]
        resultados = clf.classificar([pasta / f"{pid}_{pos}_{k}.jpg" for pid, pos, k in lote])
        for (pid, pos, k), (classe, conf) in zip(lote, resultados):
            registrar_avaliacao(conn, pid, pos, k, classe, origem="modelo", autor=clf.nome,
                                confianca=None if conf is None else round(conf, 4))
            contagem[classe] = contagem.get(classe, 0) + 1
        feitos = min(i + clf.lote, len(pendentes))
        print(f"  [{feitos}/{len(pendentes)}] quadrados avaliados", flush=True)

    resumo = ", ".join(f"{n} {c.replace('_', ' ')}" for c, n in sorted(contagem.items(), key=lambda x: -x[1]))
    print(f"  Avaliados: {sum(contagem.values())} quadrados em {time.time() - t0:.0f}s ({resumo}).")
    return sum(contagem.values())
