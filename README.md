# 🏠 Imóveis da Caixa — Mapa Interativo

[![Pipeline](https://github.com/Zalkya/zalkia-leiloes/actions/workflows/atualizar.yml/badge.svg)](https://github.com/Zalkya/zalkia-leiloes/actions/workflows/atualizar.yml)
[![GitHub Pages](https://github.com/Zalkya/zalkia-leiloes/actions/workflows/pages.yml/badge.svg)](https://github.com/Zalkya/zalkia-leiloes/actions/workflows/pages.yml)

**🔗 Acesse o mapa ao vivo: <https://zalkya.github.io/zalkia-leiloes/>**

Projeto que baixa periodicamente, via GitHub Actions, os **CSVs oficiais de imóveis da Caixa Econômica Federal**, publica como JSON/TOON, enriquece com **coordenadas geográficas** e serve um **mapa interativo** no GitHub Pages — tudo sem servidor e 100% gratuito. Veja todos os imóveis em venda da Caixa num mapa único, filtráveis por estado, em **<https://zalkya.github.io/zalkia-leiloes/>**.

---

## ✨ Destaques

- **Mapa interativo** com clustering, ícones por tipo de imóvel e detalhes com preço, desconto e link direto para a Caixa.
- **Atualização automática a cada 2h** — pipeline sem servidor, rodando inteiramente em GitHub Actions.
- **Dados abertos** em JSON e [TOON](#estrutura-dos-dados), consumíveis direto do GitHub Raw (Brasil inteiro ou por estado).
- **Geocodificação** com Google Maps (opcional) e fallback gratuito OpenStreetMap/Nominatim, com cache para não repetir chamadas.
- **Robusto contra bloqueio** do portal da Caixa (Radware Bot Manager) — veja [Robustez](#robustez-portal-protegido-por-radware-bot-manager).

## 📑 Sumário

- [O que é publicado](#o-que-é-publicado)
- [Estrutura dos dados](#estrutura-dos-dados)
- [Robustez](#robustez-portal-protegido-por-radware-bot-manager)
- [Workflows](#workflows)
- [Mapa interativo](#mapa-interativo-github-pages)
- [Usando os dados](#usando-os-dados)
- [Rodando / publicando seu próprio](#rodando--publicando-seu-próprio)
- [Estrutura do repositório](#estrutura-do-repositório)

## O que é publicado

| Arquivo | Conteúdo |
|---|---|
| `data/imoveis.{json,toon}` | **Global (Brasil inteiro)** — todos os imóveis (campo `uf` em cada um) |
| `data/{UF}/imoveis.{csv,json,toon}` | Por estado (27 UFs) |
| `index.html` | **Mapa interativo** (MapLibre GL JS + OpenFreeMap) publicado no GitHub Pages |

> O CSV global (`data/imoveis.csv`) foi **removido**: era o CSV "geral" da Caixa, que fica
> desatualizado. A fonte de verdade são os CSVs por-UF.

**Estado do pipeline** (não publicado no site) fica em `.github/state/`:

| Arquivo | Papel |
|---|---|
| `.github/state/_geocache.json` | Cache de geocodificação (`chave_geo → {lat,lng,fonte}`) |
| `.github/state/_geo_daily.json` | Contador diário de chamadas de geocodificação (zera ao virar o dia) |
| `.github/state/_status.json` | Resultado da última execução do pipeline (por UF) |

Fonte: `https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{UF}.csv` — um arquivo por UF (27 no total). O download é **paralelizado em workers** (matrix do GitHub Actions), cada um baixando uma UF com `curl` puro, espalhando as requisições por IPs distintos e evitando o bloqueio Radware.

> **Por que não o arquivo "geral"?** A Caixa mantém `Lista_imoveis_geral.csv` desatualizado
> (ficou dias congelado enquanto os por-UF seguiam atualizando). Por isso o pipeline usa os
> CSVs por-UF como fonte de verdade.

## Estrutura dos dados

Cada imóvel (em `imoveis` no JSON) tem os campos canônicos:

```
id, uf, cidade, bairro, endereco, preco, valor_avaliacao, desconto,
financiamento, descricao, modalidade, link, tipo
```

`tipo` é derivado do primeiro token de `descricao` (ex.: `casa`, `apartamento`, `terreno`,
`sala comercial`, `imovel rural`…). Após a geocodificação, ganha dois campos extras:

| Campo | Descrição |
|---|---|
| `geo` | `{lat, lng, fonte}` (`fonte` = `google` ou `osm`) — presente apenas quando localizado |
| `geo_pendente` | `true` quando ainda não foi possível geocodificar o endereço |

O dataset **global** (`data/imoveis.json`) tem no topo `atualizado_em` (quando foi produzido)
e um array `ufs[]` com `data_geracao_caixa`, `coletado_em`, `fonte` e `total` **por UF**.

**TOON** (`.toon`) é uma versão tabular e compacta do mesmo dataset (bloco `meta{}` + `imoveis[N]{colunas}`),
útil para consumo por LLMs e ferramentas que preferem um formato menor que o JSON.

## Robustez (portal protegido por Radware Bot Manager)

- **Download com `curl` puro** (sem UA de navegador): padrão comprovado. Headers "estilo navegador" são bloqueados (CAPTCHA). Rotacionar User-Agent **não** ajuda — é o que dispara o bloqueio.
- **Workers paralelos com `max-parallel: 6`** + **jitter** no backoff: espalha as requisições por IPs e evita padrão rítmico.
- **Validação de conteúdo antes de gravar**: assinatura "Lista de Im", cabeçalho reconhecível e ≥1 imóvel. UF bloqueada/falha **não sobrescreve** os arquivos bons.
- **Colunas dinâmicas**: mapeadas pelo nome do cabeçalho (normalizado). Colunas desconhecidas são preservadas como `extra_*`.
- **ID confiável**: extraído do link do imóvel (a coluna de ID pode vir em notação científica).

## Workflows

- **Atualizar dados Caixa** (`atualizar.yml`) — a cada 2h + manual (`workflow_dispatch`). Baixa os 27 CSVs por-UF em **workers paralelos** (`max-parallel: 6`), consolida no dataset global e commita apenas se houver mudança. UFs que falham são marcadas no `_status.json` (dado anterior preservado).
- **Enriquecer geodata** (`enriquecer-geo.yml`) — **por evento** (roda após cada atualização de dados) + manual. Geocodifica os endereços sem coordenadas respeitando a **cota diária** (`GEO_LIMITE_GOOGLE`, default `800`, configurável por env var). O contador diário fica em `.github/state/_geo_daily.json`.
- **Deploy GitHub Pages** (`pages.yml`) — publica `index.html` a cada push de código na `master` ou execução manual. Os dados são carregados diretamente do GitHub Raw, sem depender de redeploy.

## Mapa interativo (GitHub Pages)

🔗 **<https://zalkya.github.io/zalkia-leiloes/>**

`index.html` é uma aplicação autocontida que carrega os dados por estado (ou o global) e renderiza:

- **Mapa** MapLibre GL JS com tiles do **OpenFreeMap** (gratuito, sem chave).
- **Clustering** nativo dos imóveis por proximidade.
- **Ícones por tipo de imóvel** (`tipo` → Apartamento/Casa/Terreno/Comercial/Outros) e **POIs por categoria**.
- **Carga por UF**: detecta o estado pelo IP (1ª visita) ou usa a última seleção (`localStorage`), carregando diretamente `data/{UF}/imoveis.json` do GitHub Raw em vez do global inteiro.
- **Detalhe do imóvel** com preço, desconto, descrição, link para a Caixa e matrícula.
- **Google Street View** embutido + **rotas** (Project OSRM) + **POIs próximos** (Overpass → Photon).

O mapa lê `data/{UF}/imoveis.json` (ou `data/imoveis.json`) diretamente de `raw.githubusercontent.com`; atualizações dos dados **não** dependem de redeploy do Pages.

## Usando os dados

Os dados são públicos e podem ser lidos direto do GitHub Raw, sem autenticação:

```
# Brasil inteiro
https://raw.githubusercontent.com/Zalkya/zalkia-leiloes/master/data/imoveis.json

# Por estado (ex.: Paraíba)
https://raw.githubusercontent.com/Zalkya/zalkia-leiloes/master/data/PB/imoveis.json
```

Exemplo em Python:

```python
import json, urllib.request
d = json.load(urllib.request.urlopen(
    "https://raw.githubusercontent.com/Zalkya/zalkia-leiloes/master/data/PB/imoveis.json"))
for im in d["imoveis"]:
    geo = im.get("geo") or {}
    print(im["id"], im["cidade"], im["tipo"], im["preco"], geo.get("lat"), geo.get("lng"))
```

## Rodando / publicando seu próprio

Os scripts são **Python 3.12 puro da stdlib** (sem dependências) e usam `curl` externo. Rode a partir da raiz do repo:

```bash
python3 scripts/pipeline.py              # baixa e converte TODAS as 27 UFs
python3 scripts/pipeline.py SP RJ        # apenas UFs específicas
python3 scripts/consolidar.py            # junta por-UF -> data/imoveis.{json,toon}
python3 scripts/geo_enriquecer.py        # geocodifica endereços pendentes
```

> O download da Caixa só é confiável a partir de runners do GitHub Actions (Linux); o portal
> bloqueia por padrão de IP/ASN. O enriquecimento geográfico e a consolidação rodam em qualquer lugar.

Para publicar o mapa num fork/clone próprio:

1. Ajuste `RAW_BASE` em `index.html` para apontar para `SEU_USUARIO/SEU_REPO`.
2. Habilite **GitHub Pages**: *Settings → Pages → Source: GitHub Actions*.
3. (Opcional) Adicione o secret `GOOGLE_MAPS_API_KEY` para priorizar o Google na geocodificação; sem ele, usa apenas o OSM/Nominatim.
4. O workflow `pages.yml` publica `index.html` a cada push na `master` ou execução manual.

## Estrutura do repositório

```
.github/workflows/atualizar.yml      # baixa CSVs por-UF (matrix) e consolida o global
.github/workflows/enriquecer-geo.yml # geocodificação por evento (cota diária)
.github/workflows/pages.yml          # deploy do GitHub Pages
.github/state/_geocache.json         # cache de geocodificação
.github/state/_geo_daily.json        # contador diário de chamadas
.github/state/_status.json           # status da última execução do pipeline
scripts/pipeline.py                  # download + parse + JSON + TOON (por UF)
scripts/consolidar.py                # junta por-UF → global + reaplica geo do cache
scripts/geo.py                       # geocodificação (Google + OSM) + cache + cota diária
scripts/geo_enriquecer.py            # orquestra o enriquecimento por UF + global
index.html                           # mapa interativo (GitHub Pages)
data/{UF}/imoveis.{csv,json,toon}    # dados por UF (sempre a versão mais recente)
data/imoveis.{json,toon}             # dataset global
```

---

> Dados de origem: [Portal de Imóveis Caixa](https://venda-imoveis.caixa.gov.br/). Este projeto apenas
> republica, em formatos abertos, informações já públicas — sem vínculo oficial com a Caixa Econômica Federal.
