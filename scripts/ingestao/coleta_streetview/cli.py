"""
Linha de comando: `python -m scripts.ingestao.coleta_streetview`.

Sem argumentos, abre o menu: pergunta a rua (com quantas zonas cada uma tem)
e quantas zonas rodar, e faz tudo, do começo ao fim (comando `rua`). As
etapas continuam disponíveis como subcomandos, para rodar uma de cada vez:

    coletar    zonas e vistas candidatas (só metadados)
    baixar     closes, quadrados e vistas de contexto
    segmentar  quadrados limpos, escolha da vista de cada zona, downloads-ruas/
    reavaliar  refaz a escolha com outros limites, sem baixar nem segmentar
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

from . import config
from .banco import abrir_db, exportar_ruas, pasta_da_rua, resumo_exportacao
from .etapas import cmd_baixar, cmd_coletar, cmd_reavaliar, cmd_segmentar, zonas_da_rua

# --------------------------------------------------------------------------- #
# Fluxo completo de uma rua (modo interativo)
# --------------------------------------------------------------------------- #


def _perguntar(texto: str) -> str:
    try:
        return input(texto).strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nNada foi coletado.")


def _situacao(conn: sqlite3.Connection, zonas: list[tuple]) -> dict[tuple, str]:
    """Status no banco de cada zona (chave -> pendente | aprovada | recoleta)."""
    no_banco = {(fid, anel, ordem): status for fid, anel, ordem, status in
                conn.execute("SELECT fid, anel, ordem, status FROM pontos")}
    return {z[0]: no_banco[z[0]] for z in zonas if z[0] in no_banco}


def escolher_rua(conn: sqlite3.Connection) -> str:
    """Pergunta qual das config.RUAS coletar, com quantas zonas cada uma tem."""
    print("Qual rua coletar?")
    for i, rua in enumerate(config.RUAS, 1):
        _, zonas = zonas_da_rua(rua)
        feitas = sum(s == "aprovada" for s in _situacao(conn, zonas).values())
        print(f"  {i}) {rua}; {len(zonas)} zonas" + (f" ({feitas} já com foto)" if feitas else ""))
    while True:
        resposta = _perguntar(f"Escolha [1-{len(config.RUAS)}]: ")
        if resposta.isdigit() and 1 <= int(resposta) <= len(config.RUAS):
            return config.RUAS[int(resposta) - 1]
        print(f"Digite um número de 1 a {len(config.RUAS)}.")


def perguntar_quantidade(maximo: int) -> Optional[int]:
    """Quantas zonas rodar; None = todas."""
    while True:
        resposta = _perguntar(f"Quantas zonas rodar? [1-{maximo}, Enter = todas]: ")
        if not resposta:
            return None
        if resposta.isdigit() and 1 <= int(resposta) <= maximo:
            return int(resposta)
        print(f"Digite um número de 1 a {maximo}, ou Enter para todas.")


def cmd_rua(args, conn: sqlite3.Connection, parser: argparse.ArgumentParser):
    """
    Uma rua do começo ao fim: coleta, closes e quadrados, segmentação e
    escolha da melhor vista de cada zona, capturas históricas onde nenhuma
    recente serviu e, por fim, downloads-ruas/<rua>/. Com um limite, roda só
    N zonas ainda sem resultado, espalhadas pela rua — da coleta em diante.
    Pode ser interrompido e rodado de novo: continua de onde parou.
    """
    def etapa(*argv, **extra):
        etapa_args = parser.parse_args(argv)
        etapa_args.fluxo = True  # esconde as dicas de "rode o próximo comando"
        vars(etapa_args).update(extra)
        return etapa_args

    nome = args.nome or escolher_rua(conn)
    nome_osm, zonas = zonas_da_rua(nome)
    situacao = _situacao(conn, zonas)
    # Sem resultado ainda: nunca coletadas, ou coletadas e não terminadas.
    a_fazer = [z[0] for z in zonas if situacao.get(z[0]) not in ("aprovada", "recoleta")]
    print(f'\n"{nome_osm}": {len(zonas)} zonas, {len(zonas) - len(a_fazer)} já processadas, '
          f"{len(a_fazer)} a processar.")
    if not a_fazer:
        print("Nada a fazer. Para refazer zonas, use os comandos de etapa com --refazer.")
        print(resumo_exportacao(exportar_ruas(conn)))
        return
    limite = args.limite if args.limite else (None if args.nome else perguntar_quantidade(len(a_fazer)))
    if limite and limite < len(a_fazer):
        passo = len(a_fazer) / limite  # espalhadas pela rua
        escolhidas = [a_fazer[int(i * passo)] for i in range(limite)]
    else:
        escolhidas = a_fazer

    t0 = time.time()
    print(f"\n== 1/3 Zonas e panoramas ({len(escolhidas)} zonas)")
    cmd_coletar(etapa("coletar", "--rua", nome, apenas=set(escolhidas)), conn)
    conjunto = set(escolhidas)
    ids = [pid for pid, *chave in conn.execute("SELECT id, fid, anel, ordem FROM pontos")
           if tuple(chave) in conjunto]
    so_estas = ["--zonas", ",".join(map(str, ids))]

    # Primeira leva: capturas recentes; as seguintes, só históricas das zonas
    # em que nenhuma recente passou no filtro.
    for leva in range(1, 4):
        print(f"\n== 2/3 Closes e quadrados (leva {leva})")
        if not cmd_baixar(etapa("baixar", "--rua", nome, *so_estas), conn):
            break
        print(f"\n== 3/3 Calçada ou não: segmentação dos quadrados (leva {leva})")
        cmd_segmentar(etapa("segmentar", "--rua", nome, *so_estas), conn)

    situacao = _situacao(conn, zonas)
    rodadas = [situacao.get(c) for c in escolhidas]
    total = list(situacao.values())
    quadrados = sum(len(q.split(",")) for (q,) in conn.execute(
        "SELECT p.quadrados FROM pontos p JOIN pontos_rua r ON r.ponto_id = p.id "
        "WHERE r.rua = ? AND p.status = 'aprovada' AND p.quadrados IS NOT NULL", (nome_osm,)))
    print(f'\nPronto: {len(escolhidas)} zonas da "{nome_osm}" em {(time.time() - t0) / 60:.0f} min — '
          f"{rodadas.count('aprovada')} com foto, {rodadas.count('recoleta')} sem foto boa.")
    print(f"  Na rua: {total.count('aprovada')} de {len(zonas)} zonas com foto; "
          f"{quadrados} quadrados de calçada em {pasta_da_rua(nome_osm).relative_to(config.RAIZ)}/")


# --------------------------------------------------------------------------- #
# Argumentos
# --------------------------------------------------------------------------- #

def _parse_bbox(texto: str) -> tuple:
    valores = tuple(float(v) for v in texto.split(","))
    if len(valores) != 4:
        raise argparse.ArgumentTypeError("bbox deve ser lon_min,lat_min,lon_max,lat_max")
    return valores


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.ingestao.coleta_streetview", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("rua", help="uma rua do começo ao fim (é o que roda sem argumentos)")
    p.add_argument("--nome", help="nome da rua no OpenStreetMap; sem isso, pergunta qual das ruas conhecidas")
    p.add_argument("--limite", type=int, help="só N zonas, espalhadas pela rua; sem isso, todas as que faltam")

    p = sub.add_parser("coletar", help="zonas de calçada e vistas candidatas (só metadados)")
    p.add_argument("--rua", help='só uma rua, ex: "Rua XV de Novembro" (ignora --bbox)')
    p.add_argument("--bbox", type=_parse_bbox, default=config.CURITIBA_BBOX,
                   help="lon_min,lat_min,lon_max,lat_max (default: Curitiba inteira)")
    p.add_argument("--espacamento", type=float, default=config.ESPACAMENTO,
                   help=f"tamanho em m de cada zona; uma foto por zona (default: {config.ESPACAMENTO:.0f})")
    p.add_argument("--passo", type=float, default=config.PASSO_ALVOS,
                   help=f"m entre os alvos dentro da zona (default: {config.PASSO_ALVOS:.0f})")
    p.add_argument("--historicas", type=int, default=1,
                   help="capturas históricas de cada panorama que entram como reserva (default: 1)")
    p.add_argument("--desde", help="ignora capturas anteriores a AAAA-MM")
    p.add_argument("--distancia-rua", type=float, default=config.DISTANCIA_RUA,
                   help=f"com --rua: distância máx. da zona ao eixo da rua (default: {config.DISTANCIA_RUA:.0f})")
    p.add_argument("--calcadas", type=Path, default=config.CALCADAS_PATH,
                   help=f"camada de calçadas (default: {config.CALCADAS_PATH.relative_to(config.RAIZ)})")
    p.add_argument("--workers", type=int, default=4,
                   help="consultas em paralelo; mais que isso arrisca bloqueio (default: 4)")
    p.add_argument("--refazer", action="store_true",
                   help="consulta de novo zonas pendentes e em recoleta (as aprovadas nunca)")

    baixar = sub.add_parser("baixar", help="closes, quadrados e vistas de contexto das zonas pendentes")
    baixar.add_argument("--limite", type=int, help="só N zonas")
    baixar.add_argument("--aleatorio", action="store_true", help="sorteia as zonas (com --limite)")
    baixar.add_argument("--quadrados", type=int, default=config.QUADRADOS,
                        help=f"o close tem proporção N:1 e é cortado em N quadrados (default: {config.QUADRADOS})")
    baixar.add_argument("--altura-max", type=int, default=config.ALTURA_MAX,
                        help="altura máx. do close em px, arredondada para múltiplo de 14 "
                             f"(default: {config.ALTURA_MAX})")
    baixar.add_argument("--folga", type=float, default=config.FOLGA,
                        help=f"quanto da faixa guia-alinhamento entra na vista; 1 = só ela (default: {config.FOLGA})")
    baixar.add_argument("--fov-min", type=float, default=config.FOV_MIN,
                        help=f"campo de visão vertical mínimo em graus (default: {config.FOV_MIN:.0f})")
    baixar.add_argument("--limite-inferior", type=float, default=config.LIMITE_INFERIOR,
                        help="a vista não desce além disso (graus), onde começa o borrão do carro "
                             f"(default: {config.LIMITE_INFERIOR:.0f})")
    baixar.add_argument("--workers", type=int, default=4)

    segmentar = sub.add_parser("segmentar", help="quadrados limpos e escolha da vista de cada zona")
    segmentar.add_argument("--mascaras", action="store_true",
                           help=f"salva a segmentação em {(config.PASTA_IMAGENS / 'mascaras').relative_to(config.RAIZ)}/")
    reavaliar = sub.add_parser("reavaliar", help="refaz a escolha com outros limites, sem baixar nem segmentar")
    for p in (segmentar, reavaliar):
        p.add_argument("--min-calcada", type=float, default=config.MIN_CALCADA,
                       help=f"fração mínima de piso de calçada no quadrado (default: {config.MIN_CALCADA})")
        p.add_argument("--max-obstrucao", type=float, default=config.MAX_OBSTRUCAO,
                       help="fração máxima do quadrado tampada por veículos, pessoas ou pelo borrão "
                            f"do carro do Google (default: {config.MAX_OBSTRUCAO})")
    for p in (baixar, segmentar):
        p.add_argument("--rua", help="só as zonas de uma rua já coletada com coletar --rua")
        p.add_argument("--zonas", help="só estas zonas (ids separados por vírgula)")

    return parser


def main(argv: Optional[list[str]] = None):
    parser = criar_parser()
    argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(argv or ["rua"])  # sem argumentos: o menu
    conn = abrir_db()
    if args.comando == "rua":
        cmd_rua(args, conn, parser)
    else:
        {"coletar": cmd_coletar, "baixar": cmd_baixar, "segmentar": cmd_segmentar,
         "reavaliar": cmd_reavaliar}[args.comando](args, conn)
