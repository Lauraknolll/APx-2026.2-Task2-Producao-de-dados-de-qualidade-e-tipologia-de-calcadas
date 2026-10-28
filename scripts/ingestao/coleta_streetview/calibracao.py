"""
Calibração do filtro de calçada: um gabarito humano e a varredura dos limites.

rotular   — mostra cada quadrado segmentado (com a vista de contexto ao lado,
            o quadrado marcado nela) e grava o rótulo dado por uma pessoa na
            tabela `rotulos`. Às cegas: a decisão do filtro não aparece. A
            ordem é sorteada com semente fixa, então dá para parar e
            continuar; quadrados já rotulados não voltam.
calibrar  — reaplica o filtro, para uma grade de MIN_CALCADA e
            MAX_OBSTRUCAO, aos quadrados rotulados (as medidas já estão no
            banco: nada é baixado nem segmentado) e compara com o gabarito.
            As zonas são divididas em calibração (~70%), onde o limite é
            escolhido, e teste (~30%), onde o erro é medido — senão o número
            sai otimista. O limite escolhido é o de maior F-beta (beta = 2:
            perder uma calçada boa pesa mais do que deixar passar uma ruim,
            que a etapa de avaliação ainda pode recusar) entre os que mantêm
            a precisão mínima (default 90% das fotos aprovadas avaliáveis).

Só `calcada_ok` é o que o filtro deveria aprovar. Os outros rótulos separam
o tipo de descarte: `invadida` e `ausente` são problemas da calçada que um
descarte esconderia; `obstruida` e `nao_e_calcada` são descartes corretos.
"""

import json
import random
import sqlite3
from pathlib import Path

from .banco import filtro_zonas, motivo_rejeicao
from .config import MAX_OBSTRUCAO, MIN_CALCADA, RAIZ

# tecla -> (rótulo, descrição na tela)
ROTULOS = {
    "1": ("calcada_ok", "calçada visível e avaliável"),
    "2": ("obstruida", "existe, mas algo na frente impede avaliar"),
    "3": ("invadida", "carro, ocupação ou entulho SOBRE a calçada"),
    "4": ("ausente", "não há calçada (terra, mato, virou estacionamento)"),
    "5": ("nao_e_calcada", "a vista pegou outra coisa (rua, fachada...)"),
}
POSITIVO = "calcada_ok"
GRADE_PISO = (0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
GRADE_OBSTRUCAO = (0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 1.0)


def _e_teste(ponto_id: int) -> bool:
    """Separação fixa por zona: as vistas de uma zona são parecidas entre si,
    então calibração e teste não podem dividir a mesma zona."""
    return random.Random(ponto_id).random() < 0.3


def quadrados_segmentados(conn: sqlite3.Connection, args) -> list[tuple]:
    """(ponto_id, posicao, k, arquivo, recorte, piso, obstrucao) de cada
    quadrado já segmentado, na zona/rua pedida."""
    filtro, params = filtro_zonas(args)
    saida = []
    for pid, pos, arquivo, recorte, quadrados in conn.execute(f"""
            SELECT t.ponto_id, t.posicao, t.arquivo, t.recorte, t.quadrados
            FROM pontos p JOIN tentativas t ON t.ponto_id = p.id
            WHERE t.quadrados IS NOT NULL {filtro}""", params):
        for k, q in enumerate(json.loads(quadrados), 1):
            saida.append((pid, pos, k, arquivo, json.loads(recorte), q["piso"], q["obstrucao"]))
    return saida


# --------------------------------------------------------------------------- #
# rotular
# --------------------------------------------------------------------------- #

def cmd_rotular(args, conn: sqlite3.Connection):
    import tkinter as tk
    from PIL import Image, ImageDraw, ImageTk

    feitos = {tuple(r) for r in conn.execute("SELECT ponto_id, posicao, quadrado FROM rotulos")}
    fila = [q for q in quadrados_segmentados(conn, args) if q[:3] not in feitos]
    random.Random(42).shuffle(fila)
    if args.limite:
        fila = fila[:args.limite]
    if not fila:
        print("Nenhum quadrado segmentado sem rótulo" + (" nessa rua." if args.rua else "."))
        return
    print(f"{len(fila)} quadrados para rotular ({len(feitos)} já rotulados no banco).")

    janela = tk.Tk()
    janela.title("Rotular quadrados de calçada")
    painel = tk.Label(janela)
    painel.pack()
    legenda = "   ".join(f"[{t}] {r}" for t, (r, _) in ROTULOS.items()) + "   [s] pular   [z] desfazer   [q] sair"
    status = tk.Label(janela, font=("Segoe UI", 11), justify="left")
    status.pack(anchor="w", padx=8)
    tk.Label(janela, text=legenda, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=(0, 4))
    for t, (r, d) in ROTULOS.items():
        tk.Label(janela, text=f"{t}  {r}: {d}", font=("Segoe UI", 10)).pack(anchor="w", padx=16)

    estado = {"i": 0, "historico": [], "foto": None}

    def mostrar():
        if estado["i"] >= len(fila):
            janela.destroy()
            return
        pid, pos, k, arquivo, r, _, _ = fila[estado["i"]]
        arquivo = Path(arquivo)
        quadrado = Image.open(RAIZ / arquivo.parent / "quadrados" / f"{arquivo.stem}_{k}.jpg").convert("RGB")
        contexto = Image.open(RAIZ / arquivo.parent / "contexto" / arquivo.name).convert("RGB")
        # O quadrado k é a k-ésima fatia vertical do retângulo do close no contexto.
        w, h = contexto.size
        x0, x1 = r["x0"] * w, r["x1"] * w
        desenho = ImageDraw.Draw(contexto)
        desenho.rectangle([x0, r["y0"] * h, x1, r["y1"] * h], outline="white", width=1)
        desenho.rectangle([x0 + (x1 - x0) * (k - 1) / 3, r["y0"] * h, x0 + (x1 - x0) * k / 3, r["y1"] * h],
                          outline="yellow", width=4)
        lado = 540
        quadrado = quadrado.resize((lado, lado))
        contexto = contexto.resize((round(w * lado / h), lado))
        tela = Image.new("RGB", (lado + 8 + contexto.width, lado), "black")
        tela.paste(quadrado, (0, 0))
        tela.paste(contexto, (lado + 8, 0))
        estado["foto"] = ImageTk.PhotoImage(tela)
        painel.configure(image=estado["foto"])
        status.configure(text=f"{estado['i'] + 1}/{len(fila)}   zona {pid}, vista {pos}, quadrado {k}")

    def tecla(evento):
        c = evento.char.lower()
        if c in ROTULOS:
            pid, pos, k = fila[estado["i"]][:3]
            conn.execute("INSERT OR REPLACE INTO rotulos (ponto_id, posicao, quadrado, rotulo, autor) "
                         "VALUES (?, ?, ?, ?, ?)", (pid, pos, k, ROTULOS[c][0], args.autor))
            conn.commit()
            estado["historico"].append(estado["i"])
            estado["i"] += 1
        elif c == "s":
            estado["i"] += 1
        elif c == "z" and estado["historico"]:
            estado["i"] = estado["historico"].pop()
            conn.execute("DELETE FROM rotulos WHERE ponto_id = ? AND posicao = ? AND quadrado = ?",
                         fila[estado["i"]][:3])
            conn.commit()
        elif c == "q" or evento.keysym == "Escape":
            janela.destroy()
            return
        else:
            return
        mostrar()

    janela.bind("<Key>", tecla)
    mostrar()
    janela.mainloop()
    total = conn.execute("SELECT COUNT(*) FROM rotulos").fetchone()[0]
    print(f"{len(estado['historico'])} rotulados nesta sessão; {total} no banco. Rode 'calibrar' para a varredura.")


# --------------------------------------------------------------------------- #
# calibrar
# --------------------------------------------------------------------------- #

def _metricas(itens: list[tuple], min_calcada: float, max_obstrucao: float, beta: float) -> dict:
    """Recall e precisão do filtro contra o gabarito (positivo = calcada_ok)."""
    vp = fp = fn = 0
    for rotulo, piso, obstrucao in itens:
        aprova = motivo_rejeicao(piso, obstrucao, min_calcada, max_obstrucao) is None
        positivo = rotulo == POSITIVO
        vp += aprova and positivo
        fp += aprova and not positivo
        fn += positivo and not aprova
    recall = vp / (vp + fn) if vp + fn else 0.0
    precisao = vp / (vp + fp) if vp + fp else 0.0
    b2 = beta ** 2
    f = (1 + b2) * precisao * recall / (b2 * precisao + recall) if precisao + recall else 0.0
    return {"recall": recall, "precisao": precisao, "f": f, "aprovados": vp + fp, "perdas": fn}


def _linha(nome: str, mc: float, mo: float, m: dict) -> str:
    return (f"  {nome:10s} piso>={mc:4.0%}  obstr<={mo:4.0%}   recall {m['recall']:4.0%}   "
            f"precisão {m['precisao']:4.0%}   F{m['f']:.2f}   ({m['perdas']} calçadas boas perdidas)")


def cmd_calibrar(args, conn: sqlite3.Connection):
    medidas = {(pid, pos, k): (piso, obstr, arquivo)
               for pid, pos, k, arquivo, _, piso, obstr in quadrados_segmentados(conn, args)}
    rotulados = [(chave, rotulo) for *chave, rotulo in
                 conn.execute("SELECT ponto_id, posicao, quadrado, rotulo FROM rotulos")
                 if tuple(chave) in medidas]
    if not rotulados:
        print("Nenhum quadrado rotulado" + (" nessa rua" if args.rua else "") + " — rode 'rotular' antes.")
        return
    calib = [(r, *medidas[tuple(c)][:2]) for c, r in rotulados if not _e_teste(c[0])]
    teste = [(r, *medidas[tuple(c)][:2]) for c, r in rotulados if _e_teste(c[0])]
    print(f"{len(rotulados)} quadrados rotulados: {len(calib)} para calibrar, {len(teste)} para testar "
          f"(separados por zona).")
    if len(teste) < 30:
        print("  Atenção: menos de 30 quadrados de teste — o erro medido é pouco confiável.")

    print("\nGabarito:")
    for rotulo in (r for r, _ in ROTULOS.values()):
        print(f"  {rotulo:14s} {sum(r == rotulo for _, r in rotulados)}")

    grade = [(mc, mo, _metricas(calib, mc, mo, args.beta)) for mc in GRADE_PISO for mo in GRADE_OBSTRUCAO]
    # Sem um piso de precisão, uma amostra com muita calçada boa leva a
    # "filtro desligado" — que deixa passar todo o lixo.
    validos = [g for g in grade if g[2]["precisao"] >= args.precisao_min] or grade
    validos.sort(key=lambda g: -g[2]["f"])
    print(f"\nVarredura nas zonas de calibração (F{args.beta:g}: recall pesa {args.beta:g}x a precisão; "
          f"precisão >= {args.precisao_min:.0%}), 10 melhores:")
    if len(validos) == len(grade) and not any(g[2]["precisao"] >= args.precisao_min for g in grade):
        print(f"  Nenhuma combinação atinge {args.precisao_min:.0%} de precisão; valem todas.")
    for mc, mo, m in validos[:10]:
        print(_linha("", mc, mo, m))
    mc, mo, _ = validos[0]

    print("\nNas zonas de teste (o número para relatar):")
    print(_linha("atual", MIN_CALCADA, MAX_OBSTRUCAO, _metricas(teste, MIN_CALCADA, MAX_OBSTRUCAO, args.beta)))
    print(_linha("escolhido", mc, mo, _metricas(teste, mc, mo, args.beta)))

    print(f"\nO que o limite escolhido faz com cada rótulo (todos os {len(rotulados)}):")
    perdas = []
    for rotulo in (r for r, _ in ROTULOS.values()):
        dados = [(c, *medidas[tuple(c)]) for c, r in rotulados if r == rotulo]
        reprovados = [d for d in dados if motivo_rejeicao(d[1], d[2], mc, mo) is not None]
        if dados:
            print(f"  {rotulo:14s} {len(dados) - len(reprovados):4d} aprovados, {len(reprovados):4d} descartados"
                  + ("  <- problemas que o descarte esconde" if rotulo in ("invadida", "ausente") else ""))
        if rotulo == POSITIVO:
            perdas = reprovados
    if perdas:
        cegos = sum(piso < 0.05 for _, piso, _, _ in perdas)
        print(f"\n{len(perdas)} calçadas boas ainda descartadas; {cegos} com piso < 5% — nessas o modelo "
              f"não reconhece o piso, e nenhum limite as recupera:")
        for (pid, pos, k), piso, obstr, arquivo in sorted(perdas, key=lambda p: p[1])[:args.listar]:
            print(f"  piso {piso:4.0%}  {Path(arquivo).parent / 'quadrados' / f'{Path(arquivo).stem}_{k}.jpg'}")
    print(f"\nPara aplicar: reavaliar --min-calcada {mc} --max-obstrucao {mo}")
