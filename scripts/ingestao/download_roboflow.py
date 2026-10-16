import os
from roboflow import Roboflow
from dotenv import load_dotenv

def main():
    # Carrega variáveis do arquivo .env
    load_dotenv()
    
    API_KEY = os.getenv("ROBOFLOW_API_KEY")
    WORKSPACE = os.getenv("ROBOFLOW_WORKSPACE_NAME")
    PROJECT = os.getenv("ROBOFLOW_PROJECT_NAME")
    VERSION = int(os.getenv("ROBOFLOW_VERSION", "1"))
    FORMATO = os.getenv("ROBOFLOW_FORMAT", "coco")
    
    if not API_KEY or not WORKSPACE or not PROJECT:
        print("[ERRO] Verifique se as chaves ROBOFLOW_API_KEY, ROBOFLOW_WORKSPACE_NAME e ROBOFLOW_PROJECT_NAME estão no .env")
        return
        
    print(f"Conectando ao Roboflow (Workspace: {WORKSPACE}, Projeto: {PROJECT}, Versão: {VERSION})...")
    
    try:
        rf = Roboflow(api_key=API_KEY)
        workspace = rf.workspace(WORKSPACE)
        project = workspace.project(PROJECT)
        
        print(f"Baixando o dataset na versão {VERSION} e formato '{FORMATO}'...")
        
        # Define o caminho de destino dentro da pasta data/raw/
        destino = os.path.join(os.getcwd(), "data", "raw", f"{PROJECT}-v{VERSION}")
        os.makedirs(destino, exist_ok=True)
        
        # Faz o download local na pasta especificada
        dataset = project.version(VERSION).download(FORMATO, location=destino, overwrite=True)
        
        print("="*60)
        print("✅ DATASET BAIXADO COM SUCESSO!")
        print(f"📁 Local: {dataset.location}")
        print("="*60)
        
    except Exception as e:
        print(f"\n[ERRO] Falha ao baixar o dataset: {e}")
        print("Verifique se a versão especificada já foi gerada lá no painel do Roboflow!")

if __name__ == "__main__":
    main()
