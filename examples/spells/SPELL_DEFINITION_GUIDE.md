# Spell & Action Definition Guide

How to write weapon attacks and spells as JSON for Arbiter Arena. A spell is a file in
`examples/spells/` (scanned at startup), or an entry in a creature's `"actions"` array.

**This guide teaches; the [Block Reference](../../docs/current/BLOCK_REFERENCE.md) is the
authority.** The reference is generated from the engine's block registry and lists every
arg each block accepts, every event a trigger can listen for, and every `context` key.
It cannot fall behind the code. Where this guide and the reference disagree, the
reference wins.

---

## Contents

1. [The one idea: everything is a program](#the-one-idea-everything-is-a-program)
2. [Weapon attacks](#weapon-attacks)
3. [Spells: top-level fields](#spells-top-level-fields)
4. [How a program runs](#how-a-program-runs)
5. [Targets and fan-out](#targets-and-fan-out)
6. [Patterns](#patterns)
7. [Triggers in depth](#triggers-in-depth)
8. [Expressions](#expressions)
9. [Reference tables](#reference-tables)

---

## The one idea: everything is a program

A spell, a weapon attack and a rule are all a **`program`**: an ordered list of
**blocks**. Each block is an object with a `"block"` key naming its type, plus that
type's args. Some blocks nest a sub-program under `"then"`.

```json
{
  "program": [
    { "block": "attack_roll", "attack_bonus": "use_caster_bonus" },
    { "block": "damage", "damage_type": "FIRE", "formula": "1d10", "requires_hit": true }
  ]
}
```

Blocks share a per-cast **`context`**. Earlier blocks write results (`context.hit`,
`context.damage_dealt`, `context.save_success`), and later blocks read them.

**Every program is validated when it loads.** A mistake is a named error at startup,
not a silent no-op mid-fight. The loader rejects:
- a block type that doesn't exist;
- an arg the block doesn't declare (with a did-you-mean suggestion);
- a value of the wrong kind or outside its allowed set;
- a block that needs one target but would get a set, or the reverse;
- a `context.X` that no block writes;
- an `event.<field>` that the enclosing trigger's event doesn't carry;
- an expression that won't parse, or that leaves the sandbox;
- a `then` on a block that never runs one.

A file without a `program` does not load. The old `effects` form is retired and is
refused by name.

A key starting with `_` (such as `"_note"`) is ignored, so use it for comments.

---

## Weapon attacks

A weapon is written in a short flat form. The engine builds its program for you: one
`attack_roll`, then one `damage` block per damage entry, each needing a hit.

```json
{
  "name": "Longsword",
  "description": "A melee weapon attack.",
  "type": "attack",
  "range_ft": 5,
  "bonus_to_hit": 7,
  "damage": [
    { "type": "SLASHING", "formula": "1d8+4" }
  ]
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `name` | yes | string | — | Display name |
| `description` | | string | `""` | Flavour text |
| `type` | yes | `"attack"` | — | Marks this as a weapon attack |
| `range_ft` | | number | `5` | Reach or range in feet |
| `bonus_to_hit` | | int | `0` | Added to the d20 attack roll |
| `damage` | | list | `[]` | Entries of `{ "type", "formula" }`, or `{ "type", "amount" }` for a fixed value |
| `cost` | | object | 1 action | `{ "actions", "bonus_actions", "reactions", "movement" }` |
| `recharge` | | string | — | e.g. `"Recharge 5-6"` |
| `legendary_action_cost` | | int | `0` | If above 0, usable only as a legendary action |
| `program` | | list | built from the above | Write one when the weapon needs more than hit-then-damage |

A weapon that needs more, such as a poisoned blade with a rider save, writes its own
`program`. It is validated exactly like a spell's:

```json
{
  "name": "Poisoned Dagger",
  "description": "A dagger coated in poison.",
  "type": "attack",
  "range_ft": 5,
  "program": [
    { "block": "attack_roll", "attack_bonus": 5 },
    { "block": "damage", "damage_type": "PIERCING", "formula": "1d4+3", "requires_hit": true },
    { "block": "saving_throw", "attribute": "constitution", "dc": 13,
      "condition": "context.hit" },
    { "block": "damage", "damage_type": "POISON", "formula": "2d6", "requires_hit": true,
      "save_result": { "on_success": "half_damage" } }
  ]
}
```

---

## Spells: top-level fields

```json
{
  "name": "Fire Bolt",
  "description": "You hurl a mote of fire at a creature or object within range.",
  "type": "spell",
  "spell_level": 0,
  "spell_range": { "type": "feet", "distance_ft": 120 },
  "targeting_type": "single_target",
  "casting_time": { "type": "action", "count": 1 },
  "duration": { "unit": "instantaneous" },
  "components": { "verbal": true, "somatic": true, "material": [] },
  "program": [
    { "block": "attack_roll", "attack_bonus": "use_caster_bonus" },
    { "block": "damage", "damage_type": "FIRE", "formula": "1d10", "requires_hit": true }
  ]
}
```

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `name` | yes | string | — | Display name |
| `description` | | string | `""` | Flavour text |
| `type` | yes | `"spell"` | — | Marks this as a spell |
| `program` | yes | list | — | What the spell does. See [How a program runs](#how-a-program-runs) |
| `spell_level` | | int 0–9 | `0` | 0 is a cantrip |
| `spell_range` | | object | touch | See [Range](#range) |
| `targeting_type` | | string | `"single_target"` | See [Targets and fan-out](#targets-and-fan-out) |
| `aoe` | if AoE | object | — | `{ "shape", "size_ft" }`, required when `targeting_type` is `"aoe"`. See [AoE shapes](#aoe-shapes) |
| `casting_time` | | object | 1 action | Also sets the cost. See [Casting time](#casting-time) |
| `duration` | | object | instantaneous | See [Duration](#duration) |
| `components` | | object | V and S | `{ "verbal", "somatic", "material": [ ... ] }` |
| `can_target_self` | | bool | `false` | Whether the caster may target themselves |
| `cannot_cause_self_damage` | | bool | `false` | Leave the caster out of the spell's area |
| `higher_level_scaling` | | string | — | **Display text only.** Real upcasting is the `damage` block's `scaling` arg (below) |
| `cost` | | object | from casting time | Overrides the cost, as for weapons |
| `recharge` | | string | — | e.g. `"Recharge 5-6"` |
| `legendary_action_cost` | | int | `0` | If above 0, usable only as a legendary action |
| `animation` | | list | `[]` | Visual frames, ignored by the engine. See [ANIMATION_GUIDE.md](ANIMATION_GUIDE.md) |

### Range

`spell_range` is `{ "type": ..., "distance_ft": ... }`.

| `type` | Meaning |
|---|---|
| `feet` | Up to `distance_ft` (required). An area's aim point is clamped to it |
| `touch` | Within 5 ft |
| `self` | Starts at the caster (Thunderwave's cube, a ward on yourself); no distance check |
| `sight` / `unlimited` / `special` | No distance is enforced |

### Casting time

`casting_time` is `{ "type": ..., "count": 1 }`, plus optional free-text
`reaction_trigger` or `special_description`. Unless you set `cost` yourself, the type
decides what the cast spends:

| `type` | Spends |
|---|---|
| `action` | 1 action |
| `bonus_action` | 1 bonus action |
| `reaction` | 1 reaction |
| `instant`, `minute`, `hour`, `special` | 1 action (the default); set `cost` for anything else |

### Duration

`duration` is `{ "unit": ..., "count": 1, "concentration": false }`, with `unit` one of
`instantaneous`, `round`, `minute`, `hour`, `day`, `until_dispelled`, `special`.

This field describes the spell. **It does not end anything by itself.** What the spell
leaves behind is ended by a [`lifetime`](#a-concentration-buff-shield-of-faith) block in
its program, which is where concentration and expiry actually happen.

---

## How a program runs

- **Top to bottom.** A gate (`attack_roll`, `saving_throw`) must come before the blocks
  that read its result.
- **`requires_hit`** on `damage` skips it after a miss. `save_result` adjusts damage
  after a save (`half_damage` or `no_damage`).
- **`condition`** works on every block: an [expression](#expressions), and the block is
  skipped when it is false. `"condition": "not context.save_success"` applies something
  only on a failed save.
- **Upcasting.** `damage` takes
  `"scaling": { "per_slot_above": 3, "add_dice": "1d6" }`, adding `1d6` per slot level
  above 3rd. `context.slot_level` holds the slot the spell was cast at.
- **What lasts.** Anything that should outlive the cast (a buff, a granted action, a
  reaction) goes inside a `lifetime` block. Ending the lifetime removes all of it.

Each block's args, defaults and context reads and writes are in the
[Block Reference](../../docs/current/BLOCK_REFERENCE.md).

---

## Targets and fan-out

A block acts on the **current target**. A block that takes a `target` arg chooses:
- **`current`** (the default): the creature the spell is acting on now.
- **`self`**: the block's owner, the caster (or, inside a trigger, the rider's holder).

There is no `"defender"` or `"caster"` value for a block's `target`.

| `targeting_type` | What the caster supplies | How to write the program |
|---|---|---|
| `single_target` | one creature | flat blocks |
| `multi_target` | one target per projectile (repeats allowed) | wrap in `for_each_target`; each projectile rolls on its own |
| `aoe` | an aim point; every creature in the area is caught | wrap in `for_each_target` and put `roll_once` on the damage |

**Always wrap an area spell in `for_each_target`.** The trap: a flat program also runs
once per target, so an AoE without the wrapper still works, but **each target rolls its
own damage**. That breaks the rule that every creature in a Fireball takes the same
roll. `roll_once` shares one roll only inside `for_each_target`; outside it, it is
currently ignored without a warning.

---

## Patterns

Each example is copied from a shipped spell in `examples/spells/`, with its other fields
left out. A test holds every example here to the shipped file, so what you read is what
runs.

### Attack, then damage: Fire Bolt

```json
{
  "name": "Fire Bolt",
  "program": [
    { "block": "attack_roll", "attack_bonus": "use_caster_bonus" },
    { "block": "damage", "damage_type": "FIRE", "formula": "1d10", "requires_hit": true }
  ]
}
```

### Save for half in an area: Fireball

One save per creature, one shared roll, half damage on a success.

```json
{
  "name": "Fireball",
  "program": [
    { "block": "for_each_target", "then": [
      { "block": "saving_throw", "attribute": "dexterity", "dc": "use_caster_dc" },
      { "block": "damage", "damage_type": "FIRE", "formula": "8d6", "roll_once": true,
        "save_result": { "on_success": "half_damage" } }
    ]}
  ]
}
```

### Healing: Cure Wounds

```json
{
  "name": "Cure Wounds",
  "program": [
    { "block": "healing", "target": "current", "formula": "1d8",
      "bonus": "event.caster.spellcasting_modifier" }
  ]
}
```

`healing` takes either `formula` (plus an optional `bonus`) or a computed `amount`.

### Save or suffer a condition: Charm Person

`apply_condition` adds the condition and also installs its rules from
`rules/entity_effects/conditions/` (charmed, prone, blinded, and so on), so the
condition actually does something. `bindings` captures a value at cast time, read later
by the condition's rules as `instance_fields.<name>`: here, who did the charming.

```json
{
  "name": "Charm Person",
  "program": [
    { "block": "saving_throw", "attribute": "wisdom", "dc": "use_caster_dc" },
    { "block": "apply_condition", "condition_type": "charmed", "target": "current",
      "condition": "not context.save_success",
      "bindings": { "charmer": "event.caster" } }
  ]
}
```

### A concentration buff: Shield of Faith

A `lifetime` holds what the spell leaves behind. `kind: "concentration"` ends it when the
caster's concentration does, which also replaces any earlier concentration spell.
Ending the lifetime removes the modifier.

```json
{
  "name": "Shield of Faith",
  "program": [
    { "block": "lifetime", "kind": "concentration", "source": "shield_of_faith", "then": [
      { "block": "add_modifier", "target": "current", "stat": "ac", "value": 2,
        "source": "Shield of Faith", "effect_name": "shield_of_faith" }
    ]}
  ]
}
```

`lifetime` kinds are `concentration`, `rounds` (with `duration_rounds`, or permanent if
you leave it out) and `instant`.

### Something every turn: Haste

A `trigger` inside a lifetime subscribes to an event for as long as the lifetime lasts.
Here, at the start of each of the hasted creature's turns, it gains an extra action.

```json
{
  "name": "Haste",
  "program": [
    { "block": "lifetime", "kind": "concentration", "source": "haste",
      "duration_rounds": 10, "then": [
      { "block": "trigger", "event": "TURN_START", "holder": "defender",
        "when": "event.entity == entity", "then": [
        { "block": "add_resource", "target": "current", "resource": "actions",
          "amount": 1 }
      ]}
    ]}
  ]
}
```

### A ward that ends itself: Rime Ward

Temporary hit points, cold damage back at whoever hits the warded creature, and an end
to the whole effect once the temporary hit points are gone. `rebind_target` points the
rider's body at the attacker; `end_lifetime` closes the lifetime from inside.

```json
{
  "name": "Rime Ward",
  "program": [
    { "block": "lifetime", "kind": "rounds", "source": "rime_ward", "then": [
      { "block": "grant_temporary_hp", "target": "current", "amount": 5 },
      { "block": "trigger", "event": "ATTACK_HIT", "holder": "defender",
        "rebind_target": "event.attacker", "when": "event.defender == entity", "then": [
        { "block": "damage", "damage_type": "COLD", "formula": "5",
          "condition": "entity.temporary_hp > 0" }
      ]},
      { "block": "trigger", "event": "DAMAGE_DEALT", "holder": "defender",
        "when": "event.defender == entity", "then": [
        { "block": "end_lifetime", "condition": "entity.temporary_hp <= 0" }
      ]}
    ]}
  ]
}
```

### Grant an action, with a rider: Vampiric Touch

The cast attacks and heals at once. While concentration lasts, the caster also gets a
repeatable attack, plus a rider that heals them from what it deals.

```json
{
  "name": "Vampiric Touch",
  "program": [
    { "block": "attack_roll", "attack_bonus": "use_caster_bonus" },
    { "block": "damage", "damage_type": "NECROTIC", "formula": "3d6", "requires_hit": true },
    { "block": "healing", "target": "self", "amount": "context.damage_dealt // 2",
      "condition": "context.damage_dealt > 0" },
    { "block": "lifetime", "kind": "concentration", "source": "vampiric_touch",
      "duration_rounds": 10, "then": [
      { "block": "grant_action", "target": "self", "name": "Vampiric Touch",
        "description": "Melee spell attack granted by Vampiric Touch concentration.",
        "bonus_to_hit": "event.caster.spell_attack_bonus", "range_ft": 5,
        "damage": [ { "type": "NECROTIC", "formula": "3d6" } ] },
      { "block": "trigger", "event": "DAMAGE_DEALT", "holder": "caster",
        "when": "event.source == entity and event.action_name == 'Vampiric Touch'",
        "then": [
        { "block": "healing", "target": "self", "formula": "0",
          "bonus": "event.total // 2" }
      ]}
    ]}
  ]
}
```

More shipped spells are worth reading as examples: Magic Missile (`multi_target`),
Thunderwave (an area from `self`), Scorching Ray, and Guiding Bolt.

---

## Triggers in depth

A `trigger` runs its `then` body every time an event fires, for as long as its enclosing
`lifetime` lasts.

| Arg | What it does |
|---|---|
| `event` | The event to listen for, such as `TURN_START`, `ATTACK_HIT` or `DAMAGE_INCOMING` |
| `holder` | Whose rider this is: `caster` or `defender` (the spell's target). Inside the trigger, `entity` is the holder |
| `when` | A guard, checked when the event fires; the body runs only when it is true |
| `rebind_target` | The creature the body acts on, e.g. `"event.attacker"` |
| `bindings` | Values captured once, when the trigger is installed, and read later as `instance_fields.<name>` |
| `priority` | Order among handlers of the same event; lower runs later |

**Guard with `when`.** An event fires for every creature, so almost every trigger needs
a guard such as `event.entity == entity` (my turn) or `event.defender == entity` (I was
hit).

**Which fields an event carries.** Inside a trigger, `event.<field>` must be a field of
that event, or the spell fails to load. The generated list is in the reference's
[Events section](../../docs/current/BLOCK_REFERENCE.md#events). This check matters,
because at run time a guard that names a missing field would silently count as "did
not fire".

**Changing the event itself.** These blocks modify the event in flight, so they only
make sense inside a trigger: `cancel`, `grant_advantage`, `grant_disadvantage`,
`force_critical` and `modify_damage`. The condition rules in
`rules/entity_effects/conditions/` are written this way: `blinded.json` grants
advantage against the blinded creature, for example.

---

## Expressions

Several args take an **expression**: a small, sandboxed Python expression evaluated
during play. Look for "an expression" in the Kind column of the reference.

| Name | What it is |
|---|---|
| `event` | On a cast: `event.caster`, `event.defender` (the current target) and `event.action`. In a trigger: that event's fields |
| `context` | This cast's context, e.g. `context.damage_dealt`. The keys are in the reference's [Context keys section](../../docs/current/BLOCK_REFERENCE.md#context-keys) |
| `entity` | The block's owner: the caster, or, in a trigger, the holder |
| `instance_fields` | Values a trigger or condition captured through `bindings` |
| `save_success`, `save_roll` | Short for `context.save_success` and `context.save_roll` |

Useful creature attributes include `spellcasting_modifier`, `spell_attack_bonus`,
`spell_save_dc`, `temporary_hp` and `ac`.

**Allowed:** arithmetic, comparisons, `and`/`or`/`not`, attribute access, indexing,
and calls to `max`, `min`, `abs`, `int`, `round`, `bool`, `len` and `hasattr`.

**Not allowed:** assignment, imports, comprehensions, lambdas, method calls, any other
function, any other top-level name, and anything starting with `_`. All of these are
rejected when the spell loads.

```
"event.caster.spellcasting_modifier"   a bonus equal to the caster's modifier
"context.damage_dealt // 2"            half the damage dealt so far
"not context.save_success"             only on a failed save
"event.defender == entity"             in a trigger: only when I am the one hit
"max(10, event.total // 2)"            at least 10
```

---

## Reference tables

### Damage types

`ACID`, `BLUDGEONING`, `COLD`, `FIRE`, `FORCE`, `LIGHTNING`, `NECROTIC`, `PIERCING`,
`POISON`, `RADIANT`, `SLASHING`, `THUNDER`, `GENERIC`

### Saving throw attributes

`strength`, `dexterity`, `constitution`, `intelligence`, `wisdom`, `charisma`

### Conditions

`blinded`, `charmed`, `deafened`, `exhaustion`, `frightened`, `grappled`,
`incapacitated`, `invisible`, `paralyzed`, `petrified`, `poisoned`, `prone`,
`restrained`, `stunned`, `unconscious`

### AoE shapes

`aoe` is `{ "shape": ..., "size_ft": ... }`.

| `shape` | `size_ft` means |
|---|---|
| `sphere` | Radius |
| `cylinder` | Radius; the height equals the radius |
| `cone` | Length |
| `line` | Length; the width is 5 ft |
| `cube` | Side length, extending away from the caster from the face nearest them |
| `special` | Not modelled geometrically |

A custom cylinder height or line width is not supported yet.
