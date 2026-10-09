import os
import math
import requests
from io import BytesIO
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GOOGLE_STREET_VIEW_API_KEY", "")

PASTA_SAIDA = os.getenv("PASTA_IMAGENS", "dataset_calcadas_cic")
TOTAL_IMAGENS_ALVO = int(os.getenv("TOTAL_IMAGENS_ALVO", "100"))
MAX_WORKERS = 10  # Downloads em paralelo

# Coordenadas GPS Reais (Início e Fim) das 9 Ruas em Curitiba
# Formato: (Lat_Inicio, Lon_Inicio), (Lat_Fim, Lon_Fim)
RUAS_CURITIBA = {

# --- CIC / VILA NOSSA SENHORA DA LUZ ---
    "rua_santa_angela_de_foligno": ((-25.5075, -49.3235), (-25.5105, -49.3195)),
    "rua_desembargador_cid_campelo": ((-25.5020, -49.3320), (-25.5220, -49.3140)),
    "rua_pedro_gusso": ((-25.4950, -49.3080), (-25.5130, -49.3280)),
}

# Parâmetros de enquadramento
PITCH = -10
FOV = 80
LARGURA_API = 512
ALTURA_API = 512
SCALE = 2



def calcular_bearing(lat1, lon1, lat2, lon2):
    """Calcula a direção da rua em graus."""
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2_rad - lon1_rad
    x = math.sin(dlon) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    initial_bearing = math.atan2(x, y)
    return (math.degrees(initial_bearing) + 360) % 360


def gerar_pontos_interpolados(ponto_inicial, ponto_final, quantidade_pontos):
    """Gera coordenadas distribuídas ao longo de toda a extensão da rua."""
    lat1, lon1 = ponto_inicial
    lat2, lon2 = ponto_final
    pontos = []
    for i in range(quantidade_pontos):
        fator = i / max(1, quantidade_pontos - 1)
        lat = lat1 + (lat2 - lat1) * fator
        lon = lon1 + (lon2 - lon1) * fator
        pontos.append((lat, lon))
    return pontos


def obter_metadata_streetview(lat, lon, api_key):
    """Obtém o Pano ID único da imagem panorâmica do Google."""
    url = "https://maps.googleapis.com/maps/api/streetview/metadata"
    params = {"location": f"{lat},{lon}", "key": api_key}
    try:
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status")
            if status == "OK":
                return data.get("pano_id"), data.get("location", {}).get("lat"), data.get("location", {}).get("lng"), None
            else:
                return None, None, None, f"Status API: {status} ({data.get('error_message', 'sem mensagem')})"
    except Exception as e:
        return None, None, None, str(e)
    return None, None, None, "Erro desconhecido"


def processar_e_salvar_imagem_dinov2(conteudo_bytes, caminho_saida):
    """Corta topo/céu e ajusta proporção exata para múltiplos de 14."""
    img = Image.open(BytesIO(conteudo_bytes))
    w, h = img.size
    crop_box = (0, int(h * 0.25), w, h)
    img_cortada = img.crop(crop_box)
    img_final = img_cortada.resize((LARGURA_API, ALTURA_API), Image.Resampling.LANCZOS)
    img_final.save(caminho_saida, "JPEG", quality=95)


def baixar_imagem(idx, nome_rua_limpo, pano_id, heading, lado, pasta_saida, api_key):
    """Faz o download da imagem final."""
    url = "https://maps.googleapis.com/maps/api/streetview"
    params = {
        "size": f"{LARGURA_API}x{ALTURA_API}",
        "scale": SCALE,
        "pano": pano_id,
        "heading": round(heading, 2),
        "pitch": PITCH,
        "fov": FOV,
        "key": api_key
    }
    
    nome_arquivo = os.path.join(
        pasta_saida, f"{nome_rua_limpo}_{idx:04d}_{lado}_pano_{pano_id[:8]}.jpg"
    )
    
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            processar_e_salvar_imagem_dinov2(response.content, nome_arquivo)
            return True, nome_arquivo
        else:
            return False, f"Erro HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)


def main():
    if API_KEY == "SUA_CHAVE_API_AQUI" or not API_KEY.strip():
        print("[ERRO CRÍTICO] Você precisa colar sua chave da API do Google na variável API_KEY!")
        return

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    qtd_ruas = len(RUAS_CURITIBA)
    
    print("=" * 75)
    print("COLETA DE DATASET DE CALÇADAS DE CURITIBA (DINOv2)")
    print(f"Total de Ruas Mapeadas: {qtd_ruas}")
    print(f"Meta de Imagens Únicas: {TOTAL_IMAGENS_ALVO}")
    print("=" * 75)
    
    panos_vistos = set()
    tarefas = []
    global_idx = 1
    
    # Geramos 120 candidatos por rua para garantir amostragem longa
    pontos_candidatos_por_rua = 120  
    
    for idx_rua, (nome_rua, (p1, p2)) in enumerate(RUAS_CURITIBA.items(), start=1):
        print(f"[{idx_rua}/{qtd_ruas}] Mapeando pontos na rua: {nome_rua}...")
        
        bearing_rua = calcular_bearing(p1[0], p1[1], p2[0], p2[1])
        pontos = gerar_pontos_interpolados(p1, p2, pontos_candidatos_por_rua)

        fotos_da_rua = 0
        erros_api = set()

        for lat, lon in pontos:
            if len(tarefas) >= TOTAL_IMAGENS_ALVO:
                break

            pano_id, real_lat, real_lon, erro = obter_metadata_streetview(lat, lon, API_KEY)
            
            if erro:
                erros_api.add(erro)

            if pano_id and pano_id not in panos_vistos:
                panos_vistos.add(pano_id)
                
                heading_direita = (bearing_rua + 90) % 360
                heading_esquerda = (bearing_rua - 90) % 360
                
                # Foto calçada direita
                tarefas.append((global_idx, nome_rua, pano_id, heading_direita, "direita"))
                global_idx += 1
                fotos_da_rua += 1

                if len(tarefas) < TOTAL_IMAGENS_ALVO:
                    # Foto calçada esquerda
                    tarefas.append((global_idx, nome_rua, pano_id, heading_esquerda, "esquerda"))
                    global_idx += 1
                    fotos_da_rua += 1

        print(f"   -> {fotos_da_rua} enquadramentos inéditos adicionados.")
        if erros_api and fotos_da_rua == 0:
            print(f"   [AVISO API] Ocorreram erros nesta rua: {list(erros_api)[:2]}")

    if not tarefas:
        print("\n" + "!" * 75)
        print("[ERRO] Nenhuma imagem foi encontrada para download!")
        print("Causas prováveis:")
        print("1. A sua API_KEY é inválida ou não foi ativada.")
        print("2. A biblioteca 'Street View Static API' está desativada na sua conta Google Cloud.")
        print("!" * 75)
        return

    tarefas = tarefas[:TOTAL_IMAGENS_ALVO]
    print(f"\nBaixando {len(tarefas)} imagens distintas em paralelo...")
    print("=" * 75)

    sucessos = 0
    falhas = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(baixar_imagem, idx, rua, pano, hd, lado, PASTA_SAIDA, API_KEY)
            for idx, rua, pano, hd, lado in tarefas
        ]

        for future in as_completed(futures):
            sucesso, msg = future.result()
            if sucesso:
                sucessos += 1
            else:
                falhas += 1

    print("=" * 75)
    print("PROCESSAMENTO CONCLUÍDO!")
    print(f"Fotos salvas com sucesso: {sucessos}")
    print(f"Pasta de destino:         {os.path.abspath(PASTA_SAIDA)}")
    print("=" * 75)


if __name__ == "__main__":
    main()