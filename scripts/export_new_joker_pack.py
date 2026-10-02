# -*- coding: utf-8 -*-
"""Export whitelist-template jokers into an installable SMODS pack.

Writes to %APPDATA%/Balatro/Mods/New Joker Pack/ (default output under APPDATA).
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

REPO = Path(__file__).resolve().parents[1]
BATCH = REPO / "examples" / "template_jokers"
FLAT = BATCH / "mod_jokers_30.json"
SELECTED = BATCH / "relabel" / "selected_30.json"

MOD_DIR = Path(os.environ.get("APPDATA", "")) / "Balatro" / "Mods" / "New Joker Pack"

RARITY_MAP = {
    "Common": 1,
    "Uncommon": 2,
    "Rare": 3,
    "Legendary": 4,
}

# Short EN names for loc_txt (readable, not "Joker 中文")
EN_NAMES = {
    1: "Decision Scales",
    2: "Scavenger",
    3: "Curtain Call",
    4: "Gambler's Choice",
    5: "Chain Plan",
    6: "Venture Capital",
    7: "Contract Scales",
    8: "Metronome",
    9: "Underdog Rising",
    10: "Dual Track",
    11: "Tempo Master",
    12: "Kaleidoscope",
    13: "Flush Compass",
    14: "Paired Up",
    15: "Ladder Planner",
    16: "All In",
    17: "Echo Metronome",
    18: "Piggy Bank",
    19: "Palette",
    20: "Wildcard Gear",
    21: "Change Jar",
    22: "Balance Weight",
    23: "Reroll Echo",
    24: "Rebound Board",
    25: "Misaligned Joker",
    26: "Clockwork Joker",
    27: "Vault Guard",
    28: "Stubborn Remnant",
    29: "Wheel of Fate",
    30: "Placeholder",
}


def lua_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def lua_num(n) -> str:
    if isinstance(n, bool):
        return "true" if n else "false"
    if isinstance(n, int):
        return str(n)
    if isinstance(n, float):
        if n == int(n):
            return str(int(n))
        return repr(n)
    return lua_str(str(n))


def lua_list_strs(items: list[str]) -> str:
    if not items:
        return "{}"
    return "{ " + ", ".join(lua_str(x) for x in items) + " }"


def lua_extra_table(values: dict, hand_types: list[str], template: str) -> str:
    """Build config.extra table as Lua source."""
    parts: list[str] = []
    parts.append(f"template = {lua_str(template)}")

    def _lua_val(v: object) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return lua_num(v)
        if isinstance(v, str):
            return lua_str(v)
        if isinstance(v, list):
            inner = ", ".join(_lua_val(x) for x in v)
            return "{ " + inner + " }"
        if isinstance(v, dict):
            inner = ", ".join(f"{kk} = {_lua_val(vv)}" for kk, vv in v.items())
            return "{ " + inner + " }"
        return lua_str(str(v))

    for k, v in values.items():
        parts.append(f"{k} = {_lua_val(v)}")
    if hand_types:
        parts.append(f"hand_types = {lua_list_strs(hand_types)}")
    # runtime state
    parts.append("temp_mult = 0")
    parts.append("temp_chips = 0")
    parts.append("used_types = {}")
    parts.append("discard_count = 0")
    return "{ " + ", ".join(parts) + " }"


def template_loc_lines(template: str, values: dict, hand_types: list[str]) -> list[str]:
    """Game-facing CN text aligned with executable template (not ornate research prose)."""
    ht = "、".join(hand_types) if hand_types else "指定牌型"
    v = values

    def has(k):
        return k in v and v[k] not in (None, 0, 0.0)

    lines: list[str] = []
    if template == "bonus_if_last_hand":
        bits = []
        if has("mult"):
            bits.append(f"{{C:red}}+{v['mult']}{{}} 倍率")
        if has("chips"):
            bits.append(f"{{C:chips}}+{v['chips']}{{}} 筹码")
        if has("x_mult") and float(v.get("x_mult", 1)) != 1:
            bits.append(f"{{X:red,C:white}}X{v['x_mult']}{{}} 倍率")
        if has("dollars"):
            bits.append(f"{{C:money}}${v['dollars']}{{}}")
        if not bits:
            bits.append("{C:inactive}（无数值）{}")
        lines.append("回合的{C:attention}最后一手{}出牌时，")
        lines.append("获得 " + " 与 ".join(bits))
    elif template == "earn_on_discard":
        bits = []
        if has("dollars"):
            bits.append(f"{{C:money}}${v['dollars']}{{}}")
        if has("mult"):
            bits.append(f"下一手 {{C:red}}+{v['mult']}{{}} 倍率")
        if has("chips"):
            bits.append(f"下一手 {{C:chips}}+{v['chips']}{{}} 筹码")
        if not bits:
            bits.append("{C:inactive}（无弃牌奖励）{}")
        lines.append("每{C:attention}弃掉{}一张牌，")
        lines.append("获得 " + " 与 ".join(bits))
    elif template == "earn_dollars":
        lines.append(f"计分手牌时获得 {{C:money}}${v.get('dollars', 0)}{{}}")
    elif template == "earn_dollars_if_hand":
        if has("dollars"):
            lines.append(f"若牌型为 {{C:attention}}{ht}{{}}，")
            lines.append(f"获得 {{C:money}}${v['dollars']}{{}}")
        else:
            bits = []
            if has("mult"):
                bits.append(f"{{C:red}}+{v['mult']}{{}} 倍率")
            if has("chips"):
                bits.append(f"{{C:chips}}+{v['chips']}{{}} 筹码")
            lines.append(f"若牌型为 {{C:attention}}{ht}{{}}，")
            lines.append("获得 " + (" 与 ".join(bits) or "{C:inactive}奖励{}"))
    elif template == "flat_mult_if_hand":
        lines.append(f"若牌型为 {{C:attention}}{ht}{{}}，")
        lines.append(f"获得 {{C:red}}+{v.get('mult', 0)}{{}} 倍率")
    elif template == "flat_chips_if_hand":
        lines.append(f"若牌型为 {{C:attention}}{ht}{{}}，")
        lines.append(f"获得 {{C:chips}}+{v.get('chips', 0)}{{}} 筹码")
    elif template == "x_mult_if_hand":
        lines.append(f"若牌型为 {{C:attention}}{ht}{{}}，")
        lines.append(f"获得 {{X:red,C:white}}X{v.get('x_mult', 1)}{{}} 倍率")
    elif template == "xmult_with_penalty":
        lines.append(f"{{X:red,C:white}}X{v.get('x_mult', 1)}{{}} 倍率")
        pens = []
        if int(v.get("penalty_hands") or 0):
            pens.append(f"出牌次数 -{v['penalty_hands']}")
        if int(v.get("penalty_discards") or 0):
            pens.append(f"弃牌次数 -{v['penalty_discards']}")
        if int(v.get("penalty_dollars") or 0):
            pens.append(f"失去 ${v['penalty_dollars']}")
        if pens:
            lines.append("选择盲注时：" + "，".join(pens))
    elif template == "mult_per_unique_type":
        per = v.get("mult_per_type", v.get("mult", 0))
        lines.append(f"本回合每用过一种不同牌型，")
        lines.append(f"获得 {{C:red}}+{per}{{}} 倍率 × 种类数")
    elif template == "held_card_bonus":
        filt = v.get("card_filter", "any")
        filt_cn = {"any": "任意", "face": "人头", "even": "偶数", "odd": "奇数"}.get(
            str(filt), str(filt)
        )
        xm = v.get("x_mult", 1)
        lines.append(f"手中每张未打出的{{C:attention}}{filt_cn}{{}}牌")
        lines.append(f"使本牌 {{X:red,C:white}}X{xm}{{}}（叠乘）")
    elif template == "retrigger_scored":
        n = int(v.get("retrigger_count", 1))
        lines.append(f"计分牌额外触发 {{C:attention}}{n}{{}} 次")
    elif template == "bonus_interest":
        lines.append(f"额外获得 {{C:money}}${v.get('dollars', 0)}{{}} 利息")
    elif template == "scored_card_suit_bonus":
        suit = v.get("suit", "指定花色")
        bits = []
        if has("mult_per_card"):
            bits.append(f"{{C:red}}+{v['mult_per_card']}{{}} 倍率")
        if has("chips_per_card"):
            bits.append(f"{{C:chips}}+{v['chips_per_card']}{{}} 筹码")
        lines.append(f"每张计分的{{C:attention}}{suit}{{}}牌")
        lines.append("获得 " + (" 与 ".join(bits) or "{C:inactive}奖励{}"))
    elif template == "scored_card_rank_bonus":
        rc = {
            "face": "人头",
            "even": "偶数",
            "odd": "奇数",
            "fibonacci": "Fibonacci",
            "ace": "A",
            "number": "数字(2-10)",
        }.get(str(v.get("rank_class")), str(v.get("rank_class")))
        bits = []
        if has("mult_per_card"):
            bits.append(f"{{C:red}}+{v['mult_per_card']}{{}} 倍率")
        if has("chips_per_card"):
            bits.append(f"{{C:chips}}+{v['chips_per_card']}{{}} 筹码")
        lines.append(f"每张计分的{{C:attention}}{rc}{{}}牌")
        lines.append("获得 " + (" 与 ".join(bits) or "{C:inactive}奖励{}"))
    elif template == "bonus_scaled_by_money":
        btype = "倍率" if v.get("bonus_type") == "mult" else "筹码"
        cap = v.get("cap") or 0
        cap_s = f"（上限 {cap}）" if cap else ""
        lines.append(
            f"每持有 {{C:money}}${v.get('per_dollars', 5)}{{}}，"
            f"获得 {{C:attention}}+{v.get('bonus_amount', 0)}{{}} {btype}{cap_s}"
        )
    elif template == "bonus_scaled_by_discards":
        if v.get("mode") == "at_zero":
            bits = []
            if has("mult"):
                bits.append(f"{{C:red}}+{v['mult']}{{}} 倍率")
            if has("chips"):
                bits.append(f"{{C:chips}}+{v['chips']}{{}} 筹码")
            lines.append("当剩余弃牌次数为 {{C:attention}}0{{}} 时")
            lines.append("获得 " + (" 与 ".join(bits) or "{C:inactive}奖励{}"))
        else:
            bits = []
            if has("mult"):
                bits.append(f"{{C:red}}+{v['mult']}{{}} 倍率")
            if has("chips"):
                bits.append(f"{{C:chips}}+{v['chips']}{{}} 筹码")
            lines.append("每个剩余弃牌次数")
            lines.append("获得 " + (" 与 ".join(bits) or "{C:inactive}奖励{}"))
    elif template == "bonus_if_n_played":
        comp = {"le": "≤", "ge": "≥", "eq": "="}.get(str(v.get("comparator")), "?")
        bits = []
        if has("mult"):
            bits.append(f"{{C:red}}+{v['mult']}{{}} 倍率")
        if has("chips"):
            bits.append(f"{{C:chips}}+{v['chips']}{{}} 筹码")
        if has("x_mult") and float(v.get("x_mult", 1)) != 1:
            bits.append(f"{{X:red,C:white}}X{v['x_mult']}{{}} 倍率")
        lines.append(f"打出牌张数 {{C:attention}}{comp}{v.get('n', '?')}{{}} 时")
        lines.append("获得 " + (" 与 ".join(bits) or "{C:inactive}奖励{}"))
    elif template == "branched_hand_bonus":
        for br in v.get("branches") or []:
            if not isinstance(br, dict):
                continue
            ht_b = str(br.get("hand_type") or "?")
            bits = []
            if float(br.get("mult") or 0) > 0:
                bits.append(f"{{C:red}}+{br['mult']}{{}} 倍率")
            if float(br.get("chips") or 0) > 0:
                bits.append(f"{{C:chips}}+{br['chips']}{{}} 筹码")
            if float(br.get("x_mult") or 1) > 1:
                bits.append(f"{{X:red,C:white}}X{br['x_mult']}{{}} 倍率")
            if float(br.get("dollars") or 0) > 0:
                bits.append(f"{{C:money}}${br['dollars']}{{}}")
            reward = " 与 ".join(bits) if bits else "{C:inactive}奖励{}"
            lines.append(f"若牌型为 {{C:attention}}{ht_b}{{}}，获得 {reward}")
    elif template == "flat_mult":
        if has("mult"):
            lines.append(f"{{C:red}}+{v['mult']}{{}} 倍率")
        else:
            lines.append("{C:inactive}template: flat_mult{}")
    elif template == "flat_chips":
        if has("chips"):
            lines.append(f"{{C:chips}}+{v['chips']}{{}} 筹码")
        else:
            lines.append("{C:inactive}template: flat_chips{}")
    elif template == "x_mult":
        if has("x_mult"):
            lines.append(f"{{X:red,C:white}}X{v['x_mult']}{{}} 倍率")
        else:
            lines.append("{C:inactive}template: x_mult{}")
    else:
        lines.append(f"{{C:inactive}}template: {template}{{}}")
    return lines


def generate_joker_lua(
    slot: int,
    card: dict | None,
    *,
    force_common: bool = False,
    shop_weight: int = 10,
    cols: int = 10,
) -> str:
    x = (slot - 1) % cols
    y = (slot - 1) // cols
    if card is None:
        return f"""-- Placeholder slot {slot:02d} (missing intent / TBD)
SMODS.Joker{{
    key = "joker_{slot:02d}",
    config = {{ extra = {{ template = "stub" }} }},
    loc_txt = {{
        name = 'Placeholder {slot:02d}',
        text = {{
            '{{C:inactive}}Reserved slot{{}}',
            '{{C:inactive}}(awaiting final card){{}}'
        }},
        unlock = {{ 'Unlocked by default.' }}
    }},
    pos = {{ x = {x}, y = {y} }},
    display_size = {{ w = 71, h = 95 }},
    cost = 1,
    rarity = 1,
    weight = {shop_weight},
    blueprint_compat = true,
    eternal_compat = true,
    perishable_compat = true,
    unlocked = true,
    discovered = true,
    no_mod_badges = true,
    atlas = 'CustomJokers',
    calculate = function(self, card, context)
        -- stub: no effect
    end
}}
"""

    template = card["template"]
    values = dict(card.get("impl_values") or card.get("values") or {})
    hand_types = list(card.get("hand_types") or [])
    if force_common:
        rarity = 1
    else:
        rarity = RARITY_MAP.get(card.get("rarity") or "Uncommon", 2)
    cost = int(card.get("cost") or 5)
    # Human-eval: keep Common cost band so shop sees them often
    if force_common:
        cost = min(cost, 5)
    name_cn = card["name"]
    name_en = str(card.get("name_en") or EN_NAMES.get(slot, f"Joker {slot:02d}"))
    role = card.get("role") or ""
    loc_lines = template_loc_lines(template, values, hand_types)
    text_lua = ",\n            ".join(lua_str(line) for line in loc_lines)

    role_comment = f" role={role}" if role else ""
    return f"""-- {slot:02d} intent={card.get('intent_index')} {name_cn} [{template}]{role_comment}
SMODS.Joker{{
    key = "joker_{slot:02d}",
    config = {{
        extra = {lua_extra_table(values, hand_types, template)}
    }},
    loc_txt = {{
        name = {lua_str(name_cn)},
        text = {{
            {text_lua}
        }},
        unlock = {{ {lua_str(name_en)} }}
    }},
    pos = {{ x = {x}, y = {y} }},
    display_size = {{ w = 71, h = 95 }},
    cost = {cost},
    rarity = {rarity},
    weight = {shop_weight},
    blueprint_compat = true,
    eternal_compat = true,
    perishable_compat = true,
    unlocked = true,
    discovered = true,
    no_mod_badges = true,
    atlas = 'CustomJokers',
    loc_vars = function(self, info_queue, card)
        return NJP.loc_vars(card)
    end,
    calc_dollar_bonus = function(self, card)
        return NJP.calc_dollar_bonus(card)
    end,
    calculate = function(self, card, context)
        return NJP.calculate(card, context)
    end
}}
"""


TEMPLATES_LUA = r'''-- New Joker Pack template helpers (whitelist -> SMODS)
NJP = NJP or {}

local function extra(card)
    return (card.ability and card.ability.extra) or {}
end

local function hand_ok(ex, scoring_name)
    local list = ex.hand_types
    if not list or #list == 0 then
        return true
    end
    for i = 1, #list do
        if list[i] == scoring_name then
            return true
        end
    end
    return false
end

local function is_last_hand()
    return G.GAME and G.GAME.current_round and G.GAME.current_round.hands_left == 0
end

local function matches_filter(playing_card, filt)
    if not playing_card then return false end
    filt = filt or "any"
    if filt == "any" then return true end
    local id = playing_card:get_id()
    if filt == "face" then
        return id >= 11 and id <= 13
    end
    if filt == "even" then
        -- A=14 treated as even? Balatro A is 14; 2,4,6,8,10
        return id == 14 or (id >= 2 and id <= 10 and id % 2 == 0)
    end
    if filt == "odd" then
        return id == 14 or (id % 2 == 1 and id <= 13)
    end
    return true
end

-- ranks: id 2-10 number, 11=J, 12=Q, 13=K, 14=A (matches MiniBalatro J/Q/K/A)
local function matches_rank_class(playing_card, rank_class)
    if not playing_card then return false end
    local id = playing_card:get_id()
    if rank_class == "face" then return id >= 11 and id <= 13
    elseif rank_class == "even" then return id >= 2 and id <= 10 and id % 2 == 0
    elseif rank_class == "odd" then
        return (id >= 3 and id <= 9 and id % 2 == 1) or id == 14
    elseif rank_class == "fibonacci" then
        return id == 2 or id == 3 or id == 5 or id == 8 or id == 14
    elseif rank_class == "ace" then return id == 14
    elseif rank_class == "number" then return id >= 2 and id <= 10
    end
    return false
end

function NJP.loc_vars(card)
    local ex = extra(card)
    local vars = {}
    if ex.temp_mult and ex.temp_mult ~= 0 then vars[#vars + 1] = ex.temp_mult end
    return { vars = vars }
end

function NJP.calc_dollar_bonus(card)
    local ex = extra(card)
    if ex.template == "bonus_interest" then
        return tonumber(ex.dollars) or 0
    end
end

function NJP.calculate(card, context)
    local ex = extra(card)
    local template = ex.template
    if not template or template == "stub" then
        return
    end

    -- Round start: reset per-round state + penalties
    if context.setting_blind and not context.blueprint then
        ex.temp_mult = 0
        ex.temp_chips = 0
        ex.used_types = {}
        ex.discard_count = 0
        if template == "xmult_with_penalty" then
            local ph = tonumber(ex.penalty_hands) or 0
            local pd = tonumber(ex.penalty_discards) or 0
            local pm = tonumber(ex.penalty_dollars) or 0
            return {
                message = "Penalty",
                colour = G.C.RED,
                func = function()
                    G.E_MANAGER:add_event(Event({
                        func = function()
                            if ph > 0 then ease_hands_played(-ph) end
                            if pd > 0 then ease_discard(-pd) end
                            if pm > 0 then ease_dollars(-pm) end
                            return true
                        end
                    }))
                    return true
                end
            }
        end
        return
    end

    -- Discard hooks (fires once per discarded card via other_card)
    if context.discard and not context.blueprint and context.other_card and template == "earn_on_discard" then
        local dollars = tonumber(ex.dollars) or 0
        local mult = tonumber(ex.mult) or 0
        local chips = tonumber(ex.chips) or 0
        ex.discard_count = (ex.discard_count or 0) + 1
        if dollars ~= 0 then
            ease_dollars(dollars)
        end
        if mult ~= 0 then
            ex.temp_mult = (ex.temp_mult or 0) + mult
        end
        if chips ~= 0 then
            ex.temp_chips = (ex.temp_chips or 0) + chips
        end
        return {
            message = dollars ~= 0 and ("$" .. tostring(dollars)) or localize("k_upgrade_ex"),
            colour = G.C.MONEY
        }
    end

    -- Retrigger scored cards
    if context.repetition and context.cardarea == G.play and template == "retrigger_scored" then
        local n = tonumber(ex.retrigger_count) or 1
        if n > 0 then
            return {
                repetitions = n,
                message = localize("k_again_ex"),
                card = card
            }
        end
    end

    -- Main scoring
    if context.cardarea == G.jokers and context.joker_main then
        local scoring = context.scoring_name
        local ret = {}

        -- apply deferred discard temp bonuses once
        if (ex.temp_mult or 0) ~= 0 or (ex.temp_chips or 0) ~= 0 then
            if (ex.temp_mult or 0) ~= 0 then
                ret.mult = (ret.mult or 0) + ex.temp_mult
            end
            if (ex.temp_chips or 0) ~= 0 then
                ret.chips = (ret.chips or 0) + ex.temp_chips
            end
            ex.temp_mult = 0
            ex.temp_chips = 0
        end
        if template == "flat_mult" then
            ret.mult = (ret.mult or 0) + (tonumber(ex.mult) or 0)
        elseif template == "flat_chips" then
            ret.chips = (ret.chips or 0) + (tonumber(ex.chips) or 0)
        elseif template == "x_mult" then
            local xm = tonumber(ex.x_mult) or 1
            if xm ~= 1 then ret.x_mult = xm end
        elseif template == "flat_mult_if_hand" then
            if hand_ok(ex, scoring) then
                ret.mult = (ret.mult or 0) + (tonumber(ex.mult) or 0)
                if ex.chips then ret.chips = (ret.chips or 0) + (tonumber(ex.chips) or 0) end
                if ex.x_mult and tonumber(ex.x_mult) ~= 1 then ret.x_mult = tonumber(ex.x_mult) end
            end
        elseif template == "flat_chips_if_hand" then
            if hand_ok(ex, scoring) then
                ret.chips = (ret.chips or 0) + (tonumber(ex.chips) or 0)
            end
        elseif template == "x_mult_if_hand" then
            if hand_ok(ex, scoring) then
                local xm = tonumber(ex.x_mult) or 1
                if xm ~= 1 then ret.x_mult = xm end
                if ex.mult then ret.mult = (ret.mult or 0) + (tonumber(ex.mult) or 0) end
                if ex.chips then ret.chips = (ret.chips or 0) + (tonumber(ex.chips) or 0) end
            end
        elseif template == "earn_dollars" then
            local d = tonumber(ex.dollars) or 0
            if d ~= 0 then
                ret.dollars = d
            end
        elseif template == "earn_dollars_if_hand" then
            if hand_ok(ex, scoring) then
                local d = tonumber(ex.dollars) or 0
                if d ~= 0 then
                    ret.dollars = d
                else
                    -- fallback when export used mult/chips on this template
                    if ex.mult then ret.mult = (ret.mult or 0) + (tonumber(ex.mult) or 0) end
                    if ex.chips then ret.chips = (ret.chips or 0) + (tonumber(ex.chips) or 0) end
                end
            end
        elseif template == "bonus_if_last_hand" then
            -- hand_types empty = any last hand; otherwise require matching scoring name
            if is_last_hand() and hand_ok(ex, scoring) then
                if ex.mult and tonumber(ex.mult) ~= 0 then
                    ret.mult = (ret.mult or 0) + (tonumber(ex.mult) or 0)
                end
                if ex.chips and tonumber(ex.chips) ~= 0 then
                    ret.chips = (ret.chips or 0) + (tonumber(ex.chips) or 0)
                end
                if ex.x_mult and tonumber(ex.x_mult) ~= 1 then
                    ret.x_mult = tonumber(ex.x_mult)
                end
                if ex.dollars and tonumber(ex.dollars) ~= 0 then
                    ret.dollars = tonumber(ex.dollars)
                end
            end
        elseif template == "xmult_with_penalty" then
            local xm = tonumber(ex.x_mult) or 1
            if xm ~= 1 then
                ret.x_mult = xm
            end
        elseif template == "mult_per_unique_type" then
            ex.used_types = ex.used_types or {}
            if scoring and not ex.used_types[scoring] then
                ex.used_types[scoring] = true
            end
            local n = 0
            for _ in pairs(ex.used_types) do
                n = n + 1
            end
            local per = tonumber(ex.mult_per_type) or tonumber(ex.mult) or 0
            if per ~= 0 and n > 0 then
                ret.mult = (ret.mult or 0) + per * n
            end
        elseif template == "held_card_bonus" then
            local filt = ex.card_filter or "any"
            local count = 0
            if G.hand and G.hand.cards then
                for _, c in ipairs(G.hand.cards) do
                    if matches_filter(c, filt) then
                        count = count + 1
                    end
                end
            end
            local xm = tonumber(ex.x_mult) or 1
            if count > 0 and xm > 1 then
                ret.x_mult = xm ^ count
            end
            local add_m = tonumber(ex.mult) or 0
            if count > 0 and add_m ~= 0 then
                ret.mult = (ret.mult or 0) + add_m * count
            end
        elseif template == "scored_card_suit_bonus" then
            local suit = ex.suit
            local count = 0
            local hand = context.scoring_hand or {}
            for _, c in ipairs(hand) do
                if c and c:is_suit(suit) then count = count + 1 end
            end
            if count > 0 then
                local mp = tonumber(ex.mult_per_card) or 0
                local cp = tonumber(ex.chips_per_card) or 0
                if mp ~= 0 then ret.mult = (ret.mult or 0) + mp * count end
                if cp ~= 0 then ret.chips = (ret.chips or 0) + cp * count end
            end
        elseif template == "scored_card_rank_bonus" then
            local rc = ex.rank_class or "face"
            local count = 0
            local hand = context.scoring_hand or {}
            for _, c in ipairs(hand) do
                if c and matches_rank_class(c, rc) then count = count + 1 end
            end
            if count > 0 then
                local mp = tonumber(ex.mult_per_card) or 0
                local cp = tonumber(ex.chips_per_card) or 0
                if mp ~= 0 then ret.mult = (ret.mult or 0) + mp * count end
                if cp ~= 0 then ret.chips = (ret.chips or 0) + cp * count end
            end
        elseif template == "bonus_scaled_by_money" then
            local money = (G.GAME and G.GAME.dollars) or 0
            local per = math.max(1, tonumber(ex.per_dollars) or 1)
            local amount = tonumber(ex.bonus_amount) or 0
            local cap = tonumber(ex.cap) or 0
            local total = math.floor(money / per) * amount
            if cap > 0 then total = math.min(total, cap) end
            if total ~= 0 then
                if ex.bonus_type == "chips" then
                    ret.chips = (ret.chips or 0) + total
                else
                    ret.mult = (ret.mult or 0) + total
                end
            end
        elseif template == "bonus_scaled_by_discards" then
            local discards = (G.GAME and G.GAME.current_round and G.GAME.current_round.discards_left) or 0
            local mode = ex.mode or "per_discard"
            local mv = tonumber(ex.mult) or 0
            local cv = tonumber(ex.chips) or 0
            if mode == "at_zero" then
                if discards == 0 then
                    if mv ~= 0 then ret.mult = (ret.mult or 0) + mv end
                    if cv ~= 0 then ret.chips = (ret.chips or 0) + cv end
                end
            else
                if discards > 0 then
                    if mv ~= 0 then ret.mult = (ret.mult or 0) + mv * discards end
                    if cv ~= 0 then ret.chips = (ret.chips or 0) + cv * discards end
                end
            end
        elseif template == "bonus_if_n_played" then
            local n_played = #(context.full_hand or {})
            local comp = ex.comparator or "le"
            local n = tonumber(ex.n) or 0
            local ok = false
            if comp == "le" and n_played <= n then ok = true
            elseif comp == "ge" and n_played >= n then ok = true
            elseif comp == "eq" and n_played == n then ok = true
            end
            if ok then
                if ex.mult and tonumber(ex.mult) ~= 0 then
                    ret.mult = (ret.mult or 0) + (tonumber(ex.mult) or 0)
                end
                if ex.chips and tonumber(ex.chips) ~= 0 then
                    ret.chips = (ret.chips or 0) + (tonumber(ex.chips) or 0)
                end
                if ex.x_mult and tonumber(ex.x_mult) ~= 1 then
                    ret.x_mult = tonumber(ex.x_mult)
                end
            end
        elseif template == "branched_hand_bonus" then
            local branches = ex.branches or {}
            local ht = context.scoring_name
            for _, branch in ipairs(branches) do
                if branch and branch.hand_type == ht then
                    local mv = tonumber(branch.mult) or 0
                    local cv = tonumber(branch.chips) or 0
                    local xv = tonumber(branch.x_mult) or 1
                    local dv = tonumber(branch.dollars) or 0
                    if mv ~= 0 then ret.mult = (ret.mult or 0) + mv end
                    if cv ~= 0 then ret.chips = (ret.chips or 0) + cv end
                    if xv ~= 1 then ret.x_mult = xv end
                    if dv ~= 0 then ret.dollars = (ret.dollars or 0) + dv end
                    break
                end
            end
        end

        if next(ret) then
            return ret
        end
    end
end
'''


MAIN_LUA_TMPL = '''SMODS.Atlas({{
    key = "modicon",
    path = "ModIcon.png",
    px = 34,
    py = 34,
    atlas_table = "ASSET_ATLAS"
}})

SMODS.Atlas({{
    key = "CustomJokers",
    path = "CustomJokers.png",
    px = 71,
    py = 95,
    atlas_table = "ASSET_ATLAS"
}})

assert(SMODS.load_file("lib/templates.lua"))()

for i = 1, {n_cards} do
    local name = string.format("jokers/joker_%02d.lua", i)
    assert(SMODS.load_file(name))()
end

SMODS.current_mod.optional_features = function()
    return {{
        retrigger_joker = true
    }}
end
'''


def make_placeholder_sheet(out_1x: Path, out_2x: Path, labels: list[str], *, cols: int = 10, rows: int = 3) -> None:
    if Image is None:
        raise RuntimeError("Pillow required: pip install Pillow")
    cw, ch = 71, 95
    img = Image.new("RGBA", (cols * cw, rows * ch), (40, 40, 48, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
        font_sm = ImageFont.truetype("arial.ttf", 9)
    except Exception:
        font = ImageFont.load_default()
        font_sm = font
    colors = [
        (70, 110, 160),
        (90, 140, 100),
        (150, 100, 90),
        (120, 100, 150),
        (140, 130, 70),
    ]
    n = cols * rows
    for i in range(n):
        x, y = (i % cols) * cw, (i // cols) * ch
        c = colors[i % len(colors)]
        draw.rectangle([x, y, x + cw - 1, y + ch - 1], fill=c + (255,), outline=(20, 20, 20, 255))
        label = labels[i] if i < len(labels) else f"{i+1:02d}"
        draw.text((x + 4, y + 8), f"{i+1:02d}", fill=(255, 255, 255, 255), font=font)
        tag = label.encode("ascii", "ignore").decode("ascii")[:8] or "NJP"
        draw.text((x + 4, y + 28), tag, fill=(230, 230, 230, 255), font=font_sm)
    out_1x.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_1x)
    img2 = img.resize((cols * cw * 2, rows * ch * 2), Image.Resampling.NEAREST)
    img2.save(out_2x)


def make_mod_icon(out_1x: Path, out_2x: Path) -> None:
    if Image is None:
        raise RuntimeError("Pillow required")
    img = Image.new("RGBA", (34, 34), (55, 90, 140, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([4, 4, 29, 29], outline=(255, 255, 255, 255), width=2)
    d.text((8, 10), "NJ", fill=(255, 255, 255, 255))
    img.save(out_1x)
    img.resize((68, 68), Image.Resampling.NEAREST).save(out_2x)


def load_cards_from_selected(selected_path: Path, pack_path: Path | None = None) -> list[dict]:
    """Load a selected-joker JSON list from a batch directory."""
    selected = json.loads(selected_path.read_text(encoding="utf-8"))
    batch = selected_path.parent
    pack_by_id: dict = {}
    if pack_path and pack_path.exists():
        for c in json.loads(pack_path.read_text(encoding="utf-8")):
            pack_by_id[int(c["id"])] = c
            if c.get("intent_index") is not None:
                pack_by_id[("intent", int(c["intent_index"]))] = c

    out: list[dict] = []
    for i, row in enumerate(selected, start=1):
        merged = dict(row)
        ii = int(row.get("intent_index") or -1)
        src = pack_by_id.get(int(row.get("id") or -1)) or pack_by_id.get(("intent", ii))
        if src:
            if not merged.get("hand_types"):
                merged["hand_types"] = src.get("hand_types") or []
            if not merged.get("values"):
                merged["values"] = src.get("values") or {}

        # Prefer dual_agent condition.hand_types (export/pack often omit them)
        dual = batch / f"intent_{ii:02d}" / "dual_agent.json"
        if dual.exists():
            d = json.loads(dual.read_text(encoding="utf-8"))
            spec = d.get("spec") or {}
            impl = spec.get("implementation") or {}
            ht = (
                (impl.get("condition") or {}).get("hand_types")
                or impl.get("hand_types")
                or (spec.get("condition") or {}).get("hand_types")
                or d.get("hand_types")
                or []
            )
            if ht and not merged.get("hand_types"):
                merged["hand_types"] = list(ht)
            vals = impl.get("values")
            if vals and not merged.get("values"):
                merged["values"] = dict(vals)

        merged["impl_values"] = merged.get("values") or {}
        merged["hand_types"] = list(merged.get("hand_types") or [])
        merged["export_slot"] = i
        out.append(merged)
    return out


def load_cards() -> list[dict]:
    """Legacy: old P0 batch (30 cards + relabel conditions)."""
    cards = json.loads(FLAT.read_text(encoding="utf-8"))
    sel = json.loads(SELECTED.read_text(encoding="utf-8"))
    cond: dict[int, dict] = {}
    for row in sel:
        impl = (row.get("spec") or {}).get("implementation") or {}
        cond[int(row["intent_index"])] = {
            "hand_types": (impl.get("condition") or {}).get("hand_types")
            or row.get("hand_types")
            or [],
            "values": impl.get("values") or row.get("values") or {},
        }
    out = []
    for c in cards:
        ii = int(c["intent_index"])
        merged = dict(c)
        merged["hand_types"] = cond.get(ii, {}).get("hand_types") or []
        merged["impl_values"] = cond.get(ii, {}).get("values") or c.get("values") or {}
        out.append(merged)
    out.sort(key=lambda x: int(x["id"]))
    return out


def write_card_index(path: Path, cards: list[dict]) -> None:
    lines = [
        "# New Joker Pack — Card Index",
        "",
        "Effects follow whitelist `template` + `values`.",
        "Rarity forced Common; shop `weight` raised for encounter rate.",
        "",
        "| Slot | Key | CN name | Role | Intent | Template | Values | Hand types |",
        "|------|-----|---------|------|--------|----------|--------|------------|",
    ]
    for i, c in enumerate(cards, start=1):
        vals = json.dumps(c.get("impl_values") or c.get("values") or {}, ensure_ascii=False)
        ht = ", ".join(c.get("hand_types") or []) or "—"
        lines.append(
            f"| {i:02d} | joker_{i:02d} | {c['name']} | {c.get('role') or '—'} | "
            f"{c.get('intent_index')} | `{c['template']}` | `{vals}` | {ht} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readme(path: Path, *, n_cards: int) -> None:
    path.write_text(
        f"""# New Joker Pack

Human-study custom joker pack for Balatro (Steamodded). **Not** the survey/questionnaire mod (`BalatroMod` / `player_survey`).

## Install location

`%AppData%\\Balatro\\Mods\\New Joker Pack\\`

- **{n_cards}** jokers, all **Common**, shop weight ×4 (default vanilla ≈10 → 40)
- No mod-name badge on hover (`no_mod_badges`)
- Dependencies: Steamodded

## Art

1. `assets/1x/CustomJokers.png` / `assets/2x/CustomJokers.png` — 10×3 grid, 71×95 cells
2. Slot `joker_NN` → `x=(N-1)%10`, `y=floor((N-1)/10)`
3. Prefer Corinths-style reskin for the first {n_cards} slots when replacing art

## Regeneration

```text
python scripts/export_new_joker_pack.py ^
  --batch examples/template_jokers ^
  --force-common --weight 40
```
""",
        encoding="utf-8",
    )


def write_manifest(path: Path, *, n_cards: int) -> None:
    path.write_text(
        json.dumps(
            {
                "id": "newjokerpack",
                "name": "New Joker Pack",
                "author": ["Custom Joker Pack"],
                "description": (
                    f"Custom jokers ({n_cards} cards). "
                    "Separate from survey mods."
                ),
                "prefix": "njp",
                "main_file": "main.lua",
                "version": "0.2.0",
                "priority": 0,
                "badge_colour": "3A5F8A",
                "badge_text_colour": "FFFFFF",
                "dependencies": ["Steamodded (>=1.0.0~BETA-0827c)"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Export New Joker Pack to AppData")
    ap.add_argument(
        "--batch",
        type=str,
        default="",
        help="batch directory containing the selected-jokers JSON",
    )
    ap.add_argument(
        "--selected",
        type=str,
        default="",
        help="override path to selected_*.json",
    )
    ap.add_argument("--force-common", action="store_true", help="force rarity=Common")
    ap.add_argument(
        "--weight",
        type=int,
        default=40,
        help="SMODS shop weight (vanilla default ~10; 40 ≈ ×4)",
    )
    ap.add_argument(
        "--placeholder-art",
        action="store_true",
        help="regenerate placeholder atlas even if CustomJokers.png exists",
    )
    ap.add_argument(
        "--legacy-30",
        action="store_true",
        help="use the 30-card export layout",
    )
    args = ap.parse_args()

    if args.legacy_30:
        if not FLAT.exists():
            raise SystemExit(f"missing {FLAT}")
        cards = load_cards()
        force_common = False
        shop_weight = 10
    else:
        batch = Path(args.batch) if args.batch else (
            REPO / "examples" / "template_jokers"
        )
        if not batch.is_absolute():
            for p in (batch, REPO / batch, Path.cwd() / batch):
                if p.exists():
                    batch = p
                    break
        selected = Path(args.selected) if args.selected else (batch / "mod_jokers_v2_selected_15.json")
        if not selected.exists():
            raise SystemExit(f"missing selected file: {selected}")
        pack = batch / "mod_jokers_30.json"
        cards = load_cards_from_selected(selected, pack if pack.exists() else None)
        force_common = bool(args.force_common) or True  # default Common
        shop_weight = int(args.weight)

    n_cards = len(cards)
    MOD_DIR.mkdir(parents=True, exist_ok=True)
    (MOD_DIR / "jokers").mkdir(exist_ok=True)
    (MOD_DIR / "lib").mkdir(exist_ok=True)
    (MOD_DIR / "assets" / "1x").mkdir(parents=True, exist_ok=True)
    (MOD_DIR / "assets" / "2x").mkdir(parents=True, exist_ok=True)

    write_manifest(MOD_DIR / "newjokerpack.json", n_cards=n_cards)
    (MOD_DIR / "main.lua").write_text(
        MAIN_LUA_TMPL.format(n_cards=n_cards), encoding="utf-8"
    )
    (MOD_DIR / "lib" / "templates.lua").write_text(TEMPLATES_LUA, encoding="utf-8")
    write_readme(MOD_DIR / "README.md", n_cards=n_cards)
    write_card_index(MOD_DIR / "CARD_INDEX.md", cards)

    labels: list[str] = []
    for slot, c in enumerate(cards, start=1):
        (MOD_DIR / "jokers" / f"joker_{slot:02d}.lua").write_text(
            generate_joker_lua(
                slot,
                c,
                force_common=force_common,
                shop_weight=shop_weight,
            ),
            encoding="utf-8",
        )
        labels.append(c["name"])

    # Remove leftover jokers from older 30-card installs
    for old in (MOD_DIR / "jokers").glob("joker_*.lua"):
        try:
            num = int(old.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        if num > n_cards:
            old.unlink()
            print(f"removed stale {old.name}")

    art_1x = MOD_DIR / "assets" / "1x" / "CustomJokers.png"
    art_2x = MOD_DIR / "assets" / "2x" / "CustomJokers.png"
    if args.placeholder_art or not art_1x.exists():
        make_placeholder_sheet(art_1x, art_2x, labels)
    else:
        print(f"kept existing art: {art_1x}")

    icon_1x = MOD_DIR / "assets" / "1x" / "ModIcon.png"
    if not icon_1x.exists():
        make_mod_icon(icon_1x, MOD_DIR / "assets" / "2x" / "ModIcon.png")

    print(f"Wrote mod to {MOD_DIR}")
    print(f"Cards: {n_cards} | Common={force_common} | weight={shop_weight}")
    for i, c in enumerate(cards, start=1):
        print(f"  {i:02d} [{c.get('role')}] {c.get('name')} `{c.get('template')}`")


if __name__ == "__main__":
    main()
