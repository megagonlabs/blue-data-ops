# Project fields

`project@2.0.0` copies selected fields from records in the first input group and can rename them. Later groups are ignored.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `kept_keys` | `attributes` | `yes` | `[]` | attribute-spec:list[str]; empty is accepted | `structured` |
| `key_mapping` | `attributes` | `yes` | `{}` | attribute-spec:dict[str, str]; mapped sources must be kept and output names must not collide | `structured` |

## Behavior

Field order follows `kept_keys`. Missing fields are omitted. A record with none of the requested fields becomes `{}`. Each output record is new. A mapping can swap names, but it cannot overwrite another projected output name. The validator currently accepts some byte strings that raw dictionary lookup treats as distinct keys.

Raw `apply()` returns `[]` for empty input or an empty `kept_keys` list. `invoke()` returns `None` for an invalid mapping. `run()` normalizes empty output to `[[]]`, contains failures and timeouts, and returns `{}` for `output_attributes`.

`explain()` uses shared statistics. There is no external disclosure, side effect, or optional extra. The default raw `refiner()` returns `[]`; no structured `refine()` method exists.
