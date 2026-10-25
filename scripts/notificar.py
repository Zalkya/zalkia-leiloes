#!/usr/bin/env python3
"""notificar.py — Alertas de QUEDA de preço via Telegram.

Compara o `data/imoveis.json` recém-gerado (working tree) com a versão anterior
(`git show HEAD:data/imoveis.json`) e envia ao Telegram as quedas de preço de
imóveis JÁ listados, filtradas por UF/cidade e por um limite mínimo de %.

Config por variáveis de ambiente (NENHUMA é commitada; secrets ficam no GitHub):
  TELEGRAM_BOT_TOKEN   (secret)   token do bot — nunca é impresso
  TELEGRAM_CHAT_ID     (secret)   chat de destino
  NOTIFY_UFS           csv de UFs (ex.: "PB,PE"); vazio = todas
  NOTIFY_CIDADES       csv de cidades (ex.: "Joao Pessoa,Campina Grande"); vazio = todas
  NOTIFY_MIN_PCT       queda mínima em % para notificar (default 0 = qualquer queda)
  NOTIFY_MAX_ITENS     máx. de itens listados na mensagem (default 25)
  NOTIFY_TEST          "1" envia uma mensagem de teste e sai (valida token/chat id)

Projetado para ser "soft fail": qualquer erro de envio é logado e o script sai 0,
para não derrubar o pipeline de dados.
"""
import json
import os
import re
import subprocess
import unicodedata
import urllib.parse
import urllib.request

GLOBAL = "data/imoveis.json"
TG_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MSG = 3800  # margem sob o limite de 4096 caracteres do Telegram


def log(m):
    print(m, flush=True)


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def esc(s):
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_brl(v):
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "—"


def carregar_novo():
    with open(GLOBAL, encoding="utf-8") as f:
        return json.load(f)


def carregar_antigo():
    """Versão anterior do global, a partir do commit atual (HEAD)."""
    try:
        out = subprocess.run(["git", "show", f"HEAD:{GLOBAL}"],
                             capture_output=True, text=True)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except Exception as e:
        log(f"[NOTIFY] sem baseline anterior ({type(e).__name__})")
        return None


def mapa_preco(doc):
    m = {}
    for im in (doc or {}).get("imoveis", []):
        i, p = im.get("id"), im.get("preco")
        if i and isinstance(p, (int, float)):
            m[i] = im
    return m


def enviar(token, chat, texto):
    data = urllib.parse.urlencode({
        "chat_id": chat, "text": texto,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(TG_API.format(token=token), data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return 200 <= r.status < 300


def enviar_seguro(token, chat, texto):
    """Nunca propaga exceção nem imprime o token (que vai só na URL interna)."""
    try:
        return enviar(token, chat, texto)
    except Exception as e:
        log(f"[NOTIFY] falha ao enviar ao Telegram: {type(e).__name__}")
        return False


def chunk(linhas, header, footer=""):
    """Agrupa `linhas` em mensagens <= MAX_MSG, repetindo o header em cada parte."""
    msgs, atual = [], header
    for ln in linhas:
        if len(atual) + len(ln) + 2 > MAX_MSG:
            msgs.append(atual)
            atual = header
        atual += "\n\n" + ln
    if footer and len(atual) + len(footer) + 2 <= MAX_MSG:
        atual += "\n\n" + footer
    msgs.append(atual)
    return msgs


def _parse_csv(nome):
    return {norm(x) for x in os.environ.get(nome, "").split(",") if x.strip()}


def _env_num(nome, default, cast):
    v = (os.environ.get(nome) or "").strip()
    try:
        return cast(v) if v else default
    except ValueError:
        return default


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        log("[NOTIFY] TELEGRAM_BOT_TOKEN/CHAT_ID ausentes — pulando (nada enviado).")
        return

    if os.environ.get("NOTIFY_TEST") == "1":
        ok = enviar_seguro(token, chat,
                           "✅ <b>Alertas de queda de preço</b> configurados com sucesso.")
        log(f"[NOTIFY] mensagem de teste {'enviada' if ok else 'FALHOU'}")
        return

    ufs = _parse_csv("NOTIFY_UFS")
    cidades = _parse_csv("NOTIFY_CIDADES")
    min_pct = _env_num("NOTIFY_MIN_PCT", 0.0, float)
    max_itens = _env_num("NOTIFY_MAX_ITENS", 25, int)

    antigo = carregar_antigo()
    if antigo is None:
        log("[NOTIFY] sem versão anterior para comparar — nada a fazer.")
        return
    pa, pn = mapa_preco(antigo), mapa_preco(carregar_novo())

    quedas = []
    for i, im in pn.items():
        ant = pa.get(i)
        if not ant:
            continue
        old, new = ant["preco"], im["preco"]
        if new >= old or old <= 0:
            continue  # só quedas
        if ufs and norm(im.get("uf")) not in ufs:
            continue
        if cidades and norm(im.get("cidade")) not in cidades:
            continue
        pct = (1 - new / old) * 100
        if pct < min_pct:
            continue
        quedas.append({"im": im, "old": old, "new": new, "pct": pct})

    if not quedas:
        log(f"[NOTIFY] nenhuma queda de preço no filtro "
            f"(ufs={sorted(ufs) or 'todas'}, cidades={sorted(cidades) or 'todas'}, "
            f"min_pct={min_pct}).")
        return

    quedas.sort(key=lambda q: q["pct"], reverse=True)
    total = len(quedas)
    mostrados = quedas[:max_itens]

    header = f"🏠📉 <b>{total} queda(s) de preço</b> em imóveis da Caixa"
    linhas = []
    for q in mostrados:
        im = q["im"]
        tipo = (im.get("tipo") or "imóvel").capitalize()
        local = f"{esc(im.get('cidade') or '—')}/{esc(im.get('uf') or '—')}"
        link = im.get("link") or ""
        corpo = (f"• <b>{esc(tipo)}</b> — {local}\n"
                 f"  {fmt_brl(q['old'])} → <b>{fmt_brl(q['new'])}</b> (−{q['pct']:.1f}%)")
        if link:
            corpo += f'\n  <a href="{esc(link)}">ver na Caixa</a>'
        linhas.append(corpo)

    footer = f"… e mais {total - len(mostrados)} queda(s)." if total > len(mostrados) else ""

    enviados = 0
    for msg in chunk(linhas, header, footer):
        if enviar_seguro(token, chat, msg):
            enviados += 1
    log(f"[NOTIFY] {total} queda(s) detectada(s); {enviados} mensagem(ns) enviada(s).")


if __name__ == "__main__":
    main()
