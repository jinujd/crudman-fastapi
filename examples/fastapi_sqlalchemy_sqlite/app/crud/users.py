from crudman import Section

users = Section(
    list={
        "filters_whitelist": ["name", "email", "created_at"],
        "sorting_whitelist": ["name", "created_at"],
        "keyword": {"searchable_fields": ["name", "email"]},
    },
    create={"fields_for_uniqueness_validation": ["email", "phone"]},
    update={"fields_for_uniqueness_validation": ["email", "phone"]},
)
