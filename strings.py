"""Every user-facing string, in English and Portuguese.

Glossary (never use synonyms in the interface):
Goal · Detour · Park / Parked · Queue · Friday run · Hidden priority.
Tone: short, no guilt, no lecture. Bussola observes and offers; it never scolds.
"""

from __future__ import annotations

from typing import Any

ICON = "🧭"

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # --- injected into the model's context on the 2nd detour in a row ---
        "nudge_context": (
            "[Bussola · applies to this message only] The user's 3 goals this week: {g1}; {g2}; {g3}.\n"
            "This is their 2nd request in a row outside these goals (closest: {closest}).\n"
            "Before doing it, ask ONE short question, starting with \"🧭\", offering two options: "
            "\"Do it now\" and \"Park it\". Use your clarify tool with exactly those two options if you have it.\n"
            "If they choose \"Park it\": call bussola_park with a summary of at most 60 characters, "
            "confirm in one line, and stop.\n"
            "If they choose \"Do it now\": do the task normally and do not mention this again."
        ),
        # --- onboarding and goals ---
        "onboarding": (
            "🧭 Bussola keeps your agent pointed at your 3 goals for the week.\n"
            "It stays quiet, counts where each request goes, and only speaks up "
            "when you drift twice in a row.\n\n"
            "Set your goals in one line:\n"
            "  /bussola goals launching VDRI, hackathons, English\n\n"
            "Or see a sample week first: /bussola demo"
        ),
        "goals_split_question": "Planned split for your week?\n1) {g1}\n2) {g2}\n3) {g3}",
        "goals_split_custom": "Custom: type /bussola goals ... 60/30/10",
        "cancel": "Cancel",
        "goals_saved": (
            "🧭 Goals saved: {g1} {p1}% · {g2} {p2}% · {g3} {p3}%.\n"
            "I'll stay quiet unless you drift twice in a row. See your week anytime with /bussola.\n"
            "Tip: pin a fast, cheap model for “Bussola classifier” in `hermes model` so labels take under a second."
        ),
        "goals_demo_cleared": "The demo data was removed; from now on only your real requests count.",
        "goals_not_saved": "Goals not saved. Add the split inline to skip the question: /bussola goals {names} 50/30/20",
        "goals_parse_failed": (
            "I couldn't find 3 goals in that. Try:\n"
            "  /bussola goals \"VDRI launch: ship the beta\" \"Hackathons\" \"English\" 50/30/20"
        ),
        "goals_bad_split": "The split needs 3 whole numbers that add up to 100, like 50/30/20.",
        "goals_need_three": "Bussola needs exactly 3 goals. You gave {n}.",
        # --- park ---
        "park_saved": "🧭 Parked #{id}: {summary} · Queue: {n}",
        "park_usage": "Usage: /park <what to do later>",
        # --- fix ---
        "fix_nothing": "Nothing to fix yet: no request has been classified.",
        "fix_question": "Last request: \"{summary}\" → {label}. What was it really?",
        "fix_saved": "🧭 Got it: \"{summary}\" → {label}. I'll learn from this.",
        "fix_unchanged": "Nothing changed.",
        "fix_usage": "Usage: /bussola fix [1|2|3|detour]",
        "detour": "Detour",
        "unclassified": "Not counted",
        # --- pause ---
        "pause_on": "🧭 Bussola is paused until {until}: no classification, no nudges. /bussola pause off to resume.",
        "pause_off": "🧭 Bussola is back on.",
        "pause_usage": "Usage: /bussola pause 2h | 30m | off",
        # --- demo ---
        "demo_loaded": (
            "🧭 Demo week loaded: {n} requests, {q} parked items, sample goals. "
            "Everything is marked as demo. See it with /bussola · remove it with /bussola demo clear"
        ),
        "demo_cleared": "🧭 Demo data removed.",
        "demo_kept_goals": "Your own goals were kept; the demo only added requests and queue items.",
        # --- panel ---
        "panel_title": "🧭 Bussola · {date}",
        "panel_demo": "  (includes demo data)",
        "panel_goal": "{pct:>3}% of {planned}% planned",
        "panel_detours": "Detours",
        "panel_queue": "Queue: {n} parked · {friday}",
        "panel_friday_on": "last Friday run {when}",
        "panel_friday_off": "no Friday run yet → /blueprint bussola:friday",
        "panel_health": "⚠ {bad} of the last {n} labels were too slow or failed. Pin a fast model for “Bussola classifier” (hermes model) so nudges arrive in time.",
        "panel_hidden": "Hidden priority: \"{theme}\" ({count} requests) → /bussola goals",
        "panel_self_cost": "Bussola itself used {tokens} tokens this week",
        "panel_empty": "No requests counted yet this week. Just work; Bussola counts quietly.",
        "panel_paused": "Paused until {until} · /bussola pause off",
        "panel_requests": "{n} requests counted · {tokens} tokens",
        # --- report (PNG and caption) ---
        "report_title": "Bussola · {date}",
        "report_hero": "{pct}% of your requests went to detours",
        "report_hero_sub": "{n} requests · {tokens} tokens",
        "report_planned_actual": "{actual}% · planned {planned}%",
        "report_ready": "Ready for you",
        "report_hidden": "Hidden priority: {theme} · {count} requests",
        "report_footer": "Bussola cost: {tokens} tokens · {corrections} corrections this week",
        "report_nothing_parked": "Nothing parked this week.",
        "report_waiting": "{n} parked, waiting for the Friday run.",
        "report_caption_waiting": "🧭 Your week: {pct}% went to detours. {n} parked items wait for the Friday run.",
        "report_demo": "includes demo data",
        "report_caption": "🧭 Your week: {pct}% went to detours. {ready} of {total} parked items are ready, {needs} need you.",
        "report_caption_noqueue": "🧭 Your week: {pct}% went to detours. Nothing was parked.",
        "report_caption_hidden": "Hidden priority spotted: \"{theme}\". Swap it in with /bussola goals.",
        "report_text_fallback": "(Chart unavailable: matplotlib is not installed. Text report below.)",
        "hidden_suggestion": (
            "You have a 4th priority you never declared: \"{theme}\" ({count} requests). "
            "Swap it for goal 3? → /bussola goals"
        ),
        # --- friday guard ---
        "friday_blocked": "Bussola Friday run is read-and-draft only. Mark this item needs_you.",
        # --- misc ---
        "error": "🧭 Something went wrong, so Bussola stayed out of the way. Details are in the Hermes log.",
        "help": (
            "🧭 Bussola commands\n"
            "  /bussola              your week at a glance\n"
            "  /bussola goals ...    set your 3 goals\n"
            "  /bussola fix          correct the last classification\n"
            "  /bussola pause 2h     pause (or: off)\n"
            "  /bussola report       weekly report image now\n"
            "  /bussola demo         load a sample week (clear: /bussola demo clear)\n"
            "  /park <text>          park a detour for the Friday run\n"
            "  /blueprint bussola:friday   schedule the Friday run"
        ),
        "eval_started": "🧭 Running the classifier eval on {n} messages through ctx.llm…",
        "eval_done": "🧭 Eval written to {path}\n\n{table}",
    },
    "pt": {
        "nudge_context": (
            "[Bussola · vale só para esta mensagem] As 3 metas do usuário nesta semana: {g1}; {g2}; {g3}.\n"
            "Este é o 2º pedido seguido fora dessas metas (mais próxima: {closest}).\n"
            "Antes de fazer, faça UMA pergunta curta, começando com \"🧭\", com duas opções: "
            "\"Fazer agora\" e \"Estacionar\". Use sua ferramenta clarify com exatamente essas duas opções, se tiver.\n"
            "Se escolherem \"Estacionar\": chame bussola_park com um resumo de no máximo 60 caracteres, "
            "confirme em uma linha e pare.\n"
            "Se escolherem \"Fazer agora\": faça a tarefa normalmente e não toque mais no assunto."
        ),
        "onboarding": (
            "🧭 A Bússola mantém seu agente apontado para as suas 3 metas da semana.\n"
            "Ela fica em silêncio, conta para onde vai cada pedido e só fala "
            "quando você se desvia duas vezes seguidas.\n\n"
            "Defina suas metas numa linha:\n"
            "  /bussola goals lançar a VDRI, hackathons, inglês\n\n"
            "Ou veja uma semana de exemplo antes: /bussola demo"
        ),
        "goals_split_question": "Divisão planejada da sua semana?\n1) {g1}\n2) {g2}\n3) {g3}",
        "goals_split_custom": "Outra: digite /bussola goals ... 60/30/10",
        "cancel": "Cancelar",
        "goals_saved": (
            "🧭 Metas salvas: {g1} {p1}% · {g2} {p2}% · {g3} {p3}%.\n"
            "Fico em silêncio, a menos que você se desvie duas vezes seguidas. Veja sua semana com /bussola.\n"
            "Dica: fixe um modelo rápido e barato para “Bussola classifier” em `hermes model` para cada classificação levar menos de 1 segundo."
        ),
        "goals_demo_cleared": "Os dados de demonstração foram removidos; daqui em diante só contam seus pedidos reais.",
        "goals_not_saved": "Metas não salvas. Inclua a divisão na linha para pular a pergunta: /bussola goals {names} 50/30/20",
        "goals_parse_failed": (
            "Não encontrei 3 metas nisso. Tente:\n"
            "  /bussola goals \"Lançar a VDRI: beta no ar\" \"Hackathons\" \"Inglês\" 50/30/20"
        ),
        "goals_bad_split": "A divisão precisa de 3 números inteiros que somem 100, como 50/30/20.",
        "goals_need_three": "A Bússola precisa de exatamente 3 metas. Você deu {n}.",
        "park_saved": "🧭 Estacionado #{id}: {summary} · Fila: {n}",
        "park_usage": "Uso: /park <o que fazer depois>",
        "fix_nothing": "Nada para corrigir ainda: nenhum pedido foi classificado.",
        "fix_question": "Último pedido: \"{summary}\" → {label}. O que era de verdade?",
        "fix_saved": "🧭 Entendido: \"{summary}\" → {label}. Vou aprender com isso.",
        "fix_unchanged": "Nada mudou.",
        "fix_usage": "Uso: /bussola fix [1|2|3|desvio]",
        "detour": "Desvio",
        "unclassified": "Não contado",
        "pause_on": "🧭 Bússola pausada até {until}: sem classificação, sem avisos. /bussola pause off para retomar.",
        "pause_off": "🧭 A Bússola voltou.",
        "pause_usage": "Uso: /bussola pause 2h | 30m | off",
        "demo_loaded": (
            "🧭 Semana de demonstração carregada: {n} pedidos, {q} itens estacionados, metas de exemplo. "
            "Tudo marcado como demo. Veja com /bussola · remova com /bussola demo clear"
        ),
        "demo_cleared": "🧭 Dados de demonstração removidos.",
        "demo_kept_goals": "Suas metas foram mantidas; a demo só acrescentou pedidos e itens na fila.",
        "panel_title": "🧭 Bússola · {date}",
        "panel_demo": "  (inclui dados de demonstração)",
        "panel_goal": "{pct:>3}% de {planned}% planejado",
        "panel_detours": "Desvios",
        "panel_queue": "Fila: {n} estacionados · {friday}",
        "panel_friday_on": "última Sexta do Desvio {when}",
        "panel_friday_off": "nenhuma Sexta do Desvio ainda → /blueprint bussola:friday",
        "panel_health": "⚠ {bad} das últimas {n} classificações foram lentas demais ou falharam. Fixe um modelo rápido para “Bussola classifier” (hermes model) para os avisos chegarem a tempo.",
        "panel_hidden": "Prioridade oculta: \"{theme}\" ({count} pedidos) → /bussola goals",
        "panel_self_cost": "A própria Bússola usou {tokens} tokens nesta semana",
        "panel_empty": "Nenhum pedido contado nesta semana ainda. Trabalhe; a Bússola conta em silêncio.",
        "panel_paused": "Pausada até {until} · /bussola pause off",
        "panel_requests": "{n} pedidos contados · {tokens} tokens",
        "report_title": "Bússola · {date}",
        "report_hero": "{pct}% dos seus pedidos foram desvios",
        "report_hero_sub": "{n} pedidos · {tokens} tokens",
        "report_planned_actual": "{actual}% · planejado {planned}%",
        "report_ready": "Pronto para você",
        "report_hidden": "Prioridade oculta: {theme} · {count} pedidos",
        "report_footer": "Custo da Bússola: {tokens} tokens · {corrections} correções nesta semana",
        "report_nothing_parked": "Nada estacionado nesta semana.",
        "report_waiting": "{n} estacionados, esperando a Sexta do Desvio.",
        "report_caption_waiting": "🧭 Sua semana: {pct}% foi para desvios. {n} itens estacionados esperam a Sexta do Desvio.",
        "report_demo": "inclui dados de demonstração",
        "report_caption": "🧭 Sua semana: {pct}% foi para desvios. {ready} de {total} itens estacionados estão prontos, {needs} precisam de você.",
        "report_caption_noqueue": "🧭 Sua semana: {pct}% foi para desvios. Nada foi estacionado.",
        "report_caption_hidden": "Prioridade oculta encontrada: \"{theme}\". Troque com /bussola goals.",
        "report_text_fallback": "(Gráfico indisponível: matplotlib não está instalado. Relatório em texto abaixo.)",
        "hidden_suggestion": (
            "Você tem uma 4ª prioridade que nunca declarou: \"{theme}\" ({count} pedidos). "
            "Trocar pela meta 3? → /bussola goals"
        ),
        "friday_blocked": "A Sexta do Desvio da Bússola só lê e rascunha. Marque este item como needs_you.",
        "error": "🧭 Algo deu errado, então a Bússola saiu do caminho. Detalhes no log do Hermes.",
        "help": (
            "🧭 Comandos da Bússola\n"
            "  /bussola              sua semana num relance\n"
            "  /bussola goals ...    defina suas 3 metas\n"
            "  /bussola fix          corrija a última classificação\n"
            "  /bussola pause 2h     pausa (ou: off)\n"
            "  /bussola report       relatório da semana agora\n"
            "  /bussola demo         carrega uma semana de exemplo (apagar: /bussola demo clear)\n"
            "  /park <texto>         estaciona um desvio para a Sexta do Desvio\n"
            "  /blueprint bussola:friday   agenda a Sexta do Desvio"
        ),
        "eval_started": "🧭 Rodando a avaliação do classificador em {n} mensagens pelo ctx.llm…",
        "eval_done": "🧭 Avaliação gravada em {path}\n\n{table}",
    },
}


def t(key: str, lang: str = "en", **kwargs: Any) -> str:
    """Translate ``key``; unknown languages fall back to English, never raise."""
    table = STRINGS.get(lang) or STRINGS["en"]
    template = table.get(key) or STRINGS["en"][key]
    try:
        return template.format(**kwargs) if kwargs else template
    except (KeyError, IndexError, ValueError):
        return template
