# Traçados de ruas — OpenStreetMap

Cache dos traçados de ruas usados pela coleta do Street View
(`scripts/ingestao/coleta_streetview`) para separar as calçadas de cada rua.

- **Fonte:** OpenStreetMap, via API Overpass (vias `highway` com o nome da rua,
  dentro do município de Curitiba). Dados © colaboradores do OpenStreetMap,
  licença ODbL.
- **Obtenção:** automática, na primeira vez que uma rua é coletada; outubro de 2026.
- **Formato:** um JSON por rua, `{"nome": <nome oficial no OSM>, "trechos": [[[lat, lon], ...], ...]}`
  (WGS84), um trecho por via (`way`) do OSM.

Ruas novas entram aqui sozinhas quando são coletadas pela primeira vez.
