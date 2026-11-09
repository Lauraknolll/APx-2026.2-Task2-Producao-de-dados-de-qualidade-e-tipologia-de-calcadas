"""
Publica o resultado da coleta no Supabase — a "vitrine" compartilhada do grupo.

O estado de trabalho continua no SQLite local (data/processed/streetview.db); este
comando só lê de lá o que já é resultado (zonas aprovadas, a vista escolhida de
cada uma e seus quadrados limpos) e o envia para o Supabase: metadados nas tabelas
e os JPGs no Storage. Nada de `tentativas`, `rotulos` ou `parametros` — isso é
estado local, não interessa ao grupo.

É idempotente: roda de novo sem duplicar nada. Todo upsert usa a chave natural de
cada tabela (streets.slug, sidewalk_zones.external_id, images.storage_path), e o
upload pula arquivos que já existem no bucket (use --force para reenviar).

    python -m scripts.sync.supabase_sync            # tudo
    python -m scripts.sync.supabase_sync --rua "Rua Comendador Araújo"
    python -m scripts.sync.supabase_sync --dry-run  # só mostra o que faria

Precisa de SUPABASE_URL e SUPABASE_SERVICE_KEY no ambiente (ou no .env). A
service_role key ignora o RLS, então é o pipeline que escreve; os integrantes só
leem. Rode sempre a partir da raiz do repositório.
"""

import argparse
import json
import os
import subprocess
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from scripts.ingestao.coleta_streetview.config import DB_PATH, OBSTRUCAO_NA_FRENTE, PASTA_IMAGENS

BUCKET = "sidewalks"
LOTE = 500  # linhas por upsert


# --------------------------------------------------------------------------- #
# Auxiliares
# --------------------------------------------------------------------------- #

def slug_rua(rua: str) -> str:
    """Mesmo slug que banco.pasta_da_rua usa para nomear a pasta da rua."""
    sem_acento = unicodedata.normalize("NFKD", rua).encode("ascii", "ignore").decode()
    return "-".join("".join(c if c.isalnum() else " " for c in sem_acento.lower()).split())


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def cliente():
    """Cria o cliente Supabase a partir das variáveis de ambiente."""
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("Defina SUPABASE_URL e SUPABASE_SERVICE_KEY (no ambiente ou no .env).")
    try:
        from supabase import create_client
    except ImportError:
        sys.exit("Falta a dependência: pip install supabase (já está no requirements.txt).")
    return create_client(url, key)


def upsert_lotes(tabela, linhas: list[dict], on_conflict: str) -> list[dict]:
    """Upsert em lotes; devolve todas as linhas gravadas (com o id)."""
    gravadas = []
    for i in range(0, len(linhas), LOTE):
        res = tabela.upsert(linhas[i:i + LOTE], on_conflict=on_conflict).execute()
        gravadas.extend(res.data or [])
    return gravadas


# --------------------------------------------------------------------------- #
# Leitura do SQLite: só o resultado (zonas aprovadas e seus quadrados limpos)
# --------------------------------------------------------------------------- #

def ler_resultado(conn: sqlite3.Connection, rua_filtro: str | None):
    """
    Devolve (zonas, zona_rua), onde:
      zonas    = lista de dicts, uma por zona aprovada, com a vista escolhida,
                 suas medidas e a lista de quadrados limpos;
      zona_rua = lista de (external_id, nome_da_rua) — uma zona de esquina
                 aparece em mais de uma rua (tabela pontos_rua).
    """
    conn.row_factory = sqlite3.Row
    filtro, params = "", []
    if rua_filtro:
        filtro = " AND p.id IN (SELECT ponto_id FROM pontos_rua WHERE rua = ?)"
        params.append(rua_filtro)

    zonas = []
    for r in conn.execute(f"""
        SELECT p.id, p.fid, p.anel, p.ordem, p.status, p.tentativa, p.quadrados AS limpos,
               p.lat, p.lon, p.endereco,
               t.data, t.pano_id, t.alvo_lat, t.alvo_lon,
               t.frac_calcada, t.obstrucao, t.quadrados AS medidas
        FROM pontos p
        JOIN tentativas t ON t.ponto_id = p.id AND t.posicao = p.tentativa
        WHERE p.status = 'aprovada' AND p.quadrados IS NOT NULL {filtro}
        ORDER BY p.id
    """, params):
        zonas.append({
            "external_id": f"{r['fid']}_{r['anel']}_{r['ordem']}",
            "pid": r["id"], "tentativa": r["tentativa"],
            "status": r["status"], "lat": r["lat"], "lon": r["lon"],
            "alvo_lat": r["alvo_lat"], "alvo_lon": r["alvo_lon"],
            "pano_id": r["pano_id"], "data": r["data"],
            "frac_calcada": r["frac_calcada"],
            "obstrucao": json.loads(r["obstrucao"]) if r["obstrucao"] else {},
            "limpos": [int(k) for k in r["limpos"].split(",")] if r["limpos"] else [],
            "medidas": json.loads(r["medidas"]) if r["medidas"] else [],
        })

    aprovadas = {z["pid"] for z in zonas}
    zona_rua = [(f"{fid}_{anel}_{ordem}", rua)
                for ponto_id, rua, fid, anel, ordem in conn.execute("""
                    SELECT pr.ponto_id, pr.rua, p.fid, p.anel, p.ordem
                    FROM pontos_rua pr JOIN pontos p ON p.id = pr.ponto_id""")
                if ponto_id in aprovadas]
    return zonas, zona_rua


def obstrucao_na_frente(medidas: dict) -> float:
    """Soma das obstruções que ficam entre a câmera e o piso (como no indice.csv)."""
    return round(sum(medidas.get(t, 0.0) for t in OBSTRUCAO_NA_FRENTE), 3)


def imagens_da_zona(z: dict) -> list[dict]:
    """
    As imagens a publicar de uma zona: o close, a vista de contexto e cada
    quadrado limpo. Cada dict traz o arquivo local, o caminho no Storage e os
    metadados. Os caminhos no Storage são por zona (não por rua), então uma
    zona de esquina não duplica arquivo.
    """
    pid, tent = z["pid"], z["tentativa"]
    base = f"{pid}_{tent}"
    itens = [
        {"arquivo": PASTA_IMAGENS / f"{base}.jpg",
         "storage_path": f"closes/{base}.jpg", "image_type": "close",
         "square_number": None,
         "sidewalk_fraction": z["frac_calcada"],
         "obstruction_fraction": obstrucao_na_frente(z["obstrucao"]),
         "latitude": z["alvo_lat"], "longitude": z["alvo_lon"]},
        {"arquivo": PASTA_IMAGENS / "contexto" / f"{base}.jpg",
         "storage_path": f"contexto/{base}.jpg", "image_type": "context",
         "square_number": None, "sidewalk_fraction": None, "obstruction_fraction": None,
         "latitude": z["alvo_lat"], "longitude": z["alvo_lon"]},
    ]
    for k in z["limpos"]:
        m = z["medidas"][k - 1] if k <= len(z["medidas"]) else {"piso": None, "obstrucao": {}}
        itens.append({
            "arquivo": PASTA_IMAGENS / "quadrados" / f"{base}_{k}.jpg",
            "storage_path": f"quadrados/{base}_{k}.jpg", "image_type": "square",
            "square_number": k,
            "sidewalk_fraction": m.get("piso"),
            "obstruction_fraction": obstrucao_na_frente(m.get("obstrucao", {})),
            "latitude": z["alvo_lat"], "longitude": z["alvo_lon"]})
    return itens


# --------------------------------------------------------------------------- #
# Upload para o Storage
# --------------------------------------------------------------------------- #

def enviar_arquivo(sb, arquivo: Path, storage_path: str, force: bool) -> str:
    """Envia um JPG ao bucket. Retorna 'ok', 'pulado' (já existe) ou 'faltando'."""
    if not arquivo.exists():
        return "faltando"
    dados = arquivo.read_bytes()
    opcoes = {"content-type": "image/jpeg", "upsert": "true" if force else "false"}
    try:
        sb.storage.from_(BUCKET).upload(storage_path, dados, opcoes)
        return "ok"
    except Exception as exc:
        msg = str(exc)
        if not force and ("Duplicate" in msg or "already exists" in msg or "409" in msg):
            return "pulado"
        raise


# --------------------------------------------------------------------------- #
# Sincronização
# --------------------------------------------------------------------------- #

def sincronizar(args):
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    zonas, zona_rua = ler_resultado(conn, args.rua)
    if not zonas:
        print("Nenhuma zona aprovada para sincronizar"
              + (f' na rua "{args.rua}"' if args.rua else "") + ".")
        return

    ruas = sorted({rua for _, rua in zona_rua})
    total_imgs = sum(len(imagens_da_zona(z)) for z in zonas)
    print(f"{len(zonas)} zonas, {len(ruas)} ruas, ~{total_imgs} imagens a publicar.")
    if args.dry_run:
        for rua in ruas:
            print(f"  - {rua}  ->  slug: {slug_rua(rua)}")
        print("(--dry-run: nada foi enviado.)")
        return

    sb = cliente()

    # 1. Execução (proveniência: quem/quando gerou este envio).
    run = sb.table("pipeline_runs").insert({
        "command": "sync", "status": "running", "git_commit": git_commit(),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).execute().data[0]
    run_id = run["id"]

    try:
        # 2. Ruas -> id por slug.
        linhas_ruas = [{"name": rua, "slug": slug_rua(rua)} for rua in ruas]
        por_slug = {r["slug"]: r["id"]
                    for r in upsert_lotes(sb.table("streets"), linhas_ruas, "slug")}

        # 3. Zonas -> id por external_id.
        linhas_zonas = [{"external_id": z["external_id"], "status": z["status"],
                         "latitude": z["lat"], "longitude": z["lon"]} for z in zonas]
        por_ext = {z["external_id"]: z["id"]
                   for z in upsert_lotes(sb.table("sidewalk_zones"), linhas_zonas, "external_id")}

        # 4. Junção zona<->rua (esquina pertence a mais de uma).
        vinculos = [{"zone_id": por_ext[ext], "street_id": por_slug[slug_rua(rua)]}
                    for ext, rua in zona_rua if ext in por_ext]
        upsert_lotes(sb.table("zone_streets"), vinculos, "zone_id,street_id")

        # 5. Upload dos arquivos + linhas de images.
        linhas_imgs, cont = [], {"ok": 0, "pulado": 0, "faltando": 0}
        for n, z in enumerate(zonas, 1):
            zone_id = por_ext[z["external_id"]]
            for img in imagens_da_zona(z):
                status = enviar_arquivo(sb, img["arquivo"], img["storage_path"], args.force)
                cont[status] += 1
                if status == "faltando":
                    print(f"  ! arquivo ausente: {img['arquivo'].relative_to(PASTA_IMAGENS.parent)}")
                    continue
                linhas_imgs.append({
                    "zone_id": zone_id, "run_id": run_id,
                    "storage_path": img["storage_path"],
                    "file_name": img["arquivo"].name,
                    "image_type": img["image_type"], "tentativa": z["tentativa"],
                    "square_number": img["square_number"],
                    "latitude": img["latitude"], "longitude": img["longitude"],
                    "panorama_id": z["pano_id"], "panorama_date": z["data"],
                    "sidewalk_fraction": img["sidewalk_fraction"],
                    "obstruction_fraction": img["obstruction_fraction"],
                })
            if n % 25 == 0 or n == len(zonas):
                print(f"  [{n}/{len(zonas)} zonas] enviados={cont['ok']} "
                      f"pulados={cont['pulado']} faltando={cont['faltando']}")

        upsert_lotes(sb.table("images"), linhas_imgs, "storage_path")

        sb.table("pipeline_runs").update({
            "status": "done", "finished_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", run_id).execute()
        print(f"Pronto: {len(linhas_imgs)} imagens no banco; "
              f"storage ok={cont['ok']} pulados={cont['pulado']} faltando={cont['faltando']}.")
    except Exception as exc:
        sb.table("pipeline_runs").update({
            "status": "error", "finished_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", run_id).execute()
        raise


def criar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.sync.supabase_sync", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rua", help="nome OSM exato de uma rua (como em pontos_rua); sem isso, todas")
    p.add_argument("--db", type=Path, default=DB_PATH, help=f"banco local (default: {DB_PATH})")
    p.add_argument("--force", action="store_true", help="reenvia arquivos que já existem no Storage")
    p.add_argument("--dry-run", action="store_true", help="só mostra o que faria, sem enviar nada")
    return p


def main(argv=None):
    sincronizar(criar_parser().parse_args(argv))


if __name__ == "__main__":
    main()
