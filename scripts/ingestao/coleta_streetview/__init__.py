"""
Coleta de imagens das calçadas de Curitiba no Google Street View.

Para cada rua, divide as calçadas da camada do IPPUC em zonas de ~50 m,
escolhe a melhor vista do Street View de cada zona, recorta um close da
calçada em 3 quadrados e guarda, em downloads-ruas/<rua>/, só os quadrados em
que uma IA de segmentação confirma calçada sem obstrução. Rode com
`python -m scripts.ingestao.coleta_streetview`.

Módulos, na ordem do pipeline:
    config       constantes e caminhos
    geometria    camada de calçadas (GeoPackage), UTM, linha central das calçadas
    osm          traçado das ruas (OpenStreetMap)
    banco        o banco SQLite com o estado de tudo
    streetview   panoramas do Google e recorte de vistas em perspectiva
    coleta       etapa 1: zonas e vistas candidatas
    recorte      etapa 2: closes, quadrados e vistas de contexto
    segmentacao  etapa 3: piso e obstrução de cada quadrado
    selecao      filtro dos quadrados e escolha da vista de cada zona
    exportacao   o resultado em downloads-ruas/<rua>/
    cli          menu interativo e subcomandos
"""
