from django.db import connection


def intelligence_layer_tables_exist() -> bool:
    table_names = set(connection.introspection.table_names())
    required = {
        "skills_businesscategory",
        "skills_marketcategory",
        "skills_skillbusinesscategory",
        "skills_skillmarketcategory",
    }
    return required.issubset(table_names)
