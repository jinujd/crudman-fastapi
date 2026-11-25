---
title: Validation
---

# Validation

:::info Planned for 0.1.0
:::

Request bodies for create, update and save are validated with Pydantic models generated from your
SQLAlchemy model.

## Generated rules

| Column | Rule |
| --- | --- |
| `String(n)` | string, `max_length=n` |
| `Integer`, `BigInteger` | integer |
| `Numeric`, `Float` | number |
| `Boolean` | boolean |
| `Date`, `DateTime` | ISO date / datetime |
| non-nullable, no default | required on create (non-empty for strings) |
| nullable or has a default | optional |
| primary key, server default, `created_at`, `updated_at`, `deleted_at` | not accepted on write |

- **Create** rejects unknown fields.
- **Update (PATCH)** makes every field optional and drops unknown fields.
- `attributes.write` include/exclude narrows what can be written.

## Override the rules per request

`get_final_validation_rules(rules, ctx)` may return a Pydantic model class, or a rule dict in the same
style as crudman-nestjs (fastest-validator):

```python
def final_rules(rules, ctx):
    return {
        **rules,
        "name": {"type": "string", "min": 3, "max": 100},
        "revenue": {"type": "number", "min": 0, "optional": True},
        "is_active": {"optional": False},          # type defaults to "string" when missing, as in NestJS
    }

def final_model(model, ctx):
    class Extended(model):
        email: EmailStr
    return Extended
```

## Errors

Validation errors return HTTP 400:

```json
{
  "data": null,
  "success": false,
  "errors": [
    { "type": "required", "field": "name", "message": "The name field is required." },
    { "type": "unique", "field": "email", "message": "email must be unique" }
  ]
}
```
