# Coletor de calçadas: guia de uso

O coletor é um programa para Windows que tira fotos das calçadas de Curitiba
no Google Street View. Para cada rua, ele escolhe as melhores fotos de cada
trecho e mostra num mapa a qualidade das calçadas.

Você não precisa saber programar nem instalar nada. Tudo o que você coleta
fica no seu computador.

Este guia é para quem recebeu o programa (`Calcadas.zip`). A parte técnica
fica no [README da interface](../scripts/interface/README.md).

## Antes de começar

- **Windows 10 ou 11, 64 bits.**
- **Internet**, durante a coleta. As fotos vêm do Google Street View.
- **Espaço no disco:** o programa ocupa ~700 MB. As fotos ocupam ~4 MB por
  trecho de rua, então uma rua com 270 trechos passa de 1 GB.

## Abrir pela primeira vez

1. **Descompacte** o `Calcadas.zip` numa pasta comum, como Documentos ou a
   Área de Trabalho. Clique com o botão direito no arquivo e escolha
   *Extrair tudo*. Não abra o programa de dentro do zip, nem coloque a pasta
   em "Arquivos de Programas".
2. **Abra o `Calcadas.exe`**, dentro da pasta `Calcadas`. A pasta
   `_internal`, ao lado dele, precisa ficar onde está.
3. **Se o Windows avisar "O Windows protegeu o computador"**, clique em
   *Mais informações* e depois em *Executar assim mesmo*. O aviso aparece
   porque o programa não tem assinatura digital. Se o antivírus reclamar, é
   pelo mesmo motivo.

## A janela

No topo fica o **link do mapa**. Clique em *Abrir o mapa* para abrir o mapa
no navegador. É nele que se coleta e avalia. **Deixe a janela aberta**
enquanto usa o mapa: fechar a janela desliga o mapa.

O selo no canto superior direito diz o que o programa está fazendo, como
*Pronto para coletar* ou *Coletando · Rua X*.

Embaixo, há duas abas:

- **Fotos coletadas:** escolha uma rua no campo de busca para ver todas as
  fotos que o programa baixou dela.
- **Últimas coletas:** o andamento de cada coleta, explicado abaixo.

## Coletar uma rua

No mapa (pelo link da janela), abra a seção **Coletar uma rua**, na barra da
esquerda:

1. **Nome da rua:** digite o nome com o tipo da via na frente, por exemplo
   *Rua Comendador Araújo* ou *Av. Sete de Setembro*. Acentos e abreviações
   não importam.
2. Clique em **Procurar**. O programa mostra quantos trechos (*zonas*, de
   ~50 m cada) a rua tem e quantos faltam coletar. Se houver mais de uma rua
   com esse nome, ele pede para escolher.
3. **Quantas zonas rodar:** deixe vazio para coletar todas as que faltam, ou
   ponha um número para coletar só uma parte, espalhada pela rua. Para um
   teste rápido, ponha 2 ou 3.
4. Clique em **Coletar**.

A coleta tem três etapas:

1. **Procurando as fotos no Street View:** acha as fotos disponíveis perto
   de cada trecho.
2. **Baixando as fotos.**
3. **Conferindo se há calçada nas fotos:** uma inteligência artificial olha
   cada foto e descarta as que não mostram calçada ou estão tapadas por
   carros e pessoas. **A primeira coleta demora alguns minutos a mais
   nesta etapa**, porque baixa o modelo de IA (~110 MB). Isso acontece uma
   vez só.

Enquanto isso, a aba **Últimas coletas** da janela mostra cada etapa com uma
barra de progresso. As fotos aparecem no mapa ao fim de cada etapa.

- **Parar coleta** interrompe a coleta. Coletar a mesma rua de novo continua
  de onde parou, sem refazer nada.
- Roda uma coleta por vez.
- Fechar a janela durante uma coleta também a interrompe; a janela pergunta
  antes.

### A aba Últimas coletas

Cada coleta aparece com um selo:

| Selo | O que quer dizer |
|---|---|
| **Em andamento** (amarelo) | A coleta está rodando. |
| **Concluída** (verde) | Terminou. Embaixo aparece quantos trechos ficaram com foto boa. |
| **Cancelada** (cinza) | Alguém clicou em *Parar coleta* ou fechou a janela. Coletar a rua de novo continua de onde parou. |
| **Falhou** (vermelho) | Algo deu errado. Embaixo aparece a causa, como "A internet caiu". Na maioria das vezes, coletar a rua de novo resolve. |

*Ver o registro completo* abre o relatório técnico da coleta. Ele ajuda quem
for investigar um erro.

## Ver as fotos de uma rua

Na aba **Fotos coletadas** da janela, procure a rua pelo nome. Aparecem todas
as fotos que o programa baixou dela, na ordem da coleta. Cada foto mostra:

- o trecho (*zona*) e o número da foto (*vista*);
- o que o programa fez com ela:
  - **Escolhida para a zona:** a melhor foto do trecho, e quais dos 3
    pedaços (*quadrados*) dela mostram bem a calçada;
  - **Recusada:** não serviu, e por quê (por exemplo, "pouca_calcada");
  - **Não escolhida:** serviu, mas o trecho usa outra foto melhor;
  - **Ainda não conferida:** a coleta ainda não chegou à etapa 3.
- as **coordenadas** de onde a foto foi tirada, a data em que o Google a
  tirou e a distância até a calçada.

Clique na foto para abri-la inteira. Clique nas coordenadas para ver o lugar
no Google Maps.

## Avaliar as calçadas

No mapa, clique num trecho colorido, num ponto de foto ou numa zona da lista
de ruas. Em **Avaliar**, dê a cada quadrado da foto uma das cinco classes:
*adequada*, *parcialmente adequada*, *inadequada*, *sem calçada* ou *não
identificável*. As teclas `1` a `5` também servem.

A cor da rua no mapa vem dessas avaliações: verde para adequada, amarelo,
laranja e vermelho para sem calçada.

## Exportar para o Roboflow

A seção **Exportar para conferência**, no mapa, baixa um `.zip` com os
quadrados avaliados e as classes deles. Esse zip vai direto para o Roboflow
(*Upload*, arrastar o arquivo).

## Onde ficam os dados

Tudo fica dentro da pasta `Calcadas`, em `data\processed\`: as fotos, o
banco com as coletas e as avaliações, e os relatórios das coletas.

- **Para guardar uma cópia** ou levar para outro computador, copie a pasta
  `Calcadas` inteira.
- **Apagar a pasta apaga tudo** o que você coletou e avaliou.
- Cada pessoa tem os próprios dados, e um computador não vê as coletas do
  outro. Combinem na planilha quem coleta qual rua, para ninguém coletar a
  mesma duas vezes.

## Problemas comuns

| Problema | O que fazer |
|---|---|
| O programa não abre de jeito nenhum. | Confira se a pasta foi descompactada e se a `_internal` está ao lado do `Calcadas.exe`. |
| O mapa diz "Sem resposta do coletor". | A janela do programa foi fechada. Abra o `Calcadas.exe` de novo. |
| "As portas 8000–8010 estão ocupadas." | O programa já está aberto. Procure a janela dele na barra de tarefas. |
| A coleta fica muito tempo em "Preparando…". | Na primeira coleta é normal: o modelo de IA está sendo baixado. Nas outras, confira a internet. |
| Selo **Falhou** com "A internet caiu ou o Google não respondeu". | Espere a conexão voltar e colete a mesma rua de novo: ela continua de onde parou. |
| A busca acha várias ruas com o nome. | Escolha a certa na lista, ou digite mais do nome. |
| A busca diz que a rua "não tem calçadas na camada do IPPUC". | A rua existe, mas o mapa de calçadas da prefeitura não tem calçadas nela. Não há o que coletar. |
