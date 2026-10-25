# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é

Pipeline (sem servidor, roda 100% em GitHub Actions) que baixa os CSVs oficiais de
imóveis da Caixa por UF, converte para JSON/TOON, enriquece com coordenadas e serve
um mapa interativo (`index.html`) no GitHub Pages. Os dados versionados vivem em
`data/`; o estado do pipeline em `.github/state/` (não publicado).

## Comandos

Não há build/lint/testes. É Python 3.12 puro da stdlib (sem dependências, sem
`requirements.txt`). Scripts assumem o diretório de trabalho na raiz do repo e usam
`curl` externo. Rodados via `python3`:

```bash
python3 scripts/pipeline.py              # baixa e converte TODAS as 27 UFs
python3 scripts/pipeline.py SP RJ        # apenas UFs específicas
python3 scripts/consolidar.py            # junta por-UF -> data/imoveis.{json,toon}
python3 scripts/geo_enriquecer.py        # geocodifica pendentes (todas as UFs)
```

Variáveis de ambiente relevantes (geo):
- `GOOGLE_MAPS_API_KEY` — sem ela, pula direto para o fallback OSM/Nominatim.
- `GEO_LIMITE_GOOGLE` (default 800) / `GEO_LIMITE_OSM` (default 20000) — cota **diária**.
- `GEO_FILTRO_UF` — restringe o enriquecimento a uma única UF.
- `FRESH_UFS` (consolidar) / `FORCA=1` (força reescrita do global).

No Windows local, `curl` e `python3` precisam estar no PATH; o pipeline de download
só foi validado em runner Linux (o portal da Caixa bloqueia por padrão de IP/ASN).

## Arquitetura do pipeline

Fluxo orquestrado por `.github/workflows/atualizar.yml` (a cada 2h), em 3 jobs:

1. **`baixar`** — matrix de 27 jobs (um por UF, `max-parallel: 6`). Cada worker roda
   `pipeline.py {UF}` e sobe `data/{UF}/` como artefato. Separar por worker espalha
   as requisições por IPs distintos — essencial contra o Radware Bot Manager do portal.
2. **`consolidar`** (`if: always()`) — baixa todos os artefatos, roda `consolidar.py`,
   que junta as UFs no dataset global e commita **somente se houve mudança real**.
3. **`geocode`** — faz checkout de `ref: master` (para pegar o commit recém-pushado),
   roda `geo_enriquecer.py` e commita cache + dados. Freado pela cota **diária**.

`enriquecer-geo.yml` dispara o geocode por evento; `pages.yml` publica `index.html`.

**Alerta de queda de preço** (`scripts/notificar.py`): roda como step do job `consolidar`
**antes do commit** (quando `changed=true`), então compara `data/imoveis.json` do working
tree (novo) com `git show HEAD:data/imoveis.json` (anterior) e envia as quedas via Telegram.
Config por env: `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (secrets — nunca commitar, repo é
público), `NOTIFY_UFS`/`NOTIFY_CIDADES`/`NOTIFY_MIN_PCT`/`NOTIFY_MAX_ITENS` (vars), `NOTIFY_TEST=1`
(modo teste, usado por `notificar-teste.yml`). "Soft fail": erro de envio não derruba o pipeline.
Usa `urllib` (token não vai para argv/logs).

### Invariantes que NÃO devem quebrar

- **Download via `curl` PURO** (`pipeline.py:baixar`): sem User-Agent de navegador.
  Headers "estilo navegador" são bloqueados (302 → CAPTCHA). Rotacionar UA **piora**.
  (A rotação de UA em `geo.py` é só para Nominatim, não para a Caixa.)
- **Validação antes de gravar** (`pipeline.py:processar`): exige assinatura
  `"Lista de Im"`, cabeçalho reconhecível, ≥1 imóvel e data de geração. Uma UF
  bloqueada/inválida **nunca** sobrescreve os arquivos bons já versionados.
- **Colunas mapeadas dinamicamente** por nome de cabeçalho normalizado (`FIELD_MAP`).
  Colunas desconhecidas viram `extra_*` — mudança de layout da Caixa não quebra nem perde dado.
- **ID vem do link** (`ID_FROM_LINK`), não da coluna de ID (que pode vir em notação
  científica). Imóvel sem ID é descartado.
- **Guarda de "sem mudança"** em `consolidar.py`: só reescreve o global se alguma UF
  fresca tiver data de geração mais nova OU total diferente. Evita commit espúrio a cada ciclo.
- **Encoding**: CSV de origem é `cp1252`; JSON/TOON de saída é UTF-8.

### Geocodificação (`geo.py` + `geo_enriquecer.py`)

- Chave de cache canônica: `chave_geo` = `uf|cidade|bairro|endereco` normalizado
  (remove S/N etc.). Cache em `.github/state/_geocache.json` evita re-chamar a API.
- Ordem: **cache → Google → fallback OSM/Nominatim**. Quando a cota diária do Google
  esgota, os itens ficam `geo_pendente: true` (não caem no OSM por causa da cota) e
  esperam o próximo ciclo. O contador diário zera ao virar o dia (BR_TZ = UTC-3).
- `geo_enriquecer.py` roda em 5 fases: carrega por-UF → monta fila deduplicada por
  endereço → enriquece → regrava cada UF → regrava o global. Escrita é atômica (`.tmp` + `os.replace`).
- `consolidar.py` chama `geo.reaplicar_geo` do cache (sem API) para o mapa nunca ficar
  sem coordenadas entre execuções do geocode.

## Formato dos dados

Campos canônicos por imóvel: `id, uf, cidade, bairro, endereco, preco,
valor_avaliacao, desconto, financiamento, descricao, modalidade, link, tipo`
(+ `geo` e `geo_pendente` após geocodificação). `tipo` é derivado do 1º token da
`descricao`. TOON é um formato tabular próprio gerado por `pipeline.gerar_toon`
(bloco `meta{}` + `imoveis[N]{colunas}`); ao mexer nos campos, atualizar os dois.

O global `data/imoveis.json` tem `atualizado_em` no topo e um array `ufs[]` com
metadados por UF; os por-UF têm `data_geracao_caixa`/`coletado_em`.

## Mapa (`index.html`)

App autocontido (MapLibre GL JS + tiles OpenFreeMap, sem chave). Carrega
`data/{UF}/imoveis.json` **direto do GitHub Raw** (detecta UF pelo IP ou
`localStorage`), então atualizações de dados **não** dependem de redeploy do Pages.
Usa Street View, rotas (OSRM) e POIs (Overpass → Photon).
