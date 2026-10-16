import os
import math
import json
import requests
from io import BytesIO
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed


API_KEY = os.getenv("GOOGLE_STREET_VIEW_API_KEY", "")
PASTA_SAIDA = os.getenv("PASTA_IMAGENS", "dataset_calcadas_curitiba")
TOTAL_IMAGENS_ALVO = 5
IMAGENS_POR_BAIRRO = 1
MAX_WORKERS = 10

PITCH = -15     
FOV = 75        
LARGURA_API = 512
ALTURA_API = 512
SCALE = 2       

# Resolução DINOv2
LARGURA_DINO = 512
ALTURA_DINO = 512

LISTA_BAIRROS = [
    "Cidade Industrial de Curitiba",
    "Batel",
    "Centro",
    "Portão",
    "Santa Felicidade",
]


def buscar_ruas_por_lista_bairros(lista_bairros, cidade="Curitiba"):
    """
    Consulta o OpenStreetMap e retorna as ruas associadas aos bairros informados.
    """
    bairros_regex = "^(" + "|".join(lista_bairros) + ")$"
    print(f"[OSM] Consultando {len(lista_bairros)} bairros em {cidade} via Overpass API...")

    overpass_query = f"""
    [out:json][timeout:60];
    area["name"="{cidade}"]->.cidadeArea;
    area["name"~"{bairros_regex}"]->.bairrosArea;
    (
      way["highway"~"residential|tertiary|secondary|unclassified"](area.cidadeArea)(area.bairrosArea);
    );
    out body geom qt;
    """

    headers = {
        "User-Agent": "UTFPR-BioGuardian-StreetViewExtractor/1.0 (academic project)",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
    }

    ENDPOINTS_OVERPASS = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]

    for url in ENDPOINTS_OVERPASS:
        try:
            print(f"[OSM] Tentando servidor: {url} ...")
            response = requests.post(url, data={"data": overpass_query}, headers=headers, timeout=60)
            
            if response.status_code == 200:
                data = response.json()
                elements = data.get("elements", [])

                ruas_encontradas = {}
                for elem in elements:
                    geometry = elem.get("geometry", [])
                    tags = elem.get("tags", {})
                    nome_rua = tags.get("name", f"rua_sem_nome_{elem['id']}")

                    if len(geometry) >= 2:
                        p1 = (geometry[0]["lat"], geometry[0]["lon"])
                        p2 = (geometry[-1]["lat"], geometry[-1]["lon"])
                        chave_rua = f"{nome_rua.lower().replace(' ', '_')}_{elem['id']}"
                        
                        bairro_est = tags.get("addr:suburb", lista_bairros[0])

                        ruas_encontradas[chave_rua] = {
                            "p1": p1,
                            "p2": p2,
                            "nome": nome_rua,
                            "bairro": bairro_est
                        }

                print(f"[OSM] Sucesso! {len(ruas_encontradas)} trechos de ruas recuperados.")
                return ruas_encontradas
            else:
                print(f"[OSM] Servidor {url} retornou HTTP {response.status_code}. Tentando próximo...")

        except requests.exceptions.RequestException:
            print(f"[OSM] Timeout/Erro no servidor {url}. Tentando próximo espelho...")

    print("[ERRO CRÍTICO] Todos os servidores do Overpass falharam.")
    return {}


def calcular_bearing(lat1, lon1, lat2, lon2):
    """Calcula o azimute entre dois pontos GPS consecutivos."""
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2_rad - lon1_rad
    x = math.sin(dlon) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    initial_bearing = math.atan2(x, y)
    return (math.degrees(initial_bearing) + 360) % 360


def gerar_pontos_interpolados(ponto_inicial, ponto_final, quantidade_pontos):
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
    """Obtém o Pano ID e valida a imagem oficial da Google."""
    url = "https://maps.googleapis.com/maps/api/streetview/metadata"
    params = {"location": f"{lat},{lon}", "radius": 20, "key": api_key, "source": "outdoor"}

    try:
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status")
            copyright_info = data.get("copyright", "")
            
            if status == "OK" and "Google" in copyright_info:
                return data.get("pano_id"), data.get("location", {}).get("lat"), data.get("location", {}).get("lng"), None
            elif status == "OK" and "Google" not in copyright_info:
                return None, None, None, "Foto interna/terceiros descartada"
            elif status == "ZERO_RESULTS":
                return None, None, None, "Sem cobertura"
            else:
                return None, None, None, f"Erro API ({status})"
    except Exception as e:
        return None, None, None, str(e)
    return None, None, None, "Erro desconhecido"


def processar_e_salvar_imagem(conteudo_bytes, caminho_saida):
    """Corta topo/céu e ajusta proporção para o DINOv2."""
    img = Image.open(BytesIO(conteudo_bytes))
    w, h = img.size
    crop_box = (0, int(h * 0.25), w, h)
    img_cortada = img.crop(crop_box)
    img_final = img_cortada.resize((LARGURA_DINO, ALTURA_DINO), Image.Resampling.LANCZOS)
    img_final.save(caminho_saida, "JPEG", quality=95)


def baixar_imagem_e_salvar_metadados(idx, dados_tarefa, pasta_saida, api_key):
    """
    Baixa a imagem do Street View e gera simultaneamente o ficheiro .json
    de metadados geográficos para integração com o Roboflow.
    """
    nome_rua_limpo, pano_id, heading, lado, real_lat, real_lon, bairro, nome_rua = dados_tarefa

    url = "https://maps.googleapis.com/maps/api/streetview"
    params = {
        "size": f"{LARGURA_API}x{ALTURA_API}",
        "scale": SCALE,
        "pano": pano_id,
        "heading": round(heading, 2),
        "pitch": PITCH,
        "fov": FOV,
        "source": "outdoor",
        "return_error_code": "true",
        "key": api_key,
    }

    nome_rua_curto = nome_rua_limpo[:25]
    nome_base = f"{idx:04d}_{nome_rua_curto}_{lado}_pano_{pano_id[:8]}"
    caminho_imagem = os.path.join(pasta_saida, f"{nome_base}.jpg")
    caminho_json = os.path.join(pasta_saida, f"{nome_base}.json")

    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 200:
            # 1. Salva a imagem cortada
            processar_e_salvar_imagem(response.content, caminho_imagem)

            # 2. Salva o arquivo JSON de metadados para o Roboflow
            metadados_json = {
                "lat": real_lat,
                "lon": real_lon,
                "pano_id": pano_id,
                "heading": round(heading, 2),
                "pitch": PITCH,
                "bairro": bairro,
                "nome_rua": nome_rua,
                "lado": lado
            }
            
            with open(caminho_json, "w", encoding="utf-8") as f:
                json.dump(metadados_json, f, ensure_ascii=False, indent=2)

            return True, caminho_imagem
        else:
            return False, f"Erro HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)


def main():
    if not API_KEY.strip():
        print("[ERRO CRÍTICO] Defina GOOGLE_STREET_VIEW_API_KEY no arquivo .env!")
        return

    ruas_dinamicas = buscar_ruas_por_lista_bairros(LISTA_BAIRROS, cidade="Curitiba")

    if not ruas_dinamicas:
        print("[ERRO] Nenhuma rua foi recuperada pelo OpenStreetMap.")
        return

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    panos_vistos = set()
    tarefas = []
    global_idx = 1
    pontos_por_rua = 20

    print("=" * 75)
    print(f"PROCESSANDO VARREDURA EM {len(LISTA_BAIRROS)} BAIRROS DE CURITIBA")
    print(f"Meta Global de Imagens: {TOTAL_IMAGENS_ALVO}")
    print("=" * 75)

    for chave_rua, dados_rua in ruas_dinamicas.items():
        if len(tarefas) >= TOTAL_IMAGENS_ALVO:
            break

        p1 = dados_rua["p1"]
        p2 = dados_rua["p2"]
        nome_rua = dados_rua["nome"]
        bairro = dados_rua["bairro"]

        pontos = gerar_pontos_interpolados(p1, p2, pontos_por_rua)

        for i in range(len(pontos) - 1):
            if len(tarefas) >= TOTAL_IMAGENS_ALVO:
                break

            p_atual = pontos[i]
            p_proximo = pontos[i + 1]

            pano_id, real_lat, real_lon, erro = obter_metadata_streetview(p_atual[0], p_atual[1], API_KEY)

            if erro or not pano_id:
                continue

            if pano_id not in panos_vistos:
                panos_vistos.add(pano_id)

                # Bearing local calculado no trecho atual
                bearing_local = calcular_bearing(p_atual[0], p_atual[1], p_proximo[0], p_proximo[1])

                heading_direita = (bearing_local + 90) % 360
                heading_esquerda = (bearing_local - 90) % 360

                # Dados para tarefa direita
                dados_dir = (chave_rua, pano_id, heading_direita, "direita", real_lat, real_lon, bairro, nome_rua)
                tarefas.append((global_idx, dados_dir))
                global_idx += 1

                # Dados para tarefa esquerda
                if len(tarefas) < TOTAL_IMAGENS_ALVO:
                    dados_esq = (chave_rua, pano_id, heading_esquerda, "esquerda", real_lat, real_lon, bairro, nome_rua)
                    tarefas.append((global_idx, dados_esq))
                    global_idx += 1

    print(f"\n[OK] {len(tarefas)} enquadramentos inéditos e metadados preparados.")
    print("Iniciando downloads e geração de metadados JSON...")
    print("=" * 75)

    sucessos = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(baixar_imagem_e_salvar_metadados, idx, dados, PASTA_SAIDA, API_KEY)
            for idx, dados in tarefas
        ]

        for future in as_completed(futures):
            sucesso, _ = future.result()
            if sucesso:
                sucessos += 1

    print("=" * 75)
    print(f"COLETA E METADADOS CONCLUÍDOS!")
    print(f"{sucessos} imagens + JSONs salvos em: {os.path.abspath(PASTA_SAIDA)}")
    print("=" * 75)


if __name__ == "__main__":
    main()