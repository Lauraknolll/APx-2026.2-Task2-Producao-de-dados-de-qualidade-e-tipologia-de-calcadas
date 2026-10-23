# Traçados de ruas — OpenStreetMap

Nomes e traçados das ruas de Curitiba usados pela coleta do Street View
(`scripts/ingestao/coleta_streetview`) para achar a rua digitada e separar as
calçadas dela das outras.

- **Fonte:** OpenStreetMap, via API Overpass (vias `highway` com nome, exceto
  plataformas de ônibus, dentro do município de Curitiba). Dados ©
  colaboradores do OpenStreetMap, licença ODbL.
- **Obtenção:** automática; outubro de 2026.

## Arquivos

- `_vias_curitiba.json.gz` — todas as vias com nome, baixadas numa consulta
  só: `{"fonte", "obtido": AAAA-MM-DD, "vias": {<nome no OSM>: [trecho, ...]}}`,
  cada trecho uma lista de `[lat, lon]` (WGS84), um por via (`way`) do OSM. É
  nele que o nome digitado é procurado. Apague-o para baixar o OSM de novo.
- `<rua>.json` — o traçado de uma rua, congelado na primeira vez que ela é
  coletada (as zonas da rua não mudam se o OSM mudar):
  `{"nome": <nome oficial no OSM>, "trechos": [[[lat, lon], ...], ...]}`. O
  arquivo tem o nome sem acento, em minúsculas.
