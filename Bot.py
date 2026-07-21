"""
Automação para deixar de seguir em massa no TikTok (Playwright + Brave real).

POR QUE ESSA VERSÃO?
O TikTok costuma bloquear com captcha um navegador "novo" controlado por
automação (mesmo que seja o próprio Brave/Chromium). A solução é conectar
o Playwright no SEU Brave já aberto e já logado, usando uma aba nova nele
via CDP (Chrome DevTools Protocol) — assim o TikTok vê exatamente o mesmo
navegador/perfil que você usa todo dia.

COMO USAR:

1) Instale as dependências:
     pip install playwright
     playwright install chromium
   (o chromium instalado aqui só é usado pelo Playwright pra "falar" com o
   Brave via CDP, ele não abre uma janela própria)

2) FECHE todas as janelas do Brave completamente.

3) Abra o Brave de novo, mas com a flag de debug remoto:

   Windows (PowerShell):
     & "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe" --remote-debugging-port=9222

   macOS (Terminal):
     open -a "Brave Browser" --args --remote-debugging-port=9222

   Linux (Terminal):
     brave-browser --remote-debugging-port=9222 &

4) Deixe o Brave aberto e rode o script:
     python tiktok_unfollow_all.py

5) Confirme que você já está logado no TikTok numa aba do seu Brave. O
   script abre uma ABA NOVA nesse mesmo navegador/perfil.

6) O script:
   - abre a lista "Seguindo" e clica em "Deixar de seguir" um por um
   - quando a aba "Seguindo" esgota, tenta também a aba "Amigos" do
     mesmo modal (amigos = seguidas mútuas, também contam como "seguir")
   - quando não encontra mais botões em nenhuma das duas, RECARREGA a
     página e tenta de novo (até MAX_RELOAD_ATTEMPTS vezes seguidas sem
     progresso, aí sim considera que acabou de verdade)

7) Como o TikTok pode limitar ações em massa, o script para sozinho
   depois de MAX_UNFOLLOWS_PER_RUN pessoas no total. Rode várias vezes
   (ex: a cada algumas horas) até acabar as ~9000.

8) Toda pessoa que ele deixar de seguir é salva em "unfollowed_log.csv",
   com data/hora, pra você decidir depois quem re-seguir.

AVISO: automação de cliques em massa não é oficialmente suportada pelo
TikTok. Mesmo usando seu navegador real, prefira ir aos poucos (ex:
200-400 por vez) em vez de tentar zerar tudo de uma vez.
"""

import csv
import os
import random
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

PROFILE_URL = "https://www.tiktok.com/@aranho__"  # troque pelo seu usuário
CDP_URL = "http://localhost:9222"  # precisa bater com --remote-debugging-port
LOG_FILE = "unfollowed_log.csv"

MAX_UNFOLLOWS_PER_RUN = 250        # quantas pessoas deixar de seguir no total, por execução
DELAY_BETWEEN_CLICKS = (1.2, 3.0)  # segundos, intervalo aleatório entre ações
SCROLL_PAUSE = 1.5
MAX_RELOAD_ATTEMPTS = 4            # reloads seguidos sem progresso antes de desistir
TABS_TO_PROCESS = ["Seguindo", "Amigos"]  # abas do modal a processar, nessa ordem


def log_unfollow(username: str):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["username", "unfollowed_at"])
        writer.writerow([username, datetime.now().isoformat(timespec="seconds")])


def open_following_modal(page):
    page.locator('[data-e2e="following-count"]').click()
    time.sleep(2)


def click_tab(dialog, tab_text: str) -> bool:
    """Tenta clicar na aba (Seguindo / Amigos / etc) dentro do modal.
    Retorna True se conseguiu clicar, False se não achou a aba."""
    try:
        tab = dialog.get_by_text(tab_text, exact=False).first
        tab.click(timeout=2000)
        time.sleep(1.2)
        return True
    except Exception:
        return False


def unfollow_in_current_tab(page, dialog, budget: int) -> int:
    """Clica nos botões de unfollow visíveis na aba atualmente aberta do
    modal, rolando pra carregar mais, até esgotar a lista ou o orçamento
    (budget) de cliques permitido nesta chamada. Retorna quantos clicou."""
    unfollowed_here = 0
    empty_rounds = 0

    while unfollowed_here < budget:
        buttons = dialog.locator("button:has-text('Seguindo')")
        count = buttons.count()

        if count == 0:
            dialog.hover()
            page.mouse.wheel(0, 1800)
            time.sleep(SCROLL_PAUSE)
            empty_rounds += 1
            if empty_rounds > 6:
                break
            continue

        empty_rounds = 0
        btn = buttons.first

        row = btn.locator("xpath=ancestor::*[self::li or self::div][1]")
        username = "desconhecido"
        try:
            username = row.locator("span, p, a").first.inner_text(timeout=1000)
        except Exception:
            pass

        btn.click()
        time.sleep(0.4)

        confirm = page.get_by_text("Deixar de seguir", exact=False)
        if confirm.count() > 0:
            try:
                confirm.first.click(timeout=1500)
            except Exception:
                pass

        unfollowed_here += 1
        log_unfollow(username)
        print(f"[{unfollowed_here + _TOTAL_OFFSET[0]}] Deixou de seguir: {username}")

        time.sleep(random.uniform(*DELAY_BETWEEN_CLICKS))

    return unfollowed_here


# usado só pra numerar o print de forma contínua entre chamadas
_TOTAL_OFFSET = [0]


def run():
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(
                "Não consegui conectar no Brave em "
                f"{CDP_URL}.\n"
                "Confirme que:\n"
                "  1) Você fechou TODAS as janelas do Brave antes\n"
                "  2) Abriu ele de novo com --remote-debugging-port=9222\n"
                "  3) Ele ainda está aberto agora\n"
                f"Erro original: {e}"
            )
            return

        context = browser.contexts[0]
        page = context.new_page()
        page.goto(PROFILE_URL)

        input(
            "\nConfira que a aba abriu logada no seu perfil do TikTok.\n"
            "Se precisar, faça login manualmente nela.\n"
            "Quando estiver pronta, volte aqui e pressione ENTER...\n"
        )

        dialog = page.locator("div[role='dialog'][data-e2e='follow-info-popup']")

        total_unfollowed = 0
        reload_attempts = 0

        while total_unfollowed < MAX_UNFOLLOWS_PER_RUN and reload_attempts <= MAX_RELOAD_ATTEMPTS:
            page.reload()
            time.sleep(2)
            open_following_modal(page)

            progressed_this_round = False

            for tab_text in TABS_TO_PROCESS:
                if total_unfollowed >= MAX_UNFOLLOWS_PER_RUN:
                    break

                if not click_tab(dialog, tab_text):
                    # aba não encontrada (pode não existir, ex: sem amigos) - pula
                    continue

                budget = MAX_UNFOLLOWS_PER_RUN - total_unfollowed
                _TOTAL_OFFSET[0] = total_unfollowed
                n = unfollow_in_current_tab(page, dialog, budget)
                total_unfollowed += n
                if n > 0:
                    progressed_this_round = True

            if progressed_this_round:
                reload_attempts = 0
            else:
                reload_attempts += 1
                print(
                    f"Nenhum progresso nesta rodada. Tentativa de reload "
                    f"{reload_attempts}/{MAX_RELOAD_ATTEMPTS}."
                )

        print(f"\nConcluído. Total deixado de seguir nesta execução: {total_unfollowed}")
        print(f"Log salvo em: {LOG_FILE}")
        page.close()


if __name__ == "__main__":
    run()