"""
Interface da coleta: um mapa de Curitiba com as ruas coloridas pela
qualidade da calçada, e o coletor (.exe) que o abre. Rode da raiz do
repositório com `python -m scripts.interface.janela` (a janela do coletor)
ou `python -m scripts.interface` (só o mapa, no navegador).

A cor de cada ponto da rua é a média das avaliações das fotos em volta,
num gradiente: de longe, a cor geral da rua; de perto, a de cada altura. Na
página dá para avaliar as fotos à mão, exportar as avaliações para o
Roboflow e disparar a coleta de uma rua nova. Tudo fica neste computador,
no banco da coleta (data/processed/streetview.db).

Módulos:
    mapa          traçado de cada rua e a vista escolhida de cada zona
    servidor      servidor HTTP do coletor (biblioteca padrão): a página, a coleta e a API JSON
    janela        a janela do coletor: o link do mapa, as fotos coletadas e as últimas coletas
    galeria       a aba "Fotos coletadas": todas as vistas baixadas de uma rua
    andamento     a aba "Últimas coletas": cada coleta em linguagem simples
    exe/          o ponto de entrada, a receita do PyInstaller e as imagens do .exe
    static/       a página (Leaflet)
"""
