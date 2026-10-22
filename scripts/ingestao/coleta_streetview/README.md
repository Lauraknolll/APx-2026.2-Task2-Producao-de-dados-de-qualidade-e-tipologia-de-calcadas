# Coleta de imagens de calçadas no Street View

Coleta automática de imagens das calçadas de Curitiba no Google Street View,
para uma camada georreferenciada do estado das calçadas (AP[x] Task 2 —
UTFPR · IPPUC).

Para cada rua, o pipeline divide as calçadas da camada do IPPUC em **zonas de
~50 m**, escolhe a melhor vista do Street View de cada zona, recorta um
**close da calçada** (da guia ao alinhamento dos prédios), corta o close em
**3 quadrados** e guarda só os quadrados em que uma IA de segmentação confirma
**calçada sem obstrução**. O resultado de cada rua fica em
`downloads-ruas/<rua>/`, com um `indice.csv` que liga cada foto às
coordenadas e ao panorama de origem. É a etapa de coleta: a avaliação da
qualidade da calçada (tipologia e defeitos) vem depois e usa essas imagens.

## Instalação

Python 3.14. Da raiz do repositório, no Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r scripts/ingestao/coleta_streetview/requirements.txt
.venv\Scripts\python.exe -m pip install --no-deps streetlevel
```

No Linux/macOS, troque `.venv\Scripts\python.exe` por `.venv/bin/python`. As
dependências desta coleta ficam num `requirements.txt` próprio, para não mexer
no ambiente Docker dos notebooks.

- A [streetlevel](https://github.com/sk-zk/streetlevel) vai com `--no-deps`
  porque uma dependência dela (`pyfrpc`, só usada para o Mapy.cz) não compila
  no Python 3.14; as outras estão no `requirements.txt`.
- O `torch` instalado assim roda na CPU. Para a segmentação usar a GPU,
  instale o build com CUDA (<https://pytorch.org/get-started/locally/>) — o
  código usa a GPU sozinho quando ela está disponível.
- Na primeira segmentação, o modelo (~210 MB) é baixado do Hugging Face e
  fica em cache.

### Dados necessários

Nenhum passo manual: a **camada de calçadas do IPPUC** (`passeio.gpkg`,
SIRGAS 2000 / UTM 22S) já está no repositório, zipada em
`data/raw/_Passeio_CWB.zip`, e é extraída para `data/processed/passeio.gpkg`
no primeiro uso. Os traçados das ruas vêm do OpenStreetMap e ficam em cache em
`data/raw/ruas_osm/` (as ruas do menu já estão lá).

## Como usar

Sempre da raiz do repositório:

```powershell
.venv\Scripts\python.exe -m scripts.ingestao.coleta_streetview
```

```
Qual rua coletar?
  1) Avenida Silva Jardim; 179 zonas (7 já com foto)
  2) Avenida Sete de Setembro; 271 zonas (20 já com foto)
Escolha [1-2]: 1

"Avenida Silva Jardim": 179 zonas, 7 já processadas, 172 a processar.
Quantas zonas rodar? [1-172, Enter = todas]: 3
...
Pronto: 3 zonas da "Avenida Silva Jardim" em 3 min — 3 com foto, 0 sem foto boa.
  Na rua: 10 de 179 zonas com foto; 25 quadrados de calçada em downloads-ruas\avenida-silva-jardim/
```

- A quantidade vale para as zonas **ainda sem resultado**, escolhidas
  espalhadas pela rua, e limita tudo — inclusive a consulta aos panoramas.
  Enter roda todas as que faltam.
- Pode ser interrompido (Ctrl+C) e rodado de novo: continua de onde parou.
- Sem perguntas: `python -m scripts.ingestao.coleta_streetview rua --nome "Avenida Silva Jardim" --limite 20`.
- Para oferecer outra rua no menu, acrescente o nome a `RUAS` em
  [config.py](config.py) — o nome do **OpenStreetMap**, por
  extenso ("Avenida", não "Av.").

Uma rua inteira tem ~900 a 1.300 vistas candidatas; com a segmentação na CPU,
conte perto de uma hora.

### Etapa por etapa

O menu roda estas etapas em sequência; elas também existem como subcomandos
(`--help` em cada um mostra as opções):

```powershell
python -m scripts.ingestao.coleta_streetview coletar   --rua "Avenida Sete de Setembro"
python -m scripts.ingestao.coleta_streetview baixar    --rua "Avenida Sete de Setembro"
python -m scripts.ingestao.coleta_streetview segmentar --rua "Avenida Sete de Setembro" --mascaras
python -m scripts.ingestao.coleta_streetview reavaliar --max-obstrucao 0.08
```

- `coletar --bbox lon_min,lat_min,lon_max,lat_max` coleta uma área em vez de
  uma rua (as zonas de uma área sem rua não vão para `downloads-ruas/`).
- `baixar` e `segmentar` aceitam `--zonas 12,15` para zonas específicas; sem
  `--rua` nem `--zonas`, trabalham sobre todas as zonas pendentes do banco.
- `reavaliar` refaz a escolha com outros limites usando só o que já está no
  banco — para calibrar o filtro sem baixar nem segmentar de novo.

## Como funciona

**1. Zonas e vistas candidatas (`coletar`)** — só metadados.
A linha central de cada calçada do `passeio.gpkg` é dividida em zonas de
~50 m; entram as zonas a até 25 m do eixo da rua (traçado do OSM). Em cada
zona, o pipeline marca **alvos a cada 10 m** (o espaçamento dos panoramas do
Google) e pega o panorama mais próximo de cada alvo, com a câmera apontada
para aquele alvo: cada candidata é um close perpendicular de um pedaço
diferente da zona. Só entram panoramas do **carro do Google** (nada de fotos
de usuários, trekker ou interiores) a 2–20 m do alvo. A captura histórica
mais recente de cada panorama entra como reserva.

**2. Closes e quadrados (`baixar`).**
Da largura da calçada (do polígono do IPPUC) e da distância do carro saem os
ângulos da guia e do alinhamento; o close cobre essa faixa, na resolução
máxima do panorama, em proporção 3:1, sem descer até o borrão que o Google
põe sobre o próprio carro. Só os tiles do panorama que a vista usa são
baixados. A altura do close é arredondada para **múltiplo de 14** (o patch das
redes DINOv2/ViT, como a do Project Sidewalk), e o close é cortado em **3
quadrados** de 546 a 700 px de lado, que entram nas redes de avaliação sem
redimensionar — e um defeito pequeno pesa mais num quadrado do que diluído na
imagem toda. Junto, uma **vista de contexto** aberta, na mesma direção.
Primeiro são baixadas as capturas recentes; as históricas, só nas zonas em
que nenhuma recente passou no filtro.

**3. Calçada ou não (`segmentar`).**
O SegFormer-B2 treinado no Cityscapes classifica cada pixel da vista de
contexto (num close sem rua e prédios em volta ele não reconhece calçada). Em
cada quadrado — uma fatia exata do retângulo do close dentro do contexto — o
pipeline mede o **piso** (calçada ou terreno) e a **obstrução**: veículos,
pessoas e o borrão do carro do Google, este detectado por não ter textura.

Um quadrado é **limpo** com piso ≥ 20% e obstrução ≤ 15%. Árvores, canteiros
e muros são medidos, mas não reprovam: quase sempre ficam ao lado ou atrás da
calçada. Entre as vistas com algum quadrado limpo, a zona fica com a de
**captura mais recente** (o que se avalia é a calçada como está hoje); na
mesma data, a com mais quadrados limpos. Só os quadrados limpos da vista
escolhida vão para `downloads-ruas/<rua>/`. Zona sem nenhuma vista aprovada
fica sem foto (`recoleta`).

## Resultado

`downloads-ruas/<rua>/` tem sempre a **coleta mais recente** da rua — é
sincronizada a cada rodada: o que deixou de valer sai, o que é novo entra.

- `<zona>_<tentativa>_<quadrado>.jpg` — os quadrados de calçada limpos
  (quadrado 1 a 3, da esquerda para a direita).
- `indice.csv` — uma linha por foto:

| Coluna | Conteúdo |
|---|---|
| `arquivo` | nome da imagem |
| `zona`, `quadrado` | id da zona no banco e posição do quadrado no close |
| `captura` | mês da captura do Google (AAAA-MM) |
| `lat`, `lon` | ponto da calçada que a vista mostra (WGS84) |
| `endereco` | endereço do panorama, segundo o Google |
| `piso`, `obstrucao` | frações medidas pela segmentação no quadrado |
| `pano_id` | panorama de origem, para auditoria |

## Estrutura do código

| Módulo | Responsabilidade |
|---|---|
| [config.py](config.py) | Constantes e caminhos (ruas do menu, tamanho das zonas, limites do filtro...) |
| [geometria.py](geometria.py) | Camada de calçadas (GeoPackage, lat/lon ↔ UTM, linha central) e traçado das ruas (OpenStreetMap, com cache) |
| [streetview.py](streetview.py) | Panoramas do Google e recorte de vistas em perspectiva a partir dos tiles |
| [banco.py](banco.py) | Banco SQLite com o estado do pipeline, filtro dos quadrados e escolha da vista de cada zona, `downloads-ruas/<rua>/` e o `indice.csv` |
| [etapas.py](etapas.py) | As etapas: 1. `coletar` (zonas e vistas candidatas), 2. `baixar` (closes, quadrados, vistas de contexto), 3. `segmentar` (piso e obstrução de cada quadrado) e `reavaliar` |
| [cli.py](cli.py) | Menu interativo e subcomandos |

Cada módulo abre com uma docstring que explica o que faz e como.

### Banco (`data/processed/streetview.db`)

| Tabela | Conteúdo |
|---|---|
| `pontos` | Uma linha por **zona**: centro, status (`pendente`, `aprovada`, `recoleta`), vista escolhida (`tentativa`) e quadrados limpos dela. A identidade da zona é (polígono, anel, ordem) — estável enquanto o tamanho das zonas for o mesmo. |
| `tentativas` | As vistas candidatas de cada zona: panorama, data, alvo, câmera, arquivos baixados e o que a segmentação mediu em cada quadrado. |
| `pontos_rua` | A que rua do OSM cada zona pertence (uma zona de esquina pode estar em duas). |
| `parametros` | O tamanho das zonas. |

A etapa de avaliação pode recusar a vista escolhida de uma zona com
`scripts.ingestao.coleta_streetview.banco.registrar_rejeicao(conn, zona, motivo)`: a zona passa para
a melhor reserva e a vista recusada nunca mais é escolhida.

### Arquivos de trabalho

`data/processed/streetview/` guarda tudo o que o pipeline baixa, inclusive das vistas
que não foram escolhidas: o close de cada candidata (`<zona>_<tentativa>.jpg`),
os quadrados (`quadrados/`), a vista de contexto (`contexto/`) e, com
`--mascaras`, a segmentação (`mascaras/`: piso em magenta, quadrados limpos em
amarelo, descartados em vermelho).

## Limitações

- **Acesso ao Street View.** A `streetlevel` usa APIs internas do Google, não
  oficiais: pode quebrar se o Google mudar algo, e consultas demais seguidas
  levam a bloqueio temporário do IP (o código tenta de novo e, persistindo,
  para — basta rodar mais tarde). O uso dessas imagens está sujeito aos termos
  do Google Maps Platform.
- **Obstruções que o modelo não conhece.** O Cityscapes não tem classes para
  lixo, cones ou entulho: um saco de lixo na calçada não reprova o quadrado.
- **Segmentação aproximada.** O modelo vê a vista de contexto em 512×512 e
  subestima o piso em petit-pavé com sombra (por isso o limite de 20%). O
  limite do borrão (variância < 8) foi calibrado a olho.
- **Datas.** O Google informa só o mês (às vezes só o ano) da captura.

## Próximos passos

- Avaliação da qualidade: ajuste fino (*fine-tuning*) do modelo SurfaceProblem
  do Project Sidewalk com os quadrados rotulados (Roboflow), para tipologia
  (paver, petit-pavé, placas) e defeitos (buracos, desníveis, rachaduras).
- Detector de objetos por texto (OWLv2 / Grounding DINO) para lixo, cones e
  entulho no filtro de obstrução.
