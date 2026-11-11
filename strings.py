"""Every user-facing string, in English and Portuguese.

Glossary (never use synonyms in the interface):
Goal · Detour · Park / Parked · Queue · Friday run · Hidden priority.
Tone: short, no guilt, no lecture. Augur observes and offers; it never scolds.
"""

from __future__ import annotations

from typing import Any

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # --- injected into the model's context on the 2nd detour in a row ---
        "nudge_context": (
            "[Augur · applies to this message only] The user's 3 goals this week: {g1}; {g2}; {g3}.\n"
            "This is their 2nd request in a row outside these goals (closest: {closest}).\n"
            "Before doing it, ask ONE short question, starting with \"🧭\", offering two options in this order: "
            "\"Park it\" and \"Do it now\". Use your clarify tool with exactly those two options, in that order, if you have it.\n"
            "If they choose \"Park it\": call augur_park with a summary of at most 60 characters, "
            "confirm in one line, and stop.\n"
            "If they choose \"Do it now\": do the task normally and do not mention this again."
        ),
        "nudge_note": (
            "🧭 Heads-up: 2nd request in a row off your goals (closest: {closest}). "
            "If more ideas like this come up, /park <idea> saves them for the Friday run."
        ),
        # --- onboarding and goals ---
        "onboarding": (
            "🧭 Augur keeps your agent pointed at your 3 goals for the week.\n"
            "It stays quiet, counts where each request goes, and only speaks up "
            "when you drift twice in a row.\n\n"
            "Set your goals in one line:\n"
            "  /augur goals ship the beta, hackathon, Spanish\n\n"
            "Or see a sample week first: /augur demo"
        ),
        "goals_split_question": "Planned split for your week?\n1) {g1}\n2) {g2}\n3) {g3}",
        "cancel": "Cancel",
        "goals_saved": (
            "🧭 Goals saved: {g1} {p1}% · {g2} {p2}% · {g3} {p3}%.\n"
            "I'll stay quiet unless you drift twice in a row. See your week anytime with /augur.\n"
            "Tip: pin a fast, cheap model for “Augur classifier” in `hermes model` so labels take under a second."
        ),
        "goals_demo_cleared": "The demo data was removed; from now on only your real requests count.",
        "goals_not_saved": "Goals not saved. Add the split inline to skip the question: /augur goals {names} 50/30/20",
        "goals_parse_failed": (
            "I couldn't find 3 goals in that. Try:\n"
            "  /augur goals \"Beta launch: first 10 users\" \"Hackathon\" \"Spanish\" 50/30/20"
        ),
        "goals_bad_split": "The split needs 3 whole numbers that add up to 100, like 50/30/20.",
        "goals_need_three": "Augur needs exactly 3 goals. You gave {n}.",
        # --- park ---
        "park_saved": "🧭 Parked #{id}: {summary} · Queue: {n}",
        "park_usage": "Usage: /park <what to do later>",
        # --- fix ---
        "fix_nothing": "Nothing to fix yet: no request has been classified.",
        "fix_question": "Last request: \"{summary}\" → {label}. What was it really?",
        "fix_saved": "🧭 Got it: \"{summary}\" → {label}. I'll learn from this.",
        "fix_unchanged": "Nothing changed.",
        "fix_usage": "Usage: /augur fix [1|2|3|detour]",
        "detour": "Detour",
        # --- pause ---
        "pause_on": "🧭 Augur is paused until {until}: no classification, no nudges. /augur pause off to resume.",
        "pause_off": "🧭 Augur is back on.",
        "pause_usage": "Usage: /augur pause 2h | 30m | off",
        # --- demo ---
        "demo_loaded": (
            "🧭 Demo week loaded: {n} requests, {q} parked items, sample goals. "
            "Everything is marked as demo. See it with /augur · remove it with /augur demo clear"
        ),
        "demo_cleared": "🧭 Demo data removed.",
        "demo_kept_goals": "Your own goals were kept; the demo only added requests and queue items.",
        # --- panel ---
        "panel_title": "🧭 Augur · {date}",
        "panel_demo": "  (includes demo data)",
        "panel_goal": "{pct:>3}% of {planned}% planned",
        "panel_detours": "Detours",
        "panel_queue": "Queue: {n} {parked_word} · {friday}",
        "parked_one": "parked",
        "parked_many": "parked",
        "panel_friday_on": "last Friday run {when}",
        "panel_friday_off": "no Friday run yet → /blueprint augur:friday",
        "panel_health": "⚠ {bad} of the last {n} labels were too slow or failed. Pin a fast model for “Augur classifier” (hermes model) so nudges arrive in time.",
        "panel_hidden": "Hidden priority: \"{theme}\" ({count} requests) → /augur goals",
        "panel_self_cost": "Augur itself used {tokens} tokens this week",
        "panel_empty": "No requests counted yet this week. Just work; Augur counts quietly.",
        "panel_paused": "Paused until {until} · /augur pause off",
        "panel_requests": "{n} {requests_word} counted · {tokens} tokens",
        "requests_one": "request",
        "requests_many": "requests",
        "panel_legend": "actual / planned share of your requests",
        # --- report (PNG and caption) ---
        "report_title": "Augur · {date}",
        "report_hero": "{pct}% of your requests went to detours",
        "report_hero_sub": "{n} requests · {tokens} tokens",
        "report_planned_actual": "{actual}% · planned {planned}%",
        "report_ready": "Ready for you",
        "report_hidden": "Hidden priority: {theme} · {count} requests",
        "report_footer": "Augur cost: {tokens} tokens · {corrections} corrections this week",
        "report_nothing_parked": "Nothing parked this week.",
        "dropped_stale": "parked for more than 14 days",
        "report_waiting": "{n} parked, waiting for the Friday run.",
        "report_caption_waiting": "🧭 Your week: {pct}% went to detours. {n} parked {items_word} for the Friday run.",
        "items_wait_one": "item waits",
        "items_wait_many": "items wait",
        "report_demo": "includes demo data",
        "report_caption": "🧭 Your week: {pct}% went to detours. {ready} of {total} parked items are ready, {needs} {needs_word}.",
        "needs_one": "needs you",
        "needs_many": "need you",
        "report_caption_noqueue": "🧭 Your week: {pct}% went to detours. Nothing was parked.",
        "report_caption_hidden": "Hidden priority spotted: \"{theme}\". Swap it in with /augur goals.",
        "report_text_fallback": "(Chart unavailable: matplotlib is not installed. Text report below.)",
        # --- friday guard ---
        "friday_blocked": "Augur Friday run is read-and-draft only. Mark this item needs_you.",
        # --- misc ---
        "error": "🧭 Something went wrong, so Augur stayed out of the way. Details are in the Hermes log.",
        "help": (
            "🧭 Augur commands\n"
            "  /augur              your week at a glance\n"
            "  /augur goals ...    set your 3 goals\n"
            "  /augur fix          correct the last classification\n"
            "  /augur pause 2h     pause (or: off)\n"
            "  /augur report       weekly report image now\n"
            "  /augur demo         load a sample week (clear: /augur demo clear)\n"
            "  /park <text>           park a detour for the Friday run\n"
            "  /blueprint augur:friday  schedule the Friday run"
        ),
        "eval_done": "🧭 Eval written to {path}\n\n{table}",
    },
    "pt": {
        "nudge_context": (
            "[Augur · vale só para esta mensagem] As 3 metas do usuário nesta semana: {g1}; {g2}; {g3}.\n"
            "Este é o 2º pedido seguido fora dessas metas (mais próxima: {closest}).\n"
            "Antes de fazer, faça UMA pergunta curta, começando com \"🧭\", com duas opções nesta ordem: "
            "\"Estacionar\" e \"Fazer agora\". Use sua ferramenta clarify com exatamente essas duas opções, nessa ordem, se tiver.\n"
            "Se escolherem \"Estacionar\": chame augur_park com um resumo de no máximo 60 caracteres, "
            "confirme em uma linha e pare.\n"
            "Se escolherem \"Fazer agora\": faça a tarefa normalmente e não toque mais no assunto."
        ),
        "nudge_note": (
            "🧭 Aviso: 2º pedido seguido fora das suas metas (mais próxima: {closest}). "
            "Se surgirem mais ideias assim, /park <ideia> guarda para a Sexta do Desvio."
        ),
        "onboarding": (
            "🧭 O Augur mantém seu agente apontado para as suas 3 metas da semana.\n"
            "Ele fica em silêncio, conta para onde vai cada pedido e só fala "
            "quando você se desvia duas vezes seguidas.\n\n"
            "Defina suas metas numa linha:\n"
            "  /augur goals lançar o beta, hackathon, espanhol\n\n"
            "Ou veja uma semana de exemplo antes: /augur demo"
        ),
        "goals_split_question": "Divisão planejada da sua semana?\n1) {g1}\n2) {g2}\n3) {g3}",
        "cancel": "Cancelar",
        "goals_saved": (
            "🧭 Metas salvas: {g1} {p1}% · {g2} {p2}% · {g3} {p3}%.\n"
            "Fico em silêncio, a menos que você se desvie duas vezes seguidas. Veja sua semana com /augur.\n"
            "Dica: fixe um modelo rápido e barato para “Augur classifier” em `hermes model` para cada classificação levar menos de 1 segundo."
        ),
        "goals_demo_cleared": "Os dados de demonstração foram removidos; daqui em diante só contam seus pedidos reais.",
        "goals_not_saved": "Metas não salvas. Inclua a divisão na linha para pular a pergunta: /augur goals {names} 50/30/20",
        "goals_parse_failed": (
            "Não encontrei 3 metas nisso. Tente:\n"
            "  /augur goals \"Lançar o beta: 10 primeiros usuários\" \"Hackathon\" \"Espanhol\" 50/30/20"
        ),
        "goals_bad_split": "A divisão precisa de 3 números inteiros que somem 100, como 50/30/20.",
        "goals_need_three": "O Augur precisa de exatamente 3 metas. Você deu {n}.",
        "park_saved": "🧭 Estacionado #{id}: {summary} · Fila: {n}",
        "park_usage": "Uso: /park <o que fazer depois>",
        "fix_nothing": "Nada para corrigir ainda: nenhum pedido foi classificado.",
        "fix_question": "Último pedido: \"{summary}\" → {label}. O que era de verdade?",
        "fix_saved": "🧭 Entendido: \"{summary}\" → {label}. Vou aprender com isso.",
        "fix_unchanged": "Nada mudou.",
        "fix_usage": "Uso: /augur fix [1|2|3|desvio]",
        "detour": "Desvio",
        "pause_on": "🧭 Augur pausado até {until}: sem classificação, sem avisos. /augur pause off para retomar.",
        "pause_off": "🧭 O Augur voltou.",
        "pause_usage": "Uso: /augur pause 2h | 30m | off",
        "demo_loaded": (
            "🧭 Semana de demonstração carregada: {n} pedidos, {q} itens estacionados, metas de exemplo. "
            "Tudo marcado como demo. Veja com /augur · remova com /augur demo clear"
        ),
        "demo_cleared": "🧭 Dados de demonstração removidos.",
        "demo_kept_goals": "Suas metas foram mantidas; a demo só acrescentou pedidos e itens na fila.",
        "panel_title": "🧭 Augur · {date}",
        "panel_demo": "  (inclui dados de demonstração)",
        "panel_goal": "{pct:>3}% de {planned}% planejado",
        "panel_detours": "Desvios",
        "panel_queue": "Fila: {n} {parked_word} · {friday}",
        "parked_one": "estacionado",
        "parked_many": "estacionados",
        "panel_friday_on": "última Sexta do Desvio {when}",
        "panel_friday_off": "nenhuma Sexta do Desvio ainda → /blueprint augur:friday",
        "panel_health": "⚠ {bad} das últimas {n} classificações foram lentas demais ou falharam. Fixe um modelo rápido para “Augur classifier” (hermes model) para os avisos chegarem a tempo.",
        "panel_hidden": "Prioridade oculta: \"{theme}\" ({count} pedidos) → /augur goals",
        "panel_self_cost": "O próprio Augur usou {tokens} tokens nesta semana",
        "panel_empty": "Nenhum pedido contado nesta semana ainda. Trabalhe; o Augur conta em silêncio.",
        "panel_paused": "Pausado até {until} · /augur pause off",
        "panel_requests": "{n} {requests_word} · {tokens} tokens",
        "requests_one": "pedido contado",
        "requests_many": "pedidos contados",
        "panel_legend": "parcela real / planejada dos seus pedidos",
        "report_title": "Augur · {date}",
        "report_hero": "{pct}% dos seus pedidos foram desvios",
        "report_hero_sub": "{n} pedidos · {tokens} tokens",
        "report_planned_actual": "{actual}% · planejado {planned}%",
        "report_ready": "Pronto para você",
        "report_hidden": "Prioridade oculta: {theme} · {count} pedidos",
        "report_footer": "Custo do Augur: {tokens} tokens · {corrections} correções nesta semana",
        "report_nothing_parked": "Nada estacionado nesta semana.",
        "dropped_stale": "estacionado há mais de 14 dias",
        "report_waiting": "{n} estacionados, esperando a Sexta do Desvio.",
        "report_caption_waiting": "🧭 Sua semana: {pct}% foi para desvios. {n} {items_word} a Sexta do Desvio.",
        "items_wait_one": "item estacionado espera",
        "items_wait_many": "itens estacionados esperam",
        "report_demo": "inclui dados de demonstração",
        "report_caption": "🧭 Sua semana: {pct}% foi para desvios. {ready} de {total} itens estacionados estão prontos, {needs} {needs_word}.",
        "needs_one": "precisa de você",
        "needs_many": "precisam de você",
        "report_caption_noqueue": "🧭 Sua semana: {pct}% foi para desvios. Nada foi estacionado.",
        "report_caption_hidden": "Prioridade oculta encontrada: \"{theme}\". Troque com /augur goals.",
        "report_text_fallback": "(Gráfico indisponível: matplotlib não está instalado. Relatório em texto abaixo.)",
        "friday_blocked": "A Sexta do Desvio do Augur só lê e rascunha. Marque este item como needs_you.",
        "error": "🧭 Algo deu errado, então o Augur saiu do caminho. Detalhes no log do Hermes.",
        "help": (
            "🧭 Comandos do Augur\n"
            "  /augur              sua semana num relance\n"
            "  /augur goals ...    defina suas 3 metas\n"
            "  /augur fix          corrija a última classificação\n"
            "  /augur pause 2h     pausa (ou: off)\n"
            "  /augur report       relatório da semana agora\n"
            "  /augur demo         carrega uma semana de exemplo (apagar: /augur demo clear)\n"
            "  /park <texto>          estaciona um desvio para a Sexta do Desvio\n"
            "  /blueprint augur:friday  agenda a Sexta do Desvio"
        ),
        "eval_done": "🧭 Avaliação gravada em {path}\n\n{table}",
    },
}


def t(key: str, lang: str = "en", **kwargs: Any) -> str:
    """Translate ``key``; unknown languages fall back to English, never raise."""
    table = STRINGS.get(lang) or STRINGS["en"]
    template = table.get(key) or STRINGS["en"].get(key, key)
    try:
        return template.format(**kwargs) if kwargs else template
    except (KeyError, IndexError, ValueError):
        return template
