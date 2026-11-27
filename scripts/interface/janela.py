"""
A janela do .exe (scripts/interface/exe/), 100% local: nada vai para a
internet além da própria coleta do Street View, e tudo fica no banco e nas
pastas de data/processed/.

- No topo, o link do mapa: o servidor desta máquina, com a página de sempre
  (mapa, avaliação, exportação e a coleta de ruas), lendo só o banco local.
- Embaixo, duas abas:
  - Fotos coletadas: escolha uma rua e veja todas as vistas que a coleta
    baixou dela, inteiras, com as coordenadas de onde foram tiradas
    (galeria.py);
  - Últimas coletas: as coletas mais recentes, a que estiver rodando
    primeiro, cada uma com a situação, a barra de cada etapa e o resultado,
    sem linguagem de código (andamento.py); o log inteiro fica em
    data/processed/coletas/.

    python -m scripts.interface.janela   (o .exe roda isto)

O visual é o da página: a mesma paleta, clara ou escura conforme o tema do
Windows, e os painéis sobre um mapa de Curitiba bem apagado (a malha de
calçadas, em exe/fundo_*.png; ver exe/arte.py). Os painéis e os botões são
desenhados com o Pillow, para terem cantos arredondados e sombra como na
página; os textos, o campo de busca, a galeria e os logs ficam no Tk por cima.

Fechar a janela desliga o servidor; com uma coleta rodando, ela é
interrompida (rodar a mesma rua de novo continua de onde parou).
"""

import os
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageTk

from .andamento import ListaDeColetas, da_coleta_rodando, do_arquivo
from .exe.arte import pino
from .galeria import Galeria, fotos_da_rua, normalizar, ruas_com_fotos
from .servidor import COLETA, LOGS, conectar, iniciar

PORTAS = range(8000, 8011)  # a primeira livre
MOSTRAR = 5                 # coletas na aba de logs
ATUALIZAR_MS = 1000
RELER_S = 5                 # durante uma coleta, de quanto em quanto tempo as fotos novas aparecem
LISTA_MAX = 8               # ruas visíveis na lista do campo de busca (o resto, rolando)
TITULO = "Calçadas de Curitiba"
AJUDA = ("Pelo link: o mapa, as avaliações e a seção “Coletar uma rua”. "
         "Tudo fica só neste computador, em data/processed/.")
PROCURAR = "Procurar uma rua"
ABAS = (("fotos", "Fotos coletadas"), ("logs", "Últimas coletas"))
ARTE = Path(__file__).parent / "exe"

# Os tokens de scripts/interface/static/estilo.css, mais as cores da escala
# das calçadas para a situação de cada coleta e de cada foto.
TEMAS = {
    "claro": dict(fundo="#e9e9e6", superficie="#f7f7f5", superficie_2="#ececea", texto="#1f1f1f",
                  suave="#575757", borda="#dcdcd8", borda_forte="#c4c4bf", primaria="#2b2b2b",
                  primaria_hover="#404040", sobre_primaria="#fafafa", primaria_suave="#ffffff",
                  primaria_texto="#141414", ok="#1a7f3c", aviso="#9a6700", perigo="#b42318", sombra=0.12),
    "escuro": dict(fundo="#222222", superficie="#2a2a2a", superficie_2="#353535", texto="#ededed",
                   suave="#ababab", borda="#3a3a3a", borda_forte="#4c4c4c", primaria="#e6e6e6",
                   primaria_hover="#ffffff", sobre_primaria="#1f1f1f", primaria_suave="#444444",
                   primaria_texto="#fafafa", ok="#5cc98a", aviso="#e8b81e", perigo="#f28b82", sombra=0.45),
}


def tema_do_sistema() -> str:
    """claro | escuro, como o Windows está para os apps (o prefers-color-scheme da página)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as chave:
            return "claro" if winreg.QueryValueEx(chave, "AppsUseLightTheme")[0] else "escuro"
    except (ImportError, OSError):
        return "claro"


def coletas() -> list[dict]:
    """As MOSTRAR últimas coletas, da mais nova à mais velha (a que estiver
    rodando primeiro), já resumidas para os cartões (andamento.py)."""
    lista = [da_coleta_rodando(COLETA)] if COLETA.rodando else []
    arquivos = sorted(LOGS.glob("*.log"), reverse=True) if LOGS.is_dir() else []
    for arquivo in arquivos[:MOSTRAR - len(lista)]:
        try:
            lista.append(do_arquivo(arquivo))
        except OSError:  # apagado enquanto a lista era lida
            pass
    return lista


class Janela:
    def __init__(self, raiz: tk.Tk, url: str, servidor):
        self.raiz, self.url, self.servidor = raiz, url, servidor
        self.k = raiz.winfo_fpixels("1i") / 96  # a escala da tela: as medidas abaixo são as da página, em px
        self.fechando = False
        self.foco = None          # o botão sob o mouse
        self.botoes = {}          # nome: (caixa, ação)
        self.copiado = False
        self.aba = "fotos"
        self.ruas: list[tuple[str, int]] = []   # (rua, fotos), para o campo de busca
        self.rua = None                         # a rua escolhida
        self.opcoes: list[str] = []             # as ruas na lista aberta do campo
        self.lida = 0.0                         # quando as fotos foram lidas do banco
        self.coletava = False
        self.fundos = {}          # tema: a imagem do mapa, já na escala da tela
        self.base = None          # os painéis sem os botões (refeitos só ao mudar de tamanho ou de tema)
        self.tamanho = None

        raiz.title(TITULO)
        largura = min(self.px(1040), int(raiz.winfo_screenwidth() * 0.9))
        altura = min(self.px(800), int(raiz.winfo_screenheight() * 0.85))
        raiz.geometry(f"{largura}x{altura}")
        raiz.minsize(self.px(720), self.px(560))
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        try:
            raiz.iconbitmap(default=str(ARTE / "icone.ico"))
        except tk.TclError:
            pass

        familias = set(tkfont.families(raiz))
        sans = next(f for f in ("Fira Sans", "Segoe UI", "TkDefaultFont") if f in familias or f.startswith("Tk"))
        forte = "Segoe UI Semibold" if sans == "Segoe UI" and "Segoe UI Semibold" in familias else sans
        mono = next((f for f in ("Fira Code", "Cascadia Mono", "Consolas") if f in familias), "TkFixedFont")
        fonte = lambda familia, px, *estilo: tkfont.Font(raiz, family=familia, size=-self.px(px),
                                                           weight="bold" if "bold" in estilo else "normal")
        self.f = dict(titulo=fonte(forte, 18, "bold" if forte == sans else ""), sub=fonte(sans, 13),
                      h2=fonte(forte, 11.5, "bold" if forte == sans else ""), corpo=fonte(sans, 14),
                      botao=fonte(forte, 14), ajuda=fonte(sans, 12.5), mono=fonte(mono, 13),
                      rua=fonte(forte, 14), log=fonte(mono, 12), pequena=fonte(sans, 12.5))

        self.tela = tk.Canvas(raiz, highlightthickness=0, borderwidth=0)
        self.tela.pack(fill="both", expand=True)
        self.imagem = self.tela.create_image(0, 0, anchor="nw")

        # Aba "Fotos coletadas": o campo de busca das ruas (com a lista) e a galeria
        self.galeria = Galeria(self.tela, self)
        self.janela_galeria = self.tela.create_window(0, 0, window=self.galeria.tela, anchor="nw")
        self.janela_barra_galeria = self.tela.create_window(0, 0, window=self.galeria.barra, anchor="nw")
        self.busca = tk.Entry(self.tela, relief="flat", borderwidth=0, highlightthickness=0, font=self.f["corpo"])
        self.janela_busca = self.tela.create_window(0, 0, window=self.busca, anchor="w")
        self.lista = tk.Listbox(self.tela, relief="flat", borderwidth=0, highlightthickness=1, activestyle="none",
                                font=self.f["corpo"], exportselection=False, takefocus=0)
        self.janela_lista = self.tela.create_window(0, 0, window=self.lista, anchor="nw", state="hidden")
        self.vazia = True  # o campo mostra o PROCURAR, em cinza
        self.busca.bind("<FocusIn>", self._entrou_na_busca)
        self.busca.bind("<Button-1>", lambda _: self.raiz.after(1, self._abrir_lista), add=True)
        self.busca.bind("<FocusOut>", lambda _: self.raiz.after(150, self._saiu_da_busca))
        self.busca.bind("<KeyRelease>", self._digitou)
        self.busca.bind("<Down>", lambda _: self._mover_na_lista(1))
        self.busca.bind("<Up>", lambda _: self._mover_na_lista(-1))
        self.busca.bind("<Return>", lambda _: self._escolher_da_lista())
        self.busca.bind("<Escape>", lambda _: (self._fechar_lista(), self.tela.focus_set()))
        self.lista.bind("<ButtonRelease-1>", lambda _: self._escolher_da_lista())
        self.lista.bind("<Motion>", self._passou_na_lista)
        self.lista.bind("<MouseWheel>", lambda e: self.lista.yview_scroll(-round(e.delta / 120), "units"))

        # Aba "Últimas coletas"
        self.lista_coletas = ListaDeColetas(self.tela, self)
        self.janela_logs = self.tela.create_window(0, 0, window=self.lista_coletas.tela, anchor="nw")
        self.janela_barra = self.tela.create_window(0, 0, window=self.lista_coletas.barra, anchor="nw")

        self.tela.bind("<Configure>", lambda _: self._agendar())
        self.tela.bind("<Motion>", self._mouse)
        self.tela.bind("<Leave>", lambda _: self._focar(None))
        self.tela.bind("<Button-1>", self._clique)
        self._agendado = None

        self.tema = None
        self._aplicar_tema(tema_do_sistema())
        self._mostrar_placeholder()
        self.reler()
        self.atualizar()

    def px(self, valor: float) -> int:
        return round(valor * self.k)

    # Tema ------------------------------------------------------------------- #

    def _aplicar_tema(self, tema: str):
        self.tema, self.c = tema, TEMAS[tema]
        c = self.c
        self.tela.configure(background=c["fundo"])
        self.lista_coletas.aplicar_tema()
        self.busca.configure(background=c["superficie_2"], foreground=c["suave"] if self.vazia else c["texto"],
                             insertbackground=c["texto"], selectbackground=c["borda_forte"],
                             selectforeground=c["texto"])
        self.lista.configure(background=c["superficie"], foreground=c["texto"], selectbackground=c["superficie_2"],
                             selectforeground=c["texto"], highlightbackground=c["borda_forte"],
                             highlightcolor=c["borda_forte"])
        self.galeria.aplicar_tema()
        _barra_de_titulo(self.raiz, escura=tema == "escuro")
        self.base = None
        self._agendar()

    def _fundo(self) -> Image.Image:
        if self.tema not in self.fundos:
            try:
                img = Image.open(ARTE / f"fundo_{self.tema}.png").convert("RGB")
                if self.k != 1:
                    img = img.resize((self.px(img.width), self.px(img.height)), Image.LANCZOS)
            except OSError:
                img = Image.new("RGB", (1, 1), self.c["fundo"])
            self.fundos[self.tema] = img
        return self.fundos[self.tema]

    # Desenho ---------------------------------------------------------------- #

    def _agendar(self):
        # Ao arrastar a borda, a janela muda de tamanho dezenas de vezes: redesenha uma vez só.
        if self._agendado:
            self.raiz.after_cancel(self._agendado)
        self._agendado = self.raiz.after(30, self.desenhar)

    def _layout(self, w: int, h: int) -> dict:
        p, m = self.px, self.px(24)
        topo = m + p(40) + p(20)
        ajuda = self._linhas_de(AJUDA, self.f["ajuda"], w - 2 * m - p(40)) * self.f["ajuda"].metrics("linespace")
        mapa = (m, topo, w - m, topo + p(46 + 40 + 12 + 20) + ajuda)
        painel = (m, mapa[3] + p(16), w - m, h - m)
        abrir_w = self.f["botao"].measure("Abrir o mapa  ↗") + p(32)
        botoes_y = mapa[1] + p(46)
        abrir = (mapa[2] - p(20) - abrir_w, botoes_y, mapa[2] - p(20), botoes_y + p(40))
        campo = (mapa[0] + p(20), botoes_y, abrir[0] - p(8), botoes_y + p(40))
        copiar_w = self.f["pequena"].measure("Copiado") + p(24)
        copiar = (campo[2] - p(4) - copiar_w, campo[1] + p(4), campo[2] - p(4), campo[3] - p(4))

        # As abas: o controle segmentado da página, no topo do painel
        x0, y0, x1, y1 = painel
        abas, x = {}, x0 + p(20)
        for nome, rotulo in ABAS:
            largura = self.f["botao"].measure(rotulo) + p(32)
            abas[nome] = (x + p(4), y0 + p(18), x + p(4) + largura, y0 + p(50))
            x += largura + p(4)
        segmentado = (x0 + p(20), y0 + p(14), x + p(4), y0 + p(54))
        pasta_w = self.f["pequena"].measure("Abrir a pasta") + p(20)
        pasta = (x1 - p(12) - pasta_w, y0 + p(20), x1 - p(12), y0 + p(48))
        divisa = y0 + p(68)

        busca = (x0 + p(20), divisa + p(16), x0 + p(20) + min(p(440), x1 - x0 - p(40)), divisa + p(56))
        seta = (busca[2] - p(36), busca[1] + p(4), busca[2] - p(4), busca[3] - p(4))
        return dict(m=m, mapa=mapa, painel=painel, abrir=abrir, campo=campo, copiar=copiar, abas=abas,
                    segmentado=segmentado, pasta=pasta, divisa=divisa, busca=busca, seta=seta,
                    galeria=(x0 + p(20), busca[3] + p(16), x1 - p(28), y1 - p(14)),
                    texto=(x0 + p(20), divisa + p(16), x1 - p(28), y1 - p(14)))

    def _estado(self) -> tuple[str, str]:
        """(texto, situação) da pílula no canto: o que o coletor está fazendo."""
        if self.fechando:
            return "Fechando: parando a coleta…", "aviso"
        if COLETA.rodando:
            return f"Coletando · {COLETA.rua}", "aviso"
        return "Pronto para coletar", "ok"

    def desenhar(self):
        self._agendado = None
        w, h = self.tela.winfo_width(), self.tela.winfo_height()
        if w < 2 or h < 2:
            return
        c, p = self.c, self.px
        self.l = l = self._layout(w, h)
        estado = self._estado()
        if self.base is None or self.tamanho != (w, h, estado):
            self.base = self._compor_base(w, h, estado)
            self.tamanho = (w, h, estado)
        self._compor_botoes()

        t = self.tela
        t.delete("ui")
        m = l["m"]
        texto = lambda x, y, s, fonte, cor, **kw: t.create_text(x, y, text=s, font=self.f[fonte], fill=c[cor],
                                                               anchor=kw.pop("anchor", "nw"), tags="ui", **kw)
        centro = lambda caixa: ((caixa[0] + caixa[2]) / 2, (caixa[1] + caixa[3]) / 2)
        texto(m + p(52), m + p(1), TITULO, "titulo", "texto")
        texto(m + p(52), m + p(24), "Coletor de fotos do Street View", "sub", "suave")
        texto(self.pilula[0] + p(28), m + p(20), estado[0], "pequena", "texto", anchor="w")

        # O link do mapa
        x0, y0, x1, y1 = l["mapa"]
        texto(x0 + p(20), y0 + p(18), "MAPA DAS CALÇADAS", "h2", "suave")
        cx0, cy0, cx1, cy1 = l["campo"]
        url = self._encurtar(self.url, self.f["mono"], l["copiar"][0] - cx0 - p(24))
        texto(cx0 + p(12), (cy0 + cy1) / 2, url, "mono", "texto", anchor="w")
        texto(*centro(l["copiar"]), "Copiado" if self.copiado else "Copiar", "pequena", "suave", anchor="center")
        texto(*centro(l["abrir"]), "Abrir o mapa  ↗", "botao", "sobre_primaria", anchor="center")
        texto(x0 + p(20), cy1 + p(12), AJUDA, "ajuda", "suave", width=x1 - x0 - p(40))

        # O painel das abas
        x0, y0, x1, y1 = l["painel"]
        for nome, rotulo in ABAS:
            ativa = nome == self.aba or self.foco == f"aba_{nome}"
            texto(*centro(l["abas"][nome]), rotulo, "botao", "texto" if ativa else "suave", anchor="center")
        if self.aba == "logs" and LOGS.is_dir():
            texto(*centro(l["pasta"]), "Abrir a pasta", "pequena", "suave", anchor="center")
        t.create_line(x0 + p(1), l["divisa"], x1 - p(1), l["divisa"], fill=c["borda"], tags="ui")

        fotos = self.aba == "fotos"
        for item in (self.janela_galeria, self.janela_barra_galeria, self.janela_busca):
            t.itemconfigure(item, state="normal" if fotos else "hidden")
        for item in (self.janela_logs, self.janela_barra):
            t.itemconfigure(item, state="hidden" if fotos else "normal")
        if fotos:
            b = l["busca"]
            t.coords(self.janela_busca, b[0] + p(36), (b[1] + b[3]) / 2)
            t.itemconfigure(self.janela_busca, width=max(1, b[2] - b[0] - p(76)))
            resumo = self._resumo()
            if resumo:
                texto(b[2] + p(16), (b[1] + b[3]) / 2, self._encurtar(resumo, self.f["pequena"], x1 - b[2] - p(36)),
                      "pequena", "suave", anchor="w")
            gx0, gy0, gx1, gy1 = l["galeria"]
            t.coords(self.janela_galeria, gx0, gy0)
            t.itemconfigure(self.janela_galeria, width=max(1, gx1 - gx0), height=max(1, gy1 - gy0))
            t.coords(self.janela_barra_galeria, x1 - p(16), gy0)
            t.itemconfigure(self.janela_barra_galeria, height=max(1, gy1 - gy0))
            if t.itemcget(self.janela_lista, "state") == "normal":
                self._posicionar_lista()
        else:
            self._fechar_lista()
            tx0, ty0, tx1, ty1 = l["texto"]
            t.coords(self.janela_logs, tx0, ty0)
            t.itemconfigure(self.janela_logs, width=max(1, tx1 - tx0), height=max(1, ty1 - ty0))
            t.coords(self.janela_barra, x1 - p(16), ty0)
            t.itemconfigure(self.janela_barra, height=max(1, ty1 - ty0))
            self.desenhar_barra(self.lista_coletas.barra, self.lista_coletas.rolagem)

    @staticmethod
    def _linhas_de(texto: str, fonte: tkfont.Font, largura: int) -> int:
        """Em quantas linhas o texto quebra nessa largura (como o create_text com width)."""
        linhas, atual = 1, ""
        for palavra in texto.split():
            tentativa = f"{atual} {palavra}".strip()
            if atual and fonte.measure(tentativa) > largura:
                linhas, atual = linhas + 1, palavra
            else:
                atual = tentativa
        return linhas

    @staticmethod
    def _encurtar(texto: str, fonte: tkfont.Font, largura: int) -> str:
        if fonte.measure(texto) <= largura:
            return texto
        while texto and fonte.measure(texto + "…") > largura:
            texto = texto[:-1]
        return texto + "…"

    def _caixa(self, img: Image.Image, caixa, raio: float, cor: str, borda: str | None = None):
        """Um retângulo de cantos arredondados, sem serrilhado (desenhado a 3× e reduzido)."""
        x0, y0, x1, y1 = (round(v) for v in caixa)
        w, h = x1 - x0, y1 - y0
        if w < 1 or h < 1:
            return

        def mascara(recuo: int) -> Image.Image:
            s = 3
            m = Image.new("L", (w * s, h * s), 0)
            ImageDraw.Draw(m).rounded_rectangle((recuo * s, recuo * s, w * s - 1 - recuo * s, h * s - 1 - recuo * s),
                                                max(0, raio - recuo) * s, fill=255)
            return m.resize((w, h), Image.BOX)

        if borda:
            img.paste(ImageColor.getrgb(borda), (x0, y0, x1, y1), mascara(0))
        img.paste(ImageColor.getrgb(cor), (x0, y0, x1, y1), mascara(max(1, self.px(1)) if borda else 0))

    def _icone(self, img: Image.Image, nome: str, cx: float, cy: float, cor: str, aberta: bool = False):
        """A lupa ou a seta do campo de busca (Lucide search / chevron-down, 16 px, traço 2)."""
        tamanho, s = self.px(16), 4
        k = tamanho * s / 24
        traco = Image.new("L", (tamanho * s, tamanho * s), 0)
        tinta = ImageDraw.Draw(traco)
        largura = round(2 * k)
        if nome == "lupa":
            tinta.ellipse((3 * k, 3 * k, 19 * k, 19 * k), outline=255, width=largura)
            tinta.line((16.65 * k, 16.65 * k, 21 * k, 21 * k), fill=255, width=largura)
        else:
            pontos = [(6, 15), (12, 9), (18, 15)] if aberta else [(6, 9), (12, 15), (18, 9)]
            tinta.line([(x * k, y * k) for x, y in pontos], fill=255, width=largura, joint="curve")
        traco = traco.resize((tamanho, tamanho), Image.BOX)
        img.paste(ImageColor.getrgb(cor), (round(cx - tamanho / 2), round(cy - tamanho / 2)), traco)

    def _compor_base(self, w: int, h: int, estado: tuple[str, str]) -> Image.Image:
        c, p, l = self.c, self.px, self.l
        fundo = self._fundo()
        img = Image.new("RGB", (w, h), c["fundo"])
        # O centro do mapa (o centro da cidade), um pouco acima do meio da janela
        img.paste(fundo, ((w - fundo.width) // 2, (h - fundo.height) // 2 - p(60)))

        # A pílula: largura conforme o texto
        largura = self.f["pequena"].measure(estado[0]) + p(40)
        m = l["m"]
        self.pilula = (w - m - largura, m + p(6), w - m, m + p(34))

        # A sombra da página (0 8px 24px), sob os painéis e a pílula
        sombra = Image.new("L", (w, h), 0)
        tinta = ImageDraw.Draw(sombra)
        alfa = round(255 * c["sombra"])
        for x0, y0, x1, y1 in (l["mapa"], l["painel"]):
            tinta.rounded_rectangle((x0, y0 + p(8), x1, y1 + p(8)), p(8), fill=alfa)
        x0, y0, x1, y1 = self.pilula
        tinta.rounded_rectangle((x0, y0 + p(3), x1, y1 + p(3)), p(14), fill=alfa // 2)
        img.paste((0, 0, 0), (0, 0, w, h), sombra.filter(ImageFilter.GaussianBlur(p(12))))

        for caixa in (l["mapa"], l["painel"]):
            self._caixa(img, caixa, p(8), c["superficie"], c["borda"])
        self._caixa(img, self.pilula, p(14), c["superficie"], c["borda"])
        x0, y0, x1, y1 = self.pilula
        cy = (y0 + y1) / 2
        self._caixa(img, (x0 + p(14), cy - p(4), x0 + p(22), cy + p(4)), p(4), c[estado[1]])

        # O logo, como na página: o marcador num quadrado claro
        self._caixa(img, (m, m, m + p(40), m + p(40)), p(8), c["primaria_suave"], c["borda"])
        marcador = pino(p(40), c["primaria_texto"])
        img.paste(marcador, (m, m), marcador)
        return img

    def _compor_botoes(self):
        c, p, l = self.c, self.px, self.l
        img = self.base.copy()
        foco = self.foco
        self._caixa(img, l["campo"], p(6), c["superficie_2"], c["texto"] if foco == "campo" else c["borda_forte"])
        if foco == "copiar":
            self._caixa(img, l["copiar"], p(4), c["superficie"])
        self._caixa(img, l["abrir"], p(6), c["primaria_hover"] if foco == "abrir" else c["primaria"])

        # As abas (.segmentado da página): a escolhida em destaque
        self._caixa(img, l["segmentado"], p(8), c["superficie_2"], c["borda"])
        ativa = l["abas"][self.aba]
        if self.tema == "escuro":
            self._caixa(img, ativa, p(6), c["primaria_suave"])
        else:
            self._caixa(img, ativa, p(6), c["superficie"], c["borda_forte"])
        if self.aba == "logs" and foco == "pasta" and LOGS.is_dir():
            self._caixa(img, l["pasta"], p(6), c["superficie_2"])

        if self.aba == "fotos":
            b = l["busca"]
            focado = self.raiz.focus_get() is self.busca
            self._caixa(img, b, p(6), c["superficie_2"],
                        c["texto"] if focado or foco in ("busca", "seta") else c["borda_forte"])
            self._icone(img, "lupa", b[0] + p(18), (b[1] + b[3]) / 2, c["suave"])
            if foco == "seta":
                self._caixa(img, l["seta"], p(4), c["superficie"])
            aberta = self.tela.itemcget(self.janela_lista, "state") == "normal"
            self._icone(img, "seta", (l["seta"][0] + l["seta"][2]) / 2, (b[1] + b[3]) / 2, c["suave"], aberta)

        self.foto = ImageTk.PhotoImage(img)
        self.tela.itemconfigure(self.imagem, image=self.foto)
        self.botoes = {"copiar": (l["copiar"], self.copiar), "campo": (l["campo"], self.abrir),
                       "abrir": (l["abrir"], self.abrir)}
        for nome, _ in ABAS:
            if nome != self.aba:
                self.botoes[f"aba_{nome}"] = (l["abas"][nome], lambda n=nome: self.trocar_aba(n))
        if self.aba == "logs" and LOGS.is_dir():
            self.botoes["pasta"] = (l["pasta"], lambda: os.startfile(LOGS))
        if self.aba == "fotos":
            self.botoes["seta"] = (l["seta"], self._alternar_lista)
            self.botoes["busca"] = (l["busca"], self._abrir_busca)

    # Mouse ------------------------------------------------------------------ #

    def _botao_em(self, x, y):
        # "copiar" fica dentro do "campo", e a "seta" dentro da "busca": vêm antes na ordem dos botões
        return next((nome for nome, ((x0, y0, x1, y1), _) in self.botoes.items()
                     if x0 <= x <= x1 and y0 <= y <= y1), None)

    def _focar(self, nome):
        if nome != self.foco:
            self.foco = nome
            self.tela.configure(cursor=("xterm" if nome == "busca" else "hand2") if nome else "")
            if self.base is not None:
                self._compor_botoes()
                if nome and nome.startswith("aba_") or self.foco is None:
                    self._agendar()  # o texto da aba muda de cor

    def _mouse(self, evento):
        self._focar(self._botao_em(evento.x, evento.y))

    def _clique(self, evento):
        if nome := self._botao_em(evento.x, evento.y):
            self.botoes[nome][1]()
        else:  # fora do campo de busca: ele perde o foco
            self.tela.focus_set()
            self._fechar_lista()

    def abrir(self):
        webbrowser.open(self.url)

    def copiar(self):
        self.raiz.clipboard_clear()
        self.raiz.clipboard_append(self.url)
        self.copiado = True
        self.desenhar()

        def voltar():
            self.copiado = False
            self.desenhar()
        self.raiz.after(1500, voltar)

    def trocar_aba(self, aba: str):
        self.aba = aba
        if aba == "fotos":
            self.reler()
        self._agendar()

    # O campo de busca das ruas (o .combo da página) ----------------------- #

    def _mostrar_placeholder(self):
        self.vazia = True
        self.busca.delete(0, "end")
        self.busca.insert(0, self.rua or PROCURAR)
        self.vazia = self.rua is None
        self.busca.configure(foreground=self.c["suave"] if self.vazia else self.c["texto"])

    def _entrou_na_busca(self, _):
        # A lista abre ao clicar ou digitar, não aqui: o Windows devolve o foco ao campo sozinho
        # quando a janela volta para a frente.
        if self.vazia:
            self.busca.delete(0, "end")
            self.busca.configure(foreground=self.c["texto"])
            self.vazia = False
        else:
            self.busca.select_range(0, "end")
        self._agendar()

    def _saiu_da_busca(self):
        if self.raiz.focus_get() is self.busca:
            return
        self._fechar_lista()
        self._mostrar_placeholder()  # volta a mostrar a rua escolhida (ou o PROCURAR)
        self._agendar()

    def _abrir_busca(self):
        self.busca.focus_set()
        self._abrir_lista()

    def _alternar_lista(self):
        if self.tela.itemcget(self.janela_lista, "state") == "normal":
            self._fechar_lista()
        else:
            self.busca.focus_set()
            self._abrir_lista(todas=True)

    def _digitou(self, evento):
        if evento.keysym not in ("Up", "Down", "Return", "Escape", "Tab"):
            self._abrir_lista()

    def _abrir_lista(self, todas: bool = False):
        texto = "" if todas or self.vazia else self.busca.get()
        if texto == self.rua:
            texto = ""  # o campo mostra a rua escolhida: a lista mostra todas
        palavras = normalizar(texto).split()
        self.opcoes = [rua for rua, _ in self.ruas if all(pal in normalizar(rua) for pal in palavras)]
        fotos = dict(self.ruas)
        self.lista.delete(0, "end")
        for rua in self.opcoes:
            self.lista.insert("end", f"  {rua}   ·   {fotos[rua]} fotos")
        if not self.opcoes:
            self.lista.insert("end", "  Nenhuma rua com esse nome" if self.ruas else "  Nenhuma rua coletada ainda")
            self.lista.itemconfigure(0, foreground=self.c["suave"], selectforeground=self.c["suave"],
                                     selectbackground=self.c["superficie"])
        elif self.rua in self.opcoes:
            self.lista.selection_set(self.opcoes.index(self.rua))
            self.lista.see(self.opcoes.index(self.rua))
        self.tela.itemconfigure(self.janela_lista, state="normal")
        self.lista.lift()
        self._posicionar_lista()
        self._compor_botoes()

    def _posicionar_lista(self):
        b, p = self.l["busca"], self.px
        linhas = min(LISTA_MAX, max(1, self.lista.size()))
        self.lista.configure(height=linhas)
        self.tela.coords(self.janela_lista, b[0], b[3] + p(4))
        self.tela.itemconfigure(self.janela_lista, width=b[2] - b[0],
                                height=linhas * self.f["corpo"].metrics("linespace") + p(10))

    def _fechar_lista(self):
        if self.tela.itemcget(self.janela_lista, "state") == "normal":
            self.tela.itemconfigure(self.janela_lista, state="hidden")
            if self.base is not None:
                self._compor_botoes()

    def _mover_na_lista(self, passo: int):
        if self.tela.itemcget(self.janela_lista, "state") != "normal":
            self._abrir_lista()
        if not self.opcoes:
            return "break"
        atual = self.lista.curselection()
        i = min(len(self.opcoes) - 1, max(0, (atual[0] + passo) if atual else 0))
        self.lista.selection_clear(0, "end")
        self.lista.selection_set(i)
        self.lista.see(i)
        return "break"

    def _passou_na_lista(self, evento):
        if self.opcoes:
            i = self.lista.nearest(evento.y)
            self.lista.selection_clear(0, "end")
            self.lista.selection_set(i)

    def _escolher_da_lista(self):
        if not self.opcoes:
            return
        atual = self.lista.curselection()
        self.escolher(self.opcoes[atual[0] if atual else 0])

    def escolher(self, rua: str):
        """Mostra as fotos da rua na galeria."""
        self.rua = rua
        self._fechar_lista()
        self.tela.focus_set()
        self._mostrar_placeholder()
        self.reler(forcar=True)

    # Dados ------------------------------------------------------------------ #

    def reler(self, forcar: bool = False):
        """Lê do banco as ruas com fotos e as fotos da rua escolhida."""
        self.lida = time.time()
        try:
            conn = conectar()
            try:
                self.ruas = ruas_com_fotos(conn)
                fotos = fotos_da_rua(conn, self.rua) if self.rua else []
            finally:
                conn.close()
        except Exception as exc:  # o banco ocupado pela coleta, por exemplo: tenta de novo daqui a pouco
            self.galeria.mostrar([], ("Não deu para ler o banco da coleta", str(exc)))
            return
        if self.rua is None:
            vazio = (("Escolha uma rua", "Procure acima uma rua coletada para ver todas as fotos que a coleta "
                      "baixou dela, inteiras, com as coordenadas de onde foram tiradas.") if self.ruas else
                     ("Nenhuma foto ainda", "Abra o mapa pelo link acima e use “Coletar uma rua”: as fotos de "
                      "cada rua aparecem aqui."))
        else:
            vazio = ("Nenhuma foto dessa rua", "A coleta ainda não baixou fotos dela.")
        if forcar or fotos != self.galeria.fotos or not fotos:
            self.galeria.mostrar(fotos, vazio)
        self._agendar()  # o resumo ao lado do campo

    def _resumo(self) -> str:
        fotos = self.galeria.fotos
        if not fotos:
            return ""
        zonas = len({f["ponto_id"] for f in fotos})
        escolhidas = sum(1 for f in fotos if f["status"] == "aprovada" and f["tentativa"] == f["posicao"])
        return f"{len(fotos)} fotos de {zonas} zonas · {escolhidas} escolhidas"

    # Barras de rolagem (a do Tk não aceita cores no Windows) --------------- #

    def desenhar_barra(self, barra: tk.Canvas, rolagem: tuple[float, float]):
        barra.delete("all")
        primeiro, ultimo = rolagem
        if ultimo - primeiro >= 1:
            return
        altura, largura = barra.winfo_height(), self.px(4)
        meio, minimo = self.px(4), self.px(32)  # com centenas de fotos, a proporção daria um ponto
        topo, fim = primeiro * altura, ultimo * altura
        if fim - topo < minimo:
            topo = primeiro / max(1e-9, 1 - (ultimo - primeiro)) * (altura - minimo)
            fim = topo + minimo
        barra.create_line(meio, max(meio, topo + largura / 2), meio, min(altura - largura / 2, fim - largura / 2),
                          width=largura, capstyle="round", fill=self.c["borda_forte"])

    def atualizar(self):
        tema = tema_do_sistema()
        if tema != self.tema:
            self._aplicar_tema(tema)
        self.lista_coletas.mostrar(coletas())
        if self.tamanho and self.tamanho[2] != self._estado():  # a pílula mudou
            self._agendar()
        # As fotos novas: de tempos em tempos durante a coleta, e logo que ela acaba
        acabou = self.coletava and not COLETA.rodando
        self.coletava = COLETA.rodando
        if self.aba == "fotos" and (acabou or COLETA.rodando and time.time() - self.lida > RELER_S):
            self.reler()
        self.raiz.after(ATUALIZAR_MS, self.atualizar)

    # Fechar ----------------------------------------------------------------- #

    def fechar(self):
        if self.fechando:
            return
        if COLETA.rodando:
            if not messagebox.askyesno("Fechar", "Uma coleta está rodando. Fechar a interrompe (rodar a mesma "
                                       "rua de novo continua de onde parou). Fechar mesmo?"):
                return
            COLETA.parar()
            self.fechando = True
            self.raiz.title(f"{TITULO} — fechando")
            self._agendar()
            self.esperar_e_sair()
        else:
            self.sair()

    def esperar_e_sair(self):
        if COLETA.rodando:  # até o log da coleta ser guardado
            self.raiz.after(300, self.esperar_e_sair)
        else:
            self.sair()

    def sair(self):
        threading.Thread(target=self.servidor.shutdown, daemon=True).start()
        self.raiz.destroy()


def _barra_de_titulo(raiz: tk.Tk, escura: bool):
    """A barra de título do Windows no tema da janela (Windows 10 20H1+)."""
    try:
        import ctypes
        raiz.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(raiz.winfo_id())
        valor = ctypes.c_int(1 if escura else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(valor), ctypes.sizeof(valor))
    except (AttributeError, OSError):
        pass


def main():
    try:  # texto nítido em telas com escala (Windows)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    raiz = tk.Tk()
    servidor = None
    for porta in PORTAS:
        try:
            servidor = iniciar(porta)
            break
        except OSError:  # porta ocupada (outra janela aberta?)
            continue
    if servidor is None:
        messagebox.showerror(TITULO, f"As portas {PORTAS.start}–{PORTAS.stop - 1} estão ocupadas.")
        return
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    Janela(raiz, f"http://127.0.0.1:{servidor.server_address[1]}/", servidor)
    raiz.mainloop()


if __name__ == "__main__":
    main()
