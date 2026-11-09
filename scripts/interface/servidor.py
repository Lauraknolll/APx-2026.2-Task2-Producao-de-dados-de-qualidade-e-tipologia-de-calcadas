"""
Servidor local da interface: `python -m scripts.interface` (da raiz do
repositório), ou o .exe (janela.py), que roda este servidor por trás de uma
janela com o link e os logs.

Só a biblioteca padrão — nenhuma dependência além das da coleta. Serve a
página (static/), que lê e grava no banco da coleta
(data/processed/streetview.db) por esta API, e a coleta de ruas novas:

    GET  /api/dados           as ruas (traçado) e as zonas aprovadas (mapa.py)
    GET  /api/avaliacoes      as avaliações, o que já foi exportado e a última exportação
    POST /api/avaliacao       {zona, posicao, quadrado, classe | null, autor}
    POST /api/exportacao      {modo, rua, quadrados: [{ponto_id, posicao, quadrado, quando}]}:
                              registra o .zip que a página montou
    GET  /api/coleta          a coleta em andamento (ou a última): situação, resumo ou erro, e o log
    POST /api/coleta/previa   {nome}: a rua que o nome indica e quantas zonas dela faltam
    POST /api/coleta          {nome, limite?}: roda a coleta da rua (nome oficial, da prévia)
    POST /api/coleta/parar    interrompe a coleta (ela continua de onde parou na próxima)
    GET  /img/quadrados/<zona>_<posicao>_<k>.jpg, /img/contexto/<zona>_<posicao>.jpg

A coleta roda num subprocesso (`python -m scripts.ingestao.coleta_streetview
rua --nome ...`), uma de cada vez. O log de cada coleta fica em
data/processed/coletas/ (as últimas GUARDAR_LOGS).
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from scripts.ingestao.coleta_streetview.banco import AGORA_MS, abrir_db, pasta_da_rua, registrar_avaliacao
from scripts.ingestao.coleta_streetview.config import DB_PATH, PASTA_IMAGENS, RAIZ
from scripts.ingestao.coleta_streetview.etapas import zonas_da_rua
from scripts.ingestao.coleta_streetview.geometria import OverpassIndisponivel, RuaAmbigua, RuaNaoEncontrada

from .mapa import ruas, zonas

STATIC = Path(__file__).parent / "static"
TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}
IMAGEM = re.compile(r"^/img/(quadrados|contexto)/(\d+_\d+(?:_\d)?\.jpg)$")
MODOS = ("tudo", "novas")  # da exportação: todas as avaliações, ou só as ainda não exportadas
LOGS = RAIZ / "data" / "processed" / "coletas"  # o log de cada coleta, para a janela do .exe
GUARDAR_LOGS = 20


def comando_python(modulo: str, *args: str) -> list[str]:
    """`python -m modulo args`; no .exe (sem python), o próprio .exe com --modulo (janela.py)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--modulo", modulo, *args]
    return [sys.executable, "-m", modulo, *args]


def conectar() -> sqlite3.Connection:
    """Uma conexão por requisição: a coleta grava no mesmo banco em paralelo."""
    return sqlite3.connect(DB_PATH, timeout=15)


# --------------------------------------------------------------------------- #
# Coleta em segundo plano
# --------------------------------------------------------------------------- #

class Coleta:
    """A coleta de uma rua num subprocesso, com as últimas linhas do log."""

    def __init__(self):
        self._lock = threading.Lock()
        self._processo: Optional[subprocess.Popen] = None
        self.codigo: Optional[int] = None  # o código de saída da coleta
        self.rua: Optional[str] = None
        self.limite: Optional[int] = None
        self.inicio: Optional[float] = None
        self.fim: Optional[float] = None
        self.interrompida = False
        self.log: deque[str] = deque(maxlen=400)

    @property
    def rodando(self) -> bool:
        # Só termina depois que os logs foram lidos inteiros (self.fim marcado em _rodar).
        return self._processo is not None and self.fim is None

    @staticmethod
    def _iniciar(comando: list[str]) -> subprocess.Popen:
        return subprocess.Popen(
            comando, cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # no .exe, sem janela de console
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})

    def iniciar(self, rua: str, limite: Optional[int]):
        with self._lock:
            if self.rodando:
                raise RuntimeError(f'Já há uma coleta em andamento ("{self.rua}").')
            comando = comando_python("scripts.ingestao.coleta_streetview", "rua", "--nome", rua,
                                     *(["--limite", str(limite)] if limite else []))
            self.rua, self.limite, self.inicio, self.fim, self.codigo = rua, limite, time.time(), None, None
            self.interrompida = False
            self.log.clear()
            self.log.append("$ coleta_streetview rua --nome " + rua + (f" --limite {limite}" if limite else ""))
            self._processo = self._iniciar(comando)
            threading.Thread(target=self._rodar, args=(self._processo,), daemon=True).start()

    def _rodar(self, processo: subprocess.Popen):
        for linha in processo.stdout:
            self.log.append(linha.rstrip())
        self.codigo = processo.wait()
        if self.interrompida:
            self.log.append("Interrompida. Rodar de novo a mesma rua continua de onde parou.")
        elif self.codigo == 0:
            self.log.append("Coleta concluída.")
        else:
            self.log.append(f"A coleta terminou com erro (código {self.codigo}).")
        self.fim = time.time()
        self._guardar_log()

    def _guardar_log(self):
        """O log desta coleta em LOGS/<início>_<rua>.log; só as GUARDAR_LOGS últimas ficam."""
        textos = {"concluida": "concluída", "interrompida": "interrompida", "erro": "parou com erro"}
        cabecalho = (f"== {self.rua} · {time.strftime('%d/%m/%Y %H:%M', time.localtime(self.inicio))} · "
                     f"{textos.get(self.situacao(), '')}")
        try:
            LOGS.mkdir(parents=True, exist_ok=True)
            nome = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(self.inicio))
            slug = pasta_da_rua(self.rua or "rua").name  # sem acentos, com hífens
            (LOGS / f"{nome}_{slug}.log").write_text(
                "\n".join([cabecalho, *self.log]) + "\n", encoding="utf-8")
            for velho in sorted(LOGS.glob("*.log"))[:-GUARDAR_LOGS]:
                velho.unlink()
        except OSError:
            pass  # o log é só para consulta: não derruba a coleta

    def parar(self):
        """Interrompe a coleta (rodar a mesma rua de novo continua de onde parou)."""
        with self._lock:
            if self.rodando and self._processo.poll() is None:
                self.interrompida = True  # o código de saída vem diferente de zero, mas não é erro
                self._processo.terminate()

    def situacao(self) -> Optional[str]:
        """rodando | concluida | interrompida | erro, ou None se nenhuma coleta rodou."""
        if self._processo is None:
            return None
        if self.rodando:
            return "rodando"
        if self.interrompida:
            return "interrompida"
        return "concluida" if self.codigo == 0 else "erro"

    def _resumo(self) -> Optional[str]:
        """O que a coleta conseguiu, da linha final dela: "2 com foto, 0 sem foto boa"."""
        for linha in reversed(self.log):
            if m := re.search(r"(\d+ com foto, \d+ sem foto boa)", linha):
                return m[1]
        return None

    @staticmethod
    def _erro(log) -> Optional[str]:
        """A causa de um erro: a linha da exceção ("RuntimeError: ..."), ou a
        última linha do log (as mensagens de sys.exit)."""
        linhas = [l.strip() for l in log if l.strip() and not l.startswith("A coleta terminou com erro")]
        excecoes = [l for l in linhas if re.match(r"^[\w.]+(Error|Exception):", l)]
        return (excecoes or linhas or [None])[-1]

    def estado(self) -> dict:
        situacao = self.situacao()
        return {"rodando": self.rodando, "situacao": situacao, "rua": self.rua, "limite": self.limite,
                "inicio": self.inicio, "fim": self.fim, "log": list(self.log),
                "resumo": self._resumo() if situacao == "concluida" else None,
                "erro": self._erro(self.log) if situacao == "erro" else None}


COLETA = Coleta()


# --------------------------------------------------------------------------- #
# Respostas da API
# --------------------------------------------------------------------------- #

def api_dados() -> dict:
    with conectar() as conn:
        return {"ruas": ruas(conn), "zonas": zonas(conn)}


CAMPOS_AVALIACAO = ("ponto_id", "posicao", "quadrado", "classe", "origem", "autor", "quando")


def api_avaliacoes() -> dict:
    """As avaliações, o que já foi exportado de cada quadrado e a última exportação."""
    with conectar() as conn:
        avaliacoes = [dict(zip(CAMPOS_AVALIACAO, linha))
                      for linha in conn.execute(f"SELECT {', '.join(CAMPOS_AVALIACAO)} FROM avaliacoes")]
        exportados = [dict(zip(("ponto_id", "posicao", "quadrado", "quando_avaliacao"), linha))
                      for linha in conn.execute("SELECT ponto_id, posicao, quadrado, quando_avaliacao FROM exportados")]
        ultima = conn.execute("SELECT quando, modo, rua, quadrados FROM exportacoes ORDER BY id DESC LIMIT 1").fetchone()
    return {"avaliacoes": avaliacoes, "exportados": exportados,
            "ultima": dict(zip(("quando", "modo", "rua", "quadrados"), ultima)) if ultima else None}


def api_avaliacao(corpo: dict) -> Optional[dict]:
    """Grava a avaliação e devolve como ela ficou (None se foi apagada)."""
    zona, posicao, quadrado = int(corpo["zona"]), int(corpo["posicao"]), int(corpo["quadrado"])
    classe = corpo.get("classe")
    autor = (corpo.get("autor") or "").strip() or None
    with conectar() as conn:
        escolhida = conn.execute("SELECT tentativa, quadrados FROM pontos WHERE id = ?", (zona,)).fetchone()
        if not escolhida or escolhida[0] != posicao or str(quadrado) not in (escolhida[1] or "").split(","):
            raise ValueError("Esse quadrado não é mais da vista escolhida da zona; recarregue o mapa.")
        registrar_avaliacao(conn, zona, posicao, quadrado, classe, origem="manual", autor=autor)
        linha = conn.execute(f"SELECT {', '.join(CAMPOS_AVALIACAO)} FROM avaliacoes "
                             "WHERE ponto_id = ? AND posicao = ? AND quadrado = ?", (zona, posicao, quadrado)).fetchone()
    return dict(zip(CAMPOS_AVALIACAO, linha)) if linha else None


def api_exportacao(corpo: dict) -> dict:
    """
    Registra o .zip que a página montou: a exportação e, por quadrado, a
    avaliação que foi nele (o momento dela, não o da exportação: um quadrado
    reavaliado enquanto o zip era montado segue novo).
    """
    modo, rua, quadrados = corpo.get("modo"), corpo.get("rua") or None, corpo.get("quadrados") or []
    if modo not in MODOS:
        raise ValueError(f"modo desconhecido: {modo!r} (use {' ou '.join(MODOS)})")
    if not quadrados:
        raise ValueError("Nenhum quadrado na exportação.")
    with conectar() as conn:
        cursor = conn.execute(f"INSERT INTO exportacoes (quando, modo, rua, quadrados) VALUES ({AGORA_MS}, ?, ?, ?)",
                              (modo, rua, len(quadrados)))
        conn.executemany("INSERT OR REPLACE INTO exportados (ponto_id, posicao, quadrado, quando_avaliacao, "
                         "exportacao_id) VALUES (?, ?, ?, ?, ?)",
                         [(int(q["ponto_id"]), int(q["posicao"]), int(q["quadrado"]), q["quando"], cursor.lastrowid)
                          for q in quadrados])
    return {"ok": True}


def api_previa_coleta(corpo: dict) -> tuple[int, dict]:
    """A rua que o nome digitado indica e quantas zonas dela faltam — o que o
    menu do terminal mostra antes de perguntar quantas rodar."""
    nome = (corpo.get("nome") or "").strip()
    if not nome:
        return HTTPStatus.BAD_REQUEST, {"erro": "Digite o nome da rua."}
    try:
        oficial, zonas = zonas_da_rua(nome)
    except RuaAmbigua as exc:
        if len(exc.nomes) > 15:
            return HTTPStatus.CONFLICT, {"erro": f'{len(exc.nomes)} ruas casam com "{nome}"; digite mais do nome.'}
        return HTTPStatus.CONFLICT, {"erro": exc.titulo, "candidatas": exc.nomes}
    except (RuaNaoEncontrada, OverpassIndisponivel) as exc:
        return HTTPStatus.NOT_FOUND, {"erro": str(exc)}
    if not zonas:
        return HTTPStatus.NOT_FOUND, {"erro": f'"{oficial}" existe no OpenStreetMap, mas não tem calçadas na camada do IPPUC.'}
    with conectar() as conn:
        status = {tuple(chave): s for *chave, s in conn.execute("SELECT fid, anel, ordem, status FROM pontos")}
    a_fazer = sum(1 for z in zonas if status.get(z[0]) not in ("aprovada", "recoleta"))
    return HTTPStatus.OK, {"nome": oficial, "zonas": len(zonas), "processadas": len(zonas) - a_fazer,
                           "a_fazer": a_fazer}


def api_iniciar_coleta(corpo: dict) -> tuple[int, dict]:
    """Roda a coleta da rua; `nome` é o oficial, que veio da prévia."""
    nome = (corpo.get("nome") or "").strip()
    limite = corpo.get("limite")
    limite = int(limite) if limite not in (None, "") else None
    if not nome:
        return HTTPStatus.BAD_REQUEST, {"erro": "Digite o nome da rua."}
    if limite is not None and limite < 1:
        return HTTPStatus.BAD_REQUEST, {"erro": "O número de zonas deve ser pelo menos 1."}
    try:
        COLETA.iniciar(nome, limite)
    except RuntimeError as exc:
        return HTTPStatus.CONFLICT, {"erro": str(exc)}
    return HTTPStatus.OK, COLETA.estado()


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):
        pass  # sem uma linha por requisição no terminal

    def _json(self, dados, status: int = HTTPStatus.OK):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _arquivo(self, caminho: Path, cache: bool = False):
        if not caminho.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        corpo = caminho.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", TIPOS.get(caminho.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-cache")
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo(self) -> dict:
        tamanho = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(tamanho) or b"{}")

    def do_GET(self):
        rota = urlparse(self.path).path
        try:
            if rota == "/":
                return self._arquivo(STATIC / "index.html")
            # Os arquivos da página, ao lado do index.html
            if re.fullmatch(r"\w[\w.-]*", nome := rota[1:]) and (STATIC / nome).is_file():
                return self._arquivo(STATIC / nome)
            if m := IMAGEM.match(rota):
                pasta = PASTA_IMAGENS / m[1] if m[1] == "quadrados" else PASTA_IMAGENS / "contexto"
                return self._arquivo(pasta / m[2], cache=True)
            if rota == "/api/dados":
                return self._json(api_dados())
            if rota == "/api/avaliacoes":
                return self._json(api_avaliacoes())
            if rota == "/api/coleta":
                return self._json(COLETA.estado())
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:  # a página mostra o erro em vez de ficar sem resposta
            self._json({"erro": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        rota = urlparse(self.path).path
        try:
            if rota == "/api/avaliacao":
                return self._json(api_avaliacao(self._corpo()))
            if rota == "/api/exportacao":
                return self._json(api_exportacao(self._corpo()))
            if rota in ("/api/coleta/previa", "/api/coleta"):
                status, dados = (api_previa_coleta if rota.endswith("previa") else api_iniciar_coleta)(self._corpo())
                return self._json(dados, status)
            if rota == "/api/coleta/parar":
                COLETA.parar()
                return self._json(COLETA.estado())
            self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError) as exc:
            self._json({"erro": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"erro": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)


def iniciar(porta: int) -> ThreadingHTTPServer:
    """O servidor, pronto para serve_forever(), em 127.0.0.1:porta (só esta máquina)."""
    abrir_db().close()  # cria o banco ou acrescenta as tabelas novas (avaliacoes, exportacoes)
    return ThreadingHTTPServer(("127.0.0.1", porta), Handler)


def main(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(prog="python -m scripts.interface", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--porta", type=int, default=8000, help="porta local (default: 8000)")
    parser.add_argument("--sem-navegador", action="store_true", help="não abre o navegador sozinho")
    args = parser.parse_args(argv)

    servidor = iniciar(args.porta)
    url = f"http://127.0.0.1:{args.porta}/"
    print(f"Mapa das calçadas em {url} — Ctrl+C para sair.")
    if not args.sem_navegador:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        COLETA.parar()
        print("\nAté mais.")
