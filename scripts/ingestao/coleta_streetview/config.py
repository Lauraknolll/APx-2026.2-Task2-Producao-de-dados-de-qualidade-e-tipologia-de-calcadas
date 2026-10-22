"""
Constantes e caminhos do pipeline — tudo o que se ajusta sem mexer na lógica.

Os valores padrão da linha de comando vêm daqui; mudar um número aqui muda o
comportamento de todas as etapas que o usam.
"""

from pathlib import Path

# --------------------------------------------------------------------------- #
# Caminhos
# --------------------------------------------------------------------------- #

# Raiz do repositório (este arquivo está em scripts/ingestao/coleta_streetview/).
RAIZ = Path(__file__).resolve().parents[3]
# Camada de calçadas do IPPUC: versionada zipada em data/raw/; extraída
# automaticamente para data/processed/ no primeiro uso (geometria.garantir_calcadas).
CALCADAS_ZIP = RAIZ / "data" / "raw" / "_Passeio_CWB.zip"
CALCADAS_PATH = RAIZ / "data" / "processed" / "passeio.gpkg"
CACHE_RUAS = RAIZ / "data" / "raw" / "ruas_osm"            # traçados de ruas do OSM, já consultados
DB_PATH = RAIZ / "data" / "processed" / "streetview.db"    # estado do pipeline
PASTA_IMAGENS = RAIZ / "data" / "processed" / "streetview"       # arquivos de trabalho (todas as vistas)
PASTA_RUAS = RAIZ / "data" / "processed" / "downloads-ruas"      # resultado: data/processed/downloads-ruas/<rua>/

# --------------------------------------------------------------------------- #
# Ruas e zonas
# --------------------------------------------------------------------------- #

# Ruas oferecidas no menu interativo (nome do OpenStreetMap, por extenso).
RUAS = ["Avenida Silva Jardim", "Avenida Sete de Setembro"]

# Bounding box aproximado do município (lon_min, lat_min, lon_max, lat_max).
CURITIBA_BBOX = (-49.3900, -25.6450, -49.1850, -25.3450)

# Servidores públicos do Overpass (OSM); o principal vive sobrecarregado,
# então tentamos os espelhos em sequência.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

ESPACAMENTO = 50.0    # m: tamanho de cada zona de calçada (uma foto por zona)
PASSO_ALVOS = 10.0    # m entre os alvos dentro da zona (o Google tira um panorama a cada ~10 m)
DISTANCIA_RUA = 25.0  # m: zona "da rua" se o centro estiver a até isso do eixo dela

# --------------------------------------------------------------------------- #
# Panoramas e câmera
# --------------------------------------------------------------------------- #

# Panorama aceito: a até DIST_MAX do alvo (o carro passa no meio da rua) e
# não em cima dele (aí não há para onde apontar).
DIST_MIN, DIST_MAX = 2.0, 20.0
ALTURA_CAMERA = 2.5   # m, aproximada, da câmera do carro do Google

# Close da calçada: proporção QUADRADOS:1, cortado em QUADRADOS quadrados de
# lado múltiplo de 14 (o patch das redes DINOv2/ViT), no máximo ALTURA_MAX px.
QUADRADOS = 3
LADO_MULTIPLO = 14
ALTURA_MAX = 700
FOLGA = 1.5             # quanto da faixa guia-alinhamento entra na vista (1 = só ela)
FOV_MIN = 12.0          # graus: campo de visão vertical mínimo
LIMITE_INFERIOR = -28.0  # graus: abaixo disso começa o borrão que o Google põe sobre o carro

# Vista de contexto (só para a segmentação): mesma direção do close, mais aberta.
CONTEXTO_FOV, CONTEXTO_TAMANHO = 110.0, (960, 540)

# --------------------------------------------------------------------------- #
# Segmentação e filtro
# --------------------------------------------------------------------------- #

MODELO_SEGMENTACAO = "nvidia/segformer-b2-finetuned-cityscapes-1024-1024"
# Classes do Cityscapes. Piso de calçada = sidewalk + terrain (calçada de
# grama ou terra também é calçada).
CLASSES_PISO = (1, 9)
CLASSES_OBSTRUCAO = {
    "veiculo": (13, 14, 15, 16, 17, 18),
    "pessoa": (11, 12),
    "poste_placa": (5, 6, 7),
    "arvore": (8,),
    "muro_cerca": (3, 4),
}
# Só estes reprovam um quadrado: ficam entre a câmera e o piso. Árvores,
# canteiros e muros são medidos, mas quase sempre estão ao lado ou atrás da
# calçada. Motos com piloto saem como "pessoa"; "borrao" é medido à parte.
OBSTRUCAO_NA_FRENTE = ("veiculo", "pessoa", "borrao")
# Um quadrado é limpo com piso >= MIN_CALCADA e obstrução na frente <=
# MAX_OBSTRUCAO. O piso mínimo é baixo porque o modelo subestima petit-pavé
# com sombra.
MIN_CALCADA, MAX_OBSTRUCAO = 0.20, 0.15
