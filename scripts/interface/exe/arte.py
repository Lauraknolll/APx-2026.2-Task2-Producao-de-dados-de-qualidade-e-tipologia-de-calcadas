"""
As imagens da janela do coletor (scripts/interface/janela.py):

- fundo_claro.png e fundo_escuro.png: a malha de calçadas de Curitiba (a
  camada passeio.gpkg da coleta), bem apagada, nas cores da página;
- icone.ico: o ícone do .exe e da janela, o marcador do logo da página.

Geradas uma vez e guardadas no repositório; rode de novo só para mudar o
desenho:

    .venv\\Scripts\\python.exe -m scripts.interface.exe.arte

pino() desenha o marcador; a janela usa no logo.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PASTA = Path(__file__).parent
LARGURA = 1800  # px; a janela mostra o centro e o resto some nas bordas
DESENHO = 2     # desenha maior e reduz: linhas finas sem serrilhado
CORES = 24      # a imagem é quase toda em dois tons: com paleta, o PNG fica pequeno

# (terra, calçada): o --cor-fundo da página e um tom de contraste baixo.
TEMAS = {"claro": ("#e9e9e6", "#cfcfca"), "escuro": ("#222222", "#383838")}


def _bezier(p0, p1, p2, p3, n=24):
    return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * d
                  for a, b, c, d in zip(p0, p1, p2, p3))
            for t in (i / n for i in range(n + 1))]


def pino(tamanho: int, cor: str, fundo: str | None = None, raio: float = 0) -> Image.Image:
    """O marcador do logo da página (Lucide map-pin, traço 2 numa grade de 24)
    em `tamanho` px, sem serrilhado; com `fundo`, num quadrado de cantos `raio`."""
    s = 8  # supersample
    img = Image.new("RGBA", (tamanho * s, tamanho * s), (0, 0, 0, 0))
    tinta = ImageDraw.Draw(img)
    if fundo:
        tinta.rounded_rectangle((0, 0, img.width - 1, img.height - 1), raio * s, fill=fundo)
    # O desenho ocupa o miolo da grade de 24 (com margem, como na página: 18 px num quadrado de 36).
    margem = tamanho * (0.25 if fundo else 0.04)
    k = (tamanho - 2 * margem) * s / 24
    ponto = lambda x, y: (margem * s + x * k, margem * s + y * k)
    import math
    arco = [ponto(12 + 8 * math.cos(math.radians(a)), 10 - 8 * math.sin(math.radians(a))) for a in range(0, 181, 4)]
    direita = _bezier((12.6, 21.8), (14.46, 20.19), (20, 14.99), (20, 10))
    esquerda = _bezier((4, 10), (4, 14.99), (9.54, 20.19), (11.4, 21.8))
    contorno = [ponto(*p) for p in direita] + arco + [ponto(*p) for p in esquerda]
    tinta.line(contorno + contorno[:2], fill=cor, width=round(2 * k), joint="curve")
    cx, cy = ponto(12, 10)
    r = 3 * k
    tinta.ellipse((cx - r, cy - r, cx + r, cy + r), outline=cor, width=round(2 * k))
    return img.resize((tamanho, tamanho), Image.LANCZOS)


def fundo(aneis, terra: str, calcada: str) -> Image.Image:
    xs = [x for anel in aneis for x, _ in anel]
    ys = [y for anel in aneis for _, y in anel]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    escala = LARGURA * DESENHO / (xmax - xmin)
    tamanho = (LARGURA * DESENHO, round((ymax - ymin) * escala))
    img = Image.new("RGB", tamanho, terra)
    tinta = ImageDraw.Draw(img)
    for anel in aneis:  # coordenadas UTM: y cresce para o norte
        tinta.polygon([((x - xmin) * escala, (ymax - y) * escala) for x, y in anel], fill=calcada)
    img = img.resize((LARGURA, round(tamanho[1] / DESENHO)), Image.LANCZOS)

    # Some nas bordas: a cidade não tem forma de janela.
    mascara = Image.new("L", img.size, 0)
    margem = LARGURA // 9
    ImageDraw.Draw(mascara).rectangle((margem, margem, img.width - margem, img.height - margem), fill=255)
    mascara = mascara.filter(ImageFilter.GaussianBlur(margem / 2))
    return Image.composite(img, Image.new("RGB", img.size, terra), mascara)


def main():
    from scripts.ingestao.coleta_streetview.config import CALCADAS_PATH
    from scripts.ingestao.coleta_streetview.geometria import ler_calcadas

    aneis = [anel for p in ler_calcadas(CALCADAS_PATH) for anel in p["aneis"] if len(anel) > 2]
    print(f"{len(aneis)} polígonos")
    for tema, (terra, calcada) in TEMAS.items():
        caminho = PASTA / f"fundo_{tema}.png"
        fundo(aneis, terra, calcada).quantize(CORES).save(caminho, optimize=True)
        print(f"{caminho.name}: {caminho.stat().st_size / 1e6:.1f} MB")

    # O ícone: o marcador claro no quadrado escuro (o botão principal da página).
    tamanhos = [16, 24, 32, 48, 64, 128, 256]
    imagens = [pino(t, "#fafafa", "#2b2b2b", raio=t * 0.22) for t in tamanhos]
    imagens[-1].save(PASTA / "icone.ico", sizes=[(t, t) for t in tamanhos], append_images=imagens[:-1])
    print("icone.ico")


if __name__ == "__main__":
    main()
