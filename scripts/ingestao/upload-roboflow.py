import argparse
import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from scripts.ingestao.coleta_streetview.banco import abrir_db, exportar_ruas, pasta_da_rua
from scripts.ingestao.coleta_streetview.config import PASTA_RUAS

load_dotenv()

ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "")
WORKSPACE_NAME = os.getenv("ROBOFLOW_WORKSPACE_NAME", "")
PROJECT_NAME = os.getenv("ROBOFLOW_PROJECT_NAME", "")
MAX_WORKERS = 5


def parse_nome_quadrado(nome_arquivo: str) -> tuple[int, int, int]:
    """Extrai (zona, tentativa, quadrado) de '<zona>_<tentativa>_<quadrado>.jpg'."""
    partes = Path(nome_arquivo).stem.split("_")
    return int(partes[0]), int(partes[1]), int(partes[2])


def listar_itens_para_upload(conn, filtro_rua: str | None = None, forcar: bool = False) -> list[dict]:
    """
    Sincroniza `data/processed/downloads-ruas/` (incluindo `closes/` e `contexto/`
    das vistas aprovadas) e retorna a lista de quadrados pendentes de envio ao Roboflow.
    """
    exportar_ruas(conn)

    if not PASTA_RUAS.exists():
        return []

    ja_enviados = set()
    if not forcar:
        ja_enviados = {
            row[0] for row in conn.execute("SELECT arquivo FROM uploads_roboflow").fetchall()
        }

    slug_alvo = None
    if filtro_rua:
        slug_alvo = pasta_da_rua(filtro_rua).name

    itens = []
    vistos_nesta_execucao = set()

    for pasta_rua in sorted(p for p in PASTA_RUAS.iterdir() if p.is_dir()):
        rua_slug = pasta_rua.name
        if slug_alvo and rua_slug != slug_alvo:
            continue

        indice_path = pasta_rua / "indice.csv"
        if not indice_path.exists():
            continue

        with open(indice_path, "r", encoding="utf-8") as f:
            leitor = csv.DictReader(f)
            for linha in leitor:
                nome_arq = linha["arquivo"]
                caminho_img = pasta_rua / nome_arq
                if not caminho_img.exists():
                    continue
                if nome_arq in ja_enviados or nome_arq in vistos_nesta_execucao:
                    continue

                zona, tentativa, quadrado = parse_nome_quadrado(nome_arq)
                captura = (linha.get("captura") or "").strip()
                tags = [rua_slug]
                if captura:
                    tags.append(f"ano_{captura[:4]}")

                itens.append({
                    "arquivo": nome_arq,
                    "caminho": caminho_img,
                    "zona": zona,
                    "tentativa": tentativa,
                    "quadrado": quadrado,
                    "rua_slug": rua_slug,
                    "batch_name": f"calcadas_{rua_slug}",
                    "tags": tags,
                })
                vistos_nesta_execucao.add(nome_arq)

    return itens


def upload_imagem(item: dict, project) -> tuple[bool, dict, str]:
    """Envia um quadrado individual para o lote não anotado (Unannotated) do Roboflow."""
    try:
        project.upload(
            str(item["caminho"]),
            num_retry_uploads=3,
            batch_name=item["batch_name"],
            tag_names=item["tags"],
        )
        return True, item, f"{item['rua_slug']}/{item['arquivo']} (batch={item['batch_name']})"
    except Exception as e:
        return False, item, f"{item['rua_slug']}/{item['arquivo']} -> Erro: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="Sincroniza artefatos de contexto/close em downloads-ruas e envia quadrados aprovados ao Roboflow."
    )
    parser.add_argument("--rua", help="Enviar apenas uma rua específica (ex: 'Avenida Silva Jardim')")
    parser.add_argument("--dry-run", action="store_true", help="Apenas sincroniza pastas e lista o que seria enviado")
    parser.add_argument("--forcar", action="store_true", help="Reenvia imagens mesmo que já constem como enviadas no banco")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"Uploads simultâneos (default: {MAX_WORKERS})")
    args = parser.parse_args()

    conn = abrir_db()
    itens = listar_itens_para_upload(conn, filtro_rua=args.rua, forcar=args.forcar)

    total_enviados_antes = conn.execute("SELECT COUNT(*) FROM uploads_roboflow").fetchone()[0]
    print(f"Pasta de ruas sincronizada: {PASTA_RUAS.relative_to(RAIZ)}")
    print(f"Imagens já registradas como enviadas no banco: {total_enviados_antes}")
    print(f"Imagens novas encontradas para envio:          {len(itens)}")

    if not itens:
        print("Nenhuma imagem pendente de envio!")
        return

    if args.dry_run:
        print("\n[MODO DRY-RUN] Nenhuma imagem será enviada à API do Roboflow.")
        print("=" * 70)
        for i, item in enumerate(itens, 1):
            print(f"  [{i}/{len(itens)}] {item['caminho'].relative_to(RAIZ)} -> "
                  f"batch='{item['batch_name']}', tags={item['tags']}")
        print("=" * 70)
        return

    if ROBOFLOW_API_KEY == "SUA_PRIVATE_API_KEY_AQUI" or not ROBOFLOW_API_KEY.strip():
        print("[ERRO] Configure ROBOFLOW_API_KEY, ROBOFLOW_WORKSPACE_NAME e ROBOFLOW_PROJECT_NAME no .env!")
        return

    from roboflow import Roboflow

    print(f"\nConectando ao Roboflow (Workspace: {WORKSPACE_NAME}, Projeto: {PROJECT_NAME})...")
    rf = Roboflow(api_key=ROBOFLOW_API_KEY)
    try:
        workspace = rf.workspace(WORKSPACE_NAME)
        project = workspace.project(PROJECT_NAME)
    except Exception as e:
        print(f"[ERRO] Não foi possível encontrar o workspace/projeto: {e}")
        return

    total = len(itens)
    print(f"Iniciando o envio de {total} quadrados para o Roboflow...")
    print("=" * 70)

    sucessos = 0
    falhas = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(upload_imagem, item, project) for item in itens]

        for future in as_completed(futures):
            sucesso, item, msg = future.result()
            if sucesso:
                sucessos += 1
                agora = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT OR REPLACE INTO uploads_roboflow
                        (arquivo, ponto_id, tentativa, quadrado, rua_slug, batch_name, enviado_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["arquivo"],
                        item["zona"],
                        item["tentativa"],
                        item["quadrado"],
                        item["rua_slug"],
                        item["batch_name"],
                        agora,
                    ),
                )
                conn.commit()
                print(f"[{sucessos + falhas}/{total}] Upload OK: {msg}")
            else:
                falhas += 1
                print(f"[{sucessos + falhas}/{total}] FALHA: {msg}")

    print("=" * 70)
    print("PROCESSO CONCLUÍDO!")
    print(f"Imagens enviadas com sucesso: {sucessos}")
    print(f"Falhas:                       {falhas}")
    print("=" * 70)


if __name__ == "__main__":
    main()