// De onde a página lê e onde grava: o banco da coleta, pela API do servidor
// local (scripts/interface/servidor.py).
//
//   carregarFixos()       {ruas, zonas}: o que a coleta tem (scripts/interface/mapa.py)
//   carregarAvaliacoes()  {avaliacoes, exportados, ultima}: o que muda a cada avaliação
//   avaliar(...)          grava (ou apaga, com classe null) e devolve a avaliação como ficou
//   registrarExportacao(modo, rua, quadrados)  o .zip que a página montou
//   imagem(pasta, nome)   o endereço de uma foto (quadrados/ ou contexto/)

const FONTE = (() => {
  async function pedir(rota, corpo) {
    let resp;
    try {
      resp = await fetch(rota, corpo === undefined ? {} : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo),
      });
    } catch {
      throw new Error("Sem resposta do coletor: a janela dele foi fechada?");
    }
    let dados;
    try { dados = await resp.json(); } catch {
      throw new Error("Sem dados: abra a página pelo link da janela do coletor.");
    }
    if (!resp.ok) throw new Error(dados.erro || resp.statusText);
    return dados;
  }
  return {
    carregarFixos: () => pedir("api/dados"),
    carregarAvaliacoes: () => pedir("api/avaliacoes"),
    avaliar: (zona, posicao, quadrado, classe, autor) => pedir("api/avaliacao", { zona, posicao, quadrado, classe, autor }),
    registrarExportacao: (modo, rua, quadrados) => pedir("api/exportacao", { modo, rua, quadrados }),
    imagem: (pasta, nome) => `img/${pasta}/${nome}`,
  };
})();
