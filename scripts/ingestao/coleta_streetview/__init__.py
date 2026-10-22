"""
Coleta de imagens das calçadas de Curitiba no Google Street View.

Para cada rua, divide as calçadas da camada do IPPUC em zonas de ~50 m,
escolhe a melhor vista do Street View de cada zona, recorta um close da
calçada em 3 quadrados e guarda, em downloads-ruas/<rua>/, só os quadrados em
que uma IA de segmentação confirma calçada sem obstrução. Rode da raiz do
repositório com `python -m scripts.ingestao.coleta_streetview`.

Módulos:
    config      constantes e caminhos
    geometria   camada de calçadas (GeoPackage, UTM, linha central) e traçado das ruas (OSM)
    streetview  panoramas do Google e recorte de vistas em perspectiva
    banco       estado no SQLite, escolha da vista de cada zona e downloads-ruas/
    etapas      coletar, baixar, segmentar e reavaliar
    cli         menu interativo e subcomandos
"""
