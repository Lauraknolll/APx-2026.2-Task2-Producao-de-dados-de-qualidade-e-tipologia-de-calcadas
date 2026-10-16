import os
import glob
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from roboflow import Roboflow
from dotenv import load_dotenv

load_dotenv()

ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "")
WORKSPACE_NAME = os.getenv("ROBOFLOW_WORKSPACE_NAME", "")
PROJECT_NAME = os.getenv("ROBOFLOW_PROJECT_NAME", "")

PASTA_IMAGENS = os.getenv("PASTA_IMAGENS", "dataset_calcadas_curitiba")
MAX_WORKERS = 5


def anexar_metadados_roboflow(image_id, metadados):
    url_metadata = f"https://api.roboflow.com/{WORKSPACE_NAME}/{PROJECT_NAME}/images/{image_id}/metadata"
    headers = {"Content-Type": "application/json"}
    params = {"api_key": ROBOFLOW_API_KEY}

    # Envia individualmente cada par para que o Roboflow popule a tabela visual
    metadata_payload = {
        "metadata": {
            "latitude": str(metadados.get("lat", "")),
            "longitude": str(metadados.get("lon", "")),
            "pano_id": str(metadados.get("pano_id", "")),
            "heading": str(metadados.get("heading", "")),
            "bairro": str(metadados.get("bairro", "")),
            "nome_rua": str(metadados.get("nome_rua", "")),
            "lado": str(metadados.get("lado", ""))
        }
    }

    resp = requests.post(url_metadata, json=metadata_payload, headers=headers, params=params, timeout=10)
    return resp.status_code == 200


def upload_imagem_com_metadados(caminho_imagem, project):
    """
    Envia a imagem para o Roboflow com Tags de Bairro/Lado e
    anexa o JSON de metadados geográficos.
    """
    nome_base = os.path.basename(caminho_imagem)
    caminho_json = os.path.splitext(caminho_imagem)[0] + ".json"
    
    metadados = {}
    lista_tags = []

    if os.path.exists(caminho_json):
        try:
            with open(caminho_json, "r", encoding="utf-8") as f:
                metadados = json.load(f)
                
            if metadados.get("bairro"):
                bairro_tag = metadados["bairro"].lower().replace(" ", "_")
                lista_tags.append(bairro_tag)
                
            if metadados.get("lado"):
                lista_tags.append(metadados["lado"])
        except Exception as e:
            print(f"[AVISO] Erro ao ler JSON de metadados para {nome_base}: {e}")

    if not lista_tags:
        partes = nome_base.split("_")
        lista_tags = [p for p in partes if p in ("direita", "esquerda")]

    try:
        # 2. Upload da imagem usando tag_names (lista)
        res = project.upload(
            caminho_imagem, 
            tag_names=lista_tags if lista_tags else None, 
            num_retry_uploads=3
        )

        image_id = None
        if isinstance(res, dict):
            image_id = res.get("id") or res.get("image", {}).get("id")
        elif hasattr(res, "id"):
            image_id = res.id

        if image_id and metadados:
            meta_ok = anexar_metadados_roboflow(image_id, metadados)
            if not meta_ok:
                print(f"   [ALERTA] Imagem {nome_base} enviada, mas os metadados falharam.")
        elif not image_id:
            print(f"   [ALERTA] Não foi possível capturar o ID da imagem retornada pelo Roboflow: {res}")

        return True, nome_base

    except Exception as e:
        return False, f"{nome_base} -> Erro: {e}"


def main():
    if not ROBOFLOW_API_KEY.strip() or ROBOFLOW_API_KEY == "SUA_PRIVATE_API_KEY_AQUI":
        print("[ERRO] Defina ROBOFLOW_API_KEY no arquivo .env!")
        return

    print("Conectando ao Roboflow...")
    rf = Roboflow(api_key=ROBOFLOW_API_KEY)
    
    try:
        workspace = rf.workspace(WORKSPACE_NAME)
        project = workspace.project(PROJECT_NAME)
    except Exception as e:
        print(f"[ERRO] Não foi possível encontrar o workspace/projeto: {e}")
        return

    extensoes = ("*.jpg", "*.jpeg", "*.png", "*.JPG")
    imagens = []
    for ext in extensoes:
        imagens.extend(glob.glob(os.path.join(PASTA_IMAGENS, ext)))

    total = len(imagens)
    print(f"Total de imagens locais encontradas: {total}")
    if total == 0:
        print("Nenhuma imagem encontrada na pasta informada!")
        return

    print(f"Iniciando envio de {total} imagens + metadados para o Roboflow...")
    print("=" * 65)

    sucessos = 0
    falhas = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(upload_imagem_com_metadados, img, project) for img in imagens
        ]

        for future in as_completed(futures):
            sucesso, msg = future.result()
            if sucesso:
                sucessos += 1
                print(f"[{sucessos + falhas}/{total}] Upload + Metadados OK: {msg}")
            else:
                falhas += 1
                print(f"[{sucessos + falhas}/{total}] FALHA: {msg}")

    print("=" * 65)
    print("PROCESSO CONCLUÍDO!")
    print(f"Imagens enviadas com sucesso: {sucessos}")
    print(f"Falhas:                       {falhas}")
    print("=" * 65)


if __name__ == "__main__":
    main()