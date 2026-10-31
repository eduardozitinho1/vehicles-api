"""Gera a especificação OpenAPI 3 a partir das mesmas tabelas usadas pelo app."""

SWAGGER_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Vehicles API - Docs</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css">
</head><body><div id="ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
<script>SwaggerUIBundle({url: "/openapi.json", dom_id: "#ui", deepLinking: true});</script>
</body></html>"""

_DESC = {
    "year": "Ano do modelo exato", "year_min": "Ano mínimo", "year_max": "Ano máximo",
    "price_min": "Preço mínimo (USD)", "price_max": "Preço máximo (USD)",
    "hp_min": "Potência mínima (hp)", "hp_max": "Potência máxima (hp)",
    "range_min": "Autonomia mínima (milhas)", "mpg_city_min": "mpg cidade mínimo",
    "mpg_highway_min": "mpg estrada mínimo", "safety_min": "Nota de segurança mínima (0-5)",
    "cylinders": "Número de cilindros", "doors": "Número de portas",
}


def _q(name, schema, desc, example=None):
    p = {"name": name, "in": "query", "required": False, "description": desc, "schema": schema}
    if example is not None:
        p["example"] = example
    return p


def build_spec(columns, sortable, categorical, numeric, group_by, max_limit, facets):
    filters = []
    for col in categorical:
        sample = ", ".join(facets[col][:4])
        filters.append(_q(col, {"type": "string"},
                          f"Filtra por {col}. Aceita vários valores separados por vírgula; "
                          f"não diferencia maiúsculas. Ex.: {sample}"))
    for name, typ in numeric.items():
        filters.append(_q(name, {"type": "integer" if typ == "int" else "number"}, _DESC[name]))

    paging = [
        _q("page", {"type": "integer", "minimum": 1, "default": 1}, "Página"),
        _q("limit", {"type": "integer", "minimum": 1, "maximum": max_limit, "default": 20},
           "Itens por página"),
        _q("sort", {"type": "string", "enum": sortable, "default": "vehicle_id"}, "Campo de ordenação"),
        _q("order", {"type": "string", "enum": ["asc", "desc"], "default": "asc"}, "Direção"),
        _q("fields", {"type": "string"},
           "Campos a retornar, separados por vírgula. Ex.: make,model,price_usd"),
    ]
    int_cols = {"vehicle_id", "model_year", "cylinders", "horsepower_hp", "weight_lb", "doors", "range_miles"}
    str_cols = {"vin", "make", "model", "vehicle_type", "fuel_type", "transmission", "drivetrain",
                "origin_country", "assembly_country", "exterior_color"}
    props = {}
    for c in columns:
        t = "integer" if c in int_cols else "string" if c in str_cols else "number"
        props[c] = {"type": t, **({"nullable": True} if c in
                                  {"mpg_city", "mpg_highway", "safety_rating_5"} else {})}
    vehicle = {"$ref": "#/components/schemas/Vehicle"}
    err = {"description": "Erro", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
    ok = lambda schema, d="OK": {"description": d, "content": {"application/json": {"schema": schema}}}

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Vehicles API",
            "version": "1.0.0",
            "description": "API pública e somente-leitura com 1.000.000 de veículos **fictícios** "
                           "(VINs, preços e especificações gerados sinteticamente). "
                           "Sem autenticação; limite por IP (ver cabeçalho `X-RateLimit-Limit`).",
        },
        "paths": {
            "/vehicles": {"get": {
                "summary": "Lista veículos (filtros, ordenação e paginação)", "tags": ["Veículos"],
                "parameters": paging + filters,
                "responses": {
                    "200": ok({"type": "object", "properties": {
                        "data": {"type": "array", "items": vehicle},
                        "meta": {"type": "object", "properties": {
                            "page": {"type": "integer"}, "limit": {"type": "integer"},
                            "total": {"type": "integer"}, "total_pages": {"type": "integer"}}}}}),
                    "400": err}}},
            "/vehicles/{id}": {"get": {
                "summary": "Busca um veículo pelo ID", "tags": ["Veículos"],
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                "responses": {"200": ok(vehicle), "404": err}}},
            "/vehicles/vin/{vin}": {"get": {
                "summary": "Busca um veículo pelo VIN", "tags": ["Veículos"],
                "parameters": [{"name": "vin", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": ok(vehicle), "404": err}}},
            "/vehicles/random": {"get": {
                "summary": "Veículos aleatórios", "tags": ["Veículos"],
                "parameters": [_q("n", {"type": "integer", "minimum": 1, "maximum": max_limit, "default": 1},
                                  "Quantidade")],
                "responses": {"200": ok({"type": "object", "properties": {
                    "data": {"type": "array", "items": vehicle}}})}}},
            "/facets": {"get": {
                "summary": "Valores possíveis de cada filtro categórico e faixas numéricas",
                "tags": ["Metadados"], "responses": {"200": ok({"type": "object"})}}},
            "/models": {"get": {
                "summary": "Lista de modelos (opcionalmente de uma marca) com contagem",
                "tags": ["Metadados"],
                "parameters": [_q("make", {"type": "string"}, "Marca(s), separadas por vírgula")],
                "responses": {"200": ok({"type": "object"})}}},
            "/stats": {"get": {
                "summary": "Estatísticas agregadas (preço, potência, consumo...) com os mesmos filtros",
                "tags": ["Estatísticas"],
                "parameters": [
                    _q("group_by", {"type": "string", "enum": group_by}, "Agrupar por"),
                    _q("limit", {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
                       "Máx. de grupos")] + filters,
                "responses": {"200": ok({"type": "object"}), "400": err}}},
            "/health": {"get": {"summary": "Verificação de saúde", "tags": ["Metadados"],
                                "responses": {"200": ok({"type": "object"})}}},
        },
        "components": {"schemas": {
            "Vehicle": {"type": "object", "properties": props},
            "Error": {"type": "object", "properties": {"error": {"type": "object", "properties": {
                "code": {"type": "string"}, "message": {"type": "string"}}}}},
        }},
    }
