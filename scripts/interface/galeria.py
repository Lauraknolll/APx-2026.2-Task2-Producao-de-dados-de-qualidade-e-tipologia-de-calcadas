"""
As fotos coletadas, na janela do .exe (janela.py): todas as vistas que a
coleta baixou de cada rua, inteiras — o close de onde saem os 3 quadrados —,
com o lugar de onde cada uma foi tirada (o panorama do Street View).

ruas_com_fotos() e fotos_da_rua() leem o banco da coleta; Galeria mostra as
fotos de uma rua numa grade com rolagem. As miniaturas são feitas aos poucos,
só as que aparecem na tela (uma rua pode ter centenas de fotos).
"""

import os
import sqlite3
import tkinter as tk
import unicodedata
import webbrowser

from PIL import Image, ImageDraw, ImageTk

from scripts.ingestao.coleta_streetview.config import RAIZ

LARGURA_MIN = 320   # px: a menor miniatura; a grade põe quantas colunas couberem
ESPACO = 16         # px entre as fotos
LOTE = 3            # miniaturas feitas por vez (o resto, na próxima volta do Tk)


def normalizar(texto: str) -> str:
    """Sem acento e minúsculo, como o normalizar() da página (app.js)."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def ruas_com_fotos(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """(rua, quantas fotos) das ruas com alguma vista baixada, em ordem alfabética."""
    linhas = conn.execute("""
        SELECT pr.rua, COUNT(*) FROM pontos_rua pr JOIN tentativas t ON t.ponto_id = pr.ponto_id
        WHERE t.arquivo IS NOT NULL GROUP BY pr.rua""").fetchall()
    return sorted(linhas, key=lambda linha: normalizar(linha[0]))


def situacao(foto: dict) -> tuple[str, str]:
    """(texto, cor) do que a coleta fez com a vista."""
    if foto["status"] == "aprovada" and foto["tentativa"] == foto["posicao"]:
        quadrados = (foto["quadrados"] or "").replace(",", ", ")
        return f"Escolhida para a zona · quadrados {quadrados}" if quadrados else "Escolhida para a zona", "ok"
    if foto["posicao"] >= 1000:
        return "Recusada pela IA", "perigo"
    if foto["rejeicao"]:
        return f"Recusada: {foto['rejeicao']}", "perigo"
    if foto["status"] == "aprovada":
        return "Não escolhida (a zona usa outra vista)", "suave"
    return "Ainda não conferida", "suave"


def fotos_da_rua(conn: sqlite3.Connection, rua: str) -> list[dict]:
    """Todas as vistas baixadas das zonas da rua, na ordem da coleta (zona e vista)."""
    campos = ("ponto_id", "posicao", "arquivo", "lat", "lon", "data", "distancia", "rejeicao",
              "status", "tentativa", "quadrados")
    linhas = conn.execute("""
        SELECT t.ponto_id, t.posicao, t.arquivo, t.pano_lat, t.pano_lon, t.data, t.distancia, t.rejeicao,
               p.status, p.tentativa, p.quadrados
        FROM pontos_rua pr JOIN pontos p ON p.id = pr.ponto_id JOIN tentativas t ON t.ponto_id = p.id
        WHERE pr.rua = ? AND t.arquivo IS NOT NULL
        ORDER BY p.id, t.posicao""", (rua,)).fetchall()
    return [dict(zip(campos, linha)) for linha in linhas]


class Galeria:
    """A grade de fotos de uma rua: um Canvas com rolagem (e a barra fina da
    janela), a foto com cantos arredondados e, embaixo, a zona, a situação e
    as coordenadas. Clicar na foto a abre inteira; nas coordenadas, abre o
    lugar no Google Maps."""

    def __init__(self, pai: tk.Widget, janela):
        self.j = janela  # as cores (c), as fontes (f) e a escala (px) da janela
        self.tela = tk.Canvas(pai, highlightthickness=0, borderwidth=0, yscrollincrement=janela.px(24))
        self.barra = tk.Canvas(pai, highlightthickness=0, borderwidth=0, width=janela.px(8))
        self.fotos: list[dict] = []
        self.vazio = ("", "")
        self.cartoes = []       # (caixa da foto, foto), na ordem da grade
        self.miniaturas = {}    # (arquivo, largura, tema): PhotoImage
        self.fila = []
        self.rolagem = (0.0, 1.0)
        self.medida = None
        self.ao_topo = False
        self._carregando = None
        self.tela.configure(yscrollcommand=self._rolou)
        self.tela.bind("<Configure>", lambda _: self.organizar())
        self.tela.bind("<MouseWheel>", self._roda)
        self.barra.bind("<Button-1>", self._arrastar)
        self.barra.bind("<B1-Motion>", self._arrastar)

    def aplicar_tema(self):
        c = self.j.c
        self.tela.configure(background=c["superficie"])
        self.barra.configure(background=c["superficie"])
        self.miniaturas.clear()  # o canto arredondado leva a cor do fundo
        self.medida = None
        self.organizar()

    def mostrar(self, fotos: list[dict], vazio: tuple[str, str] = ("", "")):
        """Troca as fotos; sem fotos, `vazio` (título, explicação) no meio."""
        mesma_rua = fotos and self.fotos and fotos[0]["ponto_id"] == self.fotos[0]["ponto_id"]
        self.fotos, self.vazio, self.medida = fotos, vazio, None
        self.ao_topo = self.ao_topo or not mesma_rua  # outra rua começa do topo; a mesma (fotos novas) fica onde está
        self.organizar()

    # Grade ----------------------------------------------------------------- #

    def organizar(self):
        j, c, p = self.j, self.j.c, self.j.px
        w, h = self.tela.winfo_width(), self.tela.winfo_height()
        if w < 2:
            return
        if self.medida == (w, len(self.fotos), j.tema):
            return
        self.medida = (w, len(self.fotos), j.tema)
        t = self.tela
        t.delete("all")
        self.cartoes, self.fila = [], []
        if not self.fotos:
            titulo, explicacao = self.vazio
            t.create_text(w / 2, max(p(60), h / 2 - p(14)), text=titulo, font=j.f["corpo"], fill=c["texto"],
                          anchor="center")
            t.create_text(w / 2, max(p(60), h / 2 - p(14)) + p(24), text=explicacao, font=j.f["ajuda"],
                          fill=c["suave"], anchor="center", width=w - p(40), justify="center")
            t.configure(scrollregion=(0, 0, w, h))
            return

        espaco = p(ESPACO)
        colunas = max(1, (w + espaco) // (p(LARGURA_MIN) + espaco))
        largura = (w - espaco * (colunas - 1)) // colunas
        altura_foto = largura // 3  # o close tem 3 quadrados lado a lado
        linha = j.f["pequena"].metrics("linespace")
        altura = altura_foto + p(10) + j.f["rua"].metrics("linespace") + 2 * linha + p(4) + espaco
        for i, foto in enumerate(self.fotos):
            x = (i % colunas) * (largura + espaco)
            y = (i // colunas) * altura
            caixa = (x, y, x + largura, y + altura_foto)
            self.cartoes.append((caixa, foto))
            caminho = RAIZ / foto["arquivo"]
            fundo = t.create_rectangle(*caixa, fill=c["superficie_2"], outline="", tags=("foto", f"f{i}"))
            if not caminho.is_file():
                t.create_text((caixa[0] + caixa[2]) / 2, (caixa[1] + caixa[3]) / 2, text="Arquivo não encontrado",
                              font=j.f["pequena"], fill=c["suave"])
            else:
                self._clicavel(fundo, lambda _, cm=caminho: os.startfile(cm))
            ty = y + altura_foto + p(10)
            t.create_text(x, ty, text=f"Zona {foto['ponto_id']} · vista {foto['posicao']}", font=j.f["rua"],
                          fill=c["texto"], anchor="nw")
            ty += j.f["rua"].metrics("linespace")
            texto, cor = situacao(foto)
            t.create_text(x, ty, text=j._encurtar(texto, j.f["pequena"], largura), font=j.f["pequena"],
                          fill=c[cor], anchor="nw")
            ty += linha
            coordenadas = f"{foto['lat']:.6f}, {foto['lon']:.6f}"
            item = t.create_text(x, ty, text=coordenadas, font=j.f["log"], fill=c["texto"], anchor="nw")
            self._clicavel(item, lambda _, f=foto: webbrowser.open(
                f"https://www.google.com/maps/search/?api=1&query={f['lat']:.6f},{f['lon']:.6f}"))
            extras = [f"capturada em {foto['data']}" if foto["data"] else None,
                      f"a {foto['distancia']:.0f} m da calçada" if foto["distancia"] is not None else None]
            extras = " · ".join(e for e in extras if e)
            if extras:
                t.create_text(x + j.f["log"].measure(coordenadas) + p(8), ty + p(1), text="· " + extras,
                              font=j.f["pequena"], fill=c["suave"], anchor="nw")
        total = ((len(self.fotos) - 1) // colunas + 1) * altura - espaco
        t.configure(scrollregion=(0, 0, w, max(total, h)))
        if self.ao_topo:  # depois do scrollregion: antes, o Tk ainda mede a rolagem pela grade antiga
            t.yview_moveto(0)
            self.ao_topo = False
        self._pedir_visiveis()

    def _clicavel(self, item, acao):
        t = self.tela
        t.tag_bind(item, "<Button-1>", acao)
        t.tag_bind(item, "<Enter>", lambda _: t.configure(cursor="hand2"))
        t.tag_bind(item, "<Leave>", lambda _: t.configure(cursor=""))

    # Miniaturas, só as da tela -------------------------------------------- #

    def _pedir_visiveis(self):
        if not self.cartoes:
            return
        topo = self.tela.canvasy(0)
        fim = topo + self.tela.winfo_height()
        margem = self.tela.winfo_height() / 2  # e um pouco além, para a rolagem não mostrar o vazio
        self.fila = [(i, caixa, foto) for i, (caixa, foto) in enumerate(self.cartoes)
                     if caixa[3] >= topo - margem and caixa[1] <= fim + margem
                     and not self.tela.find_withtag(f"m{i}")]
        if self.fila and not self._carregando:
            self._carregando = self.tela.after(1, self._carregar)

    def _carregar(self):
        self._carregando = None
        for i, caixa, foto in self.fila[:LOTE]:
            imagem = self._miniatura(foto["arquivo"], caixa[2] - caixa[0], caixa[3] - caixa[1])
            if imagem:
                item = self.tela.create_image(caixa[0], caixa[1], image=imagem, anchor="nw", tags=("foto", f"m{i}"))
                self._clicavel(item, lambda _, cm=RAIZ / foto["arquivo"]: os.startfile(cm))
        self.fila = self.fila[LOTE:]
        if self.fila:
            self._carregando = self.tela.after(1, self._carregar)

    def _miniatura(self, arquivo: str, largura: int, altura: int):
        chave = (arquivo, largura, self.j.tema)
        if chave not in self.miniaturas:
            try:
                with Image.open(RAIZ / arquivo) as img:
                    img.draft("RGB", (largura * 2, altura * 2))  # o JPEG já decodifica reduzido: bem mais rápido
                    img = img.convert("RGB").resize((largura, altura), Image.LANCZOS)
            except OSError:
                return None
            s = 3  # cantos arredondados sem serrilhado, na cor do painel
            mascara = Image.new("L", (largura * s, altura * s), 0)
            ImageDraw.Draw(mascara).rounded_rectangle((0, 0, largura * s - 1, altura * s - 1), self.j.px(6) * s, fill=255)
            fundo = Image.new("RGB", (largura, altura), self.j.c["superficie"])
            fundo.paste(img, (0, 0), mascara.resize((largura, altura), Image.BOX))
            self.miniaturas[chave] = ImageTk.PhotoImage(fundo)
        return self.miniaturas[chave]

    # Rolagem ---------------------------------------------------------------- #

    def _roda(self, evento):
        self.tela.yview_scroll(-round(evento.delta / 120) * 2, "units")

    def _rolou(self, primeiro, ultimo):
        self.rolagem = (float(primeiro), float(ultimo))
        self.j.desenhar_barra(self.barra, self.rolagem)
        self._pedir_visiveis()

    def _arrastar(self, evento):
        primeiro, ultimo = self.rolagem
        self.tela.yview_moveto(evento.y / max(1, self.barra.winfo_height()) - (ultimo - primeiro) / 2)
