import argparse
import csv
import os
import shutil
import sys
import tempfile
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


def listar_ruas_disponiveis(conn) -> list[dict]:
    """Lista as pastas em downloads-ruas/ com a contagem de imagens locais e já enviadas."""
    if not PASTA_RUAS.exists():
        return []

    ja_enviados_por_rua: dict[str, set[str]] = {}
    for r_slug, arq in conn.execute("SELECT rua_slug, arquivo FROM uploads_roboflow").fetchall():
        ja_enviados_por_rua.setdefault(r_slug, set()).add(arq)

    ruas = []
    for pasta_rua in sorted(p for p in PASTA_RUAS.iterdir() if p.is_dir()):
        indice_path = pasta_rua / "indice.csv"
        if not indice_path.exists():
            continue

        rua_slug = pasta_rua.name
        enviados_desta_rua = ja_enviados_por_rua.get(rua_slug, set())

        total_local = 0
        enviadas = 0
        with open(indice_path, "r", encoding="utf-8") as f:
            for linha in csv.DictReader(f):
                arq = linha["arquivo"]
                if (pasta_rua / arq).exists():
                    total_local += 1
                    if arq in enviados_desta_rua:
                        enviadas += 1

        ruas.append({
            "slug": rua_slug,
            "pasta": pasta_rua,
            "total": total_local,
            "enviadas": enviadas,
            "pendentes": total_local - enviadas,
        })
    return ruas


def selecionar_amostras_espacadas(itens: list[dict], limite: int | None) -> list[dict]:
    """Seleciona amostras uniformemente distribuídas entre as zonas da rua."""
    if not limite or limite >= len(itens):
        return itens

    # Agrupa por zona geográfica
    por_zona: dict[int, list[dict]] = {}
    for item in itens:
        por_zona.setdefault(item["zona"], []).append(item)

    # Prioriza o quadrado central (2) antes das laterais (1 e 3)
    ordem_preferida = {2: 0, 1: 1, 3: 2}
    for z in por_zona:
        por_zona[z].sort(key=lambda x: ordem_preferida.get(x["quadrado"], x["quadrado"]))

    zonas = list(por_zona.keys())
    escolhidos = []
    escolhidos_set = set()

    rodada = 0
    while len(escolhidos) < limite:
        candidatos_rodada = [z for z in zonas if len(por_zona[z]) > rodada]
        if not candidatos_rodada:
            break

        faltam = limite - len(escolhidos)
        if faltam >= len(candidatos_rodada):
            selecionados_rodada = candidatos_rodada
        else:
            passo = len(candidatos_rodada) / faltam
            selecionados_rodada = [candidatos_rodada[int(i * passo)] for i in range(faltam)]

        for z in selecionados_rodada:
            item = por_zona[z][rodada]
            if item["arquivo"] not in escolhidos_set:
                escolhidos.append(item)
                escolhidos_set.add(item["arquivo"])

        rodada += 1

    escolhidos.sort(key=lambda x: (x["zona"], x["quadrado"]))
    return escolhidos


def listar_itens_da_rua(pasta_rua: Path, conn, forcar: bool = False) -> list[dict]:
    """Retorna os quadrados pendentes de envio de uma rua."""
    rua_slug = pasta_rua.name
    ja_enviados = set()
    if not forcar:
        ja_enviados = {
            row[0]
            for row in conn.execute(
                "SELECT arquivo FROM uploads_roboflow WHERE rua_slug = ?", (rua_slug,)
            ).fetchall()
        }

    indice_path = pasta_rua / "indice.csv"
    if not indice_path.exists():
        return []

    itens = []
    with open(indice_path, "r", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            nome_arq = linha["arquivo"]
            caminho_img = pasta_rua / nome_arq
            if not caminho_img.exists() or (nome_arq in ja_enviados):
                continue

            zona, tentativa, quadrado = parse_nome_quadrado(nome_arq)
            captura = (linha.get("captura") or "").strip()
            arquivo_remoto = f"{rua_slug}__{nome_arq}"
            tags = [rua_slug]
            if captura:
                tags.append(f"ano_{captura[:4]}")

            itens.append({
                "arquivo": nome_arq,
                "arquivo_remoto": arquivo_remoto,
                "caminho": caminho_img,
                "zona": zona,
                "tentativa": tentativa,
                "quadrado": quadrado,
                "rua_slug": rua_slug,
                "batch_name": f"calcadas_{rua_slug}",
                "tags": tags,
            })
    return itens


def upload_imagem(item: dict, project) -> tuple[bool, dict, str]:
    """Envia um quadrado individual para o Roboflow com o prefixo da rua."""
    nome_remoto = item["arquivo_remoto"]
    caminho_orig = Path(item["caminho"])

    # Cria cópia temporária com o nome remoto para registrar o prefixo no Roboflow
    temp_dir = Path(tempfile.gettempdir()) / "roboflow_upload_staging"
    temp_dir.mkdir(parents=True, exist_ok=True)
    caminho_staging = temp_dir / nome_remoto

    try:
        shutil.copyfile(caminho_orig, caminho_staging)
        project.upload(
            str(caminho_staging),
            num_retry_uploads=3,
            batch_name=item["batch_name"],
            tag_names=item["tags"],
        )
        return True, item, f"{nome_remoto} (batch={item['batch_name']})"
    except Exception as e:
        return False, item, f"{nome_remoto} -> Erro: {e}"
    finally:
        try:
            if caminho_staging.exists():
                caminho_staging.unlink()
        except Exception:
            pass


def _perguntar(texto: str) -> str:
    try:
        return input(texto).strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nOperação cancelada.")


def main():
    parser = argparse.ArgumentParser(
        description="Envia quadrados de calçadas para o Roboflow com amostragem uniforme."
    )
    parser.add_argument("--rua", help="Nome ou slug da rua (ex: 'Avenida Sete de Setembro' ou 'avenida-sete-de-setembro')")
    parser.add_argument("--limite", type=int, help="Quantidade máxima de imagens para enviar")
    parser.add_argument("--dry-run", action="store_true", help="Simula a amostragem sem enviar para a API")
    parser.add_argument("--forcar", action="store_true", help="Reenvia imagens já registradas no banco")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help=f"Uploads simultâneos (default: {MAX_WORKERS})")
    args = parser.parse_args()

    conn = abrir_db()
    exportar_ruas(conn)

    ruas_disponiveis = listar_ruas_disponiveis(conn)
    if not ruas_disponiveis:
        print(f"[AVISO] Nenhuma pasta de rua encontrada em {PASTA_RUAS.relative_to(RAIZ)}!")
        return

    # 1. Seleção da rua
    rua_escolhida = None
    if args.rua:
        slug_busca = pasta_da_rua(args.rua).name
        rua_escolhida = next((r for r in ruas_disponiveis if r["slug"] == slug_busca or args.rua.lower() in r["slug"]), None)
        if not rua_escolhida:
            print(f"[ERRO] Rua '{args.rua}' não encontrada em {PASTA_RUAS.relative_to(RAIZ)}!")
            print("Ruas disponíveis:", [r["slug"] for r in ruas_disponiveis])
            return
    else:
        print("Qual rua deseja enviar para o Roboflow?")
        for i, r in enumerate(ruas_disponiveis, 1):
            print(f"  {i}) {r['slug']} ({r['pendentes']} disponíveis para envio, {r['enviadas']} já enviadas)")

        while True:
            resp = _perguntar(f"Escolha [1-{len(ruas_disponiveis)}, Enter = todas]: ")
            if not resp:
                break
            if resp.isdigit() and 1 <= int(resp) <= len(ruas_disponiveis):
                rua_escolhida = ruas_disponiveis[int(resp) - 1]
                break
            print(f"Digite um número de 1 a {len(ruas_disponiveis)} ou pressione Enter para todas.")

    ruas_alvo = [rua_escolhida] if rua_escolhida else ruas_disponiveis

    # 2. Coleta e amostragem de itens
    itens_finais = []
    for r in ruas_alvo:
        itens_rua = listar_itens_da_rua(r["pasta"], conn, forcar=args.forcar)
        if not itens_rua:
            continue

        limite_rua = args.limite
        if limite_rua is None and len(ruas_alvo) == 1 and not args.dry_run:
            while True:
                resp = _perguntar(f"Quantas imagens enviar de '{r['slug']}'? [1-{len(itens_rua)}, Enter = todas]: ")
                if not resp:
                    limite_rua = len(itens_rua)
                    break
                if resp.isdigit() and 1 <= int(resp) <= len(itens_rua):
                    limite_rua = int(resp)
                    break
                print(f"Digite um número entre 1 e {len(itens_rua)}.")

        amostra = selecionar_amostras_espacadas(itens_rua, limite_rua)
        zonas_unicas = len({it["zona"] for it in amostra})
        print(f"\n[{r['slug']}] Selecionadas {len(amostra)} imagens de {zonas_unicas} zonas distintas "
              f"(de um total de {len(itens_rua)} imagens disponíveis).")
        itens_finais.extend(amostra)

    if not itens_finais:
        print("\nNenhuma imagem selecionada para envio!")
        return

    print("=" * 70)
    print(f"TOTAL DE IMAGENS SELECIONADAS PARA ENVIO: {len(itens_finais)}")
    print("=" * 70)

    # 3. Dry-run
    if args.dry_run:
        print("\n[MODO DRY-RUN] Nenhuma imagem será enviada à API do Roboflow.")
        print("Amostra selecionada uniformemente ao longo da rua:")
        print("=" * 70)
        for i, item in enumerate(itens_finais, 1):
            print(f"  [{i}/{len(itens_finais)}] {item['caminho'].relative_to(RAIZ)} -> "
                  f"remoto='{item['arquivo_remoto']}', zona={item['zona']}, quadrado={item['quadrado']}, batch='{item['batch_name']}'")
        print("=" * 70)
        return

    # 4. Envio ao Roboflow
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

    total = len(itens_finais)
    print(f"Iniciando o envio de {total} quadrados selecionados para o Roboflow...")
    print("=" * 70)

    sucessos = 0
    falhas = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(upload_imagem, item, project) for item in itens_finais]

        for future in as_completed(futures):
            sucesso, item, msg = future.result()
            if sucesso:
                sucessos += 1
                agora = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    INSERT OR REPLACE INTO uploads_roboflow
                        (rua_slug, arquivo, arquivo_remoto, ponto_id, tentativa, quadrado, batch_name, enviado_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["rua_slug"],
                        item["arquivo"],
                        item["arquivo_remoto"],
                        item["zona"],
                        item["tentativa"],
                        item["quadrado"],
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
