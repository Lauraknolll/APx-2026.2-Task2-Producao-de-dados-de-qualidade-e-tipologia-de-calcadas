"""
As últimas coletas, na janela do .exe (janela.py), sem linguagem de código:
cada coleta vira um cartão com a rua, um selo (em andamento, concluída,
cancelada, falhou), as três etapas com uma barra de progresso cada e o
resultado em português simples.

resumir() lê o log da coleta (o que o coleta_streetview escreve: as etapas
"== 1/3 ...", os contadores "[i/n]" e a linha final "Pronto: ...");
ListaDeColetas desenha os cartões num Canvas com rolagem. O log inteiro
continua no arquivo (data/processed/coletas/), a um clique.
"""

import os
import re
import time
import tkinter as tk
from pathlib import Path
from typing import Optional

from PIL import Image, ImageTk

ETAPAS = ("Procurando as fotos no Street View", "Baixando as fotos", "Conferindo se há calçada nas fotos")
ETAPAS_DE_NOVO = {2: "Baixando fotos mais antigas", 3: "Conferindo as fotos mais antigas"}  # da 2ª leva em diante
SELOS = {"andamento": ("Em andamento", "aviso"), "concluida": ("Concluída", "ok"),
         "cancelada": ("Cancelada", "suave"), "falhou": ("Falhou", "perigo")}
# O que o servidor grava no cabeçalho do arquivo (servidor.Coleta._guardar_log)
CABECALHOS = {"concluída": "concluida", "interrompida": "cancelada", "parou com erro": "falhou"}

# Os erros que a coleta explica (cli.py) e os de rede, em palavras simples
ERROS = [
    (r"Confira a grafia", "A rua não foi encontrada. Confira o nome."),
    (r"OpenStreetMap vivem sobrecarregados", "O OpenStreetMap, de onde vem o traçado da rua, não respondeu. "
                                             "Tente de novo em alguns minutos."),
    (r"ruas casam com", "Há mais de uma rua com esse nome. Digite mais do nome."),
    (r"não tem calçadas na camada", "Essa rua não tem calçadas no mapa da prefeitura (IPPUC)."),
    (r"(?i)connection|urlerror|max retries|getaddrinfo|timed out|timeout|name resolution",
     "A internet caiu ou o Google não respondeu. Rodar a mesma rua de novo continua de onde parou."),
    (r"(?i)no space left|espaço insuficiente", "O disco está cheio."),
    (r"(?i)out of memory|memoryerror", "Faltou memória no computador."),
]


def _quando(arquivo: Optional[Path], inicio: Optional[float]) -> Optional[float]:
    if inicio:
        return inicio
    if arquivo:  # o nome do arquivo é o início: 2026-10-30_00-01-12_rua-belem.log
        try:
            return time.mktime(time.strptime(arquivo.name[:19], "%Y-%m-%d_%H-%M-%S"))
        except ValueError:
            return None
    return None


def resumir(linhas: list[str], situacao: str, rua: str, arquivo: Optional[Path] = None,
            inicio: Optional[float] = None, fim: Optional[float] = None) -> dict:
    """
    O andamento de uma coleta, do log dela. `situacao`: andamento, concluida,
    cancelada ou falhou. Devolve {rua, situacao, zonas, inicio, fim, etapas,
    resultado, arquivo}; cada etapa é {nome, estado, fracao, texto}, com
    estado: feita, rodando, esperando, parou (cancelada ou falhou) ou pulada.
    """
    etapa, leva, fracoes, vistas, zonas, nova_leva = 0, 1, {}, {}, None, None
    pronto = na_rua = nada = None
    for linha in linhas:
        linha = linha.strip()
        if m := re.match(r"^\$ .*--limite (\d+)", linha):
            zonas = int(m[1])
        elif m := re.match(r"^== (\d)/3 ", linha):
            n = int(m[1])
            if z := re.search(r"\((\d+) zonas\)", linha):
                zonas = int(z[1])
            lv = re.search(r"\(leva (\d+)\)", linha)
            if n == 2 and lv and int(lv[1]) > 1:
                # Uma leva nova (fotos mais antigas) só conta se houver o que baixar: senão a coleta
                # anuncia a leva e acaba logo depois ("0 vistas de 0 zonas para baixar").
                nova_leva = int(lv[1])
                continue
            etapa = n
            if lv:
                leva = int(lv[1])
            fracoes[etapa] = None  # começou, ainda sem contador
        elif nova_leva and (m := re.match(r"^(\d+) vistas de \d+ zonas para baixar", linha)):
            if int(m[1]):  # a leva nova vale: as etapas 2 e 3 recomeçam
                etapa, leva = 2, nova_leva
                fracoes[2] = None
                fracoes.pop(3, None)
            nova_leva = None
        elif m := re.search(r"\[(\d+)/(\d+)\]", linha):
            if etapa:
                fracoes[etapa] = int(m[1]) / max(1, int(m[2]))
                vistas[etapa] = (int(m[1]), int(m[2]))
        elif linha.startswith("Pronto:"):
            pronto = linha
        elif linha.startswith("Na rua:"):
            na_rua = linha
        elif linha.startswith("Nada a fazer"):
            nada = linha

    etapas = []
    for n in (1, 2, 3):
        nome = ETAPAS_DE_NOVO[n] if leva > 1 and n in ETAPAS_DE_NOVO else ETAPAS[n - 1]
        if n not in fracoes:  # não começou
            if situacao == "andamento":
                estado, texto = "esperando", "Aguardando"
            elif situacao == "concluida":
                estado, texto = "pulada", "Nada a fazer"
            else:
                estado, texto = "pulada", "Não chegou aqui"
            etapas.append({"nome": nome, "estado": estado, "fracao": 0, "texto": texto})
            continue
        if n < etapa or situacao == "concluida" or fracoes[n] == 1:  # 100%: feita, mesmo se a falha veio depois
            etapas.append({"nome": nome, "estado": "feita", "fracao": 1, "texto": "Pronto"})
        elif situacao == "andamento":
            fracao = fracoes[n]
            if fracao is None:
                texto = "Preparando…"
            else:
                feitos, total = vistas[n]
                unidade = "zonas" if n == 1 else "fotos"
                texto = f"{feitos} de {total} {unidade}"
            etapas.append({"nome": nome, "estado": "rodando", "fracao": fracao, "texto": texto})
        else:
            etapas.append({"nome": nome, "estado": "parou", "fracao": fracoes[n] or 0,
                           "texto": "Cancelada" if situacao == "cancelada" else "Falhou"})

    if situacao == "concluida":
        if nada:
            resultado = ("Nada a fazer: as zonas dessa rua já tinham sido coletadas.", "suave")
        elif pronto and (m := re.search(r"(\d+) com foto, (\d+) sem foto boa", pronto)):
            com, sem = int(m[1]), int(m[2])
            texto = (f"{com + sem} zonas coletadas: {com} com foto boa" + (f", {sem} sem foto boa." if sem else "."))
            if na_rua and (r := re.search(r"(\d+) de (\d+) zonas com foto", na_rua)):
                texto += f" A rua tem {r[1]} de {r[2]} zonas com foto."
            resultado = (texto, "ok")
        else:
            resultado = ("Coleta concluída.", "ok")
    elif situacao == "cancelada":
        resultado = ("Cancelada. Rodar a mesma rua de novo continua de onde parou.", "suave")
    elif situacao == "falhou":
        texto = "\n".join(linhas)
        explicacao = next((frase for padrao, frase in ERROS if re.search(padrao, texto)), None)
        resultado = (explicacao or "A coleta parou por um erro inesperado. O registro completo tem os detalhes.", "perigo")
    else:
        resultado = None
    return {"rua": rua, "situacao": situacao, "zonas": zonas, "inicio": _quando(arquivo, inicio), "fim": fim,
            "etapas": etapas, "resultado": resultado, "arquivo": arquivo}


def da_coleta_rodando(coleta) -> dict:
    """O cartão da coleta em andamento (servidor.COLETA)."""
    return resumir(coleta.estado()["log"], "andamento", coleta.rua, inicio=coleta.inicio)


def do_arquivo(arquivo: Path) -> dict:
    """O cartão de uma coleta guardada: o cabeçalho diz a rua e como terminou."""
    linhas = arquivo.read_text(encoding="utf-8", errors="replace").splitlines()
    linhas = [l.split("\r")[-1] for l in linhas]  # o tqdm reescreve a linha com \r
    cabecalho, *resto = linhas or [""]
    # "== rua · dd/mm/aaaa HH:MM · concluída"
    rua, *detalhes = cabecalho.removeprefix("== ").split(" · ")
    situacao = next((CABECALHOS[d] for d in detalhes if d in CABECALHOS), "concluida")
    return resumir(resto, situacao, rua, arquivo=arquivo, fim=arquivo.stat().st_mtime)


def _duracao(segundos: float) -> str:
    minutos = round(segundos / 60)
    if minutos < 1:
        return "menos de 1 min"
    return f"{minutos} min" if minutos < 60 else f"{minutos // 60} h {minutos % 60:02d} min"


class ListaDeColetas:
    """Os cartões das coletas num Canvas com rolagem (a barra fina da janela)."""

    def __init__(self, pai: tk.Widget, janela):
        self.j = janela  # as cores (c), as fontes (f), a escala (px) e os desenhos (_caixa, desenhar_barra)
        self.tela = tk.Canvas(pai, highlightthickness=0, borderwidth=0, yscrollincrement=janela.px(24))
        self.barra = tk.Canvas(pai, highlightthickness=0, borderwidth=0, width=janela.px(8))
        self.coletas: list[dict] = []
        self.selos = {}  # (texto, cor, tema): a imagem do selo
        self.rolagem = (0.0, 1.0)
        self.medida = None
        self.tela.configure(yscrollcommand=self._rolou)
        self.tela.bind("<Configure>", lambda _: self.desenhar())
        self.tela.bind("<MouseWheel>", lambda e: self.tela.yview_scroll(-round(e.delta / 120) * 2, "units"))
        self.barra.bind("<Button-1>", self._arrastar)
        self.barra.bind("<B1-Motion>", self._arrastar)

    def aplicar_tema(self):
        self.tela.configure(background=self.j.c["superficie"])
        self.barra.configure(background=self.j.c["superficie"])
        self.selos.clear()
        self.medida = None
        self.desenhar()

    def mostrar(self, coletas: list[dict]):
        if coletas != self.coletas:
            self.coletas, self.medida = coletas, None
            self.desenhar()

    def _selo(self, texto: str, cor: str) -> ImageTk.PhotoImage:
        """O selo da situação: o texto numa pílula com a cor dele bem clara (como a pílula do topo)."""
        j, p = self.j, self.j.px
        chave = (texto, cor, j.tema)
        if chave not in self.selos:
            largura = j.f["pequena"].measure(texto) + p(34)
            altura = p(26)
            img = Image.new("RGB", (largura, altura), j.c["superficie"])
            j._caixa(img, (0, 0, largura, altura), altura / 2, j.c["superficie_2"], j.c["borda"])
            meio = altura / 2
            j._caixa(img, (p(12), meio - p(4), p(20), meio + p(4)), p(4), j.c[cor])
            self.selos[chave] = ImageTk.PhotoImage(img)
        return self.selos[chave]

    def desenhar(self):
        j, c, p, f = self.j, self.j.c, self.j.px, self.j.f
        w, h = self.tela.winfo_width(), self.tela.winfo_height()
        if w < 2 or self.medida == (w, j.tema):
            return
        self.medida = (w, j.tema)
        t = self.tela
        topo = t.canvasy(0)
        t.delete("all")
        if not self.coletas:
            t.create_text(w / 2, max(p(60), h / 2 - p(14)), text="Nenhuma coleta ainda", font=f["corpo"],
                          fill=c["texto"])
            t.create_text(w / 2, max(p(60), h / 2 - p(14)) + p(24), font=f["ajuda"], fill=c["suave"],
                          text="Abra o mapa pelo link acima e use “Coletar uma rua”.")
            t.configure(scrollregion=(0, 0, w, h))
            return

        rotulo = max(f["corpo"].measure(e) for e in (*ETAPAS, *ETAPAS_DE_NOVO.values())) + p(40)
        estado_w = f["pequena"].measure("Não chegou aqui") + p(16)
        y = 0
        for i, coleta in enumerate(self.coletas):
            if i:
                y += p(20)
                t.create_line(0, y, w, y, fill=c["borda"])
                y += p(20)
            # A rua e o selo
            texto, cor = SELOS[coleta["situacao"]]
            selo = self._selo(texto, cor)
            t.create_image(w - selo.width(), y, image=selo, anchor="nw")
            t.create_text(w - selo.width() + p(28), y + selo.height() / 2, text=texto, font=f["pequena"],
                          fill=c["texto"], anchor="w")
            t.create_text(0, y + selo.height() / 2, text=j._encurtar(coleta["rua"], f["rua"], w - selo.width() - p(16)),
                          font=f["rua"], fill=c["texto"], anchor="w")
            y += selo.height() + p(4)
            # Quando, quantas zonas, quanto tempo
            partes = []
            if coleta["inicio"]:
                partes.append(time.strftime("Começou em %d/%m às %H:%M", time.localtime(coleta["inicio"])))
            if coleta["zonas"]:
                partes.append(f"{coleta['zonas']} zonas")
            if coleta["inicio"]:
                if coleta["situacao"] == "andamento":
                    partes.append(f"rodando há {_duracao(time.time() - coleta['inicio'])}")
                elif coleta["fim"]:
                    partes.append(f"durou {_duracao(coleta['fim'] - coleta['inicio'])}")
            t.create_text(0, y, text=" · ".join(partes), font=f["pequena"], fill=c["suave"], anchor="nw")
            y += f["pequena"].metrics("linespace") + p(14)

            # As etapas: o sinal, o nome, a barra e o texto
            for etapa in coleta["etapas"]:
                meio = y + f["corpo"].metrics("linespace") / 2
                estado = etapa["estado"]
                sinal, cor_sinal = {"feita": ("✓", "ok"), "rodando": ("●", "aviso"), "esperando": ("○", "suave"),
                                    "pulada": ("–", "suave"),
                                    "parou": ("✕", "perigo" if coleta["situacao"] == "falhou" else "suave")}[estado]
                t.create_text(p(8), meio, text=sinal, font=f["botao"], fill=c[cor_sinal], anchor="center")
                t.create_text(p(26), meio, text=etapa["nome"], font=f["corpo"], anchor="w",
                              fill=c["texto"] if estado in ("feita", "rodando") else c["suave"])
                x0, x1 = min(rotulo, w * 0.55), w - estado_w
                if x1 - x0 > p(40):
                    espessura = p(6)
                    t.create_line(x0, meio, x1, meio, width=espessura, capstyle="round", fill=c["superficie_2"])
                    fracao = etapa["fracao"]
                    if fracao:
                        cheia = {"feita": "ok", "rodando": "primaria", "parou": cor_sinal}.get(estado, "suave")
                        t.create_line(x0, meio, x0 + max(espessura, (x1 - x0) * fracao), meio, width=espessura,
                                      capstyle="round", fill=c[cheia])
                t.create_text(w, meio, text=etapa["texto"], font=f["pequena"], anchor="e",
                              fill=c["texto"] if estado == "rodando" else c["suave"])
                y += f["corpo"].metrics("linespace") + p(10)

            # O resultado, e o log completo a um clique
            if coleta["resultado"]:
                texto, cor = coleta["resultado"]
                y += p(4)
                item = t.create_text(0, y, text=texto, font=f["ajuda"], fill=c[cor], anchor="nw", width=w)
                caixa = t.bbox(item)
                y = caixa[3] if caixa else y + f["ajuda"].metrics("linespace")
            if coleta["arquivo"]:
                y += p(6)
                link = t.create_text(0, y, text="Ver o registro completo", font=f["pequena"], fill=c["suave"],
                                     anchor="nw")
                sublinha = t.bbox(link)
                if sublinha:
                    t.create_line(sublinha[0], sublinha[3] - p(1), sublinha[2], sublinha[3] - p(1), fill=c["suave"])
                self._clicavel(link, lambda _, a=coleta["arquivo"]: os.startfile(a))
                y += f["pequena"].metrics("linespace")
        t.configure(scrollregion=(0, 0, w, max(y + p(8), h)))
        t.yview_moveto(topo / max(1, y + p(8)))  # fica onde estava

    def _clicavel(self, item, acao):
        t = self.tela
        t.tag_bind(item, "<Button-1>", acao)
        t.tag_bind(item, "<Enter>", lambda _: t.configure(cursor="hand2"))
        t.tag_bind(item, "<Leave>", lambda _: t.configure(cursor=""))

    def _rolou(self, primeiro, ultimo):
        self.rolagem = (float(primeiro), float(ultimo))
        self.j.desenhar_barra(self.barra, self.rolagem)

    def _arrastar(self, evento):
        primeiro, ultimo = self.rolagem
        self.tela.yview_moveto(evento.y / max(1, self.barra.winfo_height()) - (ultimo - primeiro) / 2)
