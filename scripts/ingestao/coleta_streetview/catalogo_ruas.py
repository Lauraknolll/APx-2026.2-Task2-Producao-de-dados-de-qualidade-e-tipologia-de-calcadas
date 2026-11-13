"""
Catálogo das vias de Curitiba: um CSV com todas as ruas nomeadas do
OpenStreetMap, já classificadas, para escolher o que coletar.

A geometria (nº de trechos e comprimento) sai do `_vias_curitiba.json.gz` que
a coleta já tem — nada de rede. A classificação (`highway`: avenida, arterial,
local...) não está nesse arquivo, então vem de uma consulta leve ao Overpass,
só com as tags (sem geometria), que raramente dá timeout. Se nenhum servidor
responder, o CSV sai mesmo assim, só sem a coluna de classificação.

Os trechos são agrupados por rua com a mesma lógica de grafia do `buscar_rua`,
de modo que todo nome do CSV serve direto na coleta:

    python -m scripts.ingestao.coleta_streetview.catalogo_ruas
    python -m scripts.ingestao.coleta_streetview.catalogo_ruas --offline
    python -m scripts.ingestao.coleta_streetview.catalogo_ruas --saida minha_lista.csv

Gera, por padrão, `data/raw/ruas_osm/ruas_curitiba_classificadas.csv`, com uma
linha por rua: nome oficial, tipo, classificação do OSM, categoria em
português, nº de trechos e comprimento total (m). Ordena das arteriais (mais
longas primeiro) para as locais, então as "principais" ficam no topo.

Rode sempre da raiz do repositório.
"""

import argparse
import csv
import gzip
import json
import math
import sys
from collections import Counter, defaultdict

import requests

from .config import CACHE_RUAS, OVERPASS_URLS
from .geometria import VIAS_CURITIBA, _chave, _grafia, ll_para_utm

# Consulta leve: só as tags (nome + highway), sem geometria. É o que falta no
# .gz; a geometria já está lá. Bem mais leve que o `out tags geom` da coleta.
QUERY_TAGS = ('[out:json][timeout:180]; area["name"="Curitiba"]["admin_level"="8"]->.cwb; '
              'way["highway"]["highway"!="platform"]["name"](area.cwb); out tags;')

# Classificação do OSM -> categoria em português e prioridade (menor = mais
# "principal"). As arteriais vêm primeiro no CSV.
CATEGORIAS = {
    "motorway":      ("Via expressa / rodovia", 0),
    "motorway_link": ("Via expressa / rodovia", 0),
    "trunk":         ("Via expressa / rodovia", 0),
    "trunk_link":    ("Via expressa / rodovia", 0),
    "primary":       ("Arterial principal", 1),
    "primary_link":  ("Arterial principal", 1),
    "secondary":     ("Arterial secundária", 2),
    "secondary_link":("Arterial secundária", 2),
    "tertiary":      ("Coletora", 3),
    "tertiary_link": ("Coletora", 3),
    "residential":   ("Local / residencial", 4),
    "living_street": ("Via de convívio", 4),
    "unclassified":  ("Local sem classificação", 5),
    "road":          ("Sem classificação", 5),
    "service":       ("Via de serviço", 6),
    "pedestrian":    ("Calçadão / pedestres", 7),
    "footway":       ("Pedestre / passeio", 8),
    "path":          ("Pedestre / passeio", 8),
    "steps":         ("Escadaria", 8),
    "cycleway":      ("Ciclovia", 9),
    "track":         ("Trilha / rural", 9),
    "construction":  ("Em obras", 10),
}
PADRAO = ("Outro", 11)
SEM_DADOS = ("(classificação indisponível)", 11)

# Ruído óbvio para marcar numa coluna (não é rua de verdade para coleta).
PREFIXOS_RUIDO = ("Acesso", "Condomínio", "Estação", "Terminal", "Residencial",
                  "AC ", "(Futura)", "Marginal")


def carregar_vias_gz() -> dict[str, list]:
    """{nome do OSM: trechos} do _vias_curitiba.json.gz (a geometria já baixada)."""
    if not VIAS_CURITIBA.exists():
        sys.exit(f"Não encontrei {VIAS_CURITIBA}. Rode uma coleta primeiro para baixá-lo, "
                 "ou gere-o com o pipeline de coleta.")
    return json.loads(gzip.decompress(VIAS_CURITIBA.read_bytes()))["vias"]


def baixar_classificacao() -> dict[str, Counter]:
    """{chave da rua: Counter de highway} do Overpass (só tags). {} se indisponível."""
    print("Consultando a classificação das vias no Overpass (só tags, ~segundos)...", flush=True)
    falhas = []
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": QUERY_TAGS},
                                 headers={"User-Agent": "calcadas-curitiba/0.1"}, timeout=200)
            resp.raise_for_status()
            elementos = resp.json().get("elements", [])
        except (requests.exceptions.RequestException, ValueError) as exc:
            falhas.append(f"{url}: {exc}")
            continue
        if len(elementos) > 1000:  # menos que isso: resposta truncada no meio
            por_chave: dict[str, Counter] = defaultdict(Counter)
            for w in elementos:
                tags = w.get("tags", {})
                nome, hw = tags.get("name"), tags.get("highway")
                if nome and hw:
                    por_chave[_chave(nome)][hw] += 1
            return por_chave
        falhas.append(f"{url}: resposta incompleta ({len(elementos)} vias)")
    print("AVISO: nenhum servidor Overpass respondeu; o CSV sai sem classificação.\n  "
          + "\n  ".join(falhas), file=sys.stderr)
    return {}


def comprimento_m(trecho: list) -> float:
    """Comprimento de um trecho (lista de [lat, lon]) em metros, via UTM."""
    pts = [ll_para_utm(lat, lon) for lat, lon in trecho]
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def agrupar(vias: dict[str, list], classificacao: dict[str, Counter]) -> list[dict]:
    """Junta geometria (do .gz) e classificação (do Overpass) por rua."""
    grafias: dict[str, list[str]] = defaultdict(list)
    n_trechos: dict[str, int] = defaultdict(int)
    comprimento: dict[str, float] = defaultdict(float)

    for nome, trechos in vias.items():
        chave = _chave(nome)
        grafias[chave].append(nome)
        n_trechos[chave] += len(trechos)
        comprimento[chave] += sum(comprimento_m(t) for t in trechos)

    ruas = []
    for chave in grafias:
        nome = _grafia(grafias[chave])
        contagem = classificacao.get(chave)
        if contagem:
            hw = contagem.most_common(1)[0][0]
            categoria, prioridade = CATEGORIAS.get(hw, PADRAO)
        else:
            hw = "?"
            categoria, prioridade = SEM_DADOS
        ruas.append({
            "nome": nome,
            "tipo": nome.split()[0] if nome.split() else "",
            "classificacao_osm": hw,
            "categoria": categoria,
            "n_trechos": n_trechos[chave],
            "comprimento_m": round(comprimento[chave]),
            "provavel_ruido": "sim" if nome.startswith(PREFIXOS_RUIDO) else "",
            "_prioridade": prioridade,
        })
    # Arteriais primeiro; dentro de cada categoria, as mais longas no topo.
    ruas.sort(key=lambda r: (r["_prioridade"], -r["comprimento_m"], r["nome"]))
    return ruas


def escrever_csv(ruas: list[dict], saida) -> None:
    campos = ["nome", "tipo", "classificacao_osm", "categoria",
              "n_trechos", "comprimento_m", "provavel_ruido"]
    with open(saida, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(ruas)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Gera o catálogo classificado das vias de Curitiba.")
    parser.add_argument("--saida", default=str(CACHE_RUAS / "ruas_curitiba_classificadas.csv"),
                        help="caminho do CSV (padrão: data/raw/ruas_osm/ruas_curitiba_classificadas.csv)")
    parser.add_argument("--offline", action="store_true",
                        help="não consulta o Overpass; gera o CSV sem a coluna de classificação")
    args = parser.parse_args(argv)

    vias = carregar_vias_gz()
    classificacao = {} if args.offline else baixar_classificacao()
    ruas = agrupar(vias, classificacao)
    escrever_csv(ruas, args.saida)

    por_cat = Counter(r["categoria"] for r in ruas)
    print(f"\n{len(ruas)} ruas -> {args.saida}\n")
    for categoria, n in sorted(por_cat.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {categoria}")


if __name__ == "__main__":
    main()
