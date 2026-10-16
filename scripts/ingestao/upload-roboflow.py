import os
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from roboflow import Roboflow
from dotenv import load_dotenv

load_dotenv()

ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "")

WORKSPACE_NAME = os.getenv("ROBOFLOW_WORKSPACE_NAME", "")
PROJECT_NAME = os.getenv("ROBOFLOW_PROJECT_NAME", "")

PASTA_IMAGENS = os.getenv("PASTA_IMAGENS", "dataset_calcadas_cic")
MAX_WORKERS = 5  # Quantidade de uploads simultâneos (para não estourar o limite da API)


def upload_imagem(caminho_imagem, project):
    """Envia uma imagem individual para o lote não anotado (Unannotated) do Roboflow."""
    try:
        project.upload(caminho_imagem, num_retry_uploads=3)
        return True, os.path.basename(caminho_imagem)
    except Exception as e:
        return False, f"{os.path.basename(caminho_imagem)} -> Erro: {e}"


def main():
    if ROBOFLOW_API_KEY == "SUA_PRIVATE_API_KEY_AQUI" or not ROBOFLOW_API_KEY.strip():
        print("[ERRO] Substitua a variável ROBOFLOW_API_KEY pela sua chave real do Roboflow!")
        return

    print("Conectando ao Roboflow...")
    rf = Roboflow(api_key=ROBOFLOW_API_KEY)
    
    try:
        workspace = rf.workspace(WORKSPACE_NAME)
        project = workspace.project(PROJECT_NAME)
    except Exception as e:
        print(f"[ERRO] Não foi possível encontrar o workspace/projeto: {e}")
        return

    # Mapeia todas as imagens da pasta
    extensoes = ("*.jpg", "*.jpeg", "*.png", "*.JPG")
    imagens = []
    for ext in extensoes:
        imagens.extend(glob.glob(os.path.join(PASTA_IMAGENS, ext)))

    total = len(imagens)
    print(f"Total de imagens locais encontradas: {total}")
    if total == 0:
        print("Nenhuma imagem encontrada no diretório informado!")
        return

    print(f"Iniciando o envio de {total} imagens para o Roboflow...")
    print("=" * 65)

    sucessos = 0
    falhas = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(upload_imagem, img, project) for img in imagens
        ]

        for future in as_completed(futures):
            sucesso, msg = future.result()
            if sucesso:
                sucessos += 1
                print(f"[{sucessos + falhas}/{total}] Upload OK: {msg}")
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