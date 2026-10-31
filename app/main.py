"""API somente-leitura de veículos (dados fictícios). Starlette + SQLite."""
import math
import os
import random
import sqlite3
import threading
import time
from collections import defaultdict

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from .openapi import build_spec, SWAGGER_HTML

DB_PATH = os.environ.get(
    "DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "vehicles.db")
)
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "120"))  # 0 desliga
MAX_LIMIT = 100
QUERY_TIMEOUT_S = 5.0

COLUMNS = [
    "vehicle_id", "vin", "make", "model", "model_year", "vehicle_type", "fuel_type",
    "engine_displacement_l", "cylinders", "horsepower_hp", "torque_lb_ft", "transmission",
    "drivetrain", "weight_lb", "length_in", "doors", "mpg_city", "mpg_highway",
    "range_miles", "price_usd", "origin_country", "assembly_country", "exterior_color",
    "safety_rating_5",
]
SORTABLE = ["vehicle_id", "make", "model_year", "price_usd", "horsepower_hp"]

# Filtros categóricos (aceitam vários valores separados por vírgula, sem diferenciar maiúsculas)
CATEGORICAL = [
    "make", "model", "vehicle_type", "fuel_type", "transmission", "drivetrain",
    "origin_country", "assembly_country", "exterior_color",
]
# Filtros numéricos: parâmetro -> (coluna, operador, tipo)
NUMERIC = {
    "year": ("model_year", "=", int),
    "year_min": ("model_year", ">=", int),
    "year_max": ("model_year", "<=", int),
    "price_min": ("price_usd", ">=", float),
    "price_max": ("price_usd", "<=", float),
    "hp_min": ("horsepower_hp", ">=", int),
    "hp_max": ("horsepower_hp", "<=", int),
    "range_min": ("range_miles", ">=", int),
    "mpg_city_min": ("mpg_city", ">=", float),
    "mpg_highway_min": ("mpg_highway", ">=", float),
    "safety_min": ("safety_rating_5", ">=", float),
    "cylinders": ("cylinders", "=", int),
    "doors": ("doors", "=", int),
}
GROUP_BY = [
    "make", "vehicle_type", "fuel_type", "model_year", "drivetrain", "transmission",
    "origin_country", "assembly_country", "exterior_color",
]

_local = threading.local()


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def db():
    con = getattr(_local, "con", None)
    if con is None:
        con = sqlite3.connect(f"file:{os.path.abspath(DB_PATH)}?mode=ro", uri=True,
                              check_same_thread=False)
        con.row_factory = sqlite3.Row
        _local.con = con
    return con


def run(sql, params=()):
    """Executa com timeout para uma consulta cara não travar o servidor."""
    con = db()
    deadline = time.monotonic() + QUERY_TIMEOUT_S
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 100_000)
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise ApiError(503, "query_timeout", "Consulta demorou demais; use mais filtros.")
        raise
    finally:
        con.set_progress_handler(None, 0)


# ---- valores canônicos para busca sem diferenciar maiúsculas ----
_facets = None
_facets_lock = threading.Lock()


def facets():
    global _facets
    if _facets is None:
        with _facets_lock:
            if _facets is None:
                f = {}
                for col in CATEGORICAL:
                    f[col] = [r[0] for r in run(
                        f"SELECT DISTINCT {col} FROM vehicles WHERE {col} IS NOT NULL ORDER BY 1")]
                _facets = f
    return _facets


def canonical(col, raw):
    lookup = {v.lower(): v for v in facets()[col]}
    out = []
    for item in raw.split(","):
        item = item.strip()
        if item:
            out.append(lookup.get(item.lower()))
    return out


def build_where(q):
    """Converte os query params em (cláusula WHERE, parâmetros)."""
    clauses, params = [], []
    for col in CATEGORICAL:
        raw = q.get(col)
        if raw is None:
            continue
        vals = canonical(col, raw)
        known = [v for v in vals if v is not None]
        if not known:  # valor inexistente -> nenhum resultado (e não erro)
            clauses.append("0")
            continue
        clauses.append(f"{col} IN ({','.join('?' * len(known))})")
        params += known
    for name, (col, op, typ) in NUMERIC.items():
        raw = q.get(name)
        if raw is None:
            continue
        try:
            val = typ(raw)
        except ValueError:
            raise ApiError(400, "invalid_parameter", f"'{name}' deve ser um número{' inteiro' if typ is int else ''}.")
        clauses.append(f"{col} {op} ?")
        params.append(val)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def int_param(q, name, default, lo, hi):
    raw = q.get(name)
    if raw is None:
        return default
    try:
        v = int(raw)
    except ValueError:
        raise ApiError(400, "invalid_parameter", f"'{name}' deve ser inteiro.")
    if not lo <= v <= hi:
        raise ApiError(400, "invalid_parameter", f"'{name}' deve estar entre {lo} e {hi}.")
    return v


def select_fields(q):
    raw = q.get("fields")
    if not raw:
        return COLUMNS
    fields = [f.strip() for f in raw.split(",") if f.strip()]
    bad = [f for f in fields if f not in COLUMNS]
    if bad:
        raise ApiError(400, "invalid_parameter", f"Campos desconhecidos: {', '.join(bad)}.")
    return fields


# ---------------- endpoints ----------------
def root(request: Request):
    return JSONResponse({
        "name": "Vehicles API",
        "description": "API pública somente-leitura com 1.000.000 de veículos fictícios.",
        "docs": "/docs", "openapi": "/openapi.json",
        "endpoints": ["/vehicles", "/vehicles/{id}", "/vehicles/vin/{vin}", "/vehicles/random",
                      "/facets", "/models?make=", "/stats?group_by=", "/health"],
    })


def health(request: Request):
    n = run("SELECT COUNT(*) FROM vehicles")[0][0]
    return JSONResponse({"status": "ok", "vehicles": n})


def list_vehicles(request: Request):
    q = request.query_params
    fields = select_fields(q)
    page = int_param(q, "page", 1, 1, 1_000_000)
    limit = int_param(q, "limit", 20, 1, MAX_LIMIT)
    sort = q.get("sort", "vehicle_id")
    order = q.get("order", "asc").lower()
    if sort not in SORTABLE:
        raise ApiError(400, "invalid_parameter", f"'sort' deve ser um de: {', '.join(SORTABLE)}.")
    if order not in ("asc", "desc"):
        raise ApiError(400, "invalid_parameter", "'order' deve ser asc ou desc.")
    where, params = build_where(q)
    total = run(f"SELECT COUNT(*) FROM vehicles{where}", params)[0][0]
    rows = run(
        f"SELECT {','.join(fields)} FROM vehicles{where} "
        f"ORDER BY {sort} {order}, vehicle_id {order} LIMIT ? OFFSET ?",
        params + [limit, (page - 1) * limit])
    return JSONResponse({
        "data": [dict(r) for r in rows],
        "meta": {"page": page, "limit": limit, "total": total,
                 "total_pages": math.ceil(total / limit)},
    })


def get_vehicle(request: Request):
    raw = request.path_params["vehicle_id"]
    if not raw.isdigit():
        raise ApiError(400, "invalid_parameter", "'id' deve ser inteiro.")
    rows = run("SELECT * FROM vehicles WHERE vehicle_id = ?", (int(raw),))
    if not rows:
        raise ApiError(404, "not_found", f"Veículo {raw} não encontrado.")
    return JSONResponse(dict(rows[0]))


def get_by_vin(request: Request):
    vin = request.path_params["vin"].upper()
    rows = run("SELECT * FROM vehicles WHERE vin = ?", (vin,))
    if not rows:
        raise ApiError(404, "not_found", f"VIN {vin} não encontrado.")
    return JSONResponse(dict(rows[0]))


def random_vehicles(request: Request):
    n = int_param(request.query_params, "n", 1, 1, MAX_LIMIT)
    max_id = run("SELECT MAX(vehicle_id) FROM vehicles")[0][0]
    ids = random.sample(range(1, max_id + 1), n)
    rows = run(f"SELECT * FROM vehicles WHERE vehicle_id IN ({','.join('?' * n)})", ids)
    return JSONResponse({"data": [dict(r) for r in rows]})


def get_facets(request: Request):
    f = dict(facets())
    r = run("SELECT MIN(model_year), MAX(model_year), MIN(price_usd), MAX(price_usd), "
            "MIN(horsepower_hp), MAX(horsepower_hp) FROM vehicles")[0]
    f["ranges"] = {"model_year": [r[0], r[1]], "price_usd": [r[2], r[3]],
                   "horsepower_hp": [r[4], r[5]]}
    return JSONResponse(f)


def list_models(request: Request):
    q = request.query_params
    where, params = "", []
    if q.get("make"):
        makes = [m for m in canonical("make", q["make"]) if m]
        if not makes:
            return JSONResponse({"data": []})
        where = f" WHERE make IN ({','.join('?' * len(makes))})"
        params = makes
    rows = run(f"SELECT make, model, COUNT(*) AS vehicles FROM vehicles{where} "
               "GROUP BY make, model ORDER BY make, model", params)
    return JSONResponse({"data": [dict(r) for r in rows]})


_stats_cache = {}


def stats(request: Request):
    key = str(sorted(request.query_params.multi_items()))
    if key in _stats_cache:
        return JSONResponse(_stats_cache[key])
    resp = _stats(request)
    if len(_stats_cache) < 256:  # dados são estáticos, então cache é seguro
        _stats_cache[key] = __import__("json").loads(resp.body)
    return resp


def _stats(request: Request):
    q = request.query_params
    group = q.get("group_by")
    if group is not None and group not in GROUP_BY:
        raise ApiError(400, "invalid_parameter", f"'group_by' deve ser um de: {', '.join(GROUP_BY)}.")
    where, params = build_where(q)
    aggs = ("COUNT(*) AS count, ROUND(AVG(price_usd), 2) AS avg_price_usd, "
            "MIN(price_usd) AS min_price_usd, MAX(price_usd) AS max_price_usd, "
            "ROUND(AVG(horsepower_hp), 1) AS avg_horsepower_hp, "
            "ROUND(AVG(mpg_city), 1) AS avg_mpg_city, "
            "ROUND(AVG(mpg_highway), 1) AS avg_mpg_highway, "
            "ROUND(AVG(range_miles), 0) AS avg_range_miles")
    if group:
        limit = int_param(q, "limit", 50, 1, 500)
        rows = run(f"SELECT {group} AS {group}, {aggs} FROM vehicles{where} "
                   f"GROUP BY {group} ORDER BY count DESC LIMIT ?", params + [limit])
        return JSONResponse({"group_by": group, "data": [dict(r) for r in rows]})
    return JSONResponse(dict(run(f"SELECT {aggs} FROM vehicles{where}", params)[0]))


def openapi_json(request: Request):
    return JSONResponse(build_spec(
        columns=COLUMNS, sortable=SORTABLE, categorical=CATEGORICAL,
        numeric={k: v[2].__name__ for k, v in NUMERIC.items()},
        group_by=GROUP_BY, max_limit=MAX_LIMIT, facets=facets()))


def docs(request: Request):
    return HTMLResponse(SWAGGER_HTML)


# ---------------- middleware / tratamento de erros ----------------
class RateLimit:
    """Limite simples por IP (janela de 60 s, em memória, por processo)."""

    def __init__(self, app):
        self.app = app
        self.hits = defaultdict(list)
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or RATE_LIMIT_PER_MIN <= 0 or scope["path"] in ("/health",):
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        fwd = headers.get(b"x-forwarded-for", b"").decode().split(",")[0].strip()
        ip = fwd or (scope["client"][0] if scope.get("client") else "?")
        now = time.monotonic()
        with self.lock:
            window = [t for t in self.hits[ip] if now - t < 60]
            ok = len(window) < RATE_LIMIT_PER_MIN
            if ok:
                window.append(now)
            self.hits[ip] = window
            if len(self.hits) > 10_000:  # evita crescer indefinidamente
                self.hits = defaultdict(list, {k: v for k, v in self.hits.items() if v and now - v[-1] < 60})
            remaining = max(0, RATE_LIMIT_PER_MIN - len(window))
        extra = [(b"x-ratelimit-limit", str(RATE_LIMIT_PER_MIN).encode()),
                 (b"x-ratelimit-remaining", str(remaining).encode())]
        if not ok:
            resp = JSONResponse({"error": {"code": "rate_limited",
                                           "message": "Muitas requisições. Tente novamente em instantes."}},
                                status_code=429, headers={"Retry-After": "60"})
            resp.raw_headers.extend(extra)
            return await resp(scope, receive, send)

        async def send_wrapped(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)
        await self.app(scope, receive, send_wrapped)


def api_error(request, exc: ApiError):
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)


def not_found(request, exc):
    return JSONResponse({"error": {"code": "not_found", "message": "Rota não encontrada."}}, status_code=404)


def server_error(request, exc):
    return JSONResponse({"error": {"code": "internal_error", "message": "Erro interno."}}, status_code=500)


class CacheHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_wrapped(message):
            if message["type"] == "http.response.start" and message["status"] == 200:
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"public, max-age=60")]
            await send(message)
        await self.app(scope, receive, send_wrapped if scope["type"] == "http" else send)


routes = [
    Route("/", root),
    Route("/health", health),
    Route("/docs", docs),
    Route("/openapi.json", openapi_json),
    Route("/vehicles", list_vehicles),
    Route("/vehicles/random", random_vehicles),
    Route("/vehicles/vin/{vin}", get_by_vin),
    Route("/vehicles/{vehicle_id}", get_vehicle),
    Route("/facets", get_facets),
    Route("/models", list_models),
    Route("/stats", stats),
]

app = Starlette(
    routes=routes,
    exception_handlers={ApiError: api_error, 404: not_found, 500: server_error},
    middleware=[
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "OPTIONS"],
                   allow_headers=["*"], expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining"]),
        Middleware(GZipMiddleware, minimum_size=1000),
        Middleware(RateLimit),
        Middleware(CacheHeaders),
    ],
)
