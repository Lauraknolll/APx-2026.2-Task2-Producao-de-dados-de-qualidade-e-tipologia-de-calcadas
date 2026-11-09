# Interface da coleta: mapa das calçadas

Mapa de Curitiba com as ruas coletadas coloridas pela qualidade da calçada,
num **gradiente** que vem das avaliações das fotos: de longe, cada rua tem a
cor geral dela; de perto, aparece a qualidade de cada altura da rua. Na mesma
página dá para avaliar as fotos à mão, exportar as avaliações para conferência
no Roboflow e disparar a coleta de uma rua nova.

Tudo roda num programa só, o **coletor** (`Calcadas.exe`), 100% local. Ele
abre uma janela no visual da página (clara ou escura, conforme o Windows)
com:

- o link do mapa: a página, com a seção de coleta, lendo e gravando só no
  banco deste computador;
- as fotos coletadas: escolha uma rua e veja todas as vistas que a coleta
  baixou dela, inteiras, com as coordenadas de onde foram tiradas;
- as últimas coletas, em linguagem simples: a situação de cada uma (em
  andamento, concluída, cancelada, falhou), uma barra para cada etapa e o
  resultado.

Nada vai para a internet além da própria coleta do Street View: as coletas,
as fotos e as avaliações ficam em `data/processed/`. Cada pessoa coleta no
seu computador, e quem coleta o quê se combina fora dele (numa planilha, por
exemplo).

Para quem só usa o `.exe`, há um [guia de uso](../../docs/coletor-de-calcadas.md)
sem linguagem técnica.

## Como usar

- **Para coletar:** abra o `Calcadas.exe` (em `dist\Calcadas\`, ver
  [O coletor](#o-coletor-exe)) e clique no link da janela. A página abre com
  a seção "Coletar uma rua". Deixe a janela aberta enquanto coleta.
- **Para ver as fotos de uma rua:** na janela do `.exe`, aba "Fotos
  coletadas" (ver [As fotos coletadas](#as-fotos-coletadas)).

Sem o `.exe`, o mesmo coletor roda pelo terminal, da raiz do repositório:
`python -m scripts.interface.janela` abre a janela, e `python -m
scripts.interface` abre só a página no navegador.

O mapa de fundo é o Stadia Alidade Smooth, claro ou escuro conforme o tema do
sistema (em `127.0.0.1` ele funciona sem conta na Stadia). O botão no canto
do mapa, acima do zoom, recolhe a barra lateral.

### Exibição das avaliações

No topo da barra lateral, três modos (`V` alterna entre eles):

- **Ocultar**: o mapa fica limpo, sem nenhuma rua ou foto destacada.
- **Ao passar**: nada fica desenhado até o mouse chegar a uma rua avaliada.
  - Aí acende só o gradiente dessa rua num raio de ~90 px em volta do mouse,
    apagando aos poucos na borda, e uma dica mostra o nome e a nota naquele
    ponto.
  - Passar o mouse numa rua da lista acende a rua inteira.
  - Com uma zona aberta, o holofote fica sobre a foto dela (o que também
    funciona no toque).
- **Tudo**: todas as ruas avaliadas coloridas.

O interruptor **Fotos no mapa** (`F`) mostra ou esconde os pontos das fotos:

- Ele vale nos modos "Ao passar" e "Tudo", e os pontos aparecem a partir do
  zoom 15.
- Só no modo "Tudo" os pontos têm a cor da nota da zona.
- Passar o mouse num ponto mostra uma prévia da foto, com a zona, a nota e o
  endereço.

### Ruas coletadas

A seção mostra o progresso geral da avaliação e um card por rua do banco,
com:

- a nota geral da rua;
- os quadrados por classe;
- quantas zonas têm foto e quantas já foram avaliadas.

A busca filtra pelo nome (acentos e maiúsculas não importam).

**Clicar no card destaca a rua no mapa**:

- A rua fica como está, o resto (as outras ruas e as fotos delas) esmaece e o
  mapa a enquadra.
- No modo "Ao passar" ela acende inteira; no "Ocultar", é a única rua
  desenhada.
- Para desfazer o destaque: clicar de novo no card, apertar `Esc` ou clicar
  num ponto vazio do mapa.

A seta no canto do card (aparece ao passar o mouse) abre as zonas da rua em
dois grupos recolhíveis, "Faltam avaliar" e "Avaliadas". Cada zona mostra o
endereço, a cor da nota e quantos quadrados já têm avaliação (ex.: `1/3`).

### Avaliar uma zona

Clique numa zona da lista, num trecho colorido ou num ponto de foto. O painel
da zona mostra:

- no topo, a vista completa da calçada, com o link para o Street View;
- embaixo, o dropdown **Avaliar**:
  - o cabeçalho mostra quantos quadrados já têm avaliação e a cor de cada um;
  - dentro, o nome de quem avalia ("Avaliando como", gravado com cada
    avaliação) e os quadrados, cada um com as cinco classes: adequada,
    parcialmente adequada, inadequada, sem calçada e não identificável.

O painel fecha pelo `×`, por `Esc` ou com um clique fora dele.

### Coletar uma rua

O nome é aceito como no menu do terminal (sem acento, abreviado...).
"Procurar" mostra quantas zonas a rua tem e quantas faltam. "Coletar" roda a
coleta da rua (`coleta_streetview rua`) num subprocesso do coletor.

Enquanto a coleta roda:

- A página mostra a etapa (1 de 3: panoramas, 2: fotos, 3: conferência das
  calçadas) e uma barra de progresso, lidas do log da coleta.
- A janela do coletor, na aba "Últimas coletas", mostra a mesma coleta
  em cartões ([andamento.py](andamento.py)):
  - um selo com a situação: em andamento, concluída, cancelada ou falhou;
  - as três etapas (procurando as fotos no Street View, baixando, conferindo
    se há calçada), cada uma com a sua barra e quanto falta;
  - o resultado: quantas zonas ficaram com foto boa ou, num erro, a causa
    em palavras simples (sem internet, rua não encontrada...);
  - "Ver o registro completo", que abre o log inteiro.
- Roda uma coleta por vez. "Parar" interrompe, e rodar a mesma rua de novo
  continua de onde parou.

Quando tudo termina, é interrompido ou para com erro, um aviso aparece por
1,5 s no canto superior direito:

- Ele mostra o resultado ou a causa do erro.
- Tem um `×` para fechar antes e fica parado enquanto o mouse estiver em
  cima.

O log de cada coleta fica em `data/processed/coletas/` (as 20 últimas).

### Atalhos

| Tecla | Ação |
|---|---|
| `V` | alterna o modo de exibição |
| `F` | mostra ou esconde os pontos das fotos |
| `N` | abre a próxima zona sem avaliação (na rua da zona aberta; quando ela acaba, nas outras) |
| `1`–`5` | dá a classe ao quadrado destacado, na ordem dos botões (com o "Avaliar" fechado, só o abre) |
| `0` | apaga a avaliação do quadrado destacado |
| `←` `→` | trocam o quadrado destacado |
| `Esc` | fecha a zona; sem zona aberta, desfaz o destaque da rua |

### O que o navegador lembra

Ficam no `localStorage`, por navegador:

- o modo de exibição e as fotos ligadas ou não;
- a barra recolhida, as seções e ruas abertas e o "Avaliar" aberto ou
  fechado;
- o nome de quem avalia;
- a rua e o "Só as novas" da exportação.

O endereço guarda a vista (`#mapa=zoom/lat/lon`) ou a zona aberta
(`#zona=<id>`), para mandar o link de um trecho ou de uma zona a alguém.

Com movimento reduzido pedido pelo sistema (no Windows, "Efeitos de animação"
desligado), as animações continuam, só que mais curtas (150 ms).

## O coletor (.exe)

O coletor é a [janela.py](janela.py) empacotada com o PyInstaller, com o
servidor, a coleta e o modelo de segmentação dentro. Para gerar, da raiz:

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller scripts\interface\exe\calcadas.spec --noconfirm
```

- **O resultado:** a pasta `dist\Calcadas\`, com o `Calcadas.exe` e a pasta
  `_internal\`. Os dois andam juntos: o `.exe` sozinho não abre. Leva alguns
  minutos para gerar e ocupa ~700 MB, por causa do torch.
- **Os dados:** o `.exe` usa os dados do repositório em que está (o banco e
  as fotos). Gerado em `dist\`, dentro do repositório, ele coleta no mesmo
  banco de sempre.
- **Para mandar a outra pessoa:** zipe a pasta `Calcadas\` inteira. Ela roda
  em qualquer Windows 64 bits, sem instalar nada:
  - Fora do repositório, ela começa um banco novo ali mesmo; já traz a
    camada de calçadas e os traçados das ruas.
  - O Windows avisa que o `.exe` não é assinado: "Mais informações" >
    "Executar assim mesmo".
- **O modelo de segmentação:** é baixado do Hugging Face na primeira coleta
  (~110 MB) e fica no cache do usuário.

## As fotos coletadas

A aba "Fotos coletadas" da janela ([galeria.py](galeria.py)) mostra o que a
coleta baixou de uma rua:

- **A rua:** o campo de busca funciona como o da página: filtra sem acento e
  por partes do nome, as setas andam na lista e Enter escolhe. Cada rua mostra
  quantas fotos tem.
- **As fotos:** todas as vistas baixadas de cada zona, inteiras: o close de
  onde saem os 3 quadrados, antes do recorte. Elas vêm na ordem da coleta, com:
  - a zona e o número da vista;
  - o que a coleta fez com ela: escolhida para a zona (e quais quadrados
    ficaram), recusada (e por quê), não escolhida ou ainda não conferida;
  - as coordenadas do panorama do Street View de onde a foto foi tirada, a
    data da captura e a distância até a calçada.
- **Os cliques:** na foto, ela abre inteira no visualizador do Windows; nas
  coordenadas, o lugar abre no Google Maps.
- **Durante uma coleta:** as fotos novas aparecem sozinhas, a cada 5 s.

As miniaturas são feitas só para as fotos que aparecem na tela, então ruas
com centenas de fotos abrem na hora.

## Exportar para conferência

A seção **Exportar para conferência** baixa um `.zip` com os quadrados
avaliados (da vista escolhida de cada zona) e as classes deles, pronto para o
Roboflow. O zip é montado na própria página. O título mostra quantas
avaliações ainda não foram exportadas.

- **Rua**: todas, ou só uma (uma zona de esquina conta nas duas ruas).
  - É um campo que filtra a lista enquanto se digita (acentos e maiúsculas
    não importam). `↑` `↓` andam, `Enter` escolhe e `Esc` fecha sem mudar.
  - Cada opção mostra quantas avaliações novas e quantas no total ela tem.
- **Só as novas** (interruptor):
  - Ligado, só entram as avaliações ainda não exportadas, ou refeitas depois
    da última exportação daquele quadrado. Avaliar a rua X, exportar e
    avaliar a rua X de novo faz a segunda avaliação contar como nova.
  - Desligado, entra tudo.
  - Exportar uma rua não muda o que é novo nas outras.
  - O botão diz quantos quadrados vão no zip.

Antes de montar o zip, a página relê as avaliações do banco. Cada exportação
fica registrada: em `exportacoes`, e por quadrado, em `exportados`, a
avaliação que foi no zip. A última aparece embaixo do botão.

- **Formato**: as imagens e um `_annotations.coco.json` (COCO).
  - O projeto `apx2-bzsou` é de detecção de objetos e é baixado em COCO pelo
    treino ([download_roboflow.py](../ingestao/download_roboflow.py),
    [extract_features.py](../transformacao/extract_features.py)), que lê a
    classe de cada imagem pelas anotações dela.
  - Por isso cada quadrado vai com uma caixa cobrindo a imagem inteira, na
    classe da avaliação.
  - Os nomes de classe são os do projeto: `Adequada`,
    `Parcialmente Adequado`, `Inadequada`, `Sem calcada` e
    `Nao identificavel`.
- **No Roboflow**: *Upload* e arrastar o `.zip`. As imagens entram já
  anotadas; confira (e corrija, se preciso) antes de gerar uma versão nova do
  dataset para o treino.
- **Nomes das imagens**: `<rua>__<zona>_<vista>_<quadrado>.jpg`, os mesmos do
  [upload-roboflow.py](../ingestao/upload-roboflow.py).
  - Uma foto que já esteja no projeto é reconhecida pelo Roboflow como
    duplicata.
  - Por isso, ao importar uma **reavaliação**, confira no Roboflow se a
    anotação da imagem foi trocada pela nova classe.

## Como a cor é decidida

1. **Nota de cada zona.** Cada classe vale uma nota: adequada = 1,
   parcialmente adequada = 0,7, inadequada = 0,4 e sem calçada = 0. "Não identificável" não tem nota,
   porque não diz nada da calçada.
   - A nota da zona é a média dos quadrados avaliados da vista escolhida pela
     coleta (a de `data/processed/downloads-ruas/`).
   - A foto fica no ponto da calçada que essa vista mostra.
2. **Nota de cada ponto da rua.** O traçado (o do OSM, congelado pela coleta)
   tem um vértice a cada 5 m.
   - Cada vértice recebe a média das notas das fotos **da mesma rua** (a foto
     de uma transversal não pinta a rua).
   - O peso é `1 / (d² + r²)`: `d` é a distância até a foto e `r`, o raio do
     zoom.
3. **O zoom.** `r` equivale a 30 pixels na tela (no mínimo 15 m):
   - **De longe** (zoom 12, `r` ≈ 1 km), as fotos da rua pesam quase igual e
     ela fica com a cor geral. Uma rua quase toda adequada fica verde.
   - **De perto** (zoom 17, `r` ≈ 30 m), só contam as fotos vizinhas. Entre
     uma foto e a outra, a cor passa de uma para a outra aos poucos, ao longo
     de todo o caminho.
4. **A escala.** A cor vai de vermelho (0, sem calçada) a laranja (0,4,
   inadequada), amarelo (0,65) e verde, que é pleno a partir de 0,85; a
   parcialmente adequada (0,7) fica entre o amarelo e o verde.

Só aparecem no mapa as ruas com ao menos uma foto avaliada, e elas são
coloridas **inteiras**: longe das fotos, vale a nota das mais próximas. Ruas
sem avaliação, ou só com fotos "não identificável", não são desenhadas.

Os pontos das fotos têm de 2,5 a 5 px de raio, crescendo com o zoom, e a cor
da nota da zona. Branco: falta avaliar; roxo: só "não identificável".

A linha tem **80% da largura com que o mapa de fundo desenha uma rua
residencial**, a via mais estreita entre as coletadas, então a cor fica dentro
de qualquer rua. A largura é a mediana medida em dezenas de pontos nos tiles
do Stadia:

| Zoom | ≤ 14 | 15 | 16 | 17 | 18 | 19 |
|---|---|---|---|---|---|---|
| Rua residencial no mapa (px) | 1 | 2 | 2 | 3 | 5 | 8 |
| Linha colorida (px) | 1 | 1,6 | 1,6 | 2,4 | 4 | 6,4 |

Em avenidas, que o mapa desenha mais largas, a linha fica proporcionalmente
mais fina.

Os valores que dá para ajustar ficam todos em [static/app.js](static/app.js):

- as notas das classes: `NOTAS`;
- a escala de cores: `ESCALA`;
- o raio da média: `RAIO_PX` e `RAIO_MIN`;
- a largura da linha: `LARGURAS`;
- o tamanho das fotos: `RAIOS_FOTO`;
- o holofote: `HOLOFOTE_RAIO` e `HOLOFOTE_ALCANCE`;
- o quanto o resto esmaece com uma rua destacada: `ESMAECIDA`.

## Onde ficam as avaliações

As avaliações ficam na tabela `avaliacoes` do banco da coleta
(`data/processed/streetview.db`), uma linha por quadrado:

| Coluna | Conteúdo |
|---|---|
| `ponto_id`, `posicao`, `quadrado` | a zona, a vista e o quadrado (1 a 3), o mesmo que `<zona>_<posicao>_<quadrado>.jpg` |
| `classe` | `adequada`, `parcialmente_adequada`, `inadequada`, `sem_calcada` ou `nao_identificavel` |
| `origem`, `autor` | `manual` e quem avaliou, ou `modelo` e o nome do modelo |
| `confianca` | probabilidade da classe, quando vem de um modelo |
| `quando` | quando foi avaliado (UTC, com milissegundos); reavaliar regrava, e a avaliação volta a contar como nova para a exportação |

As classes seguem a ordem dos rótulos do classificador em
[linear_probe.py](../modelagem/linear_probe.py): o índice da classe em
`banco.CLASSES_AVALIACAO` é o rótulo numérico do modelo
(`parcialmente_adequada`, que veio depois, é a 4, a última; o
[extract_features.py](../transformacao/extract_features.py) ainda não a lê).
Para o mapa mostrar as previsões de um modelo, grave-as na tabela
`avaliacoes`, com `origem` = `modelo`, o nome do modelo em `autor` e a
probabilidade em `confianca`, pela
`scripts.ingestao.coleta_streetview.banco.registrar_avaliacao(conn, zona, posicao, quadrado, classe, origem="modelo", autor="<modelo>", confianca=p)`.

Uma avaliação à mão grava por cima da que estiver no quadrado.

Se a coleta trocar a vista escolhida de uma zona, as avaliações da vista
antiga continuam guardadas, mas deixam de colorir o mapa.

## Estrutura

| Arquivo | Responsabilidade |
|---|---|
| [mapa.py](mapa.py) | O traçado de cada rua, com um vértice a cada 5 m, e a vista escolhida de cada zona aprovada |
| [servidor.py](servidor.py) | Servidor HTTP do coletor (biblioteca padrão): a página, a API JSON do banco (rotas na docstring do módulo), a coleta em subprocesso e os logs |
| [janela.py](janela.py) | A janela do coletor: o link do mapa e as abas "Fotos coletadas" e "Últimas coletas" (a que está rodando primeiro; o log inteiro fica em `data/processed/coletas/`) |
| [andamento.py](andamento.py) | Os cartões da aba "Últimas coletas": lê o log de cada coleta (as etapas, os contadores e o resultado) e o mostra sem linguagem de código |
| [galeria.py](galeria.py) | A aba "Fotos coletadas": as ruas com fotos, todas as vistas baixadas de uma rua e a grade com rolagem |
| [exe/](exe/) | O `.exe`: o ponto de entrada ([calcadas.py](exe/calcadas.py)), a receita do PyInstaller ([calcadas.spec](exe/calcadas.spec)) e as imagens da janela: o mapa de Curitiba do fundo e o ícone, gerados por [arte.py](exe/arte.py) |
| [static/](static/) | A página |

Os arquivos de [static/](static/):

- [index.html](static/index.html): a página, com os ícones Lucide em SVG.
- [dados.js](static/dados.js): lê e grava no banco, pela API do servidor.
- [app.js](static/app.js): o mapa (Leaflet 1.9.4) e a exportação (JSZip
  3.10.1).
- [estilo.css](static/estilo.css): tokens de cor para tema claro e escuro,
  em cinzas neutros tirados do mapa de fundo, e as fontes Fira Sans e Fira
  Code.

## Limitações

- **Os dois lados se misturam.** A rua tem uma cor só em cada altura, e ela
  mistura as fotos dos dois lados.
- **Ruas com pista dupla** (ex.: Av. Sete de Setembro) aparecem como duas
  linhas no OSM, e cada uma pesa mais as fotos do lado dela.
- **Estimativa longe das fotos.** Num trecho sem foto avaliada, a cor é
  estimada pelas fotos mais próximas, mesmo a centenas de metros. O mapa não
  mostra essa diferença: o progresso de cada rua, na lista, diz quanto dela
  já foi coletado e avaliado.
- **Cada computador tem o seu banco.** As coletas e as avaliações de uma
  pessoa ficam só no computador dela; juntar as de todos não é automático.
