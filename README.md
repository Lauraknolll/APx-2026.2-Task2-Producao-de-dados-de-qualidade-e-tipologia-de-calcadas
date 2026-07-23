# 🏛️ AP[x] — Atelier de Projetos de Extensão

> **O AP[x] é um projeto de extensão com o objetivo de proporcionar aos estudantes de Engenharia de Computação e Sistemas de Informação do Câmpus Curitiba da UTFPR a oportunidade de apoiar ações do poder público voltadas ao planejamento e à administração da cidade que demandem suporte técnico da área de Tecnologia da Informação e Comunicação (TIC). Este apoio será prestado em horas de trabalho caracterizadas como carga horária de extensão, a serem creditadas no histórico acadêmico de cada estudante participante do projeto.**

---

## 📋 Índice

- [Sobre o AP[x]](#-sobre-o-apx)
- [Objetivos](#-objetivos)
- [Estrutura](#-estrutura)
- [Como Usar](#-como-usar)
- [Regras](#-regras)
- [Fluxo de Trabalho](#-fluxo-de-trabalho)
- [Licença](#-licença)

---

## 🧭 Sobre o AP[x]

O **AP[x] — Atelier de Projetos de Extensão** é uma iniciativa que une:

- **Universidade (UTFPR):** estudantes dos cursos de **Engenharia de Computação** e **Sistemas de Informação** aplicam conhecimento acadêmico em problemas reais.
- **Órgão Público (IPPUC):** a **Diretoria Hipervisor Curitiba** do IPPUC propõe demandas reais da cidade de Curitiba que podem ser resolvidas ou apoiadas por soluções tecnológicas.

Cada estudante pode dedicar **até 120 horas por semestre** ao projeto, e as atividades são gerenciadas via **GitLab Issue Board**.

### 🎯 Objetivos

1. Resolver problemas reais do IPPUC com tecnologia
2. Formar estudantes com experiência prática em projetos reais
3. Garantir rastreabilidade total das atividades
4. Produzir documentação que permaneça como legado para a cidade

---

## 📁 Estrutura

```
├── data/                # Dados (raw, processed, reports)
├── docs/                # Decisões arquiteturais, relatórios, atas, especificações
├── notebooks/           # Jupyter Notebooks para análises exploratórias
├── scripts/             # Scripts utilitários do projeto
└── README.md
```

Cada pasta possui um `README.md` próprio com detalhes de uso.

---

## 🚀 Como Usar

### Criar um repositório a partir do template

```bash
git clone https://gitlab.com/izidoromth/apx-template.git nome-da-task
cd nome-da-task
git remote remove origin
git remote add origin https://gitlab.com/seu-usuario/nome-da-task.git
git push -u origin main
```

### Configurar o Issue Board

Colunas do Kanban:
- 📝 **A Fazer** — Issues cadastradas e priorizadas
- 👨‍💻 **Em Andamento** — Em desenvolvimento
- 🚧 **Bloqueado** — Aguardando dependência a ser resolvida
- ✅ **Revisão** — Aguardando validação (Ippuc)
- ✔️ **Concluído** — Finalizado

---

## 📜 Regras

### 👥 Responsabilidades

| Quem           | Responsabilidade |
|----------------|------------------|
| **Orientador** | Orientar a equipe, revisar código, priorizar o Board, validar entregas, ser ponte entre equipe e IPPUC |
| **Equipe**     | Manter o Board atualizado, cadastrar e puxar Issues, desenvolver, documentar, registrar horas |
| **IPPUC**      | Apresentar demandas em reuniões, esclarecer dúvidas, validar entregas |

### ⏱ Carga Horária

- Cada estudante: **até 120 horas/semestre**
- Distribuição sugerida: ~8h/semana por 15 semanas
- Registrar horas gastas nos comentários da Issue ao movê-la para "Concluído"
- O orientador acompanha o total por estudante

### 🏷 Issues — Padrão Obrigatório

| Elemento            | Obrigatório? | Descrição |
|---------------------|:---:|-----------|
| Título claro        | ✅  | Resumo direto do que precisa ser feito |
| Descrição           | ✅  | Contexto + objetivo + critérios de aceitação |
| Critérios de aceitação | ✅ | Lista de verificação do que define "pronto" |
| Assignee            | ✅  | Quem está responsável |

#### ⚠️ Regras importantes sobre Issues

- **Cada Issue = uma entrega**. Issues genéricas demais ("fazer o projeto") devem ser detalhadas
- Issues que perderam relevância devem ser fechadas com justificativa

### 🌿 Branches

Toda branch deve seguir o padrão:

```
<tipo>/<numero-da-issue>-<descricao-curta>
```

| Tipo          | Exemplo                          | Quando usar |
|---------------|----------------------------------|-------------|
| `feature/`    | `feature/42-api-consulta`       | Nova funcionalidade |
| `fix/`        | `fix/17-corrige-parsing`        | Correção de bug |
| `docs/`       | `docs/05-atualiza-readme`       | Documentação |
| `refactor/`   | `refactor/08-modulariza-api`    | Refatoração sem mudar comportamento |
| `test/`       | `test/23-adiciona-testes`       | Testes |
| `chore/`      | `chore/31-atualiza-deps`        | Manutenção (dependências, CI) |

**Regras:**
- Sempre partir da `main` atualizada
- Uma branch por Issue
- Deletar a branch após o merge
- **Nunca commitar diretamente na `main`**

### 💬 Commits (Conventional Commits)

```
<tipo>(<escopo opcional>): <descrição curta>

<corpo opcional>

<rodapé opcional>
```

**Regras:**
- Título com **no máximo 72 caracteres**
- Usar **imperativo**: "adiciona", não "adicionou" nem "adicionado"
- Commits **atômicos**: uma mudança lógica por commit
- Vincular à Issue no rodapé: `Closes #42`, `Refs #17`

**Exemplos:**
```
feat(api): adiciona endpoint GET /api/v1/zonas

Implementa consulta de zonas com filtro por bairro.

Closes #42
```
```
fix(parser): corrige encoding de caracteres especiais

Arquivos CSV do IPPUC usavam latin-1, agora tratamos UTF-8.

Closes #17
```
```
docs(readme): atualiza instruções de configuração
```
```
chore(deps): atualiza pandas para 2.1.0
```

### 🔄 Fluxo no Board

| Coluna              | Quem move | O que significa |
|---------------------|-----------|-----------------|
| 📝 **A Fazer**      | Estudante | Issue cadastrada e priorizada pela equipe e atribuída a um estudante |
| 👨‍💻 **Em Andamento**| Estudante | Issue em desenvolvimento |
| 🚧 **Bloqueado**    | Estudante | Issue depende de algo externo para prosseguir |
| ✅ **Revisão**      | Estudante | Código pronto, aguardando validação |
| ✔️ **Concluído**    | Orientador | Entregue e aprovado |

**Responsabilidades de atualização:**
- **Estudantes:** manter o Board atualizado diariamente
- **IPPUC:** acompanhar pelo Board o andamento

---