"""
O filtro dos quadrados e a escolha da melhor vista de cada zona.

Um quadrado é LIMPO quando tem piso de calçada >= MIN_CALCADA e obstrução na
frente (veículo + pessoa + borrão do carro) <= MAX_OBSTRUCAO. Uma vista passa
se tiver pelo menos um quadrado limpo. Entre as vistas que passam, a zona fica
com a de captura mais recente (o que se avalia é a calçada como está hoje);
na mesma data, a com mais quadrados limpos e, depois, a de melhor nota. Só os
quadrados limpos da vista escolhida vão para o resultado.

Estas funções só leem e gravam o banco — não baixam nem segmentam nada —, o
que permite recalibrar os limites com `reavaliar`.
"""

import json
import sqlite3
from typing import Optional

from .config import MAX_OBSTRUCAO, MIN_CALCADA, OBSTRUCAO_NA_FRENTE

# Motivos gravados pelo filtro; são refeitos a cada decisão. Qualquer outro
# motivo em `tentativas.rejeicao` é uma recusa da etapa de IA, que é mantida.
MOTIVOS_DO_FILTRO = ("pouca_calcada", "obstruida")


def motivo_rejeicao(piso: float, obstrucao: dict, min_calcada: float = MIN_CALCADA,
                    max_obstrucao: float = MAX_OBSTRUCAO) -> Optional[str]:
    """Por que um quadrado (ou vista) não passa no filtro, ou None se passa."""
    if piso < min_calcada:
        return f"pouca_calcada ({piso:.0%})"
    na_frente = {t: obstrucao.get(t, 0.0) for t in OBSTRUCAO_NA_FRENTE}
    if sum(na_frente.values()) > max_obstrucao:
        return f"obstruida ({sum(na_frente.values()):.0%}, mais {max(na_frente, key=na_frente.get)})"
    return None


def nota(piso: float, obstrucao: dict) -> float:
    """Quanto melhor a vista: piso visível menos o que está na frente dele."""
    return piso - sum(obstrucao.get(t, 0.0) for t in OBSTRUCAO_NA_FRENTE)


def avaliar_quadrados(quadrados: list[dict], min_calcada: float,
                      max_obstrucao: float) -> tuple[list[int], Optional[str], float]:
    """
    (quadrados limpos, numerados a partir de 1; motivo, se nenhum é; nota
    média dos limpos). Cada quadrado passa ou não no filtro sozinho — um carro
    num terço do close não condena os outros dois.
    """
    limpos = [k for k, q in enumerate(quadrados, 1)
              if motivo_rejeicao(q["piso"], q["obstrucao"], min_calcada, max_obstrucao) is None]
    if not limpos:
        melhor = max(quadrados, key=lambda q: nota(q["piso"], q["obstrucao"]))
        motivo = motivo_rejeicao(melhor["piso"], melhor["obstrucao"], min_calcada, max_obstrucao)
        return [], f"{motivo} em todos os quadrados", 0.0
    media = sum(nota(quadrados[k - 1]["piso"], quadrados[k - 1]["obstrucao"]) for k in limpos) / len(limpos)
    return limpos, None, media


def decidir_zona(conn: sqlite3.Connection, ponto_id: int,
                 min_calcada: float = MIN_CALCADA, max_obstrucao: float = MAX_OBSTRUCAO) -> str:
    """
    Escolhe a vista da zona entre as candidatas já segmentadas e grava o
    resultado em `pontos`. Se nenhuma passa, ou se ainda falta avaliar alguma
    mais recente que a melhor, a zona segue pendente; se não há mais o que
    avaliar, vai para recoleta. Retorna o novo status.
    """
    melhor, falta = None, []
    for posicao, data, frac_calcada, obstrucao, quadrados, rejeicao in conn.execute(
            "SELECT posicao, COALESCE(data, ''), frac_calcada, obstrucao, quadrados, rejeicao "
            "FROM tentativas WHERE ponto_id = ? AND posicao < 1000 ORDER BY posicao", (ponto_id,)).fetchall():
        if rejeicao and not rejeicao.startswith(MOTIVOS_DO_FILTRO):
            continue  # recusada pela etapa de IA: não volta
        if frac_calcada is None:
            falta.append(data)  # ainda não baixada (ou o download falhou; o 'baixar' tenta de novo)
            continue
        # Vistas segmentadas antes dos quadrados contam como um quadrado só.
        quadrados = json.loads(quadrados) if quadrados else [
            {"piso": frac_calcada, "obstrucao": json.loads(obstrucao)}]
        limpos, motivo, media = avaliar_quadrados(quadrados, min_calcada, max_obstrucao)
        conn.execute("UPDATE tentativas SET rejeicao = ? WHERE ponto_id = ? AND posicao = ?",
                     (motivo, ponto_id, posicao))
        chave = (data, len(limpos), media)
        if motivo is None and (melhor is None or chave > melhor[0]):
            melhor = (chave, posicao, limpos)

    if melhor and not any(data > melhor[0][0] for data in falta):
        status, tentativa, motivo, limpos = "aprovada", melhor[1], None, ",".join(map(str, melhor[2]))
    elif falta:
        status, tentativa, motivo, limpos = "pendente", None, None, None
    else:
        status, tentativa, motivo, limpos = "recoleta", None, "todas_rejeitadas", None
    conn.execute("UPDATE pontos SET status = ?, tentativa = COALESCE(?, tentativa), motivo = ?, quadrados = ? "
                 "WHERE id = ?", (status, tentativa, motivo, limpos, ponto_id))
    return status


def registrar_rejeicao(conn: sqlite3.Connection, ponto_id: int, motivo: str):
    """
    Para a etapa de IA de avaliação: a vista escolhida para a zona não serve.
    Ela nunca mais é escolhida, e a zona passa para a melhor reserva; se não
    houver, vai para recoleta. Rode `reavaliar` (ou o fluxo da rua) depois
    para atualizar downloads-ruas/.
    """
    tentativa = conn.execute("SELECT tentativa FROM pontos WHERE id = ?", (ponto_id,)).fetchone()[0]
    conn.execute("UPDATE tentativas SET rejeicao = ? WHERE ponto_id = ? AND posicao = ?",
                 (f"recusada: {motivo}", ponto_id, tentativa))
    decidir_zona(conn, ponto_id)
    conn.commit()


def cmd_reavaliar(args, conn: sqlite3.Connection):
    """Reaplica os limites às vistas já segmentadas, sem baixar nem segmentar
    nada — para calibrar --min-calcada e --max-obstrucao."""
    from .exportacao import exportar_ruas, resumo_exportacao

    antes = dict(conn.execute("SELECT status, COUNT(*) FROM pontos GROUP BY status").fetchall())
    zonas = [r[0] for r in conn.execute("SELECT DISTINCT ponto_id FROM tentativas WHERE frac_calcada IS NOT NULL")]
    for pid in zonas:
        decidir_zona(conn, pid, args.min_calcada, args.max_obstrucao)
    conn.commit()
    depois = dict(conn.execute("SELECT status, COUNT(*) FROM pontos GROUP BY status").fetchall())
    print(f"{len(zonas)} zonas reavaliadas. Antes: {antes}. Depois: {depois}.")
    print(resumo_exportacao(exportar_ruas(conn)))
